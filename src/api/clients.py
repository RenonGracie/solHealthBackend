# src/api/clients.py - Fixed with database storage
"""Client signup API with proper database storage."""
import json
import logging
import uuid
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from src.db import get_db_session
from src.db.models import ClientResponse

# Note: Progressive logging handled at therapist matching stage, not here

logger = logging.getLogger(__name__)

clients_bp = Blueprint("clients", __name__)


@clients_bp.route("/clients_signup", methods=["GET"])
def get_client_form():
    """Get client signup form data by response_id from database."""
    response_id = request.args.get("response_id")

    if not response_id:
        return jsonify({"error": "response_id is required"}), 400

    session = get_db_session()

    try:
        # Query database for client response
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        if client_response:
            # Convert to comprehensive SuperJson-compatible dict
            response_data = {
                # Core identity
                "response_id": client_response.id,
                "session_id": client_response.session_id,
                "journey_started_at": client_response.journey_started_at.isoformat() if client_response.journey_started_at else None,
                "survey_completed_at": client_response.survey_completed_at.isoformat() if client_response.survey_completed_at else None,
                "current_stage": client_response.current_stage or "survey_completed",
                
                # Demographics
                "first_name": client_response.first_name,
                "last_name": client_response.last_name,
                "preferred_name": client_response.preferred_name,
                "email": client_response.email,
                "phone": client_response.phone,
                "age": client_response.age,
                "gender": client_response.gender,
                "date_of_birth": client_response.date_of_birth,
                
                # Address information
                "street_address": client_response.street_address,
                "city": client_response.city,
                "state": client_response.state,
                "postal_code": client_response.postal_code,
                "university": client_response.university,
                
                # Payment & insurance
                "payment_type": client_response.payment_type,
                "insurance_provider": client_response.insurance_provider,
                "insurance_member_id": client_response.insurance_member_id,
                "insurance_date_of_birth": client_response.insurance_date_of_birth,
                "insurance_verified": client_response.insurance_verified,
                "insurance_verification_data": client_response.insurance_verification_data,
                
                # Nirvana insurance data
                "nirvana_raw_response": client_response.nirvana_raw_response,
                "nirvana_demographics": client_response.nirvana_demographics,
                "nirvana_address": client_response.nirvana_address,
                "nirvana_plan_details": client_response.nirvana_plan_details,
                "nirvana_benefits": client_response.nirvana_benefits,
                
                # Mental health assessments
                "phq9_responses": client_response.phq9_responses or {},
                "phq9_total_score": client_response.phq9_total,
                "phq9_risk_level": client_response.phq9_risk_level,
                "gad7_responses": client_response.gad7_responses or {},
                "gad7_total_score": client_response.gad7_total,
                "gad7_risk_level": client_response.gad7_risk_level,
                
                # Therapy preferences
                "what_brings_you": client_response.what_brings_you,
                "therapist_specializes_in": client_response.therapist_specializes_in or [],
                "therapist_identifies_as": client_response.therapist_identifies_as,
                "lived_experiences": client_response.lived_experiences or [],
                "matching_preference": client_response.matching_preference,
                
                # Extended demographics
                "race_ethnicity": client_response.race_ethnicity or [],
                
                # Substance screening
                "alcohol_frequency": client_response.alcohol_frequency,
                "recreational_drugs_frequency": client_response.recreational_drugs_frequency,
                "safety_screening": client_response.safety_screening,
                
                # Marketing attribution
                "utm_source": client_response.utm_source,
                "utm_medium": client_response.utm_medium,
                "utm_campaign": client_response.utm_campaign,
                "referred_by": client_response.referred_by,
                "promo_code": client_response.promo_code,
                
                # Technical metadata
                "user_agent": client_response.user_agent,
                "screen_resolution": client_response.screen_resolution,
                "timezone": client_response.timezone_data,
                "data_completeness_score": client_response.data_completeness_score,
                
                # Therapist selection
                "selected_therapist": client_response.selected_therapist,
                "selected_therapist_id": client_response.selected_therapist_id,
                "selected_therapist_email": client_response.selected_therapist_email,
            }

            # Add individual PHQ-9 and GAD-7 responses for backward compatibility
            if client_response.phq9_responses:
                response_data.update(client_response.phq9_responses)
            if client_response.gad7_responses:
                response_data.update(client_response.gad7_responses)

            return jsonify(response_data)

        # Return 404 if not found (triggers polling in frontend)
        return jsonify({"error": "Response not found"}), 404

    except Exception as e:
        logger.error(f"Error fetching client response: {str(e)}")
        return jsonify({"error": "Database error"}), 500
    finally:
        session.close()


