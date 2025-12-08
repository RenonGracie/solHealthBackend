# src/api/appointments.py - IntakeQ integrated appointment booking
import logging
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from src.db import get_db_session
from src.db.models import Appointment, ClientResponse, Therapist
from src.services.async_tasks import async_task_processor

# Note: Progressive logging now handled in 3 stages throughout the user journey
from src.utils.intakeq.booking import book_appointment_with_intakeq

logger = logging.getLogger(__name__)

appointments_bp = Blueprint("appointments", __name__)


@appointments_bp.route("/appointments/clear-cache", methods=["POST"])
def clear_calendar_cache():
    """Clear Google Calendar cache manually (for testing/debugging)."""
    try:
        from src.utils.google.google_calendar import clear_cache

        clear_cache()
        logger.info("🔄 Manual cache clear requested")
        return jsonify(
            {"success": True, "message": "Calendar cache cleared successfully"}
        )
    except Exception as e:
        logger.error(f"❌ Failed to clear cache: {e}")
        return jsonify({"error": f"Failed to clear cache: {str(e)}"}), 500


@appointments_bp.route("/appointments/validate-timezone", methods=["POST"])
def validate_timezone():
    """
    Debug endpoint to validate timezone handling between frontend and backend.

    Expected payload:
    {
        "datetime": "2025-01-15T14:00:00",  // Local time without timezone
        "browser_timezone": "America/Chicago",
        "expected_utc": "2025-01-15T20:00:00Z"  // What frontend thinks UTC should be
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No data provided"}), 400

        appointment_datetime = data.get("datetime")
        browser_timezone = data.get("browser_timezone", "America/New_York")
        expected_utc = data.get("expected_utc")

        if not appointment_datetime:
            return jsonify({"error": "datetime is required"}), 400

        logger.info("🔍 TIMEZONE VALIDATION DEBUG:")
        logger.info(f"  Frontend datetime: {appointment_datetime}")
        logger.info(f"  Frontend timezone: {browser_timezone}")
        logger.info(f"  Frontend expected UTC: {expected_utc}")

        # Process datetime using our booking logic
        import pytz

        # Determine if datetime includes timezone info
        datetime_str = str(appointment_datetime)
        has_timezone = (
            "Z" in datetime_str
            or "+" in datetime_str[-6:]
            or "-" in datetime_str[-6:]
            or ("T" in datetime_str and len(datetime_str) > 19)
        )

        if has_timezone:
            # Parse as-is, it already has timezone
            if appointment_datetime.endswith("Z"):
                appointment_datetime = appointment_datetime[:-1] + "+00:00"
            start_dt = datetime.fromisoformat(appointment_datetime)
        else:
            # This is local time in the browser's timezone
            naive_dt = datetime.fromisoformat(appointment_datetime)

            # Localize to browser timezone
            try:
                local_tz = pytz.timezone(browser_timezone)
                start_dt = local_tz.localize(naive_dt)
            except Exception as e:
                logger.error(f"❌ Invalid timezone {browser_timezone}: {e}")
                # Fallback to Eastern
                local_tz = pytz.timezone("America/New_York")
                start_dt = local_tz.localize(naive_dt)

        # Convert to UTC
        backend_utc = start_dt.astimezone(dt_timezone.utc)

        # Compare with expected
        result = {
            "success": True,
            "input": {
                "datetime": data.get("datetime"),
                "browser_timezone": browser_timezone,
                "expected_utc": expected_utc,
            },
            "backend_processing": {
                "has_timezone_info": has_timezone,
                "localized_datetime": start_dt.isoformat(),
                "backend_utc": backend_utc.isoformat(),
                "timezone_used": str(start_dt.tzinfo),
            },
            "validation": {},
        }

        if expected_utc:
            expected_dt = datetime.fromisoformat(expected_utc.replace("Z", "+00:00"))
            time_diff_seconds = abs((backend_utc - expected_dt).total_seconds())

            result["validation"] = {
                "expected_utc": expected_dt.isoformat(),
                "backend_utc": backend_utc.isoformat(),
                "time_difference_seconds": time_diff_seconds,
                "matches": time_diff_seconds < 60,  # Allow 1 minute tolerance
                "status": "✅ MATCH"
                if time_diff_seconds < 60
                else f"❌ MISMATCH ({time_diff_seconds}s difference)",
            }

            logger.info(f"  Backend UTC: {backend_utc.isoformat()}")
            logger.info(f"  Expected UTC: {expected_dt.isoformat()}")
            logger.info(f"  Difference: {time_diff_seconds} seconds")
            logger.info(f"  Status: {result['validation']['status']}")

        # Add hour verification
        browser_hour = (
            start_dt.hour
            if start_dt.tzinfo != dt_timezone.utc
            else backend_utc.astimezone(pytz.timezone(browser_timezone)).hour
        )
        result["verification"] = {
            "browser_timezone_hour": browser_hour,
            "utc_hour": backend_utc.hour,
            "reasonable_business_hours": 6 <= browser_hour <= 22,
        }

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"❌ Timezone validation error: {str(e)}")
        import traceback

        traceback.print_exc()
        return (
            jsonify(
                {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            ),
            500,
        )


@appointments_bp.route("/appointments/intakeq-webhook", methods=["POST"])
def intakeq_webhook():
    """
    Webhook endpoint for IntakeQ to notify of appointment changes.
    Call this when IntakeQ creates/cancels appointments to clear cache immediately.

    Expected payload:
    {
        "event": "appointment_created" | "appointment_cancelled",
        "therapist_email": "therapist@example.com",
        "appointment_id": "intakeq_appointment_id",
        "client_email": "client@example.com"
    }
    """
    try:
        data = request.get_json() or {}
        event = data.get("event")
        therapist_email = data.get("therapist_email")

        logger.info(f"🔔 IntakeQ webhook received: {event} for {therapist_email}")

        if not event or not therapist_email:
            return (
                jsonify({"error": "Missing required fields: event, therapist_email"}),
                400,
            )

        if event in [
            "appointment_created",
            "appointment_cancelled",
            "appointment_updated",
        ]:
            # Clear cache for the specific therapist
            from src.utils.google.google_calendar import clear_cache_for_calendar

            cleared_count = clear_cache_for_calendar(therapist_email)

            logger.info(
                f"🔄 IntakeQ webhook: Cleared {cleared_count} cache entries for {therapist_email} due to {event}"
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Cache cleared for {therapist_email}",
                    "event": event,
                    "cleared_entries": cleared_count,
                }
            )
        else:
            logger.warning(f"⚠️ Unknown IntakeQ webhook event: {event}")
            return jsonify({"error": f"Unknown event type: {event}"}), 400

    except Exception as e:
        logger.error(f"❌ IntakeQ webhook error: {e}")
        return jsonify({"error": f"Webhook processing failed: {str(e)}"}), 500


def create_intakeq_client_profile(client_response):
    """
    Create IntakeQ client profile by calling the IntakeQ creation logic directly.

    Args:
        client_response: ClientResponse database object

    Returns:
        dict: Creation result with success status and intakeq_client_id
    """
    logger.info(f"🔄 Creating IntakeQ profile for: {client_response.email}")

    try:
        # Import the IntakeQ creation function and call it directly
        import os

        from src.api.intakeq_forms import build_comprehensive_intakeq_payload

        # Prepare comprehensive client data for IntakeQ creation including Nirvana data
        client_data = {
            "response_id": client_response.id,
            "first_name": client_response.first_name,
            "last_name": client_response.last_name,
            "email": client_response.email,
            "phone": client_response.phone,
            "age": client_response.age,
            "gender": client_response.gender,
            "state": client_response.state,
            "street_address": client_response.street_address,
            "city": client_response.city,
            "postal_code": client_response.postal_code,
            "university": client_response.university,
            "payment_type": client_response.payment_type,
            "therapist_specializes_in": client_response.therapist_specializes_in or [],
            "therapist_identifies_as": client_response.therapist_identifies_as,
            "lived_experiences": client_response.lived_experiences or [],
            "insurance_provider": client_response.insurance_provider,
            "insurance_member_id": client_response.insurance_member_id,
            "insurance_date_of_birth": client_response.insurance_date_of_birth,
            "insurance_verified": client_response.insurance_verified,
            "insurance_verification_data": client_response.insurance_verification_data,
            "what_brings_you": client_response.what_brings_you,
            "selected_therapist": client_response.selected_therapist,
            "selected_therapist_id": client_response.selected_therapist_id,
            "selected_therapist_email": client_response.selected_therapist_email,
            "matching_preference": client_response.matching_preference,
            "promo_code": client_response.promo_code,
            "referred_by": client_response.referred_by,
            "utm_source": client_response.utm_source,
            "utm_medium": client_response.utm_medium,
            "utm_campaign": client_response.utm_campaign,
            "match_status": client_response.match_status,
            "matched_therapist_id": client_response.matched_therapist_id,
            # Nirvana insurance verification data for comprehensive mapping
            "nirvana_raw_response": client_response.nirvana_raw_response,
            "nirvana_demographics": client_response.nirvana_demographics,
            "nirvana_address": client_response.nirvana_address,
            "nirvana_plan_details": client_response.nirvana_plan_details,
            "nirvana_benefits": client_response.nirvana_benefits,
        }

        # Add assessment scores if available
        if client_response.phq9_responses:
            client_data["phq9_scores"] = client_response.phq9_responses
            client_data["phq9_total"] = client_response.phq9_total

        if client_response.gad7_responses:
            client_data["gad7_scores"] = client_response.gad7_responses
            client_data["gad7_total"] = client_response.gad7_total

        logger.info(f"🔍 DEBUG: Client data keys: {list(client_data.keys())}")

        # Call IntakeQ creation logic directly (avoid HTTP self-call)
        payment_type = client_data.get("payment_type", "cash_pay")
        cash_pay_key = os.getenv("CASH_PAY_INTAKEQ_API_KEY")

        if payment_type == "cash_pay":
            intakeq_api_key = cash_pay_key
        else:  # insurance
            # client_response.state is already available from DB
            client_state = client_response.state
            from src.utils.intakeq.state_config import get_insurance_intakeq_config
            intakeq_api_key = get_insurance_intakeq_config(client_state, 'api_key')
            if not intakeq_api_key:
                # Fallback to generic insurance key
                intakeq_api_key = os.getenv("INSURANCE_INTAKEQ_API_KEY")

        if not intakeq_api_key:
            error_msg = f"Missing IntakeQ API key for payment type: {payment_type}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}

        # Build IntakeQ payload
        intakeq_payload = build_comprehensive_intakeq_payload(client_data, payment_type)

        # Make direct IntakeQ API call using configured base URL and correct headers
        from src.config import get_config

        config = get_config()
        intakeq_base_url = config.INTAKEQ_BASE_URL

        response = requests.post(
            f"{intakeq_base_url}/clients",
            json=intakeq_payload,
            headers={"X-Auth-Key": intakeq_api_key, "Content-Type": "application/json"},
            timeout=30,
        )

        logger.info(f"🔍 DEBUG: IntakeQ API response status: {response.status_code}")
        logger.info(f"🔍 DEBUG: IntakeQ API response: {response.text[:500]}...")

        if response.ok:
            result = response.json()
            intakeq_client_id = result.get("ClientId")

            if intakeq_client_id:
                logger.info(
                    f"✅ IntakeQ client created successfully: {intakeq_client_id}"
                )
                return {
                    "success": True,
                    "intakeq_client_id": intakeq_client_id,
                    "result": result,
                }
            else:
                logger.error(
                    f"❌ IntakeQ client creation succeeded but no ClientId returned: {result}"
                )
                return {
                    "success": False,
                    "error": "IntakeQ client created but no ClientId returned",
                }
        else:
            error_msg = (
                f"IntakeQ API call failed: {response.status_code} - {response.text}"
            )
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"❌ Error creating IntakeQ client: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


@appointments_bp.route("/appointments", methods=["POST"])
def book_appointment():
    """
    Book an appointment with full IntakeQ integration.

    This endpoint now follows the complete booking workflow from documentation:
    1. Validate client exists in local database
    2. Search for client in IntakeQ system
    3. Book appointment in IntakeQ system
    4. Create local appointment record with IntakeQ IDs
    5. Update client response with booking information
    """
    data = request.get_json()

    # Required fields
    required_fields = [
        "client_response_id",
        "therapist_email",
        "therapist_name",
        "datetime",
    ]

    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} is required"}), 400

    response_id = data["client_response_id"]

    # Stage 2: Log therapist confirmation (booking started)
    from src.services.google_sheets_progressive_logger import progressive_logger

    confirmation_data = {
        "response_id": response_id,
        "therapist_confirmed": "true",
        "therapist_confirmation_timestamp": datetime.utcnow().isoformat(),
        "confirmed_therapist_email": data["therapist_email"],
        "confirmed_therapist_name": data["therapist_name"],
    }
    progressive_logger.async_log_stage_2(confirmation_data)

    session = get_db_session()

    try:
        # Get the client response
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == data["client_response_id"])
            .first()
        )

        if not client_response:
            return jsonify({"error": "Client response not found"}), 404

        # Find the therapist in local database
        therapist_email = data["therapist_email"].strip().lower()
        therapist_name = data.get("therapist_name", "").strip()

        logger.info(f"🔍 [THERAPIST LOOKUP] Searching for therapist:")
        logger.info(f"  Email: {therapist_email}")
        logger.info(f"  Name: {therapist_name}")

        therapist = (
            session.query(Therapist)
            .filter(func.lower(Therapist.email) == therapist_email)
            .first()
        )

        if not therapist and therapist_name:
            # Try to find by name if email doesn't match
            logger.info(f"  Email lookup failed, trying name lookup...")
            therapist = (
                session.query(Therapist)
                .filter(Therapist.name == therapist_name)
                .first()
            )

        # Get therapist timezone for calendar display
        therapist_timezone = therapist.inferred_timezone() if therapist else None

        if not therapist:
            error_msg = (
                f"Therapist not found in database. "
                f"Email: {therapist_email}, Name: {therapist_name}. "
                f"Please ensure the therapist profile exists before booking."
            )
            logger.error(f"❌ [THERAPIST NOT FOUND] {error_msg}")

            # CRITICAL FIX: Return error immediately instead of proceeding with None therapist_id
            # This prevents booking failures when specific therapist is requested
            return (
                jsonify(
                    {
                        "error": "therapist_not_found",
                        "message": error_msg,
                        "details": {
                            "therapist_email": therapist_email,
                            "therapist_name": therapist_name,
                        },
                    }
                ),
                404,
            )
        else:
            therapist_id = therapist.id
            therapist_program = therapist.program
            logger.info(f"✅ [THERAPIST FOUND] ID: {therapist_id}, Program: {therapist_program}")

        # TIMEZONE HANDLING - Enhanced logging for debugging double conversion issues
        import pytz  # Move pytz import to the top to fix variable access error

        appointment_datetime = data["datetime"]
        browser_timezone = data.get("browser_timezone", "America/New_York")
        therapist_timezone_name = therapist.inferred_timezone() if therapist else "America/New_York"

        logger.info(f"🔍 [TIMEZONE DEBUG] Processing appointment booking:")
        logger.info(f"  Raw datetime from frontend: {appointment_datetime} (type: {type(appointment_datetime)})")
        logger.info(f"  Browser timezone: {browser_timezone}")
        logger.info(f"  Therapist timezone: {therapist_timezone_name}")
        logger.info(f"  Therapist email: {data.get('therapist_email', 'N/A')}")

        # Determine if datetime includes timezone info
        datetime_str = str(appointment_datetime)
        has_timezone = (
            "Z" in datetime_str
            or "+" in datetime_str[-6:]
            or "-" in datetime_str[-6:]
            or ("T" in datetime_str and len(datetime_str) > 19)
        )

        if has_timezone:
            logger.info("  ✅ Datetime includes timezone information")
            # Parse as-is, it already has timezone
            if isinstance(appointment_datetime, str):
                if appointment_datetime.endswith("Z"):
                    appointment_datetime = appointment_datetime[:-1] + "+00:00"
                start_dt = datetime.fromisoformat(appointment_datetime)
            else:
                # Unix timestamp - always UTC
                start_dt = datetime.fromtimestamp(
                    appointment_datetime, tz=dt_timezone.utc
                )
        else:
            logger.info("  ⚠️ Datetime is timezone-naive - determining correct timezone")
            # This is local time, but we need to determine if it's in browser TZ or therapist TZ
            if isinstance(appointment_datetime, str):
                naive_dt = datetime.fromisoformat(appointment_datetime)
            else:
                naive_dt = datetime.fromtimestamp(appointment_datetime)

            # CRITICAL FIX: Availability slots are displayed in THERAPIST's timezone,
            # so naive datetime should be interpreted as therapist's local time, NOT browser/user timezone
            # This prevents the double-conversion bug where PT times are treated as ET times
            logger.info(f"  📍 Comparing browser TZ ({browser_timezone}) vs therapist TZ ({therapist_timezone_name})")

            # Use therapist's timezone if available, otherwise fall back to browser timezone
            localization_tz = therapist_timezone_name if therapist else browser_timezone
            logger.info(f"  🎯 Using timezone for localization: {localization_tz}")

            # Localize to the correct timezone
            try:
                local_tz = pytz.timezone(localization_tz)
                start_dt = local_tz.localize(naive_dt)
                logger.info(f"  ✅ Localized to {localization_tz}: {start_dt}")

                # Warn if browser and therapist timezones differ (potential frontend issue)
                if browser_timezone != localization_tz:
                    logger.warning(
                        f"  ⚠️ [TIMEZONE MISMATCH] Browser TZ ({browser_timezone}) != "
                        f"Therapist TZ ({localization_tz}). Using therapist TZ to prevent double-conversion."
                    )
            except Exception as e:
                logger.error(f"❌ Invalid timezone {localization_tz}: {e}")
                # Fallback to Eastern
                local_tz = pytz.timezone("America/New_York")
                start_dt = local_tz.localize(naive_dt)
                logger.warning(f"  Fallback to Eastern: {start_dt}")

        # Convert to UTC for all backend operations
        start_dt_utc = start_dt.astimezone(dt_timezone.utc)
        logger.info(f"  Final UTC time: {start_dt_utc}")

        # Validate the time makes sense
        hour_in_browser_tz = (
            start_dt.hour
            if start_dt.tzinfo != dt_timezone.utc
            else start_dt.astimezone(pytz.timezone(browser_timezone)).hour
        )
        if hour_in_browser_tz < 6 or hour_in_browser_tz > 22:
            logger.warning(
                f"⚠️ Suspicious appointment hour: {hour_in_browser_tz} in {browser_timezone}"
            )

        start_dt = start_dt_utc

        # ============ ENFORCE 24-HOUR MINIMUM LEAD TIME ============
        import os

        now_utc = datetime.now(dt_timezone.utc)
        time_until_appointment_hours = (start_dt_utc - now_utc).total_seconds() / 3600

        MINIMUM_LEAD_TIME_HOURS = int(
            os.getenv("MINIMUM_BOOKING_LEAD_TIME_HOURS", "24")
        )

        if time_until_appointment_hours < MINIMUM_LEAD_TIME_HOURS:
            logger.warning(
                f"⚠️ Booking rejected: Appointment at {start_dt_utc.isoformat()} is only "
                f"{time_until_appointment_hours:.1f} hours away (minimum: {MINIMUM_LEAD_TIME_HOURS}h)"
            )
            logger.warning(f"   Current time: {now_utc.isoformat()}")
            logger.warning(f"   Browser timezone: {browser_timezone}")

            return (
                jsonify(
                    {
                        "error": f"Appointments must be booked at least {MINIMUM_LEAD_TIME_HOURS} hours in advance. "
                        f"Please select a time slot further in the future.",
                        "error_code": "INSUFFICIENT_LEAD_TIME",
                        "minimum_lead_time_hours": MINIMUM_LEAD_TIME_HOURS,
                        "hours_until_appointment": round(
                            time_until_appointment_hours, 2
                        ),
                        "requested_time_utc": start_dt_utc.isoformat(),
                        "current_time_utc": now_utc.isoformat(),
                    }
                ),
                400,
            )

        logger.info(
            f"✅ Lead time validation passed: {time_until_appointment_hours:.1f}h until appointment "
            f"(minimum: {MINIMUM_LEAD_TIME_HOURS}h)"
        )
        # ============ END LEAD TIME VALIDATION ============

        # Calculate end time using unified session duration logic
        from src.utils.google.google_calendar import get_therapist_session_duration

        duration_minutes = get_therapist_session_duration(
            therapist_email=data["therapist_email"],
            payment_type=client_response.payment_type,
        )
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # INTAKEQ INTEGRATION: Create client first, then book appointment
        logger.info("🔄 Creating IntakeQ client profile and booking appointment...")

        client_name = f"{client_response.first_name} {client_response.last_name}"
        session_type = data.get("session_type", "First Session")

        # Determine session type based on payment type and discount
        if hasattr(client_response, "discount"):
            if client_response.discount == 100:
                session_type = "First Session (Free)"
            elif client_response.discount == 50:
                session_type = "First Session (Promo Code)"

        # Check if referred by Sad Girls Club (CASH_PAY only) - gets free session
        if client_response.payment_type == "cash_pay":
            referred_by = client_response.referred_by if hasattr(client_response, "referred_by") else None
            if referred_by:
                # Handle both string and list types
                referred_list = referred_by if isinstance(referred_by, list) else [referred_by]
                if any(ref in ["Sad Girls Club"] for ref in referred_list):
                    session_type = "First Session (100% Free)"
                    logger.info(f"🎓 Special referral detected: Setting session to 100% free for referred_by={referred_by}")

        # Step 1: Create IntakeQ client profile if not exists
        intakeq_client_id = client_response.intakeq_client_id
        logger.info(f"🔍 DEBUG: Current intakeq_client_id = {intakeq_client_id}")
        logger.info(f"🔍 DEBUG: Client email = {client_response.email}")
        logger.info(
            f"🔍 DEBUG: Client name = {client_response.first_name} {client_response.last_name}"
        )

        if not intakeq_client_id:
            logger.info("🔄 Creating IntakeQ client profile first...")
            client_creation_result = create_intakeq_client_profile(client_response)
            logger.info(f"🔍 DEBUG: Client creation result = {client_creation_result}")

            if not client_creation_result.get("success"):
                error_msg = f"Failed to create IntakeQ client: {client_creation_result.get('error', 'Unknown error')}"
                logger.error(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 500

            intakeq_client_id = client_creation_result.get("intakeq_client_id")
            logger.info(f"✅ IntakeQ client created: {intakeq_client_id}")

            # Update client response with IntakeQ ID
            client_response.intakeq_client_id = intakeq_client_id
            session.commit()
            logger.info(
                f"✅ Database updated with intakeq_client_id: {intakeq_client_id}"
            )

            # ========== PRACTITIONER ASSIGNMENT HANDLED BY ASYNC TASKS ==========
            # Note: Practitioner assignment is now handled by execute_post_booking_tasks()
            # which is called after the booking is complete. This ensures proper async
            # handling with retry logic and Stage 3 logging.
            logger.info(
                f"✅ Client created: {intakeq_client_id}. Practitioner assignment will be handled by post-booking async tasks."
            )
        else:
            logger.info(f"✅ Using existing IntakeQ client: {intakeq_client_id}")

        # Step 2: Create Google Calendar event with Meets link FIRST (fix for missing Meets links issue)
        logger.info("🔄 Creating Google Calendar event with Meets link...")
        google_calendar_result = None
        google_event_id = None
        google_meets_link = None

        # Create calendar event for both insurance and cash-pay (fixes issue where insurance lacked Meets links)
        try:
            from src.utils.google.google_calendar import create_gcalendar_event

            # Use therapist's timezone for Google Calendar display (so therapist sees appointment in their local time)
            # The UTC time is correct, but the calendar display timezone should match the therapist's location
            calendar_timezone_name = (
                therapist_timezone
                if "therapist_timezone" in locals() and therapist_timezone
                else "America/New_York"
            )
            logger.info(
                f"  Using therapist timezone for Google Calendar display: {calendar_timezone_name}"
            )

            # Create attendees list
            attendees = [
                {"email": client_response.email, "name": client_name},
                {"email": data["therapist_email"], "name": data["therapist_name"]},
            ]

            # Create calendar event with Google Meets link
            google_calendar_result = create_gcalendar_event(
                summary=f"Sol Health Therapy Session - {client_name} with {data['therapist_name']}",
                start_time=start_dt,
                attendees=attendees,
                duration_minutes=duration_minutes,
                description=f"""Sol Health therapy appointment

