# src/api/therapists.py - Cleaned and Fixed Version
"""
Therapist matching API with clear hard/soft factor implementation.
Hard factors: State, Payment Type/Program, Gender Preference
Soft factors: Priority (Corporate Control), Experience Level, Specialties, Therapeutic Orientation, Lived Experiences
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from src.db import get_db, get_db_session, package_client_signup
from src.db.models import ClientResponse, Therapist
from src.services.airtable_sync_service import airtable_sync_service
from src.services.cache_service import cache_service

# Note: Progressive logger imported inline to avoid circular imports

# Timezone helpers
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

try:
    from src.utils.state_utils import get_state_abbreviation, get_state_timezone
except Exception:

    def get_state_abbreviation(s: str) -> str:
        return (s or "").strip().upper()

    def get_state_timezone(abbr: str) -> str:
        return "US/Eastern"


# Import S3 utilities if available
try:
    from src.utils.s3 import S3MediaType, get_media_url

    s3_enabled = True
except ImportError:
    s3_enabled = False

logger = logging.getLogger(__name__)

therapists_bp = Blueprint("therapists", __name__)

# Default Sol Health Welcome Video
DEFAULT_WELCOME_VIDEO = "https://www.youtube.com/watch?v=OtNM4rS20Ts"

# Canonical topics for specialty matching
CANONICAL_TOPICS = {
    "adhd": "ADHD",
    "anxiety": "Anxiety",
    "body image": "Body image",
    "building confidence": "Building confidence",
    "career/academic stress": "Career/academic stress",
    "depression": "Depression",
    "eating disorders": "Eating disorders",
    "emotional regulation": "Emotional regulation",
    "family life": "Family life",
    "grief and loss": "Grief and loss",
    "lgbtq+ identity": "LGBTQ+ identity",
    "life transitions": "Life transitions",
    "loneliness": "Loneliness",
    "ocd": "OCD",
    "panic attacks": "Panic attacks",
    "phobias": "Phobias",
    "ptsd": "PTSD",
    "relationship challenges": "Relationship challenges",
    "stress and burnout": "Stress and burnout",
    "trauma": "Trauma",
}


def normalize_topic(raw: str) -> Optional[str]:
    """Normalize a topic string to canonical form."""
    s = (raw or "").strip().lower()
    if not s:
        return None

    # Direct canonical hit
    if s in CANONICAL_TOPICS:
        return CANONICAL_TOPICS[s]

    # Common synonyms/contains matching
    if "adhd" in s:
        return CANONICAL_TOPICS["adhd"]
    if "anxiety" in s and "panic" not in s and "phobia" not in s:
        return CANONICAL_TOPICS["anxiety"]
    if "panic" in s:
        return CANONICAL_TOPICS["panic attacks"]
    if "phobia" in s:
        return CANONICAL_TOPICS["phobias"]
    if "body image" in s or "body-image" in s:
        return CANONICAL_TOPICS["body image"]
    if "confidence" in s:
        return CANONICAL_TOPICS["building confidence"]
    if "career" in s or "academic" in s or "school" in s:
        return CANONICAL_TOPICS["career/academic stress"]
    if "depress" in s:
        return CANONICAL_TOPICS["depression"]
    if "eating" in s and ("disorder" in s or "food" in s):
        return CANONICAL_TOPICS["eating disorders"]
    if "emotional regulation" in s or ("emotion" in s and "regulation" in s):
        return CANONICAL_TOPICS["emotional regulation"]
    if "family" in s:
        return CANONICAL_TOPICS["family life"]
    if "grief" in s or "loss" in s:
        return CANONICAL_TOPICS["grief and loss"]
    if "lgbt" in s:
        return CANONICAL_TOPICS["lgbtq+ identity"]
    if "transition" in s:
        return CANONICAL_TOPICS["life transitions"]
    if "loneliness" in s or "lonely" in s:
        return CANONICAL_TOPICS["loneliness"]
    if "ocd" in s or "obsessive" in s:
        return CANONICAL_TOPICS["ocd"]
    if "ptsd" in s or ("post" in s and "trauma" in s):
        return CANONICAL_TOPICS["ptsd"]
    if "relationship" in s:
        return CANONICAL_TOPICS["relationship challenges"]
    if "stress" in s or "burnout" in s:
        return CANONICAL_TOPICS["stress and burnout"]
    if "trauma" in s:
        return CANONICAL_TOPICS["trauma"]

    return None


def enrich_therapist_with_s3_urls(therapist_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add S3 media URLs to therapist data if available."""
    email = therapist_dict.get("email", "")
    if not email:
        return therapist_dict

    if s3_enabled:
        # Get image URL if not provided
        if not therapist_dict.get("image_link"):
            image_url = get_media_url(email, S3MediaType.IMAGE)
            if image_url:
                therapist_dict["image_link"] = image_url

        # Get video URLs if not provided
        if not therapist_dict.get("welcome_video_link"):
            video_url = get_media_url(email, S3MediaType.VIDEO)
            if video_url:
                therapist_dict["welcome_video_link"] = video_url

        if not therapist_dict.get("greetings_video_link"):
            greetings_url = get_media_url(email, S3MediaType.GREETINGS_VIDEO)
            if greetings_url:
                therapist_dict["greetings_video_link"] = greetings_url

    # Default video if none found
    if not therapist_dict.get("welcome_video_link"):
        therapist_dict["welcome_video_link"] = DEFAULT_WELCOME_VIDEO

    return therapist_dict


def filter_therapists_by_availability(
    matched_therapists: List[dict], client_data: dict
) -> List[dict]:
    """
    Filter therapists to only include those with available appointment slots.

    OPTIMIZED: Uses batch checking for 14-day window only, much faster than monthly checks.

    Args:
        matched_therapists: List of matched therapist dictionaries
        client_data: Client data including payment type and state for timezone

    Returns:
        List of therapists that have available appointment slots
    """
    from src.utils.google.efficient_availability import (
        get_efficient_availability_window,
    )

    if not matched_therapists:
        return matched_therapists

    logger.info(
        f"🔍 [OPTIMIZED] Batch checking availability for {len(matched_therapists)} therapists (14-day window)..."
    )

    # Determine timezone based on client state
    client_state = client_data.get("state", "NY")
    if client_state in ["CA", "WA", "OR", "NV"]:
        timezone = "America/Los_Angeles"
    elif client_state in ["TX", "CO", "UT", "AZ", "MT"]:
        timezone = "America/Chicago"
    else:
        timezone = "America/New_York"  # Default for East Coast

    # Determine payment type
    payment_type = client_data.get("payment_type", "cash_pay").lower()

    # Extract all therapist emails for batch processing
    therapist_emails = []
    email_to_match = {}

    for match in matched_therapists:
        therapist = match["therapist"]
        therapist_email = therapist.get("email")

        if not therapist_email:
            logger.warning(
                f"⚠️ Therapist {therapist.get('name')} has no email, skipping availability check"
            )
            continue

        therapist_emails.append(therapist_email)
        email_to_match[therapist_email] = match

    if not therapist_emails:
        logger.warning("No therapist emails found for availability checking")
        return matched_therapists

    # Single batch API call for all therapists (14-day window only)
    try:
        # Enable debug mode for detailed availability logging in matching
        availability_results = get_efficient_availability_window(
            therapist_emails=therapist_emails,
            payment_type=payment_type,
            timezone_name=timezone,
            debug=True,  # Always enable debug for matching process
        )

        available_therapists = []

        for email, availability in availability_results.items():
            match = email_to_match[email]
            therapist = match["therapist"]

            if availability.get("error"):
                logger.warning(
                    f"  ⚠️ Error checking {therapist.get('name')} ({email}): {availability['error']}"
                )
                # Include therapist on error to avoid false negatives
                available_therapists.append(match)

            elif availability.get("has_availability") is True:
                sessions = availability.get("total_sessions", 0)
                days = availability.get("available_days", 0)
                logger.info(
                    f"  ✅ {therapist.get('name')} ({email}): {sessions} sessions across {days} days"
                )
                available_therapists.append(match)

            else:
                logger.info(
                    f"  ❌ {therapist.get('name')} ({email}): No available slots"
                )

        logger.info(
            f"📊 Availability filtering: {len(available_therapists)}/{len(matched_therapists)} therapists have available slots"
        )
        return available_therapists

    except Exception as e:
        logger.error(f"❌ Batch availability check failed: {e}")
        # On batch failure, return all therapists to avoid blocking matching
        logger.info(
            "  🔄 Falling back to returning all therapists due to availability check failure"
        )
        return matched_therapists


def calculate_severity_level(client_data: dict) -> Tuple[int, str]:
    """
    Calculate client's severity level based on assessment scores.
    Returns (severity_level, reason) where severity levels are:
    0 = Low severity
    1 = Moderate severity
    2 = High severity
    3 = Very high severity
    """
    # Safe null handling for assessment scores
    phq9_raw = client_data.get("phq9_total", 0)
    gad7_raw = client_data.get("gad7_total", 0)

    # Convert to int, handling None values
    phq9 = int(phq9_raw) if phq9_raw is not None else 0
    gad7 = int(gad7_raw) if gad7_raw is not None else 0

    # Get suicidal thoughts score (if available)
    sui = 0
    if client_data.get("suicidal_thoughts"):
        score_map = {
            "Not at all": 0,
            "Several days": 1,
            "More than half the days": 2,
            "Nearly every day": 3,
        }
        sui = score_map.get(client_data.get("suicidal_thoughts"), 0)

    # Determine severity level based on highest risk factor
    severity_reasons = []

    # Suicidal ideation takes highest priority
    if sui >= 3:
        return 3, "Daily suicidal ideation"
    elif sui >= 2:
        return 3, "Frequent suicidal ideation"
    elif sui >= 1:
        return 2, "Some suicidal ideation"

    # Very high severity PHQ-9/GAD-7 scores
    if phq9 > 20:
        severity_reasons.append(f"Severe depression (PHQ-9: {phq9})")
    if gad7 >= 15:
        severity_reasons.append(f"Severe anxiety (GAD-7: {gad7})")

    if phq9 > 20 or gad7 >= 15:
        return 3, "; ".join(severity_reasons)

    # High severity scores
    if phq9 > 14:
        severity_reasons.append(f"Moderately severe depression (PHQ-9: {phq9})")
    if gad7 >= 10:
        severity_reasons.append(f"Moderate-severe anxiety (GAD-7: {gad7})")

    if phq9 > 14 or gad7 >= 10:
        return 2, "; ".join(severity_reasons)

    # Moderate severity
    if phq9 >= 10:
        severity_reasons.append(f"Moderate depression (PHQ-9: {phq9})")
    if gad7 >= 8:
        severity_reasons.append(f"Mild-moderate anxiety (GAD-7: {gad7})")

    if phq9 >= 10 or gad7 >= 8:
        return 1, "; ".join(severity_reasons)

    # Low severity
    return 0, "Low severity scores"