@clients_bp.route("/clients_signup", methods=["POST"])
def create_client_signup():
    """Create/update client signup from frontend survey - stores in database."""
    data = request.get_json()

    response_id = data.get("response_id")
    if not response_id:
        # Generate a new response_id if not provided
        response_id = str(uuid.uuid4())
        data["response_id"] = response_id

    session = get_db_session()

    try:
        # Check if client response already exists
        existing_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        # Track journey start if this is a new user
        # is_new_user = existing_response is None  # Removed unused variable

        # Prepare PHQ-9 responses - check both flat fields and nested structure
        # Frontend may send as flat fields OR as nested phq9_responses object
        phq9_responses_nested = data.get("phq9_responses") or data.get("phq9Responses") or {}
        phq9_responses = {
            "pleasure_doing_things": data.get("pleasure_doing_things") or phq9_responses_nested.get("pleasure_doing_things") or phq9_responses_nested.get("pleasureDoingThings"),
            "feeling_down": data.get("feeling_down") or phq9_responses_nested.get("feeling_down") or phq9_responses_nested.get("feelingDown"),
            "trouble_falling": data.get("trouble_falling") or phq9_responses_nested.get("trouble_falling") or phq9_responses_nested.get("troubleFalling"),
            "feeling_tired": data.get("feeling_tired") or phq9_responses_nested.get("feeling_tired") or phq9_responses_nested.get("feelingTired"),
            "poor_appetite": data.get("poor_appetite") or phq9_responses_nested.get("poor_appetite") or phq9_responses_nested.get("poorAppetite"),
            "feeling_bad_about_yourself": data.get("feeling_bad_about_yourself") or phq9_responses_nested.get("feeling_bad_about_yourself") or phq9_responses_nested.get("feelingBadAboutYourself"),
            "trouble_concentrating": data.get("trouble_concentrating") or phq9_responses_nested.get("trouble_concentrating") or phq9_responses_nested.get("troubleConcentrating"),
            "moving_or_speaking_so_slowly": data.get("moving_or_speaking_so_slowly") or phq9_responses_nested.get("moving_or_speaking_so_slowly") or phq9_responses_nested.get("movingOrSpeakingSoSlowly"),
            "suicidal_thoughts": data.get("suicidal_thoughts") or phq9_responses_nested.get("suicidal_thoughts") or phq9_responses_nested.get("suicidalThoughts"),
        }

        # Prepare GAD-7 responses - check both flat fields and nested structure
        # Frontend may send as flat fields OR as nested gad7_responses object
        gad7_responses_nested = data.get("gad7_responses") or data.get("gad7Responses") or {}
        gad7_responses = {
            "feeling_nervous": data.get("feeling_nervous") or gad7_responses_nested.get("feeling_nervous") or gad7_responses_nested.get("feelingNervous"),
            "not_control_worrying": data.get("not_control_worrying") or gad7_responses_nested.get("not_control_worrying") or gad7_responses_nested.get("notControlWorrying"),
            "worrying_too_much": data.get("worrying_too_much") or gad7_responses_nested.get("worrying_too_much") or gad7_responses_nested.get("worryingTooMuch"),
            "trouble_relaxing": data.get("trouble_relaxing") or gad7_responses_nested.get("trouble_relaxing") or gad7_responses_nested.get("troubleRelaxing"),
            "being_so_restless": data.get("being_so_restless") or gad7_responses_nested.get("being_so_restless") or gad7_responses_nested.get("beingSoRestless"),
            "easily_annoyed": data.get("easily_annoyed") or gad7_responses_nested.get("easily_annoyed") or gad7_responses_nested.get("easilyAnnoyed"),
            "feeling_afraid": data.get("feeling_afraid") or gad7_responses_nested.get("feeling_afraid") or gad7_responses_nested.get("feelingAfraid"),
        }

        # Calculate PHQ-9 and GAD-7 scores
        phq9_total = calculate_assessment_score(phq9_responses)
        gad7_total = calculate_assessment_score(gad7_responses)

        # Handle SuperJson structure - data comes pre-processed from frontend
        mapped_data = data.copy()
        
        # Extract and parse datetime fields
        if mapped_data.get("journey_started_at"):
            try:
                from datetime import datetime
                mapped_data["journey_started_at"] = datetime.fromisoformat(
                    mapped_data["journey_started_at"].replace('Z', '+00:00')
                )
            except:
                mapped_data["journey_started_at"] = None
                
        if mapped_data.get("survey_completed_at"):
            try:
                from datetime import datetime
                mapped_data["survey_completed_at"] = datetime.fromisoformat(
                    mapped_data["survey_completed_at"].replace('Z', '+00:00')
                )
            except:
                mapped_data["survey_completed_at"] = None

        # Debug comprehensive data flow for Google Sheets including insurance verification data
        logger.info("📍 [COMPREHENSIVE DEBUG] Client signup data flow:")
        logger.info(
            f"  Basic: name='{mapped_data.get('first_name')} {mapped_data.get('last_name')}', email='{mapped_data.get('email')}'"
        )
        logger.info(
            f"  Address: street='{mapped_data.get('street_address')}', city='{mapped_data.get('city')}', state='{mapped_data.get('state')}', zip='{mapped_data.get('postal_code')}'"
        )
        logger.info(
            f"  Demographics: age='{mapped_data.get('age')}', gender='{mapped_data.get('gender')}', university='{mapped_data.get('university')}'"
        )
        logger.info(
            f"  Payment: type='{mapped_data.get('payment_type')}', insurance='{mapped_data.get('insurance_provider')}'"
        )
        logger.info(
            f"  Therapist Prefs: specializes='{mapped_data.get('therapist_specializes_in')}', identifies='{mapped_data.get('therapist_identifies_as')}'"
        )
        logger.info(
            f"  Survey: what_brings='{str(mapped_data.get('what_brings_you', ''))[:100]}...', lived_exp='{mapped_data.get('lived_experiences')}'"
        )
        logger.info(
            f"  Marketing: utm_source='{mapped_data.get('utm_source')}', referred='{mapped_data.get('referred_by')}', promo='{mapped_data.get('promo_code')}'"
        )

        # Check for insurance verification data in various possible field names
        insurance_fields = [
            "insurance_verification_data",
            "nirvana_response",
            "nirvana_data",
            "rawNirvanaResponse",
            "verificationData",
        ]
        for field in insurance_fields:
            if field in mapped_data:
                nirvana_data = mapped_data[field]
                if isinstance(nirvana_data, str):
                    logger.info(
                        f"  🏥 Insurance Data ({field}): [STRING with {len(nirvana_data)} chars]"
                    )
                    try:
                        import json

                        parsed = json.loads(nirvana_data)
                        logger.info(
                            f"      Parsed keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'Not a dict'}"
                        )
                    except:
                        logger.info("      Could not parse as JSON")
                elif isinstance(nirvana_data, dict):
                    logger.info(
                        f"  🏥 Insurance Data ({field}): [DICT with {len(nirvana_data)} keys: {list(nirvana_data.keys())}]"
                    )
                else:
                    logger.info(
                        f"  🏥 Insurance Data ({field}): {type(nirvana_data)} - {nirvana_data}"
                    )

        # Parse and structure Nirvana data for easier access later
        structured_nirvana_data = None
        for field in insurance_fields:
            if field in mapped_data and mapped_data[field]:
                try:
                    raw_data = mapped_data[field]
                    if isinstance(raw_data, str):
                        import json
                        structured_nirvana_data = json.loads(raw_data)
                    elif isinstance(raw_data, dict):
                        structured_nirvana_data = raw_data
                    
                    if structured_nirvana_data:
                        logger.info(f"✅ Successfully parsed Nirvana data from {field}")
                        # Store structured data in mapped_data for later use
                        mapped_data["nirvana_raw_response"] = structured_nirvana_data
                        mapped_data["nirvana_demographics"] = structured_nirvana_data.get("demographics", {})
                        mapped_data["nirvana_address"] = structured_nirvana_data.get("demographics", {}).get("address", {})
                        mapped_data["nirvana_plan_details"] = {
                            "plan_name": structured_nirvana_data.get("plan_name"),
                            "payer_id": structured_nirvana_data.get("payer_id"), 
                            "group_id": structured_nirvana_data.get("group_id"),
                            "plan_status": structured_nirvana_data.get("plan_status"),
                            "coverage_status": structured_nirvana_data.get("coverage_status"),
                        }
                        mapped_data["nirvana_benefits"] = {
                            "copayment": structured_nirvana_data.get("copayment"),
                            "coinsurance": structured_nirvana_data.get("coinsurance"),
                            "deductible": structured_nirvana_data.get("deductible"),
                            "remaining_deductible": structured_nirvana_data.get("remaining_deductible"),
                            "oop_max": structured_nirvana_data.get("oop_max"),
                            "remaining_oop_max": structured_nirvana_data.get("remaining_oop_max"),
                            "member_obligation": structured_nirvana_data.get("member_obligation"),
                            "payer_obligation": structured_nirvana_data.get("payer_obligation"),
                            "benefit_structure": structured_nirvana_data.get("benefit_structure"),
                        }
                        # Also ensure the legacy insurance_verification_data field is populated
                        if field != "insurance_verification_data":
                            mapped_data["insurance_verification_data"] = structured_nirvana_data
                        
                        logger.info("📊 Structured Nirvana data into separate fields for better access")
                        logger.info(f"   Demographics: {bool(mapped_data.get('nirvana_demographics'))}")
                        logger.info(f"   Address: {bool(mapped_data.get('nirvana_address'))}")
                        logger.info(f"   Plan Details: {bool(mapped_data.get('nirvana_plan_details'))}")
                        logger.info(f"   Benefits: {bool(mapped_data.get('nirvana_benefits'))}")
                        break
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse Nirvana data from {field}: {str(e)}")
                    continue
        
        if not structured_nirvana_data:
            logger.warning(
                "⚠️ NO INSURANCE VERIFICATION DATA found or could not be parsed from any expected fields!"
            )
            logger.info(
                f"  Available fields in data: {list(mapped_data.keys())[:10]} ..."
            )  # First 10 keys

        # Check for alternative/missing field names in original data
        alt_fields = [
            "address",
            "client_address",
            "zip",
            "zip_code",
            "phone_number",
            "full_name",
        ]
        missing_critical = []
        for field in alt_fields:
            if field in data:
                logger.info(f"  Alternative field '{field}': '{data.get(field)}'")

        # Flag missing critical data
        critical_fields = [
            "street_address",
            "city",
            "postal_code",
            "phone",
            "first_name",
            "last_name",
        ]
        for field in critical_fields:
            if not mapped_data.get(field):
                missing_critical.append(field)

        if missing_critical:
            logger.warning(
                f"⚠️ Missing critical fields for Google Sheets: {missing_critical}"
            )
        else:
            logger.info("✅ All critical fields populated for Google Sheets logging")

        if existing_response:
            # Update existing response
            update_response_fields(existing_response, mapped_data)
            logger.info(f"📝 Updated client response: {response_id}")
        else:
            # Create new response with only safe fields first
            new_response = ClientResponse(
                id=response_id
                # Let all other fields be None initially
            )
            
            # Update all fields using the helper function
            update_response_fields(new_response, mapped_data)
            
            session.add(new_response)
            logger.info(f"📝 Created new client response: {response_id}")

        # Commit to database
        session.commit()

        # Note: Survey data now saved directly to database only
        # Frontend will provide comprehensive SuperJson payload

        logger.info(
            f"📊 Client: {mapped_data.get('first_name', '')} {mapped_data.get('last_name', '')}"
        )
        logger.info(f"💳 Payment type: {mapped_data.get('payment_type', 'unknown')}")
        logger.info(f"📍 State: {mapped_data.get('state', 'unknown')}")
        logger.info(f"🎯 PHQ-9 Score: {phq9_total}, GAD-7 Score: {gad7_total}")
        logger.info(
            f"🔍 Therapist specializations: {mapped_data.get('therapist_specializes_in', [])}"
        )
        logger.info(
            f"👤 Gender preference: {mapped_data.get('therapist_identifies_as', 'None')}"
        )
        logger.info(f"🌟 Lived experiences: {mapped_data.get('lived_experiences', [])}")

        # Progressive Google Sheets Logging - Stage 1 or Stage 2
        try:
            from src.services.google_sheets_progressive_logger import progressive_logger

            # Prepare comprehensive data for Google Sheets
            comprehensive_data = mapped_data.copy()

            # DEBUG: Verify PHQ-9 and GAD-7 data structure before logging
            logger.info("=" * 80)
            logger.info("🔍 [PHQ-9/GAD-7 DEBUG] Checking data structure for Google Sheets:")
            logger.info(f"  📋 PHQ-9 responses dict: {phq9_responses}")
            logger.info(f"  ✓ PHQ-9 has populated values: {any(v is not None and v != '' for v in phq9_responses.values())}")
            logger.info(f"  📊 PHQ-9 total score: {phq9_total}")
            logger.info(f"  📋 GAD-7 responses dict: {gad7_responses}")
            logger.info(f"  ✓ GAD-7 has populated values: {any(v is not None and v != '' for v in gad7_responses.values())}")
            logger.info(f"  📊 GAD-7 total score: {gad7_total}")

            # Check if frontend sent nested structure
            if "phq9_responses" in data or "phq9Responses" in data:
                logger.info(f"  🎯 Found nested phq9_responses in data: {data.get('phq9_responses') or data.get('phq9Responses')}")
            if "gad7_responses" in data or "gad7Responses" in data:
                logger.info(f"  🎯 Found nested gad7_responses in data: {data.get('gad7_responses') or data.get('gad7Responses')}")

            # List relevant keys from original data
            relevant_keys = [k for k in data.keys() if any(x in k.lower() for x in ['phq', 'gad', 'pleasure', 'feeling', 'nervous', 'worry'])]
            if relevant_keys:
                logger.info(f"  🔑 Assessment-related keys in data: {relevant_keys}")
            logger.info("=" * 80)

            # Add PHQ-9 and GAD-7 scores in the format expected by comprehensive logger
            if phq9_responses:
                comprehensive_data["phq9_scores"] = phq9_responses
                comprehensive_data["phq9_total"] = phq9_total

            if gad7_responses:
                comprehensive_data["gad7_scores"] = gad7_responses
                comprehensive_data["gad7_total"] = gad7_total

            # Add timestamps
            from datetime import datetime

            comprehensive_data["signup_timestamp"] = datetime.utcnow().isoformat()
            comprehensive_data["response_id"] = response_id

            # Detect if this is partial submission (Stage 1) or complete submission (Stage 2)
            has_email = bool(comprehensive_data.get("email"))
            has_phq9 = bool(phq9_total) or any(phq9_responses.values())
            has_gad7 = bool(gad7_total) or any(gad7_responses.values())

            if has_email and not has_phq9 and not has_gad7:
                # Stage 1: Partial submission (email capture only)
                logger.info(f"📊 [STAGE 1] Partial submission detected for {response_id}")
                progressive_logger.async_log_stage_1(comprehensive_data)
            elif has_email and (has_phq9 or has_gad7):
                # Stage 2: Complete submission (with survey data)
                logger.info(f"📊 [STAGE 2] Complete submission detected for {response_id}")
                comprehensive_data["survey_completed_at"] = datetime.utcnow().isoformat()
                progressive_logger.async_log_stage_2(comprehensive_data)
            else:
                logger.info(f"📊 Survey data saved (no logging stage matched) for response_id: {response_id}")

        except Exception as e:
            logger.warning(f"Progressive logging warning: {str(e)}")
            # Don't fail the request if logging fails
            import traceback
            traceback.print_exc()

        return jsonify({"success": True, "response_id": response_id})

    except IntegrityError as e:
        session.rollback()
        logger.error(f"Database integrity error: {str(e)}")
        return jsonify({"error": "Duplicate entry or constraint violation"}), 400
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving client response: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception args: {e.args}")

        # Return more detailed error in development
        import os

        if os.getenv("ENV") != "prod":
            return (
                jsonify(
                    {
                        "error": "Failed to save response",
                        "details": str(e),
                        "type": type(e).__name__,
                    }
                ),
                500,
            )
        else:
            return jsonify({"error": "Failed to save response"}), 500
    finally:
        session.close()