Client: {client_name} ({client_response.email})
Therapist: {data['therapist_name']} ({data['therapist_email']})
Session Type: {session_type}
Payment Type: {client_response.payment_type}
""",
                timezone_name=calendar_timezone_name,
                create_meets_link=True,  # This fixes the missing Google Meets links issue
                send_updates="all",
            )

            if google_calendar_result and google_calendar_result.get("success"):
                google_event_id = google_calendar_result.get("event_id")
                google_meets_link = google_calendar_result.get("meets_link")

                logger.info(f"✅ Google Calendar event created: {google_event_id}")
                logger.info(f"✅ Google Meets link: {google_meets_link}")

                # This fixes the issue where insurance clients didn't get Google Meets links
                if not google_meets_link:
                    logger.warning(
                        "⚠️ Google Meets link was not created - this may affect user experience"
                    )
                else:
                    logger.info(
                        "✅ Google Meets link successfully created for appointment"
                    )
            else:
                error_msg = (
                    google_calendar_result.get("error")
                    if google_calendar_result
                    else "Unknown error"
                )
                is_timeout = (
                    google_calendar_result.get("timeout", False)
                    if google_calendar_result
                    else False
                )

                if is_timeout:
                    logger.warning(
                        f"⏰ Google Calendar API timeout - booking will continue without calendar event"
                    )
                    logger.info(f"📧 Email notifications will still be sent via IntakeQ")
                else:
                    logger.warning(
                        f"⚠️ Google Calendar event creation failed: {error_msg}"
                    )

                logger.warning(
                    "⚠️ Proceeding without calendar event (appointment still valid)"
                )

        except Exception as e:
            logger.error(f"❌ Error creating Google Calendar event: {str(e)}")
            logger.warning(
                "⚠️ Proceeding without calendar event (appointment still valid)"
            )
            import traceback

            traceback.print_exc()

        # Step 3: Book appointment in IntakeQ system with Google Meets link
        # Add timeout protection to prevent frontend timeout
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("IntakeQ booking timed out")

        # Set 25-second timeout for IntakeQ booking
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(25)

        # Determine if we should use client timezone for email confirmations
        # Only use client timezone for Limited Permit (associate) therapists
        email_timezone = None
        if therapist_program == "Limited Permit":
            email_timezone = data.get("user_timezone") or browser_timezone
            logger.info(
                f"🌍 Associate therapist detected - using client timezone for emails: {email_timezone}"
            )
        else:
            logger.info(
                f"🌍 Regular therapist - using default timezone for emails (therapist program: {therapist_program})"
            )

        try:
            intakeq_result = book_appointment_with_intakeq(
                client_email=client_response.email,
                client_name=client_name,
                therapist_email=data["therapist_email"],
                therapist_name=data["therapist_name"],
                appointment_datetime=start_dt,
                payment_type=client_response.payment_type,  # Use existing payment type
                session_type=session_type,
                send_email_notification=data.get(
                    "send_client_email_notification", True
                ),
                reminder_type=data.get("reminder_type", "Email"),
                status=data.get("status", "Confirmed"),
                intakeq_client_id=intakeq_client_id,  # Pass the client ID we just created
                google_meets_link=google_meets_link,  # Pass the Google Meets link for email inclusion
                client_timezone=email_timezone,  # Pass client timezone only for associate therapists
                client_state=client_response.state,  # Pass client state for state-specific API key selection
            )
        except TimeoutError:
            logger.error("❌ IntakeQ booking timed out after 25 seconds")
            return (
                jsonify(
                    {"error": "Booking timeout - please try again or contact support"}
                ),
                500,
            )
        finally:
            signal.alarm(0)  # Cancel the timeout

        if not intakeq_result.get("success"):
            error_msg = f"IntakeQ booking failed: {intakeq_result.get('error', 'Unknown error')}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        # Extract IntakeQ IDs from successful booking
        intakeq_appointment_id = intakeq_result.get("intakeq_appointment_id")
        intakeq_client_id = intakeq_result.get("intakeq_client_id")
        intakeq_therapist_id = intakeq_result.get("intakeq_therapist_id")

        logger.info(f"✅ IntakeQ appointment created: {intakeq_appointment_id}")

        # Confirm that Google Meets link was included in IntakeQ email
        if google_meets_link:
            logger.info(
                f"✅ Google Meets link included in IntakeQ appointment email: {google_meets_link}"
            )
        else:
            logger.warning(
                "⚠️ No Google Meets link available for IntakeQ appointment email"
            )

        # Note: Selenium practitioner assignment moved to async post-booking tasks

        # Create local appointment record with IntakeQ integration
        appointment_id = str(uuid.uuid4())
        appointment = Appointment(
            id=appointment_id,
            client_response_id=data["client_response_id"],
            therapist_id=therapist_id,
            practitioner_email=data["therapist_email"],
            practitioner_name=data["therapist_name"],
            start_date_iso=start_dt.isoformat(),
            status=data.get("status", "Confirmed"),
            reminder_type=data.get("reminder_type", "email"),
            send_client_email_notification=data.get(
                "send_client_email_notification", True
            ),
            booked_by_client=True,
            date_created=int(datetime.now().timestamp()),
            last_modified=int(datetime.now().timestamp()),
            created_at=datetime.now(dt_timezone.utc),
            # Store IntakeQ IDs
            intakeq_appointment_id=intakeq_appointment_id,
        )

        # Handle Google Calendar event IDs if available
        if google_event_id:
            appointment.google_event_id = google_event_id

        session.add(appointment)

        # Update client response with booking information and IntakeQ IDs
        client_response.match_status = "booked"
        client_response.matched_therapist_id = therapist_id
        client_response.matched_therapist_email = data["therapist_email"]
        client_response.matched_therapist_name = data["therapist_name"]
        client_response.matched_slot_start = start_dt
        client_response.matched_slot_end = end_dt
        client_response.practitioner_assignment_status = (
            "async_pending"  # Set when async task starts
        )
        client_response.updated_at = datetime.now(dt_timezone.utc)

        # Track therapist selection - compare selected vs algorithm suggested
        if therapist and client_response.algorithm_suggested_therapist_id:
            # Check if user chose a different therapist than algorithm's #1 pick
            selected_therapist_id = therapist.id if therapist else None
            algorithm_suggested_id = client_response.algorithm_suggested_therapist_id

            client_response.user_chose_alternative = (
                selected_therapist_id != algorithm_suggested_id
            )
            client_response.therapist_selection_timestamp = datetime.now(dt_timezone.utc)

            if client_response.user_chose_alternative:
                logger.info(
                    f"🔄 User chose alternative therapist: {data['therapist_name']} "
                    f"(suggested: {client_response.algorithm_suggested_therapist_name})"
                )
            else:
                logger.info(
                    f"✅ User chose algorithm's #1 suggestion: {data['therapist_name']}"
                )

        # Store selected therapist (what user actually booked)
        client_response.selected_therapist = data["therapist_name"]
        client_response.selected_therapist_id = therapist.id if therapist else None
        client_response.selected_therapist_email = data["therapist_email"]

        # Store IntakeQ client ID if available
        if intakeq_client_id:
            client_response.intakeq_client_id = intakeq_client_id

        # Handle additional IDs from request
        if data.get("google_event_id"):
            appointment.google_event_id = data["google_event_id"]

        # Commit all changes
        session.commit()

        # Capture appointment data before session closes (to avoid SQLAlchemy DetachedInstanceError)
        appointment_status = appointment.status
        appointment_reminder_type = appointment.reminder_type
        appointment_send_email = appointment.send_client_email_notification
        appointment_date_created = appointment.date_created
        appointment_last_modified = appointment.last_modified

        # IMPORTANT: Clear Google Calendar cache to ensure immediate availability updates
        try:
            from src.utils.google.google_calendar import clear_cache_for_calendar

            therapist_email = data.get("therapist_email")
            if therapist_email:
                cleared_count = clear_cache_for_calendar(therapist_email)
                logger.info(
                    f"🔄 Cleared {cleared_count} cache entries for {therapist_email} after booking"
                )
            else:
                # Fallback to clearing all cache if no therapist email
                from src.utils.google.google_calendar import clear_cache

                clear_cache()
                logger.info(
                    "🔄 Cleared all calendar cache after booking (no therapist email found)"
                )
        except Exception as cache_e:
            logger.warning(f"⚠️ Failed to clear calendar cache: {cache_e}")

        logger.info("=" * 50)
        logger.info("📅 [INTAKEQ APPOINTMENT BOOKED SUCCESSFULLY]")
        logger.info(f"  Local Appointment ID: {appointment_id}")
        logger.info(f"  IntakeQ Appointment ID: {intakeq_appointment_id}")
        logger.info(f"  IntakeQ Client ID: {intakeq_client_id}")
        logger.info(
            f"  Client: {client_response.first_name} {client_response.last_name} ({data['client_response_id']})"
        )
        logger.info(
            f"  Therapist: {data['therapist_name']} ({data['therapist_email']})"
        )
        logger.info(f"  Date: {start_dt.isoformat()} - {end_dt.isoformat()}")
        logger.info(f"  Duration: {duration_minutes} minutes")
        logger.info(f"  Payment Type: {client_response.payment_type}")
        logger.info(f"  Session Type: {session_type}")
        logger.info("=" * 50)

        # Note: Appointment booking tracking now handled by progressive logger Stage 3 (async)

        # Execute post-booking tasks asynchronously (Selenium + Google Sheets)
        try:
            logger.info("=" * 50)
            logger.info("📊 [STAGE 3 CHECKPOINT 1] Starting comprehensive_data construction")
            logger.info(f"  Response ID: {response_id}")
            logger.info(f"  Client Response ID: {client_response.id}")
            logger.info(f"  Therapist: {data['therapist_name']} ({data['therapist_email']})")
            logger.info("=" * 50)

            # Helper function to safely parse alternative_therapists_offered (might be JSON string or dict)
            def safe_parse_alt_therapists(field_name):
                """Safely extract field from alternative_therapists_offered which might be a JSON string"""
                import json
                alt_therapists = getattr(client_response, "alternative_therapists_offered", None)
                if not alt_therapists:
                    return [] if field_name in ["names", "ids", "emails", "scores"] else 0 if field_name == "count" else ""

                # If it's a string, try to parse it as JSON
                if isinstance(alt_therapists, str):
                    try:
                        alt_therapists = json.loads(alt_therapists)
                    except Exception as e:
                        logger.warning(f"Failed to parse alternative_therapists_offered JSON: {e}")
                        return [] if field_name in ["names", "ids", "emails", "scores"] else 0 if field_name == "count" else ""

                # Now safely get the field
                if isinstance(alt_therapists, dict):
                    if field_name == "count":
                        return len(alt_therapists.get("names", []))
                    else:
                        return alt_therapists.get(field_name, [])

                return [] if field_name in ["names", "ids", "emails", "scores"] else 0 if field_name == "count" else ""

            # Pre-compute alternative therapists data safely
            safe_alt_therapists_count = safe_parse_alt_therapists("count")
            safe_alt_therapists_names = ", ".join(safe_parse_alt_therapists("names"))
            safe_alt_therapists_ids = ", ".join(str(id) for id in safe_parse_alt_therapists("ids"))
            safe_alt_therapists_emails = ", ".join(safe_parse_alt_therapists("emails"))
            safe_alt_therapists_scores = ", ".join(str(score) for score in safe_parse_alt_therapists("scores"))

            # Prepare comprehensive data for Google Sheets logging
            comprehensive_data = {
                # Journey Tracking
                "journey_id": client_response.id,
                "stage_completed": "3",
                "stage_1_timestamp": (
                    getattr(client_response, "created_at", None) or datetime.utcnow()
                ).isoformat(),
                "stage_2_timestamp": data.get(
                    "therapist_confirmation_timestamp", datetime.utcnow().isoformat()
                ),
                "stage_3_timestamp": datetime.utcnow().isoformat(),
                "last_updated": datetime.utcnow().isoformat(),
                # Basic User Information
                "response_id": client_response.id,
                "email": client_response.email,
                "first_name": client_response.first_name,
                "last_name": client_response.last_name,
                "preferred_name": getattr(client_response, "preferred_name", ""),
                "middle_name": getattr(client_response, "middle_name", ""),
                "phone": client_response.phone,
                "mobile_phone": getattr(
                    client_response, "mobile_phone", client_response.phone
                ),
                "date_of_birth": getattr(client_response, "date_of_birth", ""),
                "age": client_response.age,
                "gender": client_response.gender,
                # Address & Location
                "street_address": getattr(client_response, "street_address", ""),
                "city": getattr(client_response, "city", ""),
                "state": client_response.state,
                "postal_code": getattr(client_response, "postal_code", ""),
                "country": getattr(client_response, "country", "USA"),
                # Nirvana Enhanced Address Fields (if available)
                "nirvana_street_line_1": getattr(
                    client_response, "nirvana_street_line_1", ""
                ),
                "nirvana_street_line_2": getattr(
                    client_response, "nirvana_street_line_2", ""
                ),
                "nirvana_city": getattr(client_response, "nirvana_city", ""),
                "nirvana_state": getattr(client_response, "nirvana_state", ""),
                "nirvana_zip": getattr(client_response, "nirvana_zip", ""),
                # Demographics & Background
                "marital_status": getattr(client_response, "marital_status", ""),
                "race_ethnicity": ", ".join(client_response.race_ethnicity)
                if client_response.race_ethnicity
                else "",
                "lived_experiences": ", ".join(client_response.lived_experiences)
                if client_response.lived_experiences
                else "",
                "university": client_response.university,
                "referred_by": client_response.referred_by,
                # PHQ-9 Assessment (expanded individual scores)
                "phq9_pleasure_doing_things": client_response.phq9_responses.get(
                    "pleasure_doing_things", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_feeling_down": client_response.phq9_responses.get(
                    "feeling_down", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_trouble_falling": client_response.phq9_responses.get(
                    "trouble_falling", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_feeling_tired": client_response.phq9_responses.get(
                    "feeling_tired", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_poor_appetite": client_response.phq9_responses.get(
                    "poor_appetite", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_feeling_bad_about_yourself": client_response.phq9_responses.get(
                    "feeling_bad_about_yourself", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_trouble_concentrating": client_response.phq9_responses.get(
                    "trouble_concentrating", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_moving_or_speaking_so_slowly": client_response.phq9_responses.get(
                    "moving_or_speaking_so_slowly", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_suicidal_thoughts": client_response.phq9_responses.get(
                    "suicidal_thoughts", ""
                )
                if client_response.phq9_responses
                else "",
                "phq9_total_score": client_response.phq9_total,
                # GAD-7 Assessment (expanded individual scores)
                "gad7_feeling_nervous": client_response.gad7_responses.get(
                    "feeling_nervous", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_not_control_worrying": client_response.gad7_responses.get(
                    "not_control_worrying", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_worrying_too_much": client_response.gad7_responses.get(
                    "worrying_too_much", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_trouble_relaxing": client_response.gad7_responses.get(
                    "trouble_relaxing", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_being_so_restless": client_response.gad7_responses.get(
                    "being_so_restless", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_easily_annoyed": client_response.gad7_responses.get(
                    "easily_annoyed", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_feeling_afraid": client_response.gad7_responses.get(
                    "feeling_afraid", ""
                )
                if client_response.gad7_responses
                else "",
                "gad7_total_score": client_response.gad7_total,
                # Substance Use
                "alcohol_frequency": getattr(client_response, "alcohol_frequency", ""),
                "recreational_drugs_frequency": getattr(
                    client_response, "recreational_drugs_frequency", ""
                ),
                # Therapist Preferences
                "therapist_gender_preference": getattr(
                    client_response, "therapist_gender_preference", ""
                ),
                "therapist_specialization": ", ".join(
                    client_response.therapist_specializes_in
                )
                if client_response.therapist_specializes_in
                else "",
                "therapist_lived_experiences": client_response.therapist_identifies_as,
                # Payment & Insurance
                "payment_type": client_response.payment_type,
                "insurance_provider": client_response.insurance_provider,
                "insurance_member_id": client_response.insurance_member_id,
                "insurance_date_of_birth": getattr(
                    client_response, "insurance_date_of_birth", ""
                ),
                "copay": getattr(client_response, "copay", ""),
                "deductible": getattr(client_response, "deductible", ""),
                "coinsurance": getattr(client_response, "coinsurance", ""),
                "out_of_pocket_max": getattr(client_response, "out_of_pocket_max", ""),
                "remaining_deductible": getattr(
                    client_response, "remaining_deductible", ""
                ),
                "remaining_oop_max": getattr(client_response, "remaining_oop_max", ""),
                "member_obligation": getattr(client_response, "member_obligation", ""),
                "benefit_structure": getattr(client_response, "benefit_structure", ""),
                "session_cost_dollars": getattr(
                    client_response, "session_cost_dollars", ""
                ),
                "payer_id": getattr(client_response, "payer_id", ""),
                # Insurance Correction Tracking
                "insurance_provider_original": getattr(
                    client_response, "insurance_provider_original", ""
                ),
                "insurance_provider_corrected": getattr(
                    client_response, "insurance_provider_corrected", ""
                ),
                "insurance_correction_type": getattr(
                    client_response, "insurance_correction_type", ""
                ),
                # Enhanced Nirvana Insurance Fields
                "nirvana_plan_name": getattr(client_response, "nirvana_plan_name", ""),
                "nirvana_group_id": getattr(client_response, "nirvana_group_id", ""),
                "nirvana_payer_id": getattr(client_response, "nirvana_payer_id", ""),
                "nirvana_plan_status": getattr(
                    client_response, "nirvana_plan_status", ""
                ),
                "nirvana_coverage_status": getattr(
                    client_response, "nirvana_coverage_status", ""
                ),
                "nirvana_relationship_to_subscriber": getattr(
                    client_response, "nirvana_relationship_to_subscriber", ""
                ),
                "nirvana_insurance_type": getattr(
                    client_response, "nirvana_insurance_type", ""
                ),
                "nirvana_insurance_company_name": getattr(
                    client_response, "nirvana_insurance_company_name", ""
                ),
                "nirvana_member_id_policy_number": getattr(
                    client_response, "nirvana_member_id_policy_number", ""
                ),
                "nirvana_group_number": getattr(
                    client_response, "nirvana_group_number", ""
                ),
                "nirvana_plan_program": getattr(
                    client_response, "nirvana_plan_program", ""
                ),
                "nirvana_policyholder_relationship": getattr(
                    client_response, "nirvana_policyholder_relationship", ""
                ),
                "nirvana_policyholder_name": getattr(
                    client_response, "nirvana_policyholder_name", ""
                ),
                "nirvana_policyholder_first_name": getattr(
                    client_response, "nirvana_policyholder_first_name", ""
                ),
                "nirvana_policyholder_last_name": getattr(
                    client_response, "nirvana_policyholder_last_name", ""
                ),
                "nirvana_policyholder_street_address": getattr(
                    client_response, "nirvana_policyholder_street_address", ""
                ),
                "nirvana_policyholder_city": getattr(
                    client_response, "nirvana_policyholder_city", ""
                ),
                "nirvana_policyholder_state": getattr(
                    client_response, "nirvana_policyholder_state", ""
                ),
                "nirvana_policyholder_zip_code": getattr(
                    client_response, "nirvana_policyholder_zip_code", ""
                ),
                "nirvana_policyholder_date_of_birth": getattr(
                    client_response, "nirvana_policyholder_date_of_birth", ""
                ),
                "nirvana_policyholder_sex": getattr(
                    client_response, "nirvana_policyholder_sex", ""
                ),
                # Algorithm Suggested Therapist (what matching algorithm recommended)
                "algorithm_suggested_therapist_id": getattr(
                    client_response, "algorithm_suggested_therapist_id", ""
                ),
                "algorithm_suggested_therapist_name": getattr(
                    client_response, "algorithm_suggested_therapist_name", ""
                ),
                "algorithm_suggested_therapist_score": getattr(
                    client_response, "algorithm_suggested_therapist_score", ""
                ),
                "alternative_therapists_count": safe_alt_therapists_count,
                "alternative_therapists_names": safe_alt_therapists_names,
                "alternative_therapists_ids": safe_alt_therapists_ids,
                "alternative_therapists_emails": safe_alt_therapists_emails,
                "alternative_therapists_scores": safe_alt_therapists_scores,
                # Selected Therapist (what user chose to book)
                "selected_therapist_id": therapist.id if therapist else None,
                "selected_therapist_name": data["therapist_name"],
                "selected_therapist_email": data["therapist_email"],
                "user_chose_alternative": getattr(client_response, "user_chose_alternative", False),
                "therapist_selection_timestamp": (
                    getattr(client_response, "therapist_selection_timestamp", None) or datetime.utcnow()
                ).isoformat(),
                # Matched Therapist Data (final confirmed booking)
                "matched_therapist_id": therapist.id if therapist else None,
                "matched_therapist_name": data[
                    "therapist_name"
                ],  # Use the therapist client actually booked
                "matched_therapist_email": data[
                    "therapist_email"
                ],  # Use the therapist client actually booked
                "match_score": getattr(client_response, "match_score", ""),
                "matched_specialties": getattr(
                    client_response, "matched_specialties", ""
                ),
                "therapist_confirmed": "true",
                "therapist_confirmation_timestamp": data.get(
                    "therapist_confirmation_timestamp", datetime.utcnow().isoformat()
                ),
                # Booked Therapist (explicit - same as matched_therapist for clarity)
                "booked_therapist_id": therapist.id if therapist else None,
                "booked_therapist_name": data["therapist_name"],
                "booked_therapist_email": data["therapist_email"],
                # Appointment Data
                "appointment_date": start_dt.date().isoformat(),
                "appointment_time": start_dt.time().isoformat(),
                "appointment_timezone": str(start_dt.tzinfo),
                "appointment_duration": duration_minutes,
                "appointment_type": session_type,
                "appointment_id": appointment_id,
                "google_event_id": google_event_id or "",
                "appointment_status": "booked",
                # IntakeQ Data
                "intakeq_client_id": intakeq_client_id,
                "intakeq_intake_url": getattr(
                    client_response, "intakeq_intake_url", ""
                ),
                "mandatory_form_sent": getattr(
                    client_response, "mandatory_form_sent", ""
                ),
                "mandatory_form_intake_id": getattr(
                    client_response, "mandatory_form_intake_id", ""
                ),
                "mandatory_form_intake_url": getattr(
                    client_response, "mandatory_form_intake_url", ""
                ),
                "mandatory_form_sent_at": getattr(
                    client_response, "mandatory_form_sent_at", ""
                ),
                # Additional Context
                "safety_screening": getattr(client_response, "safety_screening", ""),
                "matching_preference": client_response.matching_preference,
                "what_brings_you": client_response.what_brings_you,
                # Tracking Data
                "sol_health_response_id": client_response.id,
                "session_id": getattr(client_response, "session_id", ""),
                "onboarding_completed_at": (
                    getattr(client_response, "created_at", None) or datetime.utcnow()
                ).isoformat(),
                "survey_completed_at": (
                    getattr(client_response, "updated_at", None) or datetime.utcnow()
                ).isoformat(),
                "utm_source": client_response.utm_source,
                "utm_medium": client_response.utm_medium,
                "utm_campaign": client_response.utm_campaign,
                "signup_timestamp": (
                    getattr(client_response, "created_at", None) or datetime.utcnow()
                ).isoformat(),
                "completion_timestamp": datetime.utcnow().isoformat(),
                "user_agent": getattr(client_response, "user_agent", ""),
                "ip_address": getattr(client_response, "ip_address", ""),
                # Technical Metadata
                "screen_resolution": getattr(client_response, "screen_resolution", ""),
                "browser_timezone": getattr(client_response, "browser_timezone", ""),
                "data_completeness_score": getattr(client_response, "data_completeness_score", ""),
                # System Metadata
                "environment": "production",
                "api_version": "1.0",
                "frontend_version": "1.0",
                "created_at": (
                    getattr(client_response, "created_at", None) or datetime.utcnow()
                ).isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                # Additional Nirvana Fields
                "nirvana_verification_timestamp": getattr(
                    client_response, "nirvana_verification_timestamp", ""
                ),
                "nirvana_verification_status": getattr(
                    client_response, "nirvana_verification_status", ""
                ),
                "nirvana_eligibility_end_date": getattr(
                    client_response, "nirvana_eligibility_end_date", ""
                ),
                "nirvana_plan_begin_date": getattr(
                    client_response, "nirvana_plan_begin_date", ""
                ),
                "nirvana_plan_end_date": getattr(
                    client_response, "nirvana_plan_end_date", ""
                ),
                # Enhanced Financial Fields
                "copay_dollars": getattr(client_response, "copay_dollars", ""),
                "deductible_dollars": getattr(
                    client_response, "deductible_dollars", ""
                ),
                "remaining_deductible_dollars": getattr(
                    client_response, "remaining_deductible_dollars", ""
                ),
                "oop_max_dollars": getattr(client_response, "oop_max_dollars", ""),
                "remaining_oop_max_dollars": getattr(
                    client_response, "remaining_oop_max_dollars", ""
                ),
                "member_obligation_dollars": getattr(
                    client_response, "member_obligation_dollars", ""
                ),
                "payer_obligation_dollars": getattr(
                    client_response, "payer_obligation_dollars", ""
                ),
                # Telehealth Fields
                "telehealth_copay": getattr(client_response, "telehealth_copay", ""),
                "telehealth_member_obligation": getattr(
                    client_response, "telehealth_member_obligation", ""
                ),
                "sessions_before_deductible_met": getattr(
                    client_response, "sessions_before_deductible_met", ""
                ),
                "sessions_before_oop_max_met": getattr(
                    client_response, "sessions_before_oop_max_met", ""
                ),
                # Raw Data Storage
                "nirvana_raw_response_excerpt": str(
                    getattr(client_response, "nirvana_raw_response", "")
                )[:200]
                + "..."
                if getattr(client_response, "nirvana_raw_response", "")
                else "",
                "data_sources_used": getattr(client_response, "data_sources_used", ""),
                "fields_extracted_count": getattr(
                    client_response, "fields_extracted_count", ""
                ),
            }

            logger.info("=" * 50)
            logger.info("📊 [STAGE 3 CHECKPOINT 2] comprehensive_data constructed successfully")
            logger.info(f"  Total fields in comprehensive_data: {len(comprehensive_data)}")
            logger.info(f"  Stage completed: {comprehensive_data.get('stage_completed')}")
            logger.info(f"  Journey ID: {comprehensive_data.get('journey_id')}")
            logger.info(f"  Matched Therapist: {comprehensive_data.get('matched_therapist_name')}")
            logger.info(f"  Appointment ID: {comprehensive_data.get('appointment_id')}")
            logger.info(f"  IntakeQ Client ID: {comprehensive_data.get('intakeq_client_id')}")

            # Check for critical fields
            critical_fields = ['response_id', 'email', 'matched_therapist_name', 'appointment_date', 'intakeq_client_id']
            missing_critical = [f for f in critical_fields if not comprehensive_data.get(f)]
            if missing_critical:
                logger.warning(f"  ⚠️ Missing critical fields: {missing_critical}")
            else:
                logger.info(f"  ✅ All critical fields present")

            # Check for commonly missing fields that user reported
            commonly_missing = {
                'date_of_birth': comprehensive_data.get('date_of_birth'),
                'race_ethnicity': comprehensive_data.get('race_ethnicity'),
                'therapist_gender_preference': comprehensive_data.get('therapist_gender_preference'),
                'what_brings_you': comprehensive_data.get('what_brings_you'),
                'phq9_total_score': comprehensive_data.get('phq9_total_score'),
                'gad7_total_score': comprehensive_data.get('gad7_total_score'),
                'alternative_therapists_names': comprehensive_data.get('alternative_therapists_names'),
                'booked_therapist_name': comprehensive_data.get('booked_therapist_name'),
            }
            logger.info("  📋 User-reported field status:")
            for field, value in commonly_missing.items():
                status = "✅" if value else "⚠️ EMPTY"
                display_val = str(value)[:30] if value else "(empty)"
                logger.info(f"    {status} {field:35s} = {display_val}")
            logger.info("=" * 50)

            # Prepare async task data
            account_type = (
                "cash_pay"
                if client_response.payment_type == "cash_pay"
                else "insurance"
            )
            task_data = {
                # Stage 3 progressive logging
                "response_id": response_id,
                # Selenium data
                "account_type": account_type,
                "intakeq_client_id": intakeq_client_id,
                "therapist_name": data["therapist_name"],
                "state": client_response.state,  # Client state for state-specific IntakeQ credentials
                # Google Sheets data (comprehensive Stage 3 data)
                "comprehensive_data": comprehensive_data,
            }

            logger.info("=" * 50)
            logger.info("📊 [STAGE 3 CHECKPOINT 3] task_data prepared for async execution")
            logger.info(f"  Response ID: {task_data.get('response_id')}")
            logger.info(f"  Account Type: {task_data.get('account_type')}")
            logger.info(f"  State: {task_data.get('state')}")
            logger.info(f"  IntakeQ Client ID: {task_data.get('intakeq_client_id')}")
            logger.info(f"  Therapist: {task_data.get('therapist_name')}")
            logger.info(f"  comprehensive_data included: {bool(task_data.get('comprehensive_data'))}")
            logger.info(f"  comprehensive_data fields: {len(task_data.get('comprehensive_data', {}))}")
            logger.info("=" * 50)

            # Execute async post-booking tasks
            logger.info("🚀 [STAGE 3 CHECKPOINT 4] Executing async post-booking tasks...")
            async_task_processor.execute_post_booking_tasks(
                task_data=task_data,
                appointment_id=appointment_id,
                client_response_id=client_response.id,
            )
            logger.info("✅ [STAGE 3 CHECKPOINT 5] Async post-booking tasks initiated successfully")
            logger.info("=" * 50)

        except Exception as e:
            logger.error("=" * 50)
            logger.error(f"❌ [STAGE 3 CHECKPOINT ERROR] Error starting async post-booking tasks")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.error(f"  Error message: {str(e)}")
            logger.error(f"  Response ID: {response_id}")
            import traceback
            logger.error(f"  Traceback: {traceback.format_exc()}")
            logger.error("=" * 50)
            # Don't fail the booking if async tasks fail to start

        # Get therapist program for enhanced logging
        therapist_program = "Unknown"
        try:
            session = get_db_session()
            try:
                therapist = (
                    session.query(Therapist)
                    .filter(Therapist.email == data["therapist_email"])
                    .first()
                )
                if therapist and therapist.program:
                    therapist_program = therapist.program
            finally:
                session.close()
        except Exception as e:
            logger.warning(
                f"Could not lookup therapist program for {data['therapist_email']}: {str(e)}"
            )

        # Return IntakeQ-compatible response format with Google Calendar integration
        response_data = {
            "Id": appointment_id,
            "IntakeQAppointmentId": intakeq_appointment_id,
            "IntakeQClientId": intakeq_client_id,
            "IntakeQTherapistId": intakeq_therapist_id,
            "ClientResponseId": data["client_response_id"],
            "PractitionerEmail": data["therapist_email"],
            "PractitionerName": data["therapist_name"],
            "PractitionerProgram": therapist_program,
            "StartDateIso": start_dt.isoformat(),
            "EndDateIso": end_dt.isoformat(),
            "Status": appointment_status,
            "ReminderType": appointment_reminder_type,
            "SendClientEmailNotification": appointment_send_email,
            "BookedByClient": True,
            "DateCreated": appointment_date_created,
            "LastModified": appointment_last_modified,
            "match_status": client_response.match_status,
            "therapist_id": therapist_id,
            "session_type": session_type,
            "duration_minutes": duration_minutes,
            "therapist_program": therapist_program,
            "availability_system_used": "unified_availability_v2",
            "intakeq_integration": True,
            "payment_type_used": intakeq_result.get(
                "payment_type", client_response.payment_type
            ),
            # Google Calendar integration (fixes missing Meets links issue)
            "google_event_id": google_event_id,
            "google_meets_link": google_meets_link,
            "google_calendar_integration": True if google_event_id else False,
            # Selenium bot practitioner assignment status (from database)
            "practitioner_assignment_status": client_response.practitioner_assignment_status,
            "selenium_bot_integration": True,
        }

        return jsonify(response_data), 200

    except Exception as e:
        session.rollback()
        logger.error(f"❌ [INTAKEQ APPOINTMENT BOOKING ERROR] {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": f"Failed to book appointment: {str(e)}"}), 500
    finally:
        session.close()


@appointments_bp.route("/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id: str):
    """Get appointment details by ID."""
    session = get_db_session()

    try:
        appointment = (
            session.query(Appointment).filter(Appointment.id == appointment_id).first()
        )

        if not appointment:
            return jsonify({"error": "Appointment not found"}), 404

        return jsonify(
            {
                "Id": appointment.id,
                "ClientResponseId": appointment.client_response_id,
                "TherapistId": appointment.therapist_id,
                "PractitionerEmail": appointment.practitioner_email,
                "PractitionerName": appointment.practitioner_name,
                "StartDateIso": appointment.start_date_iso,
                "Status": appointment.status,
                "IntakeQAppointmentId": appointment.intakeq_appointment_id,
                "GoogleEventId": appointment.google_event_id,
                "CreatedAt": appointment.created_at.isoformat()
                if appointment.created_at
                else None,
            }
        )

    except Exception as e:
        logger.error(f"❌ [APPOINTMENT FETCH ERROR] {str(e)}")
        return jsonify({"error": "Failed to fetch appointment"}), 500
    finally:
        session.close()


@appointments_bp.route("/appointments/client/<client_response_id>", methods=["GET"])
def get_client_appointments(client_response_id: str):
    """Get all appointments for a client."""
    session = get_db_session()

    try:
        appointments = (
            session.query(Appointment)
            .filter(Appointment.client_response_id == client_response_id)
            .order_by(Appointment.created_at.desc())
            .all()
        )

        return jsonify(
            {
                "appointments": [
                    {
                        "Id": a.id,
                        "TherapistName": a.practitioner_name,
                        "TherapistEmail": a.practitioner_email,
                        "StartDateIso": a.start_date_iso,
                        "Status": a.status,
                        "CreatedAt": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in appointments
                ]
            }
        )

    except Exception as e:
        logger.error(f"❌ [CLIENT APPOINTMENTS FETCH ERROR] {str(e)}")
        return jsonify({"error": "Failed to fetch appointments"}), 500
    finally:
        session.close()


@appointments_bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id: str):
    """Cancel an appointment."""
    session = get_db_session()

    try:
        appointment = (
            session.query(Appointment).filter(Appointment.id == appointment_id).first()
        )

        if not appointment:
            return jsonify({"error": "Appointment not found"}), 404

        # Update appointment status
        appointment.status = "cancelled"
        appointment.last_modified = int(datetime.now().timestamp())

        # Update client response if this was the active booking
        client_response = (
            session.query(ClientResponse)
            .filter(ClientResponse.id == appointment.client_response_id)
            .first()
        )

        if client_response and client_response.match_status == "booked":
            # Revert to matched status
            client_response.match_status = "matched"
            client_response.matched_slot_start = None
            client_response.matched_slot_end = None
            client_response.updated_at = datetime.now(dt_timezone.utc)

        session.commit()

        # IMPORTANT: Clear Google Calendar cache to ensure immediate availability updates
        try:
            from src.utils.google.google_calendar import clear_cache_for_calendar

            # Get therapist email from appointment to clear specific cache
            therapist = (
                session.query(Therapist)
                .filter(Therapist.id == appointment.therapist_id)
                .first()
                if appointment.therapist_id
                else None
            )
            if therapist and therapist.email:
                cleared_count = clear_cache_for_calendar(therapist.email)
                logger.info(
                    f"🔄 Cleared {cleared_count} cache entries for {therapist.email} after cancellation"
                )
            else:
                # Fallback to clearing all cache if no therapist found
                from src.utils.google.google_calendar import clear_cache

                clear_cache()
                logger.info(
                    "🔄 Cleared all calendar cache after cancellation (no therapist found)"
                )
        except Exception as cache_e:
            logger.warning(f"⚠️ Failed to clear calendar cache: {cache_e}")

        logger.info("=" * 50)
        logger.info("❌ [APPOINTMENT CANCELLED]")
        logger.info(f"  Appointment ID: {appointment_id}")
        logger.info(
            f"  Client Response Status: {client_response.match_status if client_response else 'N/A'}"
        )
        logger.info("=" * 50)

        return jsonify(
            {
                "success": True,
                "message": "Appointment cancelled successfully",
                "appointment_id": appointment_id,
            }
        )

    except Exception as e:
        session.rollback()
        logger.error(f"❌ [APPOINTMENT CANCELLATION ERROR] {str(e)}")
        return jsonify({"error": "Failed to cancel appointment"}), 500
    finally:
        session.close()