def calculate_experience_score(
    client_data: dict, therapist: Therapist
) -> Tuple[int, str]:
    """
    Calculate experience-based score for ranking therapists based on client severity.
    Higher scores indicate better experience match for the client's needs.
    Returns (score, explanation)
    """
    risk_text = (therapist.risk_experience or "").lower()
    yes_count = risk_text.count("yes")

    severity_level, severity_reason = calculate_severity_level(client_data)

    # Base experience score based on risk experience "yes" responses
    # 0 yes = 0 points, 1 yes = 10 points, 2+ yes = 20 points
    base_score = min(yes_count * 10, 20)

    # Apply severity-based multipliers
    if severity_level == 0:
        # Low severity - experience doesn't matter much
        experience_score = base_score + 30  # Everyone gets good base score
        explanation = f"Low severity client (base: {base_score + 30})"

    elif severity_level == 1:
        # Moderate severity - slight preference for experience
        if yes_count >= 1:
            experience_score = base_score + 25
            explanation = f"Moderate severity, has experience ({yes_count} yes)"
        else:
            experience_score = base_score + 15  # Still decent score
            explanation = f"Moderate severity, limited experience ({yes_count} yes)"

    elif severity_level == 2:
        # High severity - stronger preference for experience
        if yes_count >= 1:
            experience_score = base_score + 30
            explanation = f"High severity, has experience ({yes_count} yes)"
        else:
            experience_score = base_score + 5  # Lower but not eliminated
            explanation = f"High severity, limited experience ({yes_count} yes)"

    elif severity_level == 3:
        # Very high severity - strong preference for high experience
        if yes_count >= 2:
            experience_score = base_score + 40
            explanation = f"Very high severity, high experience ({yes_count} yes)"
        elif yes_count >= 1:
            experience_score = base_score + 15
            explanation = f"Very high severity, some experience ({yes_count} yes)"
        else:
            experience_score = base_score + 0  # Lowest priority but still included
            explanation = f"Very high severity, no experience ({yes_count} yes)"
    else:
        experience_score = base_score
        explanation = f"Standard experience scoring ({yes_count} yes)"

    logger.debug(
        f"Experience scoring for {therapist.email}: {explanation} -> {experience_score} points"
    )

    return experience_score, explanation


def calculate_priority_score(therapist: Therapist) -> Tuple[int, str]:
    """
    Calculate priority-based score for corporate matching control.
    Returns (score, explanation)

    Priority values:
    - high: 100 points
    - medium: 50 points
    - low: 0 points
    - null/empty: 0 points (defaults to low)
    """
    priority = (therapist.priority or "low").strip().lower()

    if priority == "high":
        return 100, "High priority therapist (+100)"
    elif priority == "medium":
        return 50, "Medium priority therapist (+50)"
    else:  # low, null, or any other value
        return 0, "Standard priority therapist (+0)"


def calculate_soft_score(
    client_data: dict, therapist: Therapist
) -> Tuple[int, List[str]]:
    """
    Calculate soft factor score for ranking therapists.
    Now includes experience-based scoring and priority scoring.
    Returns (score, matched_specialties)
    """
    score = 0
    matched_specs = []

    # Add priority-based scoring (corporate control - highest priority)
    priority_score, priority_explanation = calculate_priority_score(therapist)
    score += priority_score

    # Add experience-based scoring (second highest priority factor)
    experience_score, experience_explanation = calculate_experience_score(
        client_data, therapist
    )
    score += experience_score

    # Build client topic set
    raw_client_topics = (
        client_data.get("therapist_specializes_in", [])
        + client_data.get("diagnoses", [])
        + client_data.get("topics", [])
        + client_data.get("concerns", [])
    )
    client_topics = set()
    for topic in raw_client_topics:
        normalized = normalize_topic(topic)
        if normalized:
            client_topics.add(normalized)

    # Build therapist topic set
    therapist_topics = set()

    # From array field
    for spec in therapist.diagnoses_specialties_array or []:
        normalized = normalize_topic(spec)
        if normalized:
            therapist_topics.add(normalized)

    # From text fields (CSV format)
    for field_value in [
        therapist.diagnoses_specialties,
        therapist.specialities,
        therapist.diagnoses,
    ]:
        if field_value:
            for item in field_value.split(","):
                normalized = normalize_topic(item.strip())
                if normalized:
                    therapist_topics.add(normalized)

    # Score specialty matches (second most important soft factor)
    shared = client_topics & therapist_topics
    if shared:
        matched_specs.extend(list(shared))
        score += 50 * len(shared)  # 50 points per matched specialty

    # Score therapeutic orientation matches
    client_orientations = client_data.get("therapy_preferences", []) or client_data.get(
        "therapeutic_preferences", []
    )
    therapist_orientation_text = (
        therapist.therapeutic_orientation
        or therapist.internal_therapeutic_orientation
        or ""
    )
    therapist_orientations = [
        x.strip() for x in therapist_orientation_text.split(",") if x.strip()
    ]

    for client_orient in client_orientations:
        for therapist_orient in therapist_orientations:
            if (
                client_orient.lower() in therapist_orient.lower()
                or therapist_orient.lower() in client_orient.lower()
            ):
                score += 10  # 10 points per orientation match

    # Score lived experiences
    lived = [x.lower() for x in (client_data.get("lived_experiences") or [])]

    if (
        "non-traditional" in " ".join(lived)
        and "non-traditional" in (therapist.family_household or "").lower()
    ):
        score += 5
    if (
        "generation immigrant" in " ".join(lived)
        and "gen immigrant" in (therapist.immigration_background or "").lower()
    ):
        score += 5
    if (
        "individualist" in " ".join(lived)
        and "individualist" in (therapist.culture or "").lower()
    ):
        score += 5
    if (
        "collectivist" in " ".join(lived)
        and "collectivist" in (therapist.culture or "").lower()
    ):
        score += 5
    if "suburban" in " ".join(lived) and "suburban" in (therapist.places or "").lower():
        score += 5
    if "urban" in " ".join(lived) and "urban" in (therapist.places or "").lower():
        score += 5
    if "rural" in " ".join(lived) and "rural" in (therapist.places or "").lower():
        score += 5
    if "parent" in " ".join(lived) and therapist.has_children == "Yes":
        score += 5
    if "caretaker" in " ".join(lived) and therapist.caretaker_role == "Yes":
        score += 5
    if "lgbtq" in " ".join(lived) and therapist.lgbtq_part == "Yes":
        score += 5
    if "social media" in " ".join(lived) and therapist.social_media_affected:
        score += 5

    return score, matched_specs


class MatchingLogger:
    """Centralized logging for matching flow."""

    @staticmethod
    def log_match_request(response_id: str, client_data: dict):
        """Log the initial match request."""
        logger.info("=" * 50)
        logger.info("🔍 [MATCH REQUEST]")
        logger.info(f"  Response ID: {response_id}")
        logger.info(
            f"  Client: {client_data.get('first_name')} {client_data.get('last_name')}"
        )
        logger.info(f"  Email: {client_data.get('email')}")
        logger.info(f"  State: {client_data.get('state')}")
        logger.info(f"  Payment Type: {client_data.get('payment_type')}")
        logger.info(
            f"  Gender Pref: {client_data.get('therapist_identifies_as', 'None')}"
        )
        logger.info(
            f"  Specialties: {', '.join(client_data.get('therapist_specializes_in', []))}"
        )
        logger.info(
            f"  PHQ-9: {client_data.get('phq9_total')}, GAD-7: {client_data.get('gad7_total')}"
        )

    @staticmethod
    def log_filtering_results(stage: str, count: int, details: dict = None):
        """Log results after each filtering stage."""
        logger.info(f"  [{stage}] Count: {count}")
        if details:
            for key, value in details.items():
                logger.info(f"    - {key}: {value}")

    @staticmethod
    def log_match_results(matches: list):
        """Log final match results."""
        logger.info("📊 [MATCH RESULTS]")
        logger.info(f"  Total Matches: {len(matches)}")
        if matches:
            logger.info("  Top 3 Matches:")
            for i, match in enumerate(matches[:3], 1):
                t = match["therapist"]
                logger.info(f"    {i}. {t.get('name')} ({t.get('email')})")
                logger.info(
                    f"       Program: {t.get('program')}, Score: {match['score']}"
                )
                if match["matched_diagnoses_specialities"]:
                    logger.info(
                        f"       Matched: {', '.join(match['matched_diagnoses_specialities'])}"
                    )
        logger.info("=" * 50)


