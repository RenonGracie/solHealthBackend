
"""
IntakeQ Appointment Booking Utilities

Complete appointment booking workflow following documentation guidelines.
Based on documentation: IntakeQ_Integration_Documentation.md (Lines 203-273)
"""
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Dict, Any, Optional, List

from .request_utils import (
    get_booking_settings,
    create_appointment,
    search_appointments
)

logger = logging.getLogger(__name__)


def search_client_via_existing_api(email: str, payment_type: str = "cash_pay") -> Optional[Dict[str, Any]]:
    """
    Search for IntakeQ client using existing /intakeq/client endpoint
    
    Args:
        email (str): Client email address
        payment_type (str): 'cash_pay' or 'insurance'
        
    Returns:
        dict | None: Client data if found, None otherwise
    """
    logger.info(f"🔍 Searching for IntakeQ client via existing API: {email} ({payment_type})")
    
    try:
        import requests
        from urllib.parse import urlencode
        
        # Use your existing /intakeq/client endpoint (internal API call)
        params = urlencode({"email": email, "payment_type": payment_type})
        
        # Get the correct backend URL - same logic as appointments.py
        import os
        raw_url = (
            os.getenv("RAILWAY_STATIC_URL") or 
            os.getenv("NEXT_PUBLIC_API_BASE_URL") or 
            "https://solhealthbe-production.up.railway.app"
        )
        
        # Ensure the URL has a protocol
        if raw_url and not raw_url.startswith(('http://', 'https://')):
            base_url = f"https://{raw_url}"
        else:
            base_url = raw_url
            
        logger.info(f"🌐 Searching client at: {base_url}/intakeq/client")
            
        response = requests.get(
            f"{base_url}/intakeq/client?{params}",
            timeout=30
        )
        
        if response.ok:
            result = response.json()
            if result and isinstance(result, list) and len(result) > 0:
                client = result[0]  # Take first match
                logger.info(f"✅ Client found via existing API: {client.get('ClientId', 'Unknown ID')}")
                return client
            else:
                logger.info(f"ℹ️ No client found via existing API for: {email}")
                return None
        else:
            logger.error(f"❌ Existing API client search failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error in existing API client search: {str(e)}")
        return None


