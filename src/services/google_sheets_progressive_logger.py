"""
Progressive Google Sheets Logger for Sol Health

Handles 4-stage progressive logging throughout the user journey:
0. Stage 0: Immediate Nirvana response logging (NEW - truly progressive)
1. Stage 1: After survey completion + therapist match + IntakeQ creation  
2. Stage 2: After therapist confirmation
3. Stage 3: After booking completion (comprehensive final data)

Consolidates functionality from:
- google_sheets.py (comprehensive field mapping)
- journey_tracker.py (progressive updates)
"""
import base64
import json
import logging
import os
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print(
        "Google API client not installed. Run: pip install google-api-python-client google-auth"
    )
    Credentials = None
    build = None
    HttpError = Exception

logger = logging.getLogger(__name__)


class GoogleSheetsProgressiveLogger:
    """
    Progressive logging service for comprehensive user journey tracking.

    Updates a single row per user across 3 stages of their journey.
    """

    def __init__(self):
        self.sheet_id = os.getenv("GOOGLE_SHEETS_ID")
        self.sheet_name = os.getenv(
            "GOOGLE_SHEET_NAME", "All Journeys"
        )  # Use correct sheet tab name
        self.service = None
        self._working_range_format = None  # Cache the working range format

        # Check if we have any credentials available
        has_credentials = (
            os.getenv("GOOGLE_CREDENTIALS_JSON")
            or os.getenv("GOOGLE_CREDENTIALS_JSON_B64")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )

        self.enabled = bool(self.sheet_id and has_credentials and Credentials)

        if self.enabled:
            try:
                self._initialize_service()
            except Exception as e:
                logger.error(
                    f"Failed to initialize Google Sheets progressive logger: {e}"
                )
                self.enabled = False
        else:
            logger.info(
                "Google Sheets progressive logging disabled - missing sheet_id or credentials or dependencies"
            )

    def _initialize_service(self):
        """Initialize Google Sheets service with service account credentials"""
        try:
            credentials = self._get_credentials()
            self.service = build(
                "sheets", "v4", credentials=credentials, cache_discovery=False
            )
            logger.info("Google Sheets progressive logger initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            self.enabled = False

    def _get_credentials(self):
        """Get Google credentials using multiple fallback methods"""
        raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        b64 = os.getenv("GOOGLE_CREDENTIALS_JSON_B64", "").strip()
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]

        if raw:
            try:
                info = json.loads(raw)
                return Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON: {e}")

        if b64:
            try:
                decoded = base64.b64decode(b64).decode("utf-8")
                info = json.loads(decoded)
                return Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON_B64: {e}")

        if path:
            try:
                return Credentials.from_service_account_file(path, scopes=scopes)
            except Exception as e:
                logger.error(f"Failed reading GOOGLE_APPLICATION_CREDENTIALS: {e}")

        # Fallback to credentials utility if available
        try:
            from src.utils.google.credentials import get_credentials

            creds = get_credentials()
            if creds:
                # Recreate with correct scopes for Sheets
                if hasattr(creds, "_service_account_info"):
                    return Credentials.from_service_account_info(
                        creds._service_account_info, scopes=scopes
                    )
        except ImportError:
            pass

        raise RuntimeError("No Google credentials found for Sheets service")

    def _build_range(self, range_spec: str) -> str:
        """Build a range string using the cached working format, or try multiple formats"""
        if self._working_range_format:
            return f"{self._working_range_format}!{range_spec}"
        else:
            # Default format if no working format cached yet
            return f"{self.sheet_name}!{range_spec}"

    def _get_comprehensive_headers(self) -> List[str]:
        """Get comprehensive header row for Google Sheets (83+ fields)"""
        return [
            # Journey Tracking
            "journey_id",
            "stage_completed",  # "1", "2", or "3"
            "stage_1_timestamp",
            "stage_2_timestamp",
            "stage_3_timestamp",
            "last_updated",
            # Basic User Information (11)
            "response_id",
            "email",
            "first_name",
            "last_name",
            "preferred_name",
            "middle_name",
            "phone",
            "mobile_phone",
            "date_of_birth",
            "age",
            "gender",
            # Address & Location (10) - Enhanced with Nirvana data
            "street_address",
            "city",
            "state",
            "postal_code",
            "country",
            # Nirvana Enhanced Address Fields
            "nirvana_street_line_1",
            "nirvana_street_line_2",
            "nirvana_city",
            "nirvana_state",
            "nirvana_zip",
            # Demographics & Background (5)
            "marital_status",
            "race_ethnicity",
            "lived_experiences",
            "university",
            "referred_by",
            # PHQ-9 Assessment (10)
            "phq9_pleasure_doing_things",
            "phq9_feeling_down",
            "phq9_trouble_falling",
            "phq9_feeling_tired",
            "phq9_poor_appetite",
            "phq9_feeling_bad_about_yourself",
            "phq9_trouble_concentrating",
            "phq9_moving_or_speaking_so_slowly",
            "phq9_suicidal_thoughts",
            "phq9_total_score",
            # GAD-7 Assessment (8)
            "gad7_feeling_nervous",
            "gad7_not_control_worrying",
            "gad7_worrying_too_much",
            "gad7_trouble_relaxing",
            "gad7_being_so_restless",
            "gad7_easily_annoyed",
            "gad7_feeling_afraid",
            "gad7_total_score",
            # Substance Use (2)
            "alcohol_frequency",
            "recreational_drugs_frequency",
            # Therapist Preferences (3)
            "therapist_gender_preference",
            "therapist_specialization",
            "therapist_lived_experiences",
            # Payment & Insurance (20)
            "payment_type",
            "insurance_provider",
            "insurance_member_id",
            "insurance_date_of_birth",
            "copay",
            "deductible",
            "coinsurance",
            "out_of_pocket_max",
            "remaining_deductible",
            "remaining_oop_max",
            "member_obligation",
            "benefit_structure",
            "session_cost_dollars",
            "payer_id",
            # Enhanced Nirvana Insurance Fields
            "nirvana_plan_name",
            "nirvana_group_id",
            "nirvana_payer_id",
            "nirvana_plan_status",
            "nirvana_coverage_status",
            "nirvana_relationship_to_subscriber",
            "nirvana_insurance_type",
            # Nirvana Insurance Details
            "nirvana_insurance_company_name",
            "nirvana_member_id_policy_number",
            "nirvana_group_number",
            "nirvana_plan_program",
            # Nirvana Policyholder Demographics (separate from patient demographics)
            "nirvana_policyholder_relationship",  # "self" or "child"
            "nirvana_policyholder_name",
            "nirvana_policyholder_first_name", 
            "nirvana_policyholder_last_name",
            "nirvana_policyholder_street_address",
            "nirvana_policyholder_city",
            "nirvana_policyholder_state", 
            "nirvana_policyholder_zip_code",
            "nirvana_policyholder_date_of_birth",
            "nirvana_policyholder_sex",
            # Matched Therapist Data (8) - Available from Stage 1
            "matched_therapist_id",
            "matched_therapist_name",
            "matched_therapist_email",
            "match_score",
            "matched_specialties",
            "therapist_confirmed",  # Stage 2
            "therapist_confirmation_timestamp",  # Stage 2
            "alternative_therapists_offered",  # Stage 2
            # Appointment Data (8) - Available from Stage 3
            "appointment_date",
            "appointment_time",
            "appointment_timezone",
            "appointment_duration",
            "appointment_type",
            "appointment_id",
            "google_event_id",
            "appointment_status",
            # IntakeQ Data (6) - Available from Stage 3
            "intakeq_client_id",
            "intakeq_intake_url",
            "mandatory_form_sent",
            "mandatory_form_intake_id",
            "mandatory_form_intake_url",
            "mandatory_form_sent_at",
            # Additional Context (3)
            "safety_screening",
            "matching_preference",
            "what_brings_you",
            # Tracking Data (10)
            "sol_health_response_id",
            "onboarding_completed_at",
            "survey_completed_at",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "signup_timestamp",
            "completion_timestamp",
            "user_agent",
            "ip_address",
            # System Metadata (5)
            "environment",
            "api_version",
            "frontend_version",
            "created_at",
            "updated_at",
            
            # Additional Nirvana Fields (comprehensive capture)
            "nirvana_verification_timestamp",
            "nirvana_verification_status", 
            "nirvana_insurance_company_name",
            "nirvana_member_id_policy_number",
            "nirvana_group_number",
            "nirvana_plan_program",
            "nirvana_insurance_type",
            "nirvana_eligibility_end_date",
            "nirvana_plan_begin_date",
            "nirvana_plan_end_date",
            
            # Enhanced Financial Fields
            "copay_dollars",
            "deductible_dollars", 
            "remaining_deductible_dollars",
            "oop_max_dollars",
            "remaining_oop_max_dollars",
            "member_obligation_dollars",
            "payer_obligation_dollars",
            "session_cost_dollars",
            
            # Telehealth Fields
            "telehealth_copay",
            "telehealth_member_obligation",
            "sessions_before_deductible_met",
            "sessions_before_oop_max_met",
            
            # Raw Data Storage (for audit trail)
            "nirvana_raw_response_excerpt",
            "data_sources_used",
            "fields_extracted_count",
        ]

    def _ensure_header_row(self):
        """Ensure the Google Sheet has the correct header row"""
        if not self.enabled:
            return False

        try:
            # Use only the working sheet range format
            sheet_range_attempts = [
                "All Journeys!1:1",  # Primary working sheet tab
            ]

            result = None
            last_error = None

            for attempt_range in sheet_range_attempts:
                try:
                    logger.info(f"📊 Trying range format: {attempt_range}")
                    result = (
                        self.service.spreadsheets()
                        .values()
                        .get(spreadsheetId=self.sheet_id, range=attempt_range)
                        .execute()
                    )
                    logger.info(f"✅ Success with range format: {attempt_range}")
                    # Update the working format for future use
                    self._working_range_format = attempt_range.split("!")[0]
                    break
                except Exception as e:
                    logger.info(f"❌ Failed with range {attempt_range}: {str(e)}")
                    last_error = e
                    continue

            if result is None:
                raise last_error or Exception("All range formats failed")

            values = result.get("values", [])
            headers = self._get_comprehensive_headers()

            if not values or values[0] != headers:
                # Write/update header row
                update_range = self._build_range("1:1")

                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=update_range,
                    valueInputOption="RAW",
                    body={"values": [headers]},
                ).execute()
                logger.info("Google Sheets header row updated")

            return True

        except Exception as e:
            logger.error(f"Failed to ensure header row: {e}")
            return False

    def _flatten_data_progressive(self, data: Dict[str, Any], stage: int) -> List[Any]:
        """Convert user data to flat row format for progressive updates"""

        # Helper function to safely get nested values
        def safe_get(obj, *keys):
            for key in keys:
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    return ""
            return obj if obj is not None else ""

        # Helper to convert arrays to comma-separated strings
        def array_to_string(arr):
            if isinstance(arr, list):
                return ", ".join(str(x) for x in arr if x)
            return str(arr) if arr else ""
        
        # Helper to convert insurance names from ALL CAPS to Title Case
        def format_insurance_name(name):
            if not name or not isinstance(name, str):
                return name
            # Convert from "AETNA BETTER HEALTH" to "Aetna Better Health"
            return name.title() if name.isupper() else name

        now = datetime.utcnow().isoformat()
        headers = self._get_comprehensive_headers()
        row_data = [""] * len(headers)  # Initialize with empty strings

        # Always update these fields
        journey_tracking_data = {
            "stage_completed": str(stage),
            "last_updated": now,
            f"stage_{stage}_timestamp": now,
        }

        # Stage-specific data mapping
        if stage == 0:
            # Stage 0: Immediate Nirvana response logging (minimal core data + Nirvana)
            stage_0_data = {
                # Essential identification
                "response_id": safe_get(data, "response_id"),
                "email": safe_get(data, "email"),
                "first_name": safe_get(data, "first_name"),
                "last_name": safe_get(data, "last_name"),
                "phone": safe_get(data, "phone"),
                "date_of_birth": safe_get(data, "date_of_birth"),
                "gender": safe_get(data, "gender"),
                "state": safe_get(data, "state"),
                
                # Payment type for routing
                "payment_type": safe_get(data, "payment_type"),
                
                # Insurance provider (user input before Nirvana correction)
                "insurance_provider": safe_get(data, "insurance_provider"),
                "insurance_member_id": safe_get(data, "insurance_member_id"),
                
                # Nirvana verification timestamp
                "nirvana_verification_timestamp": now,
                "nirvana_verification_status": "SUCCESS" if safe_get(data, "nirvana_data") else "FAILED",
                
                # All Nirvana insurance data (immediate logging priority)
                "copay": safe_get(data, "copay"),
                "deductible": safe_get(data, "deductible"), 
                "coinsurance": safe_get(data, "coinsurance"),
                "out_of_pocket_max": safe_get(data, "out_of_pocket_max"),
                "remaining_deductible": safe_get(data, "remaining_deductible"),
                "remaining_oop_max": safe_get(data, "remaining_oop_max"),
                "member_obligation": safe_get(data, "member_obligation"),
                "benefit_structure": safe_get(data, "benefit_structure"),
                "session_cost_dollars": safe_get(data, "session_cost_dollars"),
                "payer_id": safe_get(data, "payer_id"),
                
                # Nirvana plan details
                "nirvana_plan_name": safe_get(data, "nirvana_data", "plan_name"),
                "nirvana_plan_status": safe_get(data, "nirvana_data", "plan_status"),
                "nirvana_coverage_status": safe_get(data, "nirvana_data", "coverage_status"),
                "nirvana_mental_health_coverage": safe_get(data, "nirvana_data", "mental_health_coverage"),
                
                # Insurance provider correction tracking
                "insurance_provider_original": safe_get(data, "insurance_provider_original"),
                "insurance_provider_corrected": safe_get(data, "insurance_provider_corrected"),
                "insurance_provider_was_corrected": safe_get(data, "insurance_provider_was_corrected"),
                "insurance_provider_correction_type": safe_get(data, "insurance_provider_correction_type"),
                "insurance_provider_validation_status": safe_get(data, "insurance_provider_validation_status"),
                
                # Core timestamps for Stage 0
                "created_at": now,
                "stage": "0_nirvana_verified",
                
                # Comprehensive data capture audit
                "nirvana_verification_timestamp": now,
                "nirvana_verification_status": "SUCCESS" if safe_get(data, "nirvana_data") else "FAILED",
                "data_sources_used": ", ".join(safe_get(data, "_data_sources_found") or []),
                "fields_extracted_count": safe_get(data, "_fields_extracted") or 0,
                "nirvana_raw_response_excerpt": str(safe_get(data, "nirvana_data"))[:200] + "..." if safe_get(data, "nirvana_data") else "",
                
                # Enhanced financial fields (dollar conversions)
                "copay_dollars": safe_get(data, "copay_dollars") or (int(safe_get(data, "copay") or 0) / 100 if safe_get(data, "copay") else ""),
                "deductible_dollars": safe_get(data, "deductible_dollars") or (int(safe_get(data, "deductible") or 0) / 100 if safe_get(data, "deductible") else ""),
                "remaining_deductible_dollars": safe_get(data, "remaining_deductible_dollars") or (int(safe_get(data, "remaining_deductible") or 0) / 100 if safe_get(data, "remaining_deductible") else ""),
                "member_obligation_dollars": safe_get(data, "member_obligation_dollars") or (int(safe_get(data, "member_obligation") or 0) / 100 if safe_get(data, "member_obligation") else ""),
                
                # Additional Nirvana fields
                "nirvana_insurance_type": safe_get(data, "insurance_type") or safe_get(data, "nirvana_data", "insurance_type"),
                "nirvana_plan_begin_date": safe_get(data, "plan_begin_date") or safe_get(data, "nirvana_data", "plan_begin_date"),
                "nirvana_plan_end_date": safe_get(data, "plan_end_date") or safe_get(data, "nirvana_data", "plan_end_date"),
                "nirvana_eligibility_end_date": safe_get(data, "eligibility_end_date") or safe_get(data, "nirvana_data", "eligibility_end_date"),
            }
            journey_tracking_data.update(stage_0_data)
            
        if stage >= 1:
            # Stage 1: Survey completion + initial match
            stage_1_data = {
                # Basic User Information
                "response_id": safe_get(data, "response_id"),
                "email": safe_get(data, "email"),
                "first_name": safe_get(data, "first_name"),
                "last_name": safe_get(data, "last_name"),
                "preferred_name": safe_get(data, "preferred_name"),
                "middle_name": safe_get(data, "middle_name"),
                "phone": safe_get(data, "phone"),
                "mobile_phone": safe_get(data, "mobile_phone"),
                "date_of_birth": safe_get(data, "date_of_birth"),
                "age": safe_get(data, "age"),
                "gender": safe_get(data, "gender"),
                # Address & Location (with Nirvana priority)
                "street_address": safe_get(data, "street_address"),
                "city": safe_get(data, "city"),
                "state": safe_get(data, "state"),
                "postal_code": safe_get(data, "postal_code"),
                "country": safe_get(data, "country"),
                # Enhanced Nirvana Address Fields
                "nirvana_street_line_1": safe_get(
                    data, "nirvana_data", "demographics", "address", "street_line_1"
                ),
                "nirvana_street_line_2": safe_get(
                    data, "nirvana_data", "demographics", "address", "street_line_2"
                ),
                "nirvana_city": safe_get(
                    data, "nirvana_data", "demographics", "address", "city"
                ),
                "nirvana_state": safe_get(
                    data, "nirvana_data", "demographics", "address", "state"
                ),
                "nirvana_zip": safe_get(
                    data, "nirvana_data", "demographics", "address", "zip"
                ),
                # Demographics & Background
                "marital_status": safe_get(data, "marital_status"),
                "race_ethnicity": array_to_string(safe_get(data, "race_ethnicity")),
                "lived_experiences": array_to_string(
                    safe_get(data, "lived_experiences")
                ),
                "university": safe_get(data, "university"),
                "referred_by": safe_get(data, "referred_by"),
                # PHQ-9 Assessment
                "phq9_pleasure_doing_things": safe_get(
                    data, "phq9_scores", "pleasure_doing_things"
                ),
                "phq9_feeling_down": safe_get(data, "phq9_scores", "feeling_down"),
                "phq9_trouble_falling": safe_get(
                    data, "phq9_scores", "trouble_falling"
                ),
                "phq9_feeling_tired": safe_get(data, "phq9_scores", "feeling_tired"),
                "phq9_poor_appetite": safe_get(data, "phq9_scores", "poor_appetite"),
                "phq9_feeling_bad_about_yourself": safe_get(
                    data, "phq9_scores", "feeling_bad_about_yourself"
                ),
                "phq9_trouble_concentrating": safe_get(
                    data, "phq9_scores", "trouble_concentrating"
                ),
                "phq9_moving_or_speaking_so_slowly": safe_get(
                    data, "phq9_scores", "moving_or_speaking_so_slowly"
                ),
                "phq9_suicidal_thoughts": safe_get(
                    data, "phq9_scores", "suicidal_thoughts"
                ),
                "phq9_total_score": safe_get(data, "phq9_total_score"),
                # GAD-7 Assessment
                "gad7_feeling_nervous": safe_get(
                    data, "gad7_scores", "feeling_nervous"
                ),
                "gad7_not_control_worrying": safe_get(
                    data, "gad7_scores", "not_control_worrying"
                ),
                "gad7_worrying_too_much": safe_get(
                    data, "gad7_scores", "worrying_too_much"
                ),
                "gad7_trouble_relaxing": safe_get(
                    data, "gad7_scores", "trouble_relaxing"
                ),
                "gad7_being_so_restless": safe_get(
                    data, "gad7_scores", "being_so_restless"
                ),
                "gad7_easily_annoyed": safe_get(data, "gad7_scores", "easily_annoyed"),
                "gad7_feeling_afraid": safe_get(data, "gad7_scores", "feeling_afraid"),
                "gad7_total_score": safe_get(data, "gad7_total_score"),
                # Substance Use
                "alcohol_frequency": safe_get(data, "alcohol_frequency"),
                "recreational_drugs_frequency": safe_get(
                    data, "recreational_drugs_frequency"
                ),
                # Therapist Preferences
                "therapist_gender_preference": safe_get(
                    data, "therapist_gender_preference"
                ),
                "therapist_specialization": array_to_string(
                    safe_get(data, "therapist_specialization")
                ),
                "therapist_lived_experiences": array_to_string(
                    safe_get(data, "therapist_lived_experiences")
                ),
                # Payment & Insurance
                "payment_type": safe_get(data, "payment_type"),
                # Prioritize Nirvana's plan_name over user's insurance_provider selection
                "insurance_provider": format_insurance_name(
                    safe_get(data, "nirvana_data", "plan_name") or safe_get(data, "insurance_provider")
                ),
                "insurance_member_id": safe_get(data, "insurance_member_id"),
                "insurance_date_of_birth": safe_get(data, "insurance_date_of_birth"),
                "copay": safe_get(data, "copay"),
                "deductible": safe_get(data, "deductible"),
                "coinsurance": safe_get(data, "coinsurance"),
                "out_of_pocket_max": safe_get(data, "out_of_pocket_max"),
                "remaining_deductible": safe_get(data, "remaining_deductible"),
                "remaining_oop_max": safe_get(data, "remaining_oop_max"),
                "member_obligation": safe_get(data, "member_obligation"),
                "benefit_structure": safe_get(data, "benefit_structure"),
                "session_cost_dollars": safe_get(data, "session_cost_dollars"),
                "payer_id": safe_get(data, "payer_id"),
                # Enhanced Nirvana Insurance Fields
                "nirvana_plan_name": safe_get(data, "nirvana_data", "plan_name"),
                "nirvana_group_id": safe_get(data, "nirvana_data", "group_id"),
                "nirvana_payer_id": safe_get(data, "nirvana_data", "payer_id"),
                "nirvana_plan_status": safe_get(data, "nirvana_data", "plan_status"),
                "nirvana_coverage_status": safe_get(
                    data, "nirvana_data", "coverage_status"
                ),
                "nirvana_relationship_to_subscriber": safe_get(
                    data, "nirvana_data", "relationship_to_subscriber"
                ),
                "nirvana_insurance_type": safe_get(
                    data, "nirvana_data", "insurance_type"
                ),
                # Nirvana Insurance Details
                "nirvana_insurance_company_name": safe_get(data, "nirvana_data", "plan_name"),
                "nirvana_member_id_policy_number": safe_get(data, "nirvana_data", "demographics", "member_id"),
                "nirvana_group_number": safe_get(data, "nirvana_data", "group_id"),
                "nirvana_plan_program": safe_get(data, "nirvana_data", "plan_name"),
                # Nirvana Policyholder Demographics (subscriber demographics)
                "nirvana_policyholder_relationship": safe_get(data, "nirvana_data", "relationship_to_subscriber"),
                "nirvana_policyholder_name": f"{safe_get(data, 'nirvana_data', 'subscriber_demographics', 'first_name', '') or ''} {safe_get(data, 'nirvana_data', 'subscriber_demographics', 'last_name', '') or ''}".strip(),
                "nirvana_policyholder_first_name": safe_get(data, "nirvana_data", "subscriber_demographics", "first_name"),
                "nirvana_policyholder_last_name": safe_get(data, "nirvana_data", "subscriber_demographics", "last_name"),
                "nirvana_policyholder_street_address": safe_get(data, "nirvana_data", "subscriber_demographics", "address", "street_line_1"),
                "nirvana_policyholder_city": safe_get(data, "nirvana_data", "subscriber_demographics", "address", "city"),
                "nirvana_policyholder_state": safe_get(data, "nirvana_data", "subscriber_demographics", "address", "state"),
                "nirvana_policyholder_zip_code": safe_get(data, "nirvana_data", "subscriber_demographics", "address", "zip"),
                "nirvana_policyholder_date_of_birth": safe_get(data, "nirvana_data", "subscriber_demographics", "dob"),
                "nirvana_policyholder_sex": safe_get(data, "nirvana_data", "subscriber_demographics", "gender"),
                # Matched Therapist (if available)
                "matched_therapist_id": safe_get(data, "matched_therapist_id"),
                "matched_therapist_name": safe_get(data, "matched_therapist_name"),
                "matched_therapist_email": safe_get(data, "matched_therapist_email"),
                "match_score": safe_get(data, "match_score"),
                "matched_specialties": safe_get(data, "matched_specialties"),
                # Additional Context
                "safety_screening": safe_get(data, "safety_screening"),
                "matching_preference": safe_get(data, "matching_preference"),
                "what_brings_you": safe_get(data, "what_brings_you"),
                # Tracking Data
                "sol_health_response_id": safe_get(data, "sol_health_response_id"),
                "onboarding_completed_at": safe_get(data, "onboarding_completed_at"),
                "survey_completed_at": safe_get(data, "survey_completed_at"),
                "utm_source": safe_get(data, "utm_source"),
                "utm_medium": safe_get(data, "utm_medium"),
                "utm_campaign": safe_get(data, "utm_campaign"),
                "signup_timestamp": safe_get(data, "signup_timestamp"),
                "completion_timestamp": safe_get(data, "completion_timestamp"),
                "user_agent": safe_get(data, "user_agent"),
                "ip_address": safe_get(data, "ip_address"),
                # System Metadata
                "environment": os.getenv("ENVIRONMENT", "production"),
                "api_version": os.getenv("API_VERSION", "1.0"),
                "frontend_version": os.getenv("FRONTEND_VERSION", "1.0"),
                "created_at": now if stage == 1 else "",  # Only set on first creation
            }
            journey_tracking_data.update(stage_1_data)

        if stage >= 2:
            # Stage 2: Therapist confirmation
            stage_2_data = {
                "therapist_confirmed": safe_get(data, "therapist_confirmed", "true"),
                "therapist_confirmation_timestamp": safe_get(
                    data, "therapist_confirmation_timestamp", now
                ),
                "alternative_therapists_offered": array_to_string(
                    safe_get(data, "alternative_therapists_offered")
                ),
            }
            journey_tracking_data.update(stage_2_data)

        if stage >= 3:
            # Stage 3: Booking completion
            stage_3_data = {
                # Appointment Data
                "appointment_date": safe_get(data, "appointment_date"),
                "appointment_time": safe_get(data, "appointment_time"),
                "appointment_timezone": safe_get(data, "appointment_timezone"),
                "appointment_duration": safe_get(data, "appointment_duration"),
                "appointment_type": safe_get(data, "appointment_type"),
                "appointment_id": safe_get(data, "appointment_id"),
                "google_event_id": safe_get(data, "google_event_id"),
                "appointment_status": safe_get(data, "appointment_status"),
                # IntakeQ Data
                "intakeq_client_id": safe_get(data, "intakeq_client_id"),
                "intakeq_intake_url": safe_get(data, "intakeq_intake_url"),
                "mandatory_form_sent": safe_get(data, "mandatory_form_sent"),
                "mandatory_form_intake_id": safe_get(data, "mandatory_form_intake_id"),
                "mandatory_form_intake_url": safe_get(
                    data, "mandatory_form_intake_url"
                ),
                "mandatory_form_sent_at": safe_get(data, "mandatory_form_sent_at"),
            }
            journey_tracking_data.update(stage_3_data)

        # Fill row data based on headers
        for header in headers:
            if header in journey_tracking_data:
                idx = headers.index(header)
                row_data[idx] = (
                    str(journey_tracking_data[header])
                    if journey_tracking_data[header] is not None
                    else ""
                )

        return row_data

    def _find_existing_row(self, response_id: str) -> Optional[int]:
        """Find existing row by response_id. Returns row number (1-indexed) or None."""
        if not self.enabled:
            return None

        try:
            # Use only the working sheet range format
            range_attempts = [
                "All Journeys!A:Z",  # Primary working sheet tab
            ]

            result = None
            for range_name in range_attempts:
                try:
                    logger.info(f"📊 Trying data range: {range_name}")
                    result = (
                        self.service.spreadsheets()
                        .values()
                        .get(spreadsheetId=self.sheet_id, range=range_name)
                        .execute()
                    )
                    logger.info(f"✅ Success with data range: {range_name}")
                    break
                except Exception as e:
                    logger.info(f"❌ Failed with data range {range_name}: {str(e)}")
                    continue

            if result is None:
                logger.error("All data range formats failed")
                return None

            values = result.get("values", [])
            if len(values) < 2:  # No data rows
                return None

            headers = values[0]
            if "response_id" not in headers:
                return None

            response_id_col = headers.index("response_id")

            # Search for matching response_id
            for row_idx, row in enumerate(
                values[1:], start=2
            ):  # Start at row 2 (1-indexed)
                if len(row) > response_id_col and row[response_id_col] == response_id:
                    return row_idx

            return None

        except Exception as e:
            logger.error(f"Error finding existing row: {e}")
            return None

    def _update_or_create_row(self, response_id: str, row_data: List[Any], stage: int):
        """Update existing row or create new one with data preservation"""
        if not self.enabled:
            return False

        try:
            # Ensure headers exist
            self._ensure_header_row()

            existing_row = self._find_existing_row(response_id)

            if existing_row:
                # PRESERVE EXISTING DATA - merge instead of overwrite
                logger.info(f"📊 Preserving existing data for {response_id} at row {existing_row}")
                
                # Get current row data
                current_range = self._build_range(f"{existing_row}:{existing_row}")
                current_result = (
                    self.service.spreadsheets()
                    .values()
                    .get(spreadsheetId=self.sheet_id, range=current_range)
                    .execute()
                )
                
                current_values = current_result.get("values", [[]])[0] if current_result.get("values") else []
                
                # Merge: keep existing non-empty values, add new non-empty values
                merged_data = []
                for i, new_value in enumerate(row_data):
                    existing_value = current_values[i] if i < len(current_values) else ""
                    
                    # Preserve existing data unless new data is explicitly provided
                    if existing_value and not new_value:
                        # Keep existing value if new is empty
                        merged_data.append(existing_value)
                    elif new_value:
                        # Use new value if provided
                        merged_data.append(new_value)
                    else:
                        # Both empty, keep empty
                        merged_data.append("")
                
                # Log what's being preserved vs updated
                non_empty_preserved = sum(1 for i, val in enumerate(merged_data) if val and (i >= len(current_values) or not current_values[i]))
                non_empty_existing = sum(1 for val in current_values if val)
                logger.info(f"  📋 Preserving {non_empty_existing} existing fields, adding {non_empty_preserved} new fields")

                # Update with merged data
                update_range = self._build_range(f"{existing_row}:{existing_row}")

                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=update_range,
                    valueInputOption="RAW",
                    body={"values": [merged_data]},
                ).execute()

                logger.info(
                    f"✅ Updated existing row {existing_row} for {response_id} (Stage {stage}) with data preservation"
                )

            else:
                # Use only the working sheet range format
                append_attempts = [
                    "All Journeys!A:A",  # Primary working sheet tab
                ]

                append_success = False
                for append_range in append_attempts:
                    try:
                        logger.info(f"📊 Trying append range: {append_range}")
                        self.service.spreadsheets().values().append(
                            spreadsheetId=self.sheet_id,
                            range=append_range,
                            valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS",
                            body={"values": [row_data]},
                        ).execute()
                        logger.info(f"✅ Success with append range: {append_range}")
                        append_success = True
                        break
                    except Exception as e:
                        logger.info(
                            f"❌ Failed with append range {append_range}: {str(e)}"
                        )
                        continue

                if not append_success:
                    raise Exception("All append range formats failed")

                logger.info(f"📊 Created new row for {response_id} (Stage {stage})")

            return True

        except HttpError as e:
            logger.error(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to update/create row: {e}")
            return False

    # PUBLIC API METHODS

    def log_stage_0_nirvana_response(self, user_data: Dict[str, Any]) -> bool:
        """
        Stage 0: Immediate logging right after Nirvana 200 response
        
        This is the truly progressive first stage that logs immediately when 
        we get insurance verification data from Nirvana.
        
        Args:
            user_data: Dictionary containing survey data + Nirvana response
            
        Returns:
            bool: True if logging successful
        """
        logger.info("📊 [STAGE 0] Logging immediate Nirvana response data")
        
        if not user_data:
            logger.error("No user data provided for Stage 0 logging")
            return False
            
        response_id = user_data.get("response_id")
        if not response_id:
            logger.error("No response_id found in user data for Stage 0")
            return False
            
        try:
            self._initialize_service()
            if not self.service:
                logger.error("Failed to initialize Google Sheets service for Stage 0")
                return False
                
            # Build the range for updating/inserting data
            range_name = self._build_range("A:Z")  # Full range for stage 0
            
            # Get existing data to check for this response_id
            try:
                result = self.service.spreadsheets().values().get(
                    spreadsheetId=self.sheet_id, range=range_name
                ).execute()
                values = result.get('values', [])
            except HttpError as e:
                logger.warning(f"Could not read existing data for Stage 0: {e}")
                values = []
            
            # Check if this response_id already exists
            response_id_col = 0  # Assuming response_id is in column A
            existing_row_index = None
            
            for idx, row in enumerate(values[1:], start=2):  # Skip header row
                if len(row) > response_id_col and row[response_id_col] == response_id:
                    existing_row_index = idx
                    break
            
            # Flatten user data for Stage 0 (Nirvana-focused)
            row_data = self._flatten_data_progressive(user_data, stage=0)
            
            if existing_row_index:
                # Update existing row
                update_range = f"{self.sheet_name}!A{existing_row_index}:Z{existing_row_index}"
                logger.info(f"📊 [STAGE 0] Updating existing row {existing_row_index}")
                
                body = {
                    'values': [row_data]
                }
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=update_range,
                    valueInputOption='RAW',
                    body=body
                ).execute()
                
            else:
                # Append new row
                logger.info(f"📊 [STAGE 0] Adding new row for response_id: {response_id}")
                
                body = {
                    'values': [row_data]
                }
                
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.sheet_id,
                    range=range_name,
                    valueInputOption='RAW',
                    insertDataOption='INSERT_ROWS',
                    body=body
                ).execute()
            
            logger.info(f"✅ [STAGE 0] Successfully logged Nirvana data for {response_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [STAGE 0] Failed to log Nirvana response: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def log_stage_1_survey_complete(self, user_data: Dict[str, Any]) -> bool:
        """
        Log Stage 1: Survey completion + therapist match

        Args:
            user_data: Dictionary containing user survey data and match info

        Returns:
            bool: True if successful
        """
        if not self.enabled:
            logger.info("Google Sheets progressive logging disabled")
            return False

        # Debug what data we're receiving for Google Sheets
        logger.info("🔍 [STAGE 1 DATA AUDIT] Received data for Google Sheets:")
        logger.info(f"  Total fields: {len(user_data)}")

        # Check critical address fields
        address_fields = ["street_address", "city", "state", "postal_code"]
        address_data = {field: user_data.get(field) for field in address_fields}
        populated_address = sum(1 for v in address_data.values() if v)
        logger.info(
            f"  Address fields populated: {populated_address}/{len(address_fields)} - {address_data}"
        )

        # Check survey response fields
        survey_fields = [
            "phq9_scores",
            "gad7_scores",
            "what_brings_you",
            "therapist_specializes_in",
        ]
        survey_data = {field: bool(user_data.get(field)) for field in survey_fields}
        logger.info(f"  Survey data populated: {survey_data}")

        # Check insurance/Nirvana fields
        insurance_fields = ["insurance_provider", "insurance_verified"]
        insurance_data = {field: user_data.get(field) for field in insurance_fields}
        logger.info(f"  Insurance data: {insurance_data}")

        # ENHANCED: Check for Nirvana data specifically
        nirvana_data_check = user_data.get("nirvana_data")
        if nirvana_data_check:
            logger.info("  🎯 NIRVANA DATA FOUND! Checking fields:")
            if isinstance(nirvana_data_check, dict):
                nirvana_fields_to_check = [
                    "plan_name",
                    "group_id",
                    "payer_id",
                    "plan_status",
                    "coverage_status",
                    "relationship_to_subscriber",
                    "insurance_type",
                ]
                for field in nirvana_fields_to_check:
                    value = nirvana_data_check.get(field)
                    logger.info(f"    {field}: '{value}' {'✓' if value else '✗'}")
            else:
                logger.info(
                    f"    Nirvana data type: {type(nirvana_data_check)}, value: {str(nirvana_data_check)[:200]}..."
                )
        else:
            logger.warning("  ⚠️ NO NIRVANA DATA FOUND in user_data")
            # Check for alternative field names
            alt_nirvana_fields = [
                "insurance_verification_data",
                "nirvana_response",
                "rawNirvanaResponse",
            ]
            for alt_field in alt_nirvana_fields:
                if user_data.get(alt_field):
                    logger.info(f"    Found alternative Nirvana field: {alt_field}")
                    break
            else:
                logger.warning("    No alternative Nirvana fields found either")

        # List all available field names for debugging
        all_fields = sorted(user_data.keys())
        logger.info(
            f"  All available fields: {all_fields[:20]}{'...' if len(all_fields) > 20 else ''}"
        )

        try:
            response_id = user_data.get("response_id")
            if not response_id:
                logger.error("No response_id provided for Stage 1 logging")
                return False

            logger.info(
                f"📊 [STAGE 1] Logging survey completion + match for {response_id}"
            )

            row_data = self._flatten_data_progressive(user_data, stage=1)
            success = self._update_or_create_row(response_id, row_data, stage=1)

            if success:
                logger.info(
                    f"✅ [STAGE 1] Successfully logged survey + match data for {response_id}"
                )
            else:
                logger.error(
                    f"❌ [STAGE 1] Failed to log survey + match data for {response_id}"
                )

            return success

        except Exception as e:
            logger.error(f"❌ [STAGE 1] Error logging survey completion: {e}")
            traceback.print_exc()
            return False

    def log_stage_2_therapist_confirmed(
        self, response_id: str, confirmation_data: Dict[str, Any]
    ) -> bool:
        """
        Log Stage 2: Therapist confirmation

        Args:
            response_id: User response ID
            confirmation_data: Dictionary containing confirmation details

        Returns:
            bool: True if successful
        """
        if not self.enabled:
            logger.info("Google Sheets progressive logging disabled")
            return False

        try:
            logger.info(f"📊 [STAGE 2] Logging therapist confirmation for {response_id}")

            # Add response_id to data for processing
            data_with_id = {"response_id": response_id, **confirmation_data}

            row_data = self._flatten_data_progressive(data_with_id, stage=2)
            success = self._update_or_create_row(response_id, row_data, stage=2)

            if success:
                logger.info(
                    f"✅ [STAGE 2] Successfully logged therapist confirmation for {response_id}"
                )
            else:
                logger.error(
                    f"❌ [STAGE 2] Failed to log therapist confirmation for {response_id}"
                )

            return success

        except Exception as e:
            logger.error(f"❌ [STAGE 2] Error logging therapist confirmation: {e}")
            traceback.print_exc()
            return False

    def log_stage_3_booking_complete(
        self, response_id: str, booking_data: Dict[str, Any]
    ) -> bool:
        """
        Log Stage 3: Final booking completion with comprehensive data

        Args:
            response_id: User response ID
            booking_data: Dictionary containing appointment and completion details

        Returns:
            bool: True if successful
        """
        if not self.enabled:
            logger.info("Google Sheets progressive logging disabled")
            return False

        try:
            logger.info(f"📊 [STAGE 3] Logging booking completion for {response_id}")

            # Add response_id to data for processing
            data_with_id = {"response_id": response_id, **booking_data}

            row_data = self._flatten_data_progressive(data_with_id, stage=3)
            success = self._update_or_create_row(response_id, row_data, stage=3)

            if success:
                logger.info(
                    f"✅ [STAGE 3] Successfully logged final booking data for {response_id}"
                )
            else:
                logger.error(
                    f"❌ [STAGE 3] Failed to log final booking data for {response_id}"
                )

            return success

        except Exception as e:
            logger.error(f"❌ [STAGE 3] Error logging booking completion: {e}")
            traceback.print_exc()
            return False

    # ASYNC CONVENIENCE METHODS

    def async_log_stage_1(self, user_data: Dict[str, Any]):
        """Async wrapper for Stage 1 logging"""

        def run_async():
            self.log_stage_1_survey_complete(user_data)

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        logger.info(
            f"🚀 [ASYNC] Started Stage 1 logging for {user_data.get('response_id', 'unknown')}"
        )

    def async_log_stage_2(self, response_id: str, confirmation_data: Dict[str, Any]):
        """Async wrapper for Stage 2 logging"""

        def run_async():
            self.log_stage_2_therapist_confirmed(response_id, confirmation_data)

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        logger.info(f"🚀 [ASYNC] Started Stage 2 logging for {response_id}")

    def async_log_stage_3(self, response_id: str, booking_data: Dict[str, Any]):
        """Async wrapper for Stage 3 logging"""

        def run_async():
            self.log_stage_3_booking_complete(response_id, booking_data)

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        logger.info(f"🚀 [ASYNC] Started Stage 3 logging for {response_id}")

    # INCOMPLETE USER LOGGING

    def log_incomplete_user(self, user_data: Dict[str, Any], reason: str = "unsupported_state") -> bool:
        """
        Log incomplete user information to the 'Incomplete' sheet
        
        Args:
            user_data: Dictionary containing available user data
            reason: Reason for incompleteness (e.g., "unsupported_state")
            
        Returns:
            bool: True if successful
        """
        if not self.enabled:
            logger.info("Google Sheets logging disabled for incomplete users")
            return False

        try:
            response_id = user_data.get("response_id", f"incomplete_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
            logger.info(f"📋 [INCOMPLETE] Logging incomplete user: {response_id}, reason: {reason}")

            # Build incomplete user headers
            incomplete_headers = [
                "response_id",
                "timestamp",
                "reason",
                "email", 
                "preferred_name",
                "first_name",
                "last_name",
                "state",
                "selected_state_name",
                "payment_type",
                "utm_source",
                "utm_medium", 
                "utm_campaign",
                "user_agent",
                "ip_address",
                "phone",
                "date_of_birth",
                "what_brings_you",
                "created_at"
            ]

            # Helper function to safely get nested values
            def safe_get(obj, *keys):
                for key in keys:
                    if isinstance(obj, dict) and key in obj:
                        obj = obj[key]
                    else:
                        return ""
                return obj if obj is not None else ""

            now = datetime.utcnow().isoformat()
            
            # Build incomplete user data row
            incomplete_data = [
                response_id,
                now,
                reason,
                safe_get(user_data, "email"),
                safe_get(user_data, "preferred_name") or safe_get(user_data, "preferredName"),
                safe_get(user_data, "first_name") or safe_get(user_data, "firstName"),
                safe_get(user_data, "last_name") or safe_get(user_data, "lastName"), 
                safe_get(user_data, "state"),
                safe_get(user_data, "selected_state_name"),
                safe_get(user_data, "payment_type"),
                safe_get(user_data, "utm_source"),
                safe_get(user_data, "utm_medium"),
                safe_get(user_data, "utm_campaign"),
                safe_get(user_data, "user_agent"),
                safe_get(user_data, "ip_address"),
                safe_get(user_data, "phone"),
                safe_get(user_data, "date_of_birth") or safe_get(user_data, "dateOfBirth"),
                safe_get(user_data, "what_brings_you"),
                now
            ]

            # Use 'Incomplete' sheet
            incomplete_sheet_name = "Incomplete"
            
            # Ensure header row exists in Incomplete sheet
            try:
                header_range = f"{incomplete_sheet_name}!1:1"
                result = self.service.spreadsheets().values().get(
                    spreadsheetId=self.sheet_id, 
                    range=header_range
                ).execute()
                
                values = result.get("values", [])
                if not values or values[0] != incomplete_headers:
                    # Write header row
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.sheet_id,
                        range=header_range,
                        valueInputOption="RAW",
                        body={"values": [incomplete_headers]},
                    ).execute()
                    logger.info(f"Updated header row for {incomplete_sheet_name} sheet")
                    
            except Exception as e:
                logger.warning(f"Could not ensure headers for {incomplete_sheet_name} sheet: {e}")
                # Continue anyway - sheet might not exist yet

            # Append data to Incomplete sheet
            append_range = f"{incomplete_sheet_name}!A:A"
            self.service.spreadsheets().values().append(
                spreadsheetId=self.sheet_id,
                range=append_range,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [incomplete_data]},
            ).execute()

            logger.info(f"✅ [INCOMPLETE] Successfully logged incomplete user {response_id} to {incomplete_sheet_name} sheet")
            return True

        except Exception as e:
            logger.error(f"❌ [INCOMPLETE] Error logging incomplete user: {e}")
            traceback.print_exc()
            return False

    def async_log_incomplete_user(self, user_data: Dict[str, Any], reason: str = "unsupported_state"):
        """Async wrapper for incomplete user logging"""
        def run_async():
            self.log_incomplete_user(user_data, reason)

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        logger.info(f"🚀 [ASYNC] Started incomplete user logging for {user_data.get('response_id', 'unknown')}")

    # LEGACY COMPATIBILITY METHOD

    def log_user_signup(self, user_data: Dict[str, Any]) -> bool:
        """
        Legacy compatibility method for existing code.
        Routes to appropriate stage based on data completeness.
        """
        # Determine stage based on available data
        has_appointment = user_data.get("appointment_date") or user_data.get(
            "appointment_id"
        )
        has_therapist_confirmation = user_data.get(
            "therapist_confirmed"
        ) or user_data.get("therapist_confirmation_timestamp")
        has_match = user_data.get("matched_therapist_id") or user_data.get(
            "matched_therapist_name"
        )

        if has_appointment:
            return self.log_stage_3_booking_complete(
                user_data.get("response_id", ""), user_data
            )
        elif has_therapist_confirmation:
            return self.log_stage_2_therapist_confirmed(
                user_data.get("response_id", ""), user_data
            )
        elif has_match:
            return self.log_stage_1_survey_complete(user_data)
        else:
            # Default to Stage 1 for basic survey data
            return self.log_stage_1_survey_complete(user_data)


# Global instance
progressive_logger = GoogleSheetsProgressiveLogger()