@therapists_bp.route("/therapists/match", methods=["GET"])
def get_therapist_match():
    """
    Get matched therapists for a client based on survey responses.

    Hard factors (must match or no results):
    - State alignment
    - Payment type → Program mapping
    - Gender preference

    Soft factors (for ranking):
    - Priority (corporate control: high=+100, medium=+50, low=+0)
    - Experience level (based on severity and risk experience)
    - Specialty matches
    - Therapeutic orientation
    - Lived experiences
    """
    response_id = request.args.get("response_id")
    limit = int(request.args.get("limit", 50))  # Increased from 10 to show more available therapists

    # CRITICAL DEBUG: Make sure this endpoint is being called
    print(f"🚨 THERAPIST MATCH ENDPOINT CALLED - Response ID: {response_id}")
    logger.info(f"🚨 THERAPIST MATCH ENDPOINT CALLED - Response ID: {response_id}")

    if not response_id:
        return jsonify({"error": "response_id is required"}), 400

    session = get_db_session()

    try:
        # Get client data from database
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        if not client_response:
            return jsonify({"error": "Client response not found"}), 404

        # Convert to dict for processing - include ALL available fields for comprehensive logging
        client_data = {
            "response_id": client_response.id,
            "first_name": client_response.first_name,
            "last_name": client_response.last_name,
            "email": client_response.email,
            "phone": client_response.phone,
            "age": client_response.age,
            "gender": client_response.gender,
            # Address Information (critical for Google Sheets)
            "state": client_response.state,
            "street_address": client_response.street_address,
            "city": client_response.city,
            "postal_code": client_response.postal_code,
            # Survey & Preferences
            "university": client_response.university,
            "payment_type": client_response.payment_type,
            "therapist_specializes_in": client_response.therapist_specializes_in or [],
            "therapist_identifies_as": client_response.therapist_identifies_as,
            "lived_experiences": client_response.lived_experiences or [],
            "what_brings_you": client_response.what_brings_you,
            # Assessment Scores & Responses (for comprehensive logging)
            "phq9_total": client_response.phq9_total,
            "gad7_total": client_response.gad7_total,
            "phq9_scores": client_response.phq9_responses,
            "gad7_scores": client_response.gad7_responses,
            # Insurance Information
            "insurance_provider": client_response.insurance_provider,
            "insurance_verified": client_response.insurance_verified,
            # Therapist Selection & Matching
            "selected_therapist": client_response.selected_therapist,
            "selected_therapist_id": client_response.selected_therapist_id,
            "selected_therapist_email": client_response.selected_therapist_email,
            "matching_preference": client_response.matching_preference,
            "requested_therapist_name": client_response.selected_therapist,  # Keep for compatibility
            "requested_therapist_email": client_response.selected_therapist_email,  # Keep for compatibility
            # UTM & Marketing
            "promo_code": client_response.promo_code,
            "referred_by": client_response.referred_by,
            "utm_source": client_response.utm_source,
            "utm_medium": client_response.utm_medium,
            "utm_campaign": client_response.utm_campaign,
            # Match Status
            "match_status": client_response.match_status,
            "matched_therapist_id": client_response.matched_therapist_id,
        }

        # ========== ENRICH WITH NIRVANA DATA ==========
        # Before matching, enrich client_data with any available Nirvana insurance verification data
        try:
            # Skip Nirvana enrichment for now - the module doesn't exist
            logger.info(
                f"ℹ️ [NIRVANA ENRICHMENT] Skipping data_flow_integration module"
            )
        except Exception as e:
            logger.error(
                f"❌ [NIRVANA ENRICHMENT] Failed to enrich with Nirvana data: {e}"
            )

        # Debug: Log what we got from the database
        print(f"🔍 [THERAPIST MATCH DEBUG] - Response ID: {response_id}")
        print(
            f"  client_response.selected_therapist: '{client_response.selected_therapist}'"
        )
        print(
            f"  client_response.selected_therapist_email: '{client_response.selected_therapist_email}'"
        )
        print(
            f"  client_response.matching_preference: '{client_response.matching_preference}'"
        )
        print(f"  client_data mapped values:")
        print(
            f"    requested_therapist_name: '{client_data.get('requested_therapist_name')}'"
        )
        print(
            f"    requested_therapist_email: '{client_data.get('requested_therapist_email')}'"
        )
        print(f"  CATHERINE BURNETT CHECK:")
        print(
            f"    Is name 'Catherine Burnett'? {client_data.get('requested_therapist_name') == 'Catherine Burnett'}"
        )
        print(
            f"    Is email 'catherine.burnett@solhealth.co'? {client_data.get('requested_therapist_email') == 'catherine.burnett@solhealth.co'}"
        )

        # Also use logger in case that works better
        logger.info(f"🔍 [DATABASE VALUES] - Response ID: {response_id}")
        logger.info(
            f"  client_response.selected_therapist: '{client_response.selected_therapist}'"
        )
        logger.info(
            f"  client_response.selected_therapist_email: '{client_response.selected_therapist_email}'"
        )
        logger.info(
            f"  client_response.matching_preference: '{client_response.matching_preference}'"
        )
        logger.info(f"  client_data mapped values:")
        logger.info(
            f"    requested_therapist_name: '{client_data.get('requested_therapist_name')}'"
        )
        logger.info(
            f"    requested_therapist_email: '{client_data.get('requested_therapist_email')}'"
        )
        logger.info(f"  CATHERINE BURNETT CHECK:")
        logger.info(
            f"    Is name 'Catherine Burnett'? {client_data.get('requested_therapist_name') == 'Catherine Burnett'}"
        )
        logger.info(
            f"    Is email 'catherine.burnett@solhealth.co'? {client_data.get('requested_therapist_email') == 'catherine.burnett@solhealth.co'}"
        )

        # Add PHQ-9/GAD-7 responses for risk assessment
        if client_response.phq9_responses:
            client_data.update(client_response.phq9_responses)
        if client_response.gad7_responses:
            client_data.update(client_response.gad7_responses)

        # Derive concerns from assessment scores if no specialties selected
        if not client_data.get("therapist_specializes_in"):
            derived = []

            # Safe null handling for assessment scores
            gad7_score = client_data.get("gad7_total") or 0
            phq9_score = client_data.get("phq9_total") or 0

            if isinstance(gad7_score, (int, float)) and gad7_score >= 8:
                derived.append("Anxiety")
            if isinstance(phq9_score, (int, float)) and phq9_score >= 10:
                derived.append("Depression")
            if derived:
                client_data["diagnoses"] = derived

        MatchingLogger.log_match_request(response_id, client_data)

        # ========== EXPLICIT THERAPIST REQUEST (highest priority) ==========
        # Check if client has specifically requested a therapist by name or email
        requested_therapist_name = client_data.get("requested_therapist_name")
        requested_therapist_email = client_data.get("requested_therapist_email")

        print(f"🔍 [SPECIFIC THERAPIST CHECK]")
        print(f"  requested_therapist_name: {requested_therapist_name}")
        print(f"  requested_therapist_email: {requested_therapist_email}")
        print(
            f"  client_response.selected_therapist: {client_response.selected_therapist}"
        )
        print(
            f"  client_response.selected_therapist_email: {client_response.selected_therapist_email}"
        )
        print(
            f"  client_response.matching_preference: {client_response.matching_preference}"
        )

        logger.info(f"🔍 [SPECIFIC THERAPIST CHECK]")
        logger.info(f"  requested_therapist_name: {requested_therapist_name}")
        logger.info(f"  requested_therapist_email: {requested_therapist_email}")
        logger.info(
            f"  client_response.selected_therapist: {client_response.selected_therapist}"
        )
        logger.info(
            f"  client_response.selected_therapist_email: {client_response.selected_therapist_email}"
        )
        logger.info(
            f"  client_response.matching_preference: {client_response.matching_preference}"
        )

        if requested_therapist_name or requested_therapist_email:
            try:
                logger.info("🎯 [SPECIFIC THERAPIST REQUEST]")
                logger.info(f"  Requested name: {requested_therapist_name}")
                logger.info(f"  Requested email: {requested_therapist_email}")

                # Query for the specific therapist
                specific_therapist_query = session.query(Therapist)

                if requested_therapist_email:
                    # Email has priority as it's more specific
                    specific_therapist = specific_therapist_query.filter(
                        func.lower(Therapist.email)
                        == requested_therapist_email.lower().strip()
                    ).first()
                elif requested_therapist_name:
                    # Simplified and more robust name matching
                    logger.info(f"  Searching by name: '{requested_therapist_name}'")
                    try:
                        # Method 1: Exact match (case insensitive)
                        specific_therapist = specific_therapist_query.filter(
                            func.lower(Therapist.name)
                            == requested_therapist_name.lower().strip()
                        ).first()

                        if not specific_therapist:
                            # Method 2: Contains match for partial names
                            search_name = requested_therapist_name.lower().strip()
                            logger.info(
                                f"  Trying partial name search for: '{search_name}'"
                            )
                            specific_therapist = specific_therapist_query.filter(
                                func.lower(Therapist.name).contains(search_name)
                            ).first()

                        logger.info(
                            f"  Name search result: {'Found' if specific_therapist else 'Not found'}"
                        )

                        # Debug: Check if Catherine Burnett exists in database at all
                        if (
                            not specific_therapist
                            and requested_therapist_name.lower().strip()
                            == "catherine burnett"
                        ):
                            logger.info("  🔍 CATHERINE BURNETT DATABASE CHECK:")
                            all_catherines = (
                                session.query(Therapist)
                                .filter(
                                    func.lower(Therapist.name).contains("catherine")
                                )
                                .all()
                            )
                            logger.info(
                                f"    Found {len(all_catherines)} therapists with 'catherine' in name:"
                            )
                            for therapist in all_catherines:
                                logger.info(
                                    f"      - {therapist.name} ({therapist.email}) - NJ available: {'NJ' in (therapist.states or [])}"
                                )

                    except Exception as e:
                        logger.error(f"❌ Error in name search: {e}")
                        specific_therapist = None
                else:
                    specific_therapist = None

                if specific_therapist:
                    # Verify the requested therapist meets basic requirements
                    logger.info(
                        f"✅ Found requested therapist: {specific_therapist.name} ({specific_therapist.email})"
                    )

                    # Check if therapist is accepting new clients and available in client's state
                    therapist_states = specific_therapist.states or []
                    client_state_check = client_data.get("state", "").strip().upper()

                    if not specific_therapist.accepting_new_clients:
                        logger.warning(
                            f"⚠️ Requested therapist {specific_therapist.name} is not accepting new clients"
                        )
                    elif client_state_check not in therapist_states:
                        logger.warning(
                            f"⚠️ Requested therapist {specific_therapist.name} not available in {client_state_check}"
                        )
                        logger.warning(f"  Therapist states: {therapist_states}")
                    else:
                        # Return the specific therapist as the only match
                        logger.info(
                            "🎯 Returning specific therapist request (bypassing general matching)"
                        )

                        # Use the same conversion as general matching
                        therapist_dict = specific_therapist.to_dict()
                        # Enrich with S3 URLs
                        try:
                            therapist_dict = enrich_therapist_with_s3_urls(
                                therapist_dict
                            )
                        except Exception as e:
                            logger.warning(f"Failed to enrich therapist S3 URLs: {e}")

                        specific_match = {
                            "therapist": therapist_dict,
                            "score": 1000,  # Highest possible score for explicit requests
                            "matched_diagnoses_specialities": [],
                            "match_reason": "Explicitly requested therapist",
                        }

                        MatchingLogger.log_match_results([specific_match])

                        return jsonify(
                            {
                                "client": {
                                    "id": client_data.get("id"),
                                    "first_name": client_data.get("first_name"),
                                    "last_name": client_data.get("last_name"),
                                    "email": client_data.get("email"),
                                    "response_id": response_id,
                                },
                                "therapists": [specific_match],
                                "match_type": "specific_request",
                                "total_count": 1,
                            }
                        )
                else:
                    logger.warning(
                        f"❌ Could not find requested therapist: {requested_therapist_name or requested_therapist_email}"
                    )
                    logger.info("🔄 Falling back to general matching algorithm")

            except Exception as e:
                logger.error(f"❌ Error in specific therapist matching: {str(e)}")
                logger.info("🔄 Falling back to general matching algorithm due to error")
                import traceback

                traceback.print_exc()

        # ========== HARD FACTOR 1: State ==========
        client_state = (client_data.get("state") or "").strip().upper()
        if not client_state:
            return jsonify({"error": "Client state is required for matching"}), 400

        # ========== HARD FACTOR 2: Payment Type → Program ==========
        payment_type = (client_data.get("payment_type") or "cash_pay").strip().lower()

        # Insurance is only available in NJ for now
        if payment_type == "insurance" and client_state != "NJ":
            logger.warning(f"⚠️ Insurance requested for non-NJ state: {client_state}")
            return (
                jsonify(
                    {
                        "error": "Insurance matching is currently only available in New Jersey",
                        "client_state": client_state,
                        "therapists": [],
                    }
                ),
                200,
            )

        # Insurance clients should ONLY get Limited Permit (associate) therapists
        if payment_type == "insurance":
            # For insurance: ONLY Limited Permit (associates) - associates handle insurance billing
            eligible_programs = ["Limited Permit"]  
        else:  # cash_pay
            # For cash pay: Only graduate therapists (exclude Limited Permit which is for insurance only)
            eligible_programs = ["MFT", "MHC", "MSW"]

        MatchingLogger.log_filtering_results(
            "Program Selection",
            len(eligible_programs),
            {"payment_type": payment_type, "programs": eligible_programs},
        )

        # ========== Query Database with Hard Factors 1 & 2 ==========

        # Debug: Check counts before filtering
        logger.info("🔍 [DATABASE DEBUG - Step by step filtering]")

        # Total therapists
        total_count = session.query(Therapist).count()
        logger.info(f"  Total therapists in DB: {total_count}")

        # Program filter
        program_query = session.query(Therapist).filter(
            Therapist.program.in_(eligible_programs)
        )
        program_count = program_query.count()
        logger.info(f"  Therapists with programs {eligible_programs}: {program_count}")

        # State filter - handle PostgreSQL array format like {TX,FL}
        state_query = program_query.filter(
            Therapist.states_array.contains([client_state])
        )
        state_count = state_query.count()
        logger.info(f"  Above + serving state {client_state}: {state_count}")

        # Accepting new clients filter
        accepting_query = state_query.filter(
            or_(
                func.lower(Therapist.accepting_new_clients) == "yes",
                func.lower(Therapist.accepting_new_clients) == "true",
                func.lower(Therapist.accepting_new_clients) == "checked",
                Therapist.accepting_new_clients == "1",
                func.lower(Therapist.accepting_new_clients) == "t",
                func.lower(Therapist.accepting_new_clients) == "y",
            )
        )
        accepting_count = accepting_query.count()
        logger.info(f"  Above + accepting new clients: {accepting_count}")

        # Capacity filter
        query = accepting_query.filter(Therapist.max_caseload > 0)
        capacity_count = query.count()
        logger.info(f"  Above + has capacity (max_caseload > 0): {capacity_count}")

        eligible_therapists = query.all()

        # Show sample therapists at each filtering step for debugging
        if state_count > 0:
            sample_state_therapists = state_query.limit(5).all()
            logger.info(
                f"  📋 Sample therapists serving {client_state} ({eligible_programs}):"
            )
            for t in sample_state_therapists:
                is_accepting = any(
                    [
                        str(t.accepting_new_clients or "").lower() == "yes",
                        str(t.accepting_new_clients or "").lower() == "true",
                        str(t.accepting_new_clients or "").lower() == "checked",
                        str(t.accepting_new_clients or "") == "1",
                        str(t.accepting_new_clients or "").lower() == "t",
                        str(t.accepting_new_clients or "").lower() == "y",
                    ]
                )
                status = (
                    "✅ MATCH"
                    if (is_accepting and (t.max_caseload or 0) > 0)
                    else "❌ FILTERED"
                )
                logger.info(
                    f"    {status} - {t.name} | Accepting: '{t.accepting_new_clients}' | Capacity: {t.max_caseload}"
                )

        if capacity_count == 0 and state_count > 0:
            logger.warning(
                f"  🚨 All {state_count} therapists serving {client_state} were filtered out by accepting/capacity constraints"
            )

        MatchingLogger.log_filtering_results(
            "State & Program Filter", len(eligible_therapists)
        )

        if not eligible_therapists:
            logger.warning(
                f"❌ No therapists available for {payment_type} in {client_state}"
            )
            return (
                jsonify(
                    {
                        "client": {
                            "id": client_data.get("id"),
                            "first_name": client_data.get("first_name"),
                            "last_name": client_data.get("last_name"),
                            "email": client_data.get("email"),
                            "response_id": response_id,
                            "state": client_state,
                        },
                        "therapists": [],
                        "message": f"No therapists available for {payment_type} in {client_state}",
                    }
                ),
                200,
            )

        # ========== HARD FACTOR 3: Gender Preference ==========
        gender_pref = (client_data.get("therapist_identifies_as") or "").strip().lower()

        if gender_pref and gender_pref not in ["no preference", "any", "none", ""]:
            # Filter to only therapists matching gender preference
            gender_filtered = []

            logger.info(f"🔍 Filtering by gender preference: '{gender_pref}'")

            for therapist in eligible_therapists:
                # Normalize therapist gender - prefer identities_as over gender field
                therapist_gender_raw = (
                    (therapist.identities_as or therapist.gender or "").strip().lower()
                )

                # Log each therapist's gender for debugging
                logger.debug(
                    f"  Therapist {therapist.email}: gender='{therapist.gender}', identities_as='{therapist.identities_as}', normalized='{therapist_gender_raw}'"
                )

                # Exact and safe matching logic
                is_match = False

                if gender_pref == "male":
                    # Only match if it's exactly "male" or starts with "male" (like "male (he/him)")
                    is_match = (
                        therapist_gender_raw == "male"
                        or therapist_gender_raw.startswith("male ")
                        or therapist_gender_raw.startswith("male(")
                    )

                elif gender_pref == "female":
                    # Only match if it's exactly "female" or starts with "female"
                    is_match = (
                        therapist_gender_raw == "female"
                        or therapist_gender_raw.startswith("female ")
                        or therapist_gender_raw.startswith("female(")
                    )

                elif gender_pref in [
                    "non-binary",
                    "nonbinary",
                    "non binary",
                    "non_binary",
                ]:
                    # Match various non-binary representations
                    is_match = (
                        therapist_gender_raw
                        in ["non-binary", "nonbinary", "non binary", "non_binary"]
                        or "non-binary" in therapist_gender_raw
                        or "nonbinary" in therapist_gender_raw
                        or "non binary" in therapist_gender_raw
                    )

                if is_match:
                    gender_filtered.append(therapist)
                    logger.debug(f"    ✓ MATCHED: {therapist.email}")
                else:
                    logger.debug(f"    ✗ No match: {therapist.email}")

            logger.info(
                f"  Gender filtering results: {len(gender_filtered)}/{len(eligible_therapists)} therapists matched"
            )

            if not gender_filtered:
                return (
                    jsonify(
                        {
                            "client": {
                                "id": client_data.get("id"),
                                "first_name": client_data.get("first_name"),
                                "last_name": client_data.get("last_name"),
                                "email": client_data.get("email"),
                                "response_id": response_id,
                                "state": client_state,
                            },
                            "therapists": [],
                            "message": f"No {gender_pref} therapists available for {payment_type} in {client_state}. Consider broadening your gender preference.",
                        }
                    ),
                    200,
                )

            eligible_therapists = gender_filtered
            MatchingLogger.log_filtering_results(
                "Gender Filter", len(eligible_therapists), {"preference": gender_pref}
            )

        # ========== EXPERIENCE-BASED RANKING (No Hard Filtering) ==========
        # Instead of filtering out therapists based on experience, we now use
        # experience as a ranking factor in the soft scoring system.
        # This allows clients with high severity to still see all therapists,
        # but with experienced therapists ranked higher.

        severity_level, severity_reason = calculate_severity_level(client_data)
        logger.info(
            f"🎯 Client severity assessment: Level {severity_level} - {severity_reason}"
        )

        MatchingLogger.log_filtering_results(
            "Experience Assessment",
            len(eligible_therapists),
            {"severity_level": severity_level, "reason": severity_reason},
        )

        # ========== FINAL GENDER VERIFICATION ==========
        # Double-check that gender preference is still being respected
        if gender_pref and gender_pref not in ["no preference", "any", "none", ""]:
            logger.info(
                f"🔍 Final gender verification for '{gender_pref}' preference..."
            )
            verified_therapists = []

            for therapist in eligible_therapists:
                therapist_gender_raw = (
                    (therapist.identities_as or therapist.gender or "").strip().lower()
                )

                is_valid = False
                if gender_pref == "male":
                    is_valid = (
                        therapist_gender_raw == "male"
                        or therapist_gender_raw.startswith("male ")
                        or therapist_gender_raw.startswith("male(")
                    )
                elif gender_pref == "female":
                    is_valid = (
                        therapist_gender_raw == "female"
                        or therapist_gender_raw.startswith("female ")
                        or therapist_gender_raw.startswith("female(")
                    )
                elif gender_pref in [
                    "non-binary",
                    "nonbinary",
                    "non binary",
                    "non_binary",
                ]:
                    is_valid = (
                        therapist_gender_raw
                        in ["non-binary", "nonbinary", "non binary", "non_binary"]
                        or "non-binary" in therapist_gender_raw
                        or "nonbinary" in therapist_gender_raw
                        or "non binary" in therapist_gender_raw
                    )

                if is_valid:
                    verified_therapists.append(therapist)
                else:
                    logger.warning(
                        f"❌ GENDER MISMATCH CAUGHT: {therapist.email} has gender '{therapist_gender_raw}' but client requested '{gender_pref}'"
                    )

            eligible_therapists = verified_therapists
            logger.info(
                f"  Final verification: {len(eligible_therapists)} therapists confirmed for '{gender_pref}' preference"
            )

        # ========== Calculate Soft Scores for Ranking ==========
        matched_therapists = []

        for therapist in eligible_therapists:
            score, matched_specs = calculate_soft_score(client_data, therapist)

            therapist_dict = therapist.to_dict()

            # Enrich with S3 URLs
            try:
                therapist_dict = enrich_therapist_with_s3_urls(therapist_dict)
            except Exception as e:
                logger.warning(f"Failed to enrich S3 URLs for {therapist.email}: {e}")

            matched_therapists.append(
                {
                    "therapist": therapist_dict,
                    "score": score,
                    "matched_diagnoses_specialities": matched_specs,
                }
            )

        # Sort by score (highest first), with randomization for ties
        import random

        # Group therapists by score to add randomness within score tiers
        score_groups = {}
        for therapist in matched_therapists:
            score = therapist["score"]
            if score not in score_groups:
                score_groups[score] = []
            score_groups[score].append(therapist)

        # Randomize within each score group, then sort groups by score
        randomized_therapists = []
        for score in sorted(score_groups.keys(), reverse=True):
            group = score_groups[score]
            random.shuffle(group)  # Randomize therapists with the same score
            randomized_therapists.extend(group)

        matched_therapists = randomized_therapists

        # Apply age-based boost (move similar age therapists up)
        client_age = client_data.get("age")
        if client_age:
            try:
                client_age_int = int(client_age)

                # Find therapists within 5 years of client's age
                similar_age = []
                others = []

                for match in matched_therapists:
                    therapist_age = match["therapist"].get("age")
                    if therapist_age:
                        try:
                            therapist_age_int = int(therapist_age)
                            if abs(therapist_age_int - client_age_int) <= 5:
                                similar_age.append(match)
                            else:
                                others.append(match)
                        except:
                            others.append(match)
                    else:
                        others.append(match)

                # Put up to 3 similar-age therapists at the top
                matched_therapists = similar_age[:3] + others + similar_age[3:]
            except:
                pass

        # Limit results
        matched_therapists = matched_therapists[:limit]

        # ========== AVAILABILITY FILTERING ==========
        # Filter out therapists who have no available appointment slots
        # This can be disabled by setting DISABLE_AVAILABILITY_FILTERING=true environment variable
        availability_filtering_enabled = (
            os.environ.get("DISABLE_AVAILABILITY_FILTERING", "false").lower() != "true"
        )

        if matched_therapists and availability_filtering_enabled:
            logger.info(
                "🔍 [AVAILABILITY FILTERING] Checking availability for matched therapists..."
            )
            matched_therapists = filter_therapists_by_availability(
                matched_therapists, client_data
            )
            logger.info(
                f"  After availability filtering: {len(matched_therapists)} therapists remain"
            )
        elif not availability_filtering_enabled:
            logger.info(
                "⏭️ [AVAILABILITY FILTERING] Skipped (disabled via environment variable)"
            )

        # Log final matching results from live database
        logger.info("=" * 60)
        logger.info("🎯 [FINAL MATCHING RESULTS - With Availability Filtering]")
        logger.info(
            f"  Client: {client_data.get('first_name')} {client_data.get('last_name')} ({client_data.get('email')})"
        )
        logger.info(
            f"  Criteria: {payment_type} | {client_state} | Gender: {client_data.get('therapist_identifies_as', 'any')}"
        )
        logger.info(
            f"  Total matched therapists (with availability): {len(matched_therapists)}"
        )

        if matched_therapists:
            logger.info("  📋 Matched therapists (from database):")
            for i, match in enumerate(matched_therapists, 1):
                t = match["therapist"]
                logger.info(f"    {i}. {t.get('intern_name')} ({t.get('email')})")
                logger.info(
                    f"       Program: {t.get('program')} | States: {t.get('states_array')} | Score: {match['score']}"
                )
                logger.info(
                    f"       Priority: {t.get('priority', 'low')} | Accepting: {t.get('accepting_new_clients')} | Capacity: {t.get('max_caseload')}"
                )
        else:
            logger.warning("  ❌ No therapists matched all criteria in database")

        logger.info("=" * 60)

        MatchingLogger.log_match_results(matched_therapists)

        # Log to Google Sheets - comprehensive logging with matching results
        try:
            # Prepare comprehensive data including matching results
            comprehensive_data = client_data.copy()

            # Add matching results
            if matched_therapists:
                top_match = matched_therapists[0]
                comprehensive_data.update(
                    {
                        "matched_therapist_id": top_match["therapist"].get("id"),
                        "matched_therapist_name": top_match["therapist"].get("name"),
                        "matched_therapist_email": top_match["therapist"]["email"],
                        "match_score": top_match["score"],
                        "therapists_matched_count": len(matched_therapists),
                    }
                )

            # Add matching metadata
            comprehensive_data.update(
                {
                    "matching_completed_at": datetime.utcnow().isoformat(),
                    "specialties_requested": client_data.get(
                        "therapist_specializes_in", []
                    ),
                    "client_state": client_state,
                    "payment_type": payment_type,
                }
            )

            # Add matched therapist data for Stage 1 logging
            if matched_therapists:
                top_match = matched_therapists[0]
                therapist_data = top_match.get("therapist", {})
                comprehensive_data.update(
                    {
                        "matched_therapist_id": therapist_data.get("id", ""),
                        "matched_therapist_name": therapist_data.get(
                            "intern_name", therapist_data.get("name", "")
                        ),
                        "matched_therapist_email": therapist_data.get("email", ""),
                        "match_score": top_match.get("score", 0),
                        "matched_specialties": ", ".join(
                            top_match.get("matched_diagnoses_specialities", [])
                        ),
                    }
                )

            # Stage 1: Log survey completion + therapist match (async)
            from src.services.google_sheets_progressive_logger import progressive_logger

            progressive_logger.async_log_stage_1(comprehensive_data)

        except Exception as e:
            logger.warning(f"Failed to log to Google Sheets (Stage 1): {e}")

        # Note: Removed journey_tracker calls - now handled by progressive logger

        # Store algorithm suggestions and alternatives in database
        try:
            if matched_therapists and len(matched_therapists) > 0:
                # Update client_response with algorithm suggested therapist and alternatives
                client_response = (
                    session.query(ClientResponse)
                    .filter(ClientResponse.id == response_id)
                    .first()
                )

                if client_response:
                    # Store algorithm's #1 suggested therapist
                    top_match = matched_therapists[0]
                    client_response.algorithm_suggested_therapist_id = top_match["therapist"].get("id")
                    client_response.algorithm_suggested_therapist_name = top_match["therapist"].get("name")
                    client_response.algorithm_suggested_therapist_score = float(top_match.get("score", 0))

                    # Store all alternatives as JSON (summary format: count + names)
                    alternative_names = []
                    alternative_ids = []
                    alternative_scores = []

                    for match in matched_therapists:
                        therapist = match.get("therapist", {})
                        alternative_names.append(therapist.get("name", "Unknown"))
                        alternative_ids.append(therapist.get("id", ""))
                        alternative_scores.append(float(match.get("score", 0)))

                    client_response.alternative_therapists_offered = {
                        "count": len(matched_therapists),
                        "names": alternative_names,
                        "ids": alternative_ids,
                        "scores": alternative_scores,
                    }

                    session.commit()
                    logger.info(f"✅ Stored algorithm suggestions: #1={top_match['therapist'].get('name')}, total={len(matched_therapists)}")

                    # Update comprehensive_data for Stage 2 logging
                    comprehensive_data["algorithm_suggested_therapist_id"] = client_response.algorithm_suggested_therapist_id
                    comprehensive_data["algorithm_suggested_therapist_name"] = client_response.algorithm_suggested_therapist_name
                    comprehensive_data["algorithm_suggested_therapist_score"] = client_response.algorithm_suggested_therapist_score
                    comprehensive_data["alternative_therapists_count"] = len(matched_therapists)
                    comprehensive_data["alternative_therapists_names"] = ", ".join(alternative_names)

        except Exception as e:
            logger.warning(f"Failed to store algorithm suggestions: {e}")
            import traceback
            traceback.print_exc()

        return jsonify(
            {
                "client": {
                    "id": client_data.get("id"),
                    "first_name": client_data.get("first_name"),
                    "last_name": client_data.get("last_name"),
                    "email": client_data.get("email"),
                    "response_id": response_id,
                    "state": client_state,
                },
                "therapists": matched_therapists,
            }
        )

    except Exception as e:
        logger.error(f"❌ [MATCH ERROR] {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": "Failed to match therapists"}), 500
    finally:
        session.close()