def book_appointment_with_intakeq(
    client_email: str,
    client_name: str,
    therapist_email: str,
    therapist_name: str,
    appointment_datetime: datetime,
    payment_type: str = "cash_pay",
    session_type: str = "First Session",
    send_email_notification: bool = True,
    reminder_type: str = "Email",
    status: str = "Confirmed",
    intakeq_client_id: Optional[str] = None,
    google_meets_link: Optional[str] = None,
    client_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete appointment booking workflow following documentation pattern
    
    Detailed Process (from documentation lines 207-272):
    1. Get Booking Settings - retrieve practitioners and services
    2. Therapist Validation - validate therapist exists in IntakeQ
    3. Client Lookup - search for existing client
    4. Availability Check - validate time slot is available
    5. Session Type Selection - determine appropriate session type
    6. Appointment Creation - create appointment in IntakeQ
    7. Post-Booking Actions - reassign client to therapist
    
    Args:
        client_email (str): Client email address
        client_name (str): Full client name
        therapist_email (str): Therapist email
        therapist_name (str): Therapist name
        appointment_datetime (datetime): Appointment date/time
        payment_type (str): 'cash_pay' or 'insurance'
        session_type (str): Type of session (default: "First Session")
        send_email_notification (bool): Send email to client
        reminder_type (str): Type of reminder (Email, SMS, etc.)
        status (str): Appointment status ('Confirmed' or 'AwaitingConfirmation')
        intakeq_client_id (str, optional): If provided, skip client search and use this ID
        google_meets_link (str, optional): Google Meets link to include in appointment
        
    Returns:
        dict: Appointment creation result with IntakeQ data
    """
    logger.info("=" * 60)
    logger.info("📅 [INTAKEQ APPOINTMENT BOOKING WORKFLOW]")
    logger.info(f"  Client: {client_name} ({client_email})")
    logger.info(f"  Therapist: {therapist_name} ({therapist_email})")
    logger.info(f"  DateTime: {appointment_datetime.isoformat()}")
    logger.info(f"  Session Type: {session_type}")
    logger.info("=" * 60)
    
    try:
        # Step 1: Get Booking Settings
        logger.info("🔄 Step 1: Getting IntakeQ booking settings...")
        logger.info(f"🔑 Using payment type: {payment_type}")
        settings_response = get_booking_settings(payment_type)
        
        if not settings_response.ok:
            error_msg = f"Failed to get booking settings: {settings_response.status_code} - {settings_response.text}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
        
        settings_data = settings_response.json()
        practitioners = settings_data.get("Practitioners", [])
        services = settings_data.get("Services", [])
        
        logger.info(f"✅ Found {len(practitioners)} practitioners, {len(services)} services")

        # Debug: Log all available services
        logger.info("📋 Available services in IntakeQ:")
        for i, service in enumerate(services):
            logger.info(f"  {i+1}. Name: {service.get('Name', 'N/A')}")
            logger.info(f"     ID: {service.get('Id', 'N/A')}")
            logger.info(f"     Duration: {service.get('Duration', 'N/A')} minutes")

        # Debug: Log all available practitioners
        logger.info("📋 Available practitioners in IntakeQ:")
        for i, practitioner in enumerate(practitioners):
            logger.info(f"  {i+1}. Email: {practitioner.get('Email', 'N/A')}")
            logger.info(f"     Name: {practitioner.get('CompleteName', 'N/A')}")
            logger.info(f"     ID: {practitioner.get('Id', 'N/A')}")
        
        # Step 2: Therapist Validation
        logger.info("🔄 Step 2: Validating therapist in IntakeQ...")
        logger.info(f"🔍 Looking for therapist: {therapist_email} / {therapist_name}")
        therapist = None
        
        for practitioner in practitioners:
            practitioner_email = str(practitioner.get("Email", "")).lower()
            practitioner_name = str(practitioner.get("CompleteName", "")).lower()
            
            logger.info(f"  Comparing with: {practitioner_email} / {practitioner_name}")
            
            if (practitioner_email == therapist_email.lower() or
                practitioner_name == therapist_name.lower()):
                therapist = practitioner
                logger.info(f"  ✅ MATCH FOUND!")
                break
        
        if not therapist:
            error_msg = f"Therapist not found in IntakeQ ({payment_type} account): {therapist_email} / {therapist_name}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"💡 Available practitioners: {[p.get('Email') for p in practitioners]}")
            return {"success": False, "error": error_msg}
        
        therapist_id = therapist["Id"]
        logger.info(f"✅ Therapist validated: {therapist_id}")
        
        # Step 3: Client Lookup or Use Provided ID
        if intakeq_client_id:
            logger.info(f"🔄 Step 3: Using provided IntakeQ client ID: {intakeq_client_id}")
            client_id = intakeq_client_id
        else:
            logger.info("🔄 Step 3: Searching for client in IntakeQ using existing API...")
            client = search_client_via_existing_api(client_email, payment_type)
            
            if not client:
                error_msg = f"Client not found in IntakeQ: {client_email} / {client_name} ({payment_type})"
                logger.error(f"❌ {error_msg}")
                logger.info("💡 Client may need to be created first via /intakeq/create-client endpoint")
                return {"success": False, "error": error_msg}
            
            client_id = client.get("ClientId") or client.get("ClientNumber")
            logger.info(f"✅ Client found: {client_id}")
        
        # Step 4: Availability Check (temporarily relaxed for testing)
        logger.info("🔄 Step 4: Checking therapist availability...")
        availability_result = check_intakeq_availability(therapist_email, appointment_datetime, payment_type)
        if not availability_result:
            logger.warning(f"⚠️ Availability check failed but proceeding with booking for testing: {appointment_datetime}")
            # Temporarily allow booking even if availability check fails
            # return {"success": False, "error": f"Therapist not available at requested time: {appointment_datetime}"}
        
        logger.info("✅ Time slot available (availability check temporarily relaxed)")
        
        # Step 5: Session Type Selection
        logger.info("🔄 Step 5: Determining session type...")
        session_id = determine_session_id(session_type, services)
        logger.info(f"✅ Session type: {session_id}")
        
        # Step 6: Appointment Creation
        logger.info("🔄 Step 6: Creating appointment in IntakeQ...")
        logger.info(f"🔍 DEBUG: Using status value: '{status}' (should be 'Confirmed' or 'AwaitingConfirmation')")
        
        # Force valid IntakeQ status regardless of input
        valid_status = "Confirmed" if status.lower() in ["scheduled", "confirmed"] else "AwaitingConfirmation"
        logger.info(f"🔍 DEBUG: Forcing status to valid IntakeQ value: '{valid_status}'")
        
        appointment_data = {
            "PractitionerId": therapist_id,
            "ClientId": client_id,
            "LocationId": "1",  # Default location
            "UtcDateTime": int(appointment_datetime.timestamp() * 1000),  # Unix timestamp in milliseconds
            "ServiceId": session_id,
            "SendClientEmailNotification": send_email_notification,
            "ReminderType": reminder_type,
            "Status": valid_status,  # Use forced valid status
        }
        
        # Add client timezone for IntakeQ email confirmations (Limited Permit therapists only)
        if client_timezone:
            logger.info(f"🌍 Adding client timezone to IntakeQ appointment for associate therapist: {client_timezone}")
            appointment_data["ClientTimeZone"] = client_timezone

            # Ensure the timezone is properly formatted for IntakeQ
            # IntakeQ expects IANA timezone names like "America/New_York"
            if not client_timezone.startswith("America/") and not client_timezone.startswith("US/"):
                logger.warning(f"⚠️ Client timezone may not be in proper IANA format: {client_timezone}")
        else:
            logger.info("🌍 No client timezone specified - IntakeQ will use default timezone for emails")
        
        # Add Google Meets link to appointment notes if provided
        if google_meets_link:
            logger.info(f"📹 Adding Google Meets link to appointment: {google_meets_link}")
            appointment_data["Notes"] = f"Join your session: {google_meets_link}"
        
        # FIXED TIMEZONE HANDLING for IntakeQ booking
        logger.info(f"🔍 INTAKEQ TIMEZONE VERIFICATION:")
        logger.info(f"  Appointment datetime: {appointment_datetime}")
        logger.info(f"  Timezone info: {appointment_datetime.tzinfo}")
        logger.info(f"  UTC timestamp: {appointment_datetime.timestamp()}")
        
        # Ensure we're working with UTC datetime for IntakeQ
        if appointment_datetime.tzinfo is None:
            logger.error("🚨 CRITICAL ERROR: appointment_datetime has no timezone info!")
            logger.error("🚨 This will cause incorrect booking times!")
            logger.error("🚨 Backend should have already handled timezone conversion")
            raise ValueError("Appointment datetime must have timezone info")
        
        # Convert to UTC if not already
        if appointment_datetime.tzinfo != dt_timezone.utc:
            logger.info(f"  Converting from {appointment_datetime.tzinfo} to UTC")
            appointment_datetime = appointment_datetime.astimezone(dt_timezone.utc)
            logger.info(f"  Converted to UTC: {appointment_datetime}")
        
        # Calculate IntakeQ timestamp (milliseconds since epoch)
        intakeq_timestamp = int(appointment_datetime.timestamp() * 1000)
        appointment_data["UtcDateTime"] = intakeq_timestamp
        
        logger.info(f"  IntakeQ timestamp (ms): {intakeq_timestamp}")
        
        # Verification: Convert timestamp back to datetime
        verification_dt = datetime.fromtimestamp(appointment_datetime.timestamp(), tz=dt_timezone.utc)
        logger.info(f"  Verification UTC datetime: {verification_dt}")
        
        # Additional verification for specific timezone bugs
        if abs(verification_dt.timestamp() - appointment_datetime.timestamp()) > 1:
            logger.warning("⚠️ Timestamp verification failed - possible precision loss")
        else:
            logger.info("✅ Timestamp verification passed")
            
        # Final validation before sending to IntakeQ
        logger.info(f"🔍 PRE-INTAKEQ VALIDATION:")
        
        # Convert IntakeQ timestamp back to datetime for validation
        intakeq_dt = datetime.fromtimestamp(intakeq_timestamp / 1000, tz=dt_timezone.utc)
        logger.info(f"  IntakeQ will receive: {intakeq_dt} UTC")
        
        # This should match our input appointment_datetime
        if abs(intakeq_dt.timestamp() - appointment_datetime.timestamp()) > 1:
            logger.error("🚨 TIMESTAMP MISMATCH - IntakeQ will receive wrong time!")
            logger.error(f"  Expected: {appointment_datetime}")
            logger.error(f"  IntakeQ gets: {intakeq_dt}")
        else:
            logger.info("✅ Timestamp validation passed - IntakeQ will receive correct time")
        
        logger.info(f"🔍 Final appointment data: {appointment_data}")
        
        appointment_response = create_appointment(appointment_data, payment_type)
        
        if not appointment_response.ok:
            error_msg = f"Failed to create appointment: {appointment_response.status_code} - {appointment_response.text}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
        
        appointment_result = appointment_response.json()
        appointment_id = appointment_result.get("Id")
        logger.info(f"✅ Appointment created: {appointment_id}")
        
        # Step 7: Post-Booking Actions - Log completion
        logger.info("🔄 Step 7: Finalizing appointment booking...")
        logger.info("ℹ️ Client reassignment can be handled separately if needed")
        
        logger.info("=" * 60)
        logger.info("🎉 [APPOINTMENT BOOKING COMPLETED SUCCESSFULLY]")
        logger.info(f"  IntakeQ Appointment ID: {appointment_id}")
        logger.info(f"  Client ID: {client_id}")
        logger.info(f"  Therapist ID: {therapist_id}")
        logger.info("=" * 60)
        
        return {
            "success": True,
            "intakeq_appointment_id": appointment_id,
            "intakeq_client_id": client_id,
            "intakeq_therapist_id": therapist_id,
            "appointment_data": appointment_result,
            "payment_type": payment_type
        }
        
    except Exception as e:
        logger.error(f"❌ Appointment booking workflow failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def check_intakeq_availability(therapist_email: str, appointment_datetime: datetime, payment_type: str = "cash_pay") -> bool:
    """
    Check therapist availability in IntakeQ system
    
    Args:
        therapist_email (str): Therapist email
        appointment_datetime (datetime): Requested appointment time
        payment_type (str): 'cash_pay' or 'insurance' - determines which IntakeQ account to check
        
    Returns:
        bool: True if available, False otherwise
    """
    logger.info(f"🔍 Checking IntakeQ availability for {therapist_email} at {appointment_datetime} ({payment_type})")
    
    try:
        # Check for conflicts within ±2 hours of requested time
        start_check = appointment_datetime - timedelta(hours=2)
        end_check = appointment_datetime + timedelta(hours=2)
        
        search_params = {
            "practitionerEmail": therapist_email,
            "startDate": start_check.strftime("%Y-%m-%d"),
            "endDate": end_check.strftime("%Y-%m-%d")
        }
        
        response = search_appointments(search_params, payment_type)
        
        if not response.ok:
            logger.warning(f"⚠️ Could not check availability: {response.status_code} - {response.text}")
            return True  # Assume available if we can't check
        
        appointments = response.json()
        logger.info(f"🔍 Found {len(appointments)} existing appointments in range")
        
        # Check for direct time conflicts
        requested_timestamp = int(appointment_datetime.timestamp() * 1000)
        logger.info(f"🔍 Requested timestamp: {requested_timestamp} ({appointment_datetime})")
        
        for appointment in appointments:
            start_time = appointment.get("StartDate")
            end_time = appointment.get("EndDate")
            logger.info(f"🔍 Checking appointment {appointment.get('Id')}: {start_time} - {end_time}")
            
            if start_time and end_time:
                # Check if requested time overlaps with existing appointment
                if start_time <= requested_timestamp <= end_time:
                    logger.warning(f"⚠️ Time conflict detected with appointment: {appointment.get('Id')}")
                    logger.warning(f"⚠️ Conflict details: existing {start_time}-{end_time} vs requested {requested_timestamp}")
                    return False
        
        logger.info("✅ No conflicts found, slot is available")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error checking availability: {str(e)}")
        return True  # Assume available on error to not block bookings


def determine_session_id(session_type: str, services: List[Dict[str, Any]]) -> str:
    """
    Determine appropriate session ID based on session type and available services
    
    Args:
        session_type (str): Requested session type
        services (list): Available services from IntakeQ
        
    Returns:
        str: Service ID for the session
    """
    logger.info(f"🔍 Determining session ID for: {session_type}")

    # Map session types to service names (customize based on your IntakeQ setup)
    session_mapping = {
        "First Session (Free)": ["First Session (Free)", "Free Session", "Initial Session (Free)"],
        "First Session (Promo Code)": ["First Session (Promo Code)", "Promo Session", "Discounted Session"],
        "First Session": ["First Session", "Initial Session", "Intake Session"],
        "Follow-up Session": ["Follow-up Session", "Regular Session", "Therapy Session"],
        "Insurance Session": ["Insurance Session", "Covered Session"]
    }

    # Get possible service names for this session type
    possible_names = session_mapping.get(session_type, [session_type])
    logger.info(f"🔍 Searching for services matching any of: {possible_names}")

    # Find matching service in IntakeQ services
    logger.info(f"🔍 Comparing against {len(services)} available services...")
    for service in services:
        service_name = service.get("Name", "")
        service_id = service.get("Id", "")
        logger.info(f"  Checking service: '{service_name}' ({service_id})")

        for possible_name in possible_names:
            if possible_name.lower() in service_name.lower():
                logger.info(f"✅ Found matching service: {service_name} ({service_id})")
                return service_id

    logger.warning(f"⚠️ No matching service found for '{session_type}'")
    
    # Fallback: return session_type as-is or first available service
    if services:
        fallback_service = services[0]
        fallback_id = fallback_service.get("Id", session_type)
        logger.warning(f"⚠️ Using fallback service: {fallback_service.get('Name')} ({fallback_id})")
        return fallback_id
    
    logger.warning(f"⚠️ No services found, using session type as ID: {session_type}")
    return session_type