def calculate_assessment_score(responses: dict) -> int:
    """Calculate total score for PHQ-9 or GAD-7 assessment."""
    score_map = {
        "Not at all": 0,
        "Several days": 1,
        "More than half the days": 2,
        "Nearly every day": 3,
    }

    total = 0
    for key, value in responses.items():
        if value and isinstance(value, str):
            total += score_map.get(value, 0)

    return total


@clients_bp.route("/clients/<response_id>", methods=["GET"])
def get_client_details(response_id: str):
    """Get detailed client information by response_id."""
    session = get_db_session()

    try:
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        if not client_response:
            return jsonify({"error": "Client not found"}), 404

        # Return detailed client information
        return jsonify(
            {
                "id": client_response.id,
                "email": client_response.email,
                "name": f"{client_response.first_name} {client_response.last_name}",
                "state": client_response.state,
                "payment_type": client_response.payment_type,
                "phq9_score": client_response.phq9_total,
                "gad7_score": client_response.gad7_total,
                "risk_level": get_risk_level(
                    client_response.phq9_total, client_response.gad7_total
                ),
                "created_at": client_response.created_at.isoformat()
                if client_response.created_at
                else None,
            }
        )

    except Exception as e:
        logger.error(f"Error fetching client details: {str(e)}")
        return jsonify({"error": "Database error"}), 500
    finally:
        session.close()