@therapists_bp.route("/therapists/select", methods=["POST"])
def select_therapist():
    """
    Record when a client selects a therapist (before booking).
    This updates the match_status to 'matched' and records the therapist info.
    """
    data = request.get_json() or {}
    response_id = data.get("response_id", "").strip()
    therapist_email = data.get("therapist_email", "").strip().lower()
    therapist_name = data.get("therapist_name", "").strip()

    if not response_id:
        return jsonify({"error": "response_id is required"}), 400

    if not therapist_email and not therapist_name:
        return jsonify({"error": "therapist_email or therapist_name is required"}), 400

    session = get_db_session()

    try:
        # Get client response
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        if not client_response:
            return jsonify({"error": "Client response not found"}), 404

        # Find therapist
        therapist = None
        if therapist_email:
            therapist = (
                session.query(Therapist)
                .filter(func.lower(Therapist.email) == therapist_email)
                .first()
            )

        if not therapist and therapist_name:
            therapist = (
                session.query(Therapist)
                .filter(Therapist.name == therapist_name)
                .first()
            )

        if not therapist:
            logger.warning(f"Therapist not found: {therapist_email} / {therapist_name}")
            # Still record the selection even if therapist not in DB
            client_response.match_status = "matched"
            client_response.matched_therapist_email = therapist_email
            client_response.matched_therapist_name = therapist_name
        else:
            # Record the match using the client's actual selection (not database override)
            client_response.match_status = "matched"
            client_response.matched_therapist_id = therapist.id
            # FIXED: Use the therapist data from the request, not the database
            # This preserves the user's actual selection (e.g., "Associate Test")
            client_response.matched_therapist_email = therapist_email  # From request
            client_response.matched_therapist_name = therapist_name    # From request

        client_response.updated_at = datetime.utcnow()
        session.commit()

        logger.info("=" * 50)
        logger.info("🎯 [THERAPIST SELECTED]")
        logger.info(f"  Response ID: {response_id}")
        logger.info(
            f"  Client: {client_response.first_name} {client_response.last_name}"
        )
        logger.info(f"  Therapist: {therapist_name} ({therapist_email})")
        logger.info(f"  Status: {client_response.match_status}")
        
        # DEBUG: Log what was stored vs what was requested
        logger.info(f"  🔍 STORED IN DB:")
        logger.info(f"    matched_therapist_name: {client_response.matched_therapist_name}")
        logger.info(f"    matched_therapist_email: {client_response.matched_therapist_email}")
        logger.info(f"  🔍 FROM REQUEST:")
        logger.info(f"    therapist_name: {therapist_name}")
        logger.info(f"    therapist_email: {therapist_email}")
        if therapist:
            logger.info(f"  🔍 DATABASE RECORD:")
            logger.info(f"    db_name: {therapist.name}")
            logger.info(f"    db_email: {therapist.email}")
        logger.info("=" * 50)

        return jsonify(
            {
                "success": True,
                "match_status": client_response.match_status,
                "therapist_id": client_response.matched_therapist_id,
                "therapist_email": client_response.matched_therapist_email,
                "therapist_name": client_response.matched_therapist_name,
            }
        )

    except Exception as e:
        session.rollback()
        logger.error(f"❌ [THERAPIST SELECTION ERROR] {str(e)}")
        return jsonify({"error": "Failed to record selection"}), 500
    finally:
        session.close()