@clients_bp.route("/clients_signup/<response_id>", methods=["PATCH"])
def update_client_response(response_id: str):
    """Update client response with additional data like IntakeQ ID."""
    session = get_db_session()

    try:
        # Get the client response
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == response_id)
            .first()
        )

        if not client_response:
            return jsonify({"error": "Client response not found"}), 404

        # Get update data from request
        update_data = request.get_json() or {}

        # Log the update request
        logger.info(f"🔄 [CLIENT UPDATE] {response_id}")
        logger.info(f"  Update data: {list(update_data.keys())}")

        # Update IntakeQ fields if provided
        if "intakeq_client_id" in update_data:
            client_response.intakeq_client_id = update_data["intakeq_client_id"]
            logger.info(
                f"  ✅ Updated IntakeQ Client ID: {update_data['intakeq_client_id']}"
            )

        if "intakeq_intake_url" in update_data:
            client_response.intakeq_intake_url = update_data["intakeq_intake_url"]
            logger.info(
                f"  ✅ Updated IntakeQ Intake URL: {update_data['intakeq_intake_url']}"
            )

        # Update any other provided fields
        updatable_fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "age",
            "gender",
            "state",
            "university",
            "payment_type",
            "insurance_provider",
        ]

        for field in updatable_fields:
            if field in update_data:
                setattr(client_response, field, update_data[field])
                logger.info(f"  ✅ Updated {field}: {update_data[field]}")

        # Update timestamp
        from datetime import datetime

        client_response.updated_at = datetime.utcnow()

        # Commit changes
        session.commit()

        logger.info(f"  ✅ Client response {response_id} updated successfully")

        return jsonify(
            {
                "success": True,
                "response_id": response_id,
                "updated_fields": list(update_data.keys()),
                "intakeq_client_id": client_response.intakeq_client_id,
                "intakeq_intake_url": client_response.intakeq_intake_url,
            }
        )

    except Exception as e:
        session.rollback()
        logger.error(f"❌ [CLIENT UPDATE ERROR] {response_id}: {str(e)}")
        return jsonify({"error": f"Failed to update client response: {str(e)}"}), 500
    finally:
        session.close()

def update_response_fields(response_obj, data):
    """Helper to update response fields from SuperJson data."""
    # Basic demographics
    response_obj.email = data.get("email", response_obj.email)
    response_obj.first_name = data.get("first_name", response_obj.first_name)
    response_obj.last_name = data.get("last_name", response_obj.last_name)
    response_obj.preferred_name = data.get("preferred_name", response_obj.preferred_name)
    response_obj.phone = data.get("phone", response_obj.phone)
    response_obj.date_of_birth = data.get("date_of_birth", response_obj.date_of_birth)
    response_obj.age = data.get("age", response_obj.age)
    response_obj.gender = data.get("gender", response_obj.gender)
    response_obj.state = data.get("state", response_obj.state)

    # Address information
    response_obj.street_address = data.get("street_address", response_obj.street_address)
    response_obj.city = data.get("city", response_obj.city)
    response_obj.postal_code = data.get("postal_code", response_obj.postal_code)
    response_obj.university = data.get("university", response_obj.university)

    # Assessment scores and responses - handle both individual responses and totals
    if data.get("phq9_responses"):
        response_obj.phq9_responses = data.get("phq9_responses")
    if data.get("gad7_responses"):
        response_obj.gad7_responses = data.get("gad7_responses")
        
    response_obj.phq9_total = data.get("phq9_total", response_obj.phq9_total)
    response_obj.gad7_total = data.get("gad7_total", response_obj.gad7_total)
    response_obj.phq9_risk_level = data.get("phq9_risk_level", response_obj.phq9_risk_level)
    response_obj.gad7_risk_level = data.get("gad7_risk_level", response_obj.gad7_risk_level)
    
    # Journey tracking
    response_obj.journey_started_at = data.get("journey_started_at", response_obj.journey_started_at)
    response_obj.survey_completed_at = data.get("survey_completed_at", response_obj.survey_completed_at)
    response_obj.current_stage = data.get("current_stage", response_obj.current_stage)
    response_obj.session_id = data.get("session_id", response_obj.session_id)

    # Payment and insurance information
    response_obj.payment_type = data.get("payment_type", response_obj.payment_type)
    response_obj.insurance_provider = data.get("insurance_provider", response_obj.insurance_provider)
    response_obj.insurance_member_id = data.get("insurance_member_id", response_obj.insurance_member_id)
    response_obj.insurance_date_of_birth = data.get("insurance_date_of_birth", response_obj.insurance_date_of_birth)
    response_obj.insurance_verified = data.get("insurance_verified", response_obj.insurance_verified)
    response_obj.insurance_verification_data = data.get("insurance_verification_data", response_obj.insurance_verification_data)
    
    # Nirvana insurance data
    response_obj.nirvana_raw_response = data.get("nirvana_raw_response", response_obj.nirvana_raw_response)
    response_obj.nirvana_demographics = data.get("nirvana_demographics", response_obj.nirvana_demographics)
    response_obj.nirvana_address = data.get("nirvana_address", response_obj.nirvana_address)
    response_obj.nirvana_plan_details = data.get("nirvana_plan_details", response_obj.nirvana_plan_details)
    response_obj.nirvana_benefits = data.get("nirvana_benefits", response_obj.nirvana_benefits)

    # Therapy preferences
    response_obj.therapist_specializes_in = data.get("therapist_specializes_in", response_obj.therapist_specializes_in)
    response_obj.therapist_identifies_as = data.get("therapist_identifies_as", response_obj.therapist_identifies_as)
    response_obj.lived_experiences = data.get("lived_experiences", response_obj.lived_experiences)
    response_obj.matching_preference = data.get("matching_preference", response_obj.matching_preference)
    response_obj.what_brings_you = data.get("what_brings_you", response_obj.what_brings_you)

    # Extended demographics and screening
    response_obj.race_ethnicity = data.get("race_ethnicity", response_obj.race_ethnicity)
    response_obj.alcohol_frequency = data.get("alcohol_frequency", response_obj.alcohol_frequency)
    response_obj.recreational_drugs_frequency = data.get("recreational_drugs_frequency", response_obj.recreational_drugs_frequency)
    response_obj.safety_screening = data.get("safety_screening", response_obj.safety_screening)

    # Marketing attribution
    response_obj.utm_source = data.get("utm_source", response_obj.utm_source)
    response_obj.utm_medium = data.get("utm_medium", response_obj.utm_medium)
    response_obj.utm_campaign = data.get("utm_campaign", response_obj.utm_campaign)
    response_obj.referred_by = data.get("referred_by", response_obj.referred_by)
    response_obj.promo_code = data.get("promo_code", response_obj.promo_code)

    # Technical metadata
    response_obj.user_agent = data.get("user_agent", response_obj.user_agent)
    response_obj.screen_resolution = data.get("screen_resolution", response_obj.screen_resolution)
    response_obj.timezone_data = data.get("timezone", response_obj.timezone_data)
    response_obj.data_completeness_score = data.get("data_completeness_score", response_obj.data_completeness_score)

    # Therapist matching
    response_obj.selected_therapist_id = data.get("selected_therapist_id", response_obj.selected_therapist_id)
    response_obj.selected_therapist_email = data.get("selected_therapist_email", response_obj.selected_therapist_email)
    
    # Handle both string and object formats for selected_therapist
    selected_therapist_data = data.get("selected_therapist")
    if selected_therapist_data:
        if isinstance(selected_therapist_data, str):
            response_obj.selected_therapist = selected_therapist_data
        elif isinstance(selected_therapist_data, dict):
            # Extract name from object for database storage
            response_obj.selected_therapist = selected_therapist_data.get("name", "")
            # Also extract email if not already set
            if not response_obj.selected_therapist_email and selected_therapist_data.get("email"):
                response_obj.selected_therapist_email = selected_therapist_data.get("email")
    elif response_obj.selected_therapist is None:
        response_obj.selected_therapist = ""