@therapists_bp.route("/therapists/search", methods=["GET"])
def search_therapists():
    """Search for therapists by name or email."""
    q = (request.args.get("q") or "").strip()
    payment_type = (request.args.get("payment_type", "insurance") or "").strip().lower()
    state = (request.args.get("state") or "").strip().upper()

    logger.info(
        f"🔍 [THERAPIST SEARCH] Query: '{q}', Payment: '{payment_type}', State: '{state}'"
    )

    if not state:
        return jsonify({"therapists": []})

    # For initial load (empty query), return all eligible therapists
    is_initial_load = len(q) == 0

    # Insurance requires Limited Permit only, cash_pay allows graduate programs only
    eligible_programs = (
        ["MFT", "MHC", "MSW"] if payment_type == "cash_pay" else ["Limited Permit"]
    )

    session = get_db_session()
    try:
        accepting_filter = or_(
            func.lower(Therapist.accepting_new_clients) == "yes",
            func.lower(Therapist.accepting_new_clients) == "true",
            func.lower(Therapist.accepting_new_clients) == "checked",
            Therapist.accepting_new_clients == "1",
        )

        # Build base query
        base_query = session.query(Therapist).filter(
            and_(
                accepting_filter,
                Therapist.program.in_(eligible_programs),
                Therapist.states_array.contains([state]),
            )
        )

        if is_initial_load:
            # For initial load, return all eligible therapists (no search filter)
            therapists = base_query.limit(50).all()  # Increased limit for initial load
            logger.info(
                f"  Initial load: Found {len(therapists)} therapists for {payment_type} in {state}"
            )
        else:
            # For search, require at least 2 characters and apply search filter
            if len(q) < 2:
                return jsonify({"therapists": []})

            like_q = f"%{q.lower()}%"
            therapists = (
                base_query.filter(
                    or_(
                        func.lower(Therapist.name).like(like_q),
                        func.lower(Therapist.email).like(like_q),
                    )
                )
                .limit(10)
                .all()
            )
            logger.info(f"  Search query '{q}': Found {len(therapists)} therapists")

        return jsonify(
            {
                "therapists": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "email": t.email,
                        "program": t.program,
                        "states": t.states_array or [],
                    }
                    for t in therapists
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error in therapist search: {str(e)}")
        import traceback

        logger.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({"therapists": []}), 500
    finally:
        session.close()


@therapists_bp.route("/therapists/slots", methods=["GET"])
def get_therapist_slots():
    """Get available slots for a therapist."""
    from src.utils.state_utils import get_state_abbreviation, get_state_timezone

    try:
        from zoneinfo import ZoneInfo
    except Exception:
        ZoneInfo = None

    calendar_email = (request.args.get("email") or "").strip()
    if not calendar_email:
        return jsonify({"available_slots": []}), 400

    explicit_tz = (request.args.get("tz") or "").strip()
    explicit_state = get_state_abbreviation(request.args.get("state") or "")
    response_id = (request.args.get("response_id") or "").strip()

    tzname = None

    # Determine timezone
    if explicit_tz:
        tzname = explicit_tz
    elif explicit_state:
        tzname = get_state_timezone(explicit_state)
    elif response_id:
        try:
            with get_db() as session:
                cr = (
                    session.query(ClientResponse)
                    .filter(ClientResponse.id == response_id)
                    .first()
                )
                if cr and cr.state:
                    tzname = get_state_timezone(get_state_abbreviation(cr.state))
        except Exception:
            pass

    if not tzname:
        tzname = "US/Eastern"

    tz = ZoneInfo(tzname) if ZoneInfo else None

    # Get next 14 days of availability
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(days=14)

    # Get busy times from Google Calendar
    try:
        from src.utils.google.google_calendar import get_busy_events_from_gcalendar

        busy_data = get_busy_events_from_gcalendar(
            [calendar_email],
            time_min=now_utc.date().isoformat(),
            time_max=end_utc.date().isoformat(),
        )
        calendar_busy = (
            busy_data.get(calendar_email, {}).get("busy", []) if busy_data else []
        )
    except Exception as e:
        logger.error(f"Failed to fetch busy data for {calendar_email}: {e}")
        calendar_busy = []

    # Parse busy intervals
    def parse_iso(dt_str: str) -> datetime:
        s = dt_str[:-1] + "+00:00" if dt_str.endswith("Z") else dt_str
        try:
            return datetime.fromisoformat(s)
        except:
            return now_utc

    busy_intervals = []
    for b in calendar_busy:
        start = parse_iso(b.get("start"))
        end = parse_iso(b.get("end"))
        if start and end and end > start:
            busy_intervals.append((start, end))

    # Generate candidate slots
    slot_duration = timedelta(minutes=45)
    candidate_slots = []

    base_local = datetime.now(tz) if tz else datetime.now()
    for day_offset in range(14):
        local_date = (base_local + timedelta(days=day_offset)).date()
        if local_date.weekday() >= 5:  # Skip weekends
            continue

        for hour in range(9, 20):  # 9 AM to 7 PM
            for minute in (0, 30):
                if tz:
                    start_local = datetime(
                        local_date.year,
                        local_date.month,
                        local_date.day,
                        hour,
                        minute,
                        tzinfo=tz,
                    )
                    start_utc = start_local.astimezone(timezone.utc)
                else:
                    start_utc = datetime(
                        local_date.year,
                        local_date.month,
                        local_date.day,
                        hour,
                        minute,
                        tzinfo=timezone.utc,
                    )

                end_utc_slot = start_utc + slot_duration
                if start_utc < now_utc or end_utc_slot > end_utc:
                    continue
                candidate_slots.append(start_utc)

    candidate_slots = sorted(set(candidate_slots))

    # Filter out busy slots
    def overlaps_any_busy(start_dt: datetime, end_dt: datetime) -> bool:
        for b_start, b_end in busy_intervals:
            if start_dt < b_end and end_dt > b_start:
                return True
        return False

    available = []
    for s in candidate_slots:
        e = s + slot_duration
        if not overlaps_any_busy(s, e):
            available.append(s.isoformat())
            if len(available) >= 50:
                break

    return jsonify({"available_slots": available})


@therapists_bp.route("/therapists/assign", methods=["POST"])
def assign_therapist_to_client():
    """Mark a therapist as matched to a client."""
    data = request.get_json() or {}
    response_id = (data.get("response_id") or "").strip()
    therapist_email = (data.get("therapist_email") or "").strip().lower()
    therapist_id = (data.get("therapist_id") or "").strip()

    if not response_id:
        return jsonify({"error": "response_id is required"}), 400

    session = get_db_session()
    try:
        cr = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )
        if not cr:
            return jsonify({"error": "ClientResponse not found"}), 404

        t = None
        if therapist_id:
            t = session.query(Therapist).filter(Therapist.id == therapist_id).first()
        if t is None and therapist_email:
            t = (
                session.query(Therapist)
                .filter(func.lower(Therapist.email) == therapist_email)
                .first()
            )

        if not t:
            return jsonify({"error": "Therapist not found"}), 404

        cr.record_assignment(t)
        session.commit()

        return (
            jsonify(
                {
                    "ok": True,
                    "client_response_id": cr.id,
                    "match_status": cr.match_status,
                    "matched_therapist_email": cr.matched_therapist_email,
                    "matched_therapist_name": cr.matched_therapist_name,
                    "matched_therapist_id": cr.matched_therapist_id,
                }
            ),
            200,
        )
    except Exception as e:
        session.rollback()
        logger.error(f"/therapists/assign error: {e}")
        return jsonify({"error": "failed to assign therapist"}), 500
    finally:
        session.close()