def get_risk_level(phq9_score: int, gad7_score: int) -> str:
    """Determine risk level based on assessment scores."""
    max_score = max(phq9_score or 0, gad7_score or 0)

    if max_score >= 20:
        return "severe"
    elif max_score >= 15:
        return "moderately_severe"
    elif max_score >= 10:
        return "moderate"
    elif max_score >= 5:
        return "mild"
    else:
        return "minimal"


@clients_bp.route("/clients_signup/update_journey", methods=["POST"])
def update_journey():
    """
    Update client journey stage and SuperJson data
    
    This endpoint is called by the frontend to track user progress through
    different stages of the onboarding flow (survey_completed, therapist_matched, 
    therapist_selected, appointment_confirmed)
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        # Extract required fields
        response_id = data.get("response_id") or data.get("id")
        current_stage = data.get("current_stage")
        
        if not response_id:
            return jsonify({"error": "response_id is required"}), 400
        
        logger.info(f"📊 Journey update request: {response_id} -> {current_stage}")
        
        # Debug: Log key data fields being received
        critical_fields = ['payment_type', 'state', 'age', 'phq9_total', 'gad7_total', 'insurance_provider', 'alcohol_frequency']
        logger.info(f"🔍 Critical fields in update request:")
        for field in critical_fields:
            value = data.get(field)
            logger.info(f"  {field}: {value}")
        
        session = get_db_session()
        
        # Find existing response
        client_response = session.query(ClientResponse).filter_by(id=response_id).first()
        
        if not client_response:
            logger.warning(f"⚠️ Client response not found for journey update: {response_id}")
            return jsonify({"error": "Client response not found"}), 404
        
        logger.info(f"📋 BEFORE UPDATE - Current client data:")
        logger.info(f"  payment_type: {client_response.payment_type}")
        logger.info(f"  state: {client_response.state}")
        logger.info(f"  age: {client_response.age}")
        logger.info(f"  phq9_total: {client_response.phq9_total}")
        logger.info(f"  gad7_total: {client_response.gad7_total}")
        
        # Update current stage
        if current_stage:
            client_response.current_stage = current_stage
            logger.info(f"✅ Updated stage to: {current_stage}")
        
        # Update any other SuperJson fields that may have been sent
        update_response_fields(client_response, data)
        
        logger.info(f"📋 AFTER UPDATE - Updated client data:")
        logger.info(f"  payment_type: {client_response.payment_type}")
        logger.info(f"  state: {client_response.state}")
        logger.info(f"  age: {client_response.age}")
        logger.info(f"  phq9_total: {client_response.phq9_total}")
        logger.info(f"  gad7_total: {client_response.gad7_total}")
        
        # Save changes
        session.commit()
        
        logger.info(f"✅ Journey update successful for {response_id}")
        
        return jsonify({
            "success": True,
            "response_id": response_id,
            "current_stage": client_response.current_stage,
            "updated_at": client_response.updated_at.isoformat() if client_response.updated_at else None
        })
        
    except Exception as e:
        logger.error(f"❌ Error updating journey: {str(e)}")
        session.rollback()
        return jsonify({"error": f"Failed to update journey: {str(e)}"}), 500
    finally:
        session.close()