@therapists_bp.route("/appointments/sync", methods=["POST"])
def sync_appointment_to_client_response():
    """Persist booking info into client_responses after an appointment is created."""
    payload = request.get_json() or {}
    response_id = (
        payload.get("ClientResponseId") or payload.get("client_response_id") or ""
    ).strip()

    if not response_id:
        return jsonify({"error": "ClientResponseId is required"}), 400

    practitioner_email = (
        (payload.get("PractitionerEmail") or payload.get("therapist_email") or "")
        .strip()
        .lower()
    )
    practitioner_name = (
        payload.get("PractitionerName") or payload.get("therapist_name") or ""
    ).strip()
    start_iso = (payload.get("StartDateIso") or payload.get("start") or "").strip()
    duration_min = int(payload.get("DurationMinutes") or 45)
    intakeq_client_id = payload.get("IntakeQClientId") or payload.get(
        "intakeq_client_id"
    )

    session = get_db_session()
    try:
        cr = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )
        if not cr:
            return jsonify({"error": "ClientResponse not found"}), 404

        # Resolve therapist
        t = None
        if practitioner_email:
            t = (
                session.query(Therapist)
                .filter(func.lower(Therapist.email) == practitioner_email)
                .first()
            )
        if t is None and practitioner_name:
            t = (
                session.query(Therapist)
                .filter(Therapist.name.ilike(practitioner_name))
                .first()
            )

        # Parse dates
        start_dt_utc = None
        end_dt_utc = None

        if start_iso:
            try:
                from datetime import datetime as dt
                from zoneinfo import ZoneInfo

                client_state_abbr = get_state_abbreviation(cr.state or "")
                tzname = get_state_timezone(client_state_abbr or "NY")

                naive = dt.fromisoformat(start_iso)
                if naive.tzinfo is None:
                    start_local = naive.replace(tzinfo=ZoneInfo(tzname))
                else:
                    start_local = naive.astimezone(ZoneInfo(tzname))

                end_local = start_local + timedelta(minutes=duration_min)
                start_dt_utc = start_local.astimezone(timezone.utc)
                end_dt_utc = end_local.astimezone(timezone.utc)
            except Exception as e:
                logger.warning(f"Failed to parse StartDateIso='{start_iso}': {e}")

        # Persist
        cr.record_booking(
            t, start_dt_utc, end_dt_utc, intakeq_client_id=intakeq_client_id
        )
        session.commit()

        return (
            jsonify(
                {
                    "ok": True,
                    "client_response_id": cr.id,
                    "match_status": cr.match_status,
                    "matched_therapist_email": cr.matched_therapist_email,
                    "matched_therapist_name": cr.matched_therapist_name,
                    "matched_therapist_id": cr.matched_therapist_id,
                    "matched_slot_start": cr.matched_slot_start.isoformat()
                    if cr.matched_slot_start
                    else None,
                    "matched_slot_end": cr.matched_slot_end.isoformat()
                    if cr.matched_slot_end
                    else None,
                    "intakeq_client_id": cr.intakeq_client_id,
                }
            ),
            200,
        )

    except Exception as e:
        session.rollback()
        logger.error(f"/appointments/sync error: {e}")
        return jsonify({"error": "failed to sync appointment"}), 500
    finally:
        session.close()


# ========== Admin Endpoints ==========


@therapists_bp.route("/admin/super-sync", methods=["POST"])
def super_sync():
    """Complete database rebuild from Airtable."""
    auth = request.headers.get("Authorization")
    if auth != "Bearer super-secret-1231":
        return {"error": "Unauthorized"}, 401

    from pyairtable import Table
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from src.db.models import Base, SyncLog, Therapist

    logger.info("🚀 SUPER SYNC INITIATED")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {"error": "DATABASE_URL not configured"}, 500

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    try:
        engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

        # Drop and recreate tables
        logger.info("💥 Dropping all tables...")
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables = [row[0] for row in result]

            for table in tables:
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                    logger.info(f"  - Dropped table: {table}")
                except Exception as e:
                    logger.error(f"  - Error dropping {table}: {e}")

        logger.info("🏗️ Creating fresh tables...")
        Base.metadata.create_all(bind=engine)

        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        sync_log = SyncLog(
            sync_type="super_sync", status="running", started_at=datetime.utcnow()
        )
        session.add(sync_log)
        session.commit()

        # Fetch from Airtable
        api_key = os.getenv("AIRTABLE_API_KEY")
        base_id = os.getenv("AIRTABLE_BASE_ID")
        table_id = os.getenv("AIRTABLE_TABLE_ID", "Therapists")

        if not api_key or not base_id:
            sync_log.status = "error"
            sync_log.error_message = "Missing Airtable credentials"
            sync_log.completed_at = datetime.utcnow()
            session.commit()
            return {"error": "Airtable credentials not configured"}, 500

        logger.info("☁️ Fetching from Airtable...")
        table = Table(api_key, base_id, table_id)
        airtable_records = table.all()
        logger.info(f"  - Found {len(airtable_records)} records")

        stats = {
            "total": len(airtable_records),
            "processed": 0,
            "created": 0,
            "skipped": 0,
            "errors": [],
        }

        seen_emails = set()

        for i, record in enumerate(airtable_records, 1):
            try:
                fields = record.get("fields", {})
                record_id = record["id"]

                email = fields.get("Email", "").strip().lower()
                name = fields.get("Name", "").strip()

                if not email or not name:
                    stats["skipped"] += 1
                    continue

                if email in seen_emails:
                    stats["skipped"] += 1
                    continue

                seen_emails.add(email)

                # Parse arrays
                states_raw = fields.get("States", "")
                states_array = (
                    [s.strip() for s in states_raw.split(",") if s.strip()]
                    if isinstance(states_raw, str)
                    else states_raw
                )

                diag_spec_raw = fields.get("Diagnoses + Specialties", "")
                diag_spec_array = (
                    [s.strip() for s in diag_spec_raw.split(",") if s.strip()]
                    if isinstance(diag_spec_raw, str)
                    else diag_spec_raw
                )

                # Create therapist
                therapist = Therapist(
                    id=record_id,
                    name=name,
                    email=email,
                    calendar=fields.get("Calendar", ""),
                    accepting_new_clients=fields.get("Accepting New Clients", ""),
                    cohort=fields.get("Cohort", ""),
                    program=fields.get("Program", ""),
                    max_caseload=int(fields.get("Max Caseload", 0) or 0),
                    current_caseload=float(fields.get("Current Caseload", 0) or 0),
                    states=fields.get("States", ""),
                    states_array=states_array,
                    priority=fields.get("Priority", "low"),  # New priority field
                    age=fields.get("Age", ""),
                    gender=fields.get("Gender", ""),
                    identities_as=fields.get("Identities as (Gender)", ""),
                    ethnicity=fields.get("Ethnicity", ""),
                    gender_experience=fields.get(
                        "Gender: Do you have experience and/or interest in working with individuals who do not identify as cisgender? (i.e. transgender, gender fluid, etc.) ",
                        "",
                    ),
                    sexual_orientation_experience=fields.get(
                        "Sexual Orientation: Do you have experience and/or interest in working with individuals who are part of the LGBTQ+ community?",
                        "",
                    ),
                    neurodivergence_experience=fields.get(
                        "Neurodivergence: Do you have experience and/or interest in working with individuals who are neurodivergent? ",
                        "",
                    ),
                    risk_experience=fields.get(
                        "Risk: Do you have experience and/or interest in working with higher-risk clients? ",
                        "",
                    ),
                    religion=fields.get(
                        "Religion: Please select the religions you have experience working with and/or understanding of. ",
                        "",
                    ),
                    diagnoses=fields.get(
                        "Diagnoses: Please select the diagnoses you have experience and/or interest in working with",
                        "",
                    ),
                    therapeutic_orientation=fields.get(
                        "Therapeutic Orientation: Please select the modalities you most frequently utilize. ",
                        "",
                    ),
                    internal_therapeutic_orientation=fields.get(
                        "(Internal) Therapeutic Orientation: Please select the modalities you most frequently utilize.",
                        "",
                    ),
                    specialities=fields.get(
                        "Specialities: Please select any specialities you have experience and/or interest in working with. ",
                        "",
                    ),
                    diagnoses_specialties=diag_spec_raw,
                    diagnoses_specialties_array=diag_spec_array,
                    social_media_affected=fields.get(
                        "Social Media: Have you ever been negatively affected by social media?",
                        "",
                    ),
                    family_household=fields.get(
                        "Traditional vs. Non-traditional family household", ""
                    ),
                    culture=fields.get("Individualist vs. Collectivist culture", ""),
                    places=fields.get("Many places or only one or two places?", ""),
                    immigration_background=fields.get("Immigration Background", ""),
                    has_children=fields.get("Children: Do you have children?", ""),
                    married=fields.get(
                        "Marriage: Are you / have ever been married?", ""
                    ),
                    caretaker_role=fields.get(
                        "Caretaker Role: Have you ever been in a caretaker role?", ""
                    ),
                    lgbtq_part=fields.get(
                        "LGBTQ+: Are you a part of the LGBTQ+ community?", ""
                    ),
                    performing_arts=fields.get(
                        "Performing/Visual Arts: Do you currently participate / have participated in any performing or visual art activities?",
                        "",
                    ),
                    intro_bio=fields.get("Intro Bios (Shortened)", ""),
                    welcome_video=fields.get("Welcome Video", ""),
                    last_modified=fields.get("Last Modified", ""),
                    first_generation=fields.get(
                        "Are you a first generation college student?", ""
                    ),
                    has_job=fields.get(
                        "Do you currently have a full-time or part-time job (apart from your internship)?",
                        "",
                    ),
                    calendar_synced=fields.get("Calendar Synced", ""),
                )

                session.add(therapist)
                stats["created"] += 1
                stats["processed"] += 1

                if i % 10 == 0:
                    session.commit()
                    logger.info(f"  Progress: {i}/{stats['total']} records")

            except Exception as e:
                error_msg = f"Error on record {i}: {str(e)}"
                logger.error(f"  ❌ {error_msg}")
                stats["errors"].append(error_msg[:200])
                session.rollback()
                continue

        session.commit()

        sync_log.status = "success" if len(stats["errors"]) == 0 else "partial"
        sync_log.completed_at = datetime.utcnow()
        sync_log.duration_seconds = (
            sync_log.completed_at - sync_log.started_at
        ).total_seconds()
        sync_log.records_processed = stats["processed"]
        sync_log.records_created = stats["created"]
        sync_log.error_message = (
            "\n".join(stats["errors"][:10]) if stats["errors"] else None
        )
        session.commit()

        logger.info("✅ SUPER SYNC COMPLETED")

        return jsonify(
            {
                "success": True,
                "message": "Super sync completed - database rebuilt from Airtable",
                "stats": stats,
                "duration_seconds": sync_log.duration_seconds,
            }
        )

    except Exception as e:
        logger.error(f"❌ SUPER SYNC FAILED: {str(e)}")
        return {"error": f"Super sync failed: {str(e)}"}, 500


@therapists_bp.route("/admin/test-matching", methods=["POST"])
def test_matching():
    """Test the matching algorithm with specific criteria."""
    auth = request.headers.get("Authorization")
    if auth != "Bearer super-secret-1231":
        return {"error": "Unauthorized"}, 401

    data = request.get_json() or {}
    test_state = data.get("state", "NY")
    test_payment = data.get("payment_type", "cash_pay")
    test_specialties = data.get("specialties", ["Anxiety", "Depression"])
    test_gender = data.get("gender_preference", "")

    session = get_db_session()

    try:
        logger.info(f"🧪 Testing matching for: {test_payment} client in {test_state}")

        # Determine eligible programs - insurance requires Limited Permit only
        if test_payment == "insurance":
            eligible_programs = ["Limited Permit"]
        else:
            eligible_programs = ["MFT", "MHC", "MSW"]

        logger.info(f"  Eligible programs: {eligible_programs}")

        # Build query
        query = session.query(Therapist).filter(
            and_(
                or_(
                    func.lower(Therapist.accepting_new_clients) == "yes",
                    func.lower(Therapist.accepting_new_clients) == "true",
                    func.lower(Therapist.accepting_new_clients) == "checked",
                    Therapist.accepting_new_clients == "1",
                ),
                Therapist.program.in_(eligible_programs),
                Therapist.states_array.op("&&")([test_state]),
            )
        )

        eligible_therapists = query.all()

        # Apply gender filter if specified
        if test_gender and test_gender not in ["no preference", "any", ""]:
            gender_filtered = []
            for t in eligible_therapists:
                t_gender = ((t.gender or t.identities_as) or "").lower()
                if test_gender == "male" and "male" in t_gender:
                    gender_filtered.append(t)
                elif test_gender == "female" and "female" in t_gender:
                    gender_filtered.append(t)
                elif test_gender in ["non-binary", "nonbinary"] and "non" in t_gender:
                    gender_filtered.append(t)
            eligible_therapists = gender_filtered

        results = {
            "test_criteria": {
                "state": test_state,
                "payment_type": test_payment,
                "eligible_programs": eligible_programs,
                "gender_preference": test_gender or "none",
                "requested_specialties": test_specialties,
            },
            "summary": {
                "total_eligible": len(eligible_therapists),
                "breakdown_by_program": {},
                "sample_therapists": [],
            },
        }

        # Count by program
        program_counts = {}
        for therapist in eligible_therapists:
            program = therapist.program or "Unknown"
            program_counts[program] = program_counts.get(program, 0) + 1
        results["summary"]["breakdown_by_program"] = program_counts

        # Get samples
        for therapist in eligible_therapists[:5]:
            results["summary"]["sample_therapists"].append(
                {
                    "name": therapist.name,
                    "email": therapist.email,
                    "program": therapist.program,
                    "states": therapist.states_array,
                    "accepting": therapist.accepting_new_clients,
                    "gender": therapist.gender or therapist.identities_as,
                    "specialties_count": len(
                        therapist.diagnoses_specialties_array or []
                    ),
                }
            )

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error in test matching: {str(e)}")
        return {"error": str(e)}, 500
    finally:
        session.close()


@therapists_bp.route("/admin/sync-status", methods=["GET"])
def sync_status():
    """Check the current sync status and database state."""
    auth = request.headers.get("Authorization")
    if auth != "Bearer super-secret-1231":
        return {"error": "Unauthorized"}, 401

    from src.db.models import ClientResponse, SyncLog

    session = get_db_session()

    try:
        status = {
            "database": {
                "therapists_total": session.query(Therapist).count(),
                "therapists_accepting": session.query(Therapist)
                .filter(Therapist.accepting_new_clients == "Yes")
                .count(),
                "client_responses": session.query(ClientResponse).count(),
            },
            "programs": {},
            "states_coverage": 0,
            "last_sync": None,
        }

        # Program distribution
        programs = (
            session.query(Therapist.program, func.count(Therapist.id).label("count"))
            .group_by(Therapist.program)
            .all()
        )

        for program, count in programs:
            status["programs"][program or "None"] = count

        # Count unique states
        therapists_with_states = (
            session.query(Therapist).filter(Therapist.states_array.isnot(None)).all()
        )

        unique_states = set()
        for t in therapists_with_states:
            if t.states_array:
                unique_states.update(t.states_array)
        status["states_coverage"] = len(unique_states)

        # Last sync info
        last_sync = session.query(SyncLog).order_by(SyncLog.started_at.desc()).first()

        if last_sync:
            status["last_sync"] = {
                "type": last_sync.sync_type,
                "status": last_sync.status,
                "started_at": last_sync.started_at.isoformat()
                if last_sync.started_at
                else None,
                "completed_at": last_sync.completed_at.isoformat()
                if last_sync.completed_at
                else None,
                "records_processed": last_sync.records_processed,
                "records_created": last_sync.records_created,
                "duration_seconds": last_sync.duration_seconds,
            }

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting sync status: {str(e)}")
        return {"error": str(e)}, 500
    finally:
        session.close()


@therapists_bp.route("/admin/refresh-therapists", methods=["POST"])
def refresh_therapists():
    """Lightweight refresh of therapists from Airtable - no data deletion."""
    auth = request.headers.get("Authorization")
    if auth != "Bearer super-secret-1231":
        return {"error": "Unauthorized"}, 401

    logger.info("🔄 Starting lightweight therapist refresh from API endpoint...")

    try:
        from pyairtable import Table

        from src.db.models import SyncLog

        # Create sync log
        session = get_db_session()
        sync_log = SyncLog(
            sync_type="therapist_refresh_api",
            status="running",
            started_at=datetime.utcnow(),
        )
        session.add(sync_log)
        session.commit()

        # Airtable setup
        api_key = os.getenv("AIRTABLE_API_KEY")
        base_id = os.getenv("AIRTABLE_BASE_ID")
        table_id = os.getenv("AIRTABLE_TABLE_ID", "Therapists")

        if not api_key or not base_id:
            sync_log.status = "error"
            sync_log.error_message = "Missing Airtable credentials"
            sync_log.completed_at = datetime.utcnow()
            session.commit()
            session.close()
            return {"error": "Airtable credentials not configured"}, 500

        logger.info("☁️ Fetching from Airtable...")
        table = Table(api_key, base_id, table_id)
        airtable_records = table.all()
        logger.info(f"  - Found {len(airtable_records)} records")

        # Stats tracking
        stats = {
            "total_airtable": len(airtable_records),
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
        }

        # Get existing therapists
        existing_therapists = {t.id: t for t in session.query(Therapist).all()}
        logger.info(f"  - Found {len(existing_therapists)} existing therapists")

        seen_emails = set()

        # Process records
        for i, record in enumerate(airtable_records, 1):
            try:
                fields = record.get("fields", {})
                record_id = record["id"]

                email = fields.get("Email", "").strip().lower()
                name = fields.get("Name", "").strip()

                if not email or not name:
                    stats["skipped"] += 1
                    continue

                if email in seen_emails:
                    stats["skipped"] += 1
                    continue

                seen_emails.add(email)

                # Parse arrays
                states_raw = fields.get("States", "")
                states_array = (
                    [s.strip() for s in states_raw.split(",") if s.strip()]
                    if isinstance(states_raw, str) and states_raw
                    else (states_raw if isinstance(states_raw, list) else [])
                )

                diag_spec_raw = fields.get("Diagnoses + Specialties", "")
                diag_spec_array = (
                    [s.strip() for s in diag_spec_raw.split(",") if s.strip()]
                    if isinstance(diag_spec_raw, str) and diag_spec_raw
                    else (diag_spec_raw if isinstance(diag_spec_raw, list) else [])
                )

                existing_therapist = existing_therapists.get(record_id)

                if existing_therapist:
                    # Update existing
                    existing_therapist.name = name
                    existing_therapist.email = email
                    existing_therapist.calendar = fields.get("Calendar", "")
                    existing_therapist.accepting_new_clients = fields.get(
                        "Accepting New Clients", ""
                    )
                    existing_therapist.cohort = fields.get("Cohort", "")
                    existing_therapist.program = fields.get("Program", "")
                    existing_therapist.max_caseload = int(
                        fields.get("Max Caseload", 0) or 0
                    )
                    existing_therapist.current_caseload = float(
                        fields.get("Current Caseload", 0) or 0
                    )
                    existing_therapist.states = fields.get("States", "")
                    existing_therapist.states_array = states_array
                    existing_therapist.priority = fields.get("Priority", "low")
                    existing_therapist.age = fields.get("Age", "")
                    existing_therapist.gender = fields.get("Gender", "")
                    existing_therapist.identities_as = fields.get(
                        "Identities as (Gender)", ""
                    )
                    existing_therapist.ethnicity = fields.get("Ethnicity", "")
                    existing_therapist.diagnoses_specialties = diag_spec_raw
                    existing_therapist.diagnoses_specialties_array = diag_spec_array
                    existing_therapist.intro_bio = fields.get("Intro Bios (Shortened)", "")
                    existing_therapist.welcome_video = fields.get("Welcome Video", "")
                    existing_therapist.last_modified = fields.get("Last Modified", "")
                    existing_therapist.first_generation = fields.get(
                        "Are you a first generation college student?", ""
                    )
                    existing_therapist.has_job = fields.get(
                        "Do you currently have a full-time or part-time job (apart from your internship)?",
                        "",
                    )
                    existing_therapist.calendar_synced = fields.get("Calendar Synced", "")

                    stats["updated"] += 1

                else:
                    # Create new
                    new_therapist = Therapist(
                        id=record_id,
                        name=name,
                        email=email,
                        calendar=fields.get("Calendar", ""),
                        accepting_new_clients=fields.get("Accepting New Clients", ""),
                        cohort=fields.get("Cohort", ""),
                        program=fields.get("Program", ""),
                        max_caseload=int(fields.get("Max Caseload", 0) or 0),
                        current_caseload=float(fields.get("Current Caseload", 0) or 0),
                        states=fields.get("States", ""),
                        states_array=states_array,
                        priority=fields.get("Priority", "low"),
                        age=fields.get("Age", ""),
                        gender=fields.get("Gender", ""),
                        identities_as=fields.get("Identities as (Gender)", ""),
                        ethnicity=fields.get("Ethnicity", ""),
                        diagnoses_specialties=diag_spec_raw,
                        diagnoses_specialties_array=diag_spec_array,
                        intro_bio=fields.get("Intro Bios (Shortened)", ""),
                        welcome_video=fields.get("Welcome Video", ""),
                        last_modified=fields.get("Last Modified", ""),
                        first_generation=fields.get(
                            "Are you a first generation college student?", ""
                        ),
                        has_job=fields.get(
                            "Do you currently have a full-time or part-time job (apart from your internship)?",
                            "",
                        ),
                        calendar_synced=fields.get("Calendar Synced", "")
                    )

                    session.add(new_therapist)
                    stats["created"] += 1

                stats["processed"] += 1

                if i % 10 == 0:
                    session.commit()
                    logger.info(f"  Progress: {i}/{stats['total_airtable']}")

            except Exception as e:
                error_msg = f"Error on record {i}: {str(e)}"
                logger.error(f"  ❌ {error_msg}")
                stats["errors"].append(error_msg[:200])
                continue

        # Final commit
        session.commit()

        # Update sync log
        sync_log.status = "success" if len(stats["errors"]) == 0 else "partial"
        sync_log.completed_at = datetime.utcnow()
        sync_log.duration_seconds = (
            sync_log.completed_at - sync_log.started_at
        ).total_seconds()
        sync_log.records_processed = stats["processed"]
        sync_log.records_created = stats["created"]
        sync_log.error_message = (
            "\n".join(stats["errors"][:10]) if stats["errors"] else None
        )
        session.commit()

        logger.info("✅ API therapist refresh completed!")

        return jsonify(
            {
                "success": True,
                "message": "Therapist refresh completed (no data deleted)",
                "stats": stats,
                "duration_seconds": sync_log.duration_seconds,
            }
        )

    except Exception as e:
        logger.error(f"❌ API therapist refresh failed: {str(e)}")
        return {"error": f"Refresh failed: {str(e)}"}, 500
    finally:
        if "session" in locals():
            session.close()


@therapists_bp.route("/therapists/available-states", methods=["GET"])
def get_available_states():
    """
    Get list of states where therapists are available and accepting new clients.
    Supports filtering by payment type (cash_pay vs insurance).
    """
    session = get_db_session()
    try:
        payment_type = (
            (request.args.get("payment_type", "cash_pay") or "").strip().lower()
        )

        logger.info(
            f"🌍 [AVAILABLE STATES] Getting states for payment_type: {payment_type}"
        )

        # Determine eligible programs based on payment type - insurance requires Limited Permit only
        if payment_type == "insurance":
            eligible_programs = ["Limited Permit"]
        else:  # cash_pay
            eligible_programs = ["MFT", "MHC", "MSW"]

        # Query therapists with the right program types who are accepting new clients
        query = session.query(Therapist).filter(
            and_(
                Therapist.program.in_(eligible_programs),
                or_(
                    func.lower(Therapist.accepting_new_clients) == "yes",
                    func.lower(Therapist.accepting_new_clients) == "true",
                    func.lower(Therapist.accepting_new_clients) == "checked",
                    Therapist.accepting_new_clients == "1",
                    func.lower(Therapist.accepting_new_clients) == "t",
                    func.lower(Therapist.accepting_new_clients) == "y",
                ),
                Therapist.max_caseload > 0,
                Therapist.states_array.isnot(None),
            )
        )

        accepting_therapists = query.all()

        # Extract unique states from accepting therapists
        available_states = set()
        state_therapist_count = {}

        for therapist in accepting_therapists:
            if therapist.states_array:
                for state in therapist.states_array:
                    state_code = get_state_abbreviation(state)
                    if state_code:
                        available_states.add(state_code)
                        state_therapist_count[state_code] = (
                            state_therapist_count.get(state_code, 0) + 1
                        )

        # Convert to sorted list for consistent ordering
        available_states_list = sorted(list(available_states))

        result = {
            "payment_type": payment_type,
            "available_states": available_states_list,
            "state_counts": state_therapist_count,
            "total_states": len(available_states_list),
            "total_therapists": len(accepting_therapists),
        }

        logger.info(
            f"✅ [AVAILABLE STATES] Found {len(available_states_list)} states with {len(accepting_therapists)} therapists"
        )
        logger.info(f"  States: {', '.join(available_states_list)}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting available states: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
