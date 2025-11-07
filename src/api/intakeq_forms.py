"""
IntakeQ Integration API

This module provides endpoints for managing IntakeQ client integration:

Endpoints:
- POST /intakeq/create-client: Create a new client in IntakeQ system
- GET /intakeq/client: Retrieve client information by email
- POST /intakeq_forms/mandatory_form: Send mandatory forms (legacy)

The IntakeQ integration supports both cash pay and insurance clients with
separate API keys configured via environment variables:
- CASH_PAY_INTAKEQ_API_KEY: For cash paying clients
- INSURANCE_INTAKEQ_API_KEY: For insurance clients

Client data includes:
- Basic information (name, email, phone, DOB)
- Payment type and insurance details
- Mental health screening scores (PHQ-9, GAD-7)
- Substance use screening (alcohol, drugs)
- Therapy preferences and specialization requests
- Demographics and background information
- Custom fields for tracking response IDs and preferences
"""
import json
import logging
import os
import time
from datetime import datetime
from urllib.parse import urlencode

import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def safe_extract_string(value):
    """
    Safely extract a string value from either a string or a dictionary.
    If value is a dict, tries to extract street_line_1, otherwise returns empty string.
    If value is a string, returns it as-is.
    """
    if isinstance(value, dict):
        # Extract the actual street line from Nirvana address dict
        return value.get('street_line_1', '')
    elif isinstance(value, str):
        return value
    else:
        return ""


def normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number by removing +1 country code prefix.

    IntakeQ expects US phone numbers without the +1 prefix.
    Input: "+13102391030" or "13102391030" or "+1310239103" or "1310239103"
    Output: "3102391030" (10 digits, no leading 1)

    Args:
        phone: Phone number string (may include +1, spaces, parentheses, dashes)

    Returns:
        Normalized 10-digit phone number without +1 prefix
    """
    if not phone:
        return ""

    # Convert to string and strip whitespace
    phone = str(phone).strip()

    # Extract only digits
    phone_digits = "".join(c for c in phone if c.isdigit())

    # Log original format for debugging
    if phone != phone_digits:
        logger.info(f"📞 Phone normalized: '{phone}' → '{phone_digits}' ({len(phone_digits)} digits)")

    # Remove leading "1" if present (US country code)
    # Case 1: 11 digits starting with 1 (e.g., "13102391030" → "3102391030")
    if len(phone_digits) == 11 and phone_digits.startswith("1"):
        original = phone_digits
        phone_digits = phone_digits[1:]
        logger.info(f"✂️ Stripped country code: {original} → {phone_digits}")

    # Case 2: 10 digits starting with 1 (e.g., "1310239103" → "310239103")
    # US area codes never start with 1, so this is definitely a country code prefix
    elif len(phone_digits) == 10 and phone_digits.startswith("1"):
        original = phone_digits
        phone_digits = phone_digits[1:]
        logger.warning(f"⚠️ Invalid 10-digit number with leading 1: {original} → {phone_digits} (now 9 digits - CHECK SOURCE DATA!)")

    # Final validation
    if len(phone_digits) != 10:
        logger.error(f"❌ Phone number is not 10 digits: '{phone}' → '{phone_digits}' ({len(phone_digits)} digits)")

    return phone_digits


# Import Google Sheets logging service
try:
    from ..services.google_sheets import sheets_logger
except ImportError as e:
    logger.warning(f"Google Sheets service not available: {e}")
    sheets_logger = None

# Import insurance mapping utility
try:
    from ..utils.insurance_mapping import get_payer_id
except ImportError as e:
    logger.warning(f"Insurance mapping utility not available: {e}")
    get_payer_id = None

# Import progressive data capture utility
try:
    from ..utils.progressive_data_capture import validate_intakeq_data_completeness
    from ..utils.comprehensive_data_logger import ensure_comprehensive_logging
except ImportError as e:
    logger.warning(f"Data capture utilities not available: {e}")
    validate_intakeq_data_completeness = None
    ensure_comprehensive_logging = None

# Note: Journey tracking now handled by progressive logger in 3 stages
intakeq_forms_bp = Blueprint("intakeq_forms", __name__)


def calculate_phq9_score(phq9_scores: dict) -> int:
    """Calculate PHQ-9 total score from individual responses"""
    if not phq9_scores or not isinstance(phq9_scores, dict):
        return 0

    score_map = {
        "Not at all": 0,
        "Several days": 1,
        "More than half the days": 2,
        "Nearly every day": 3,
    }

    total = 0
    for response in phq9_scores.values():
        if response in score_map:
            total += score_map[response]

    return total


def extract_financial_data_from_nirvana(client_data: dict) -> dict:
    """
    Extract financial fields from Nirvana data and convert to Google Sheets format.
    
    Maps Nirvana field names to the standardized names expected by Google Sheets.
    Converts cents to dollars where needed.
    """
    financial_data = {}
    
    # Try to extract from various Nirvana data sources
    for nirvana_field in [
        "nirvana_raw_response",
        "insurance_verification_data", 
        "nirvana_response",
        "rawNirvanaResponse"
    ]:
        nirvana_data = client_data.get(nirvana_field)
        if not nirvana_data:
            continue
            
        try:
            if isinstance(nirvana_data, str):
                nirvana_parsed = json.loads(nirvana_data)
            else:
                nirvana_parsed = nirvana_data
            
            # Convert cents to dollars helper
            def cents_to_dollars(cents_value):
                if cents_value is None or cents_value == "":
                    return None
                try:
                    return round(int(cents_value) / 100, 2) if int(cents_value) != 0 else 0.00
                except (ValueError, TypeError):
                    return None
            
            # Map Nirvana fields to Google Sheets fields
            field_mappings = {
                "copay": cents_to_dollars(nirvana_parsed.get("copayment")),
                "deductible": cents_to_dollars(nirvana_parsed.get("deductible")),  
                "coinsurance": nirvana_parsed.get("coinsurance"),
                "out_of_pocket_max": cents_to_dollars(nirvana_parsed.get("oop_max")),
                "remaining_deductible": cents_to_dollars(nirvana_parsed.get("remaining_deductible")),
                "remaining_oop_max": cents_to_dollars(nirvana_parsed.get("remaining_oop_max")),
                "member_obligation": cents_to_dollars(nirvana_parsed.get("member_obligation")),
                "benefit_structure": nirvana_parsed.get("benefit_structure"),
                "session_cost_dollars": cents_to_dollars(nirvana_parsed.get("member_obligation"))  # Use member obligation as session cost
            }
            
            # Only include fields that have values
            for field, value in field_mappings.items():
                if value is not None:
                    financial_data[field] = value
                    
            if financial_data:
                logger.info(f"📊 Extracted financial data from {nirvana_field}")
                break
                
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse {nirvana_field}: {e}")
            continue
    
    return financial_data


def calculate_gad7_score(gad7_scores: dict) -> int:
    """Calculate GAD-7 total score from individual responses"""
    if not gad7_scores or not isinstance(gad7_scores, dict):
        return 0

    score_map = {
        "Not at all": 0,
        "Several days": 1,
        "More than half the days": 2,
        "Nearly every day": 3,
    }

    total = 0
    for response in gad7_scores.values():
        if response in score_map:
            total += score_map[response]

    return total


# Custom field mappings for IntakeQ (based on your example)
INTAKEQ_CUSTOM_FIELDS = {
    "copay": "791z",
    "deductible": "v5wl",
    "coinsurance": "1rd4",
    "out_of_pocket_max": "ii1b",
    "remaining_deductible": "2iwu",
    "remaining_oop_max": "vpum",
    "member_obligation": "uk2k",
    "payer_obligation": "pkiu",
    "insurance_type": "brop",
    "benefit_structure": "801h",
    "plan_status": "kj4y",
    "coverage_status": "ch4e",
    "mental_health_coverage": "q3lb",
    "sessions_before_deductible": "wzm0",
    "sessions_before_oop_max": "ozuf",
    "telehealth_coinsurance": "mtyd",
    "telehealth_benefit_structure": "571k",
}


@intakeq_forms_bp.route("/intakeq/create-client", methods=["POST"])
def create_intakeq_client():
    """Create a new client in IntakeQ system with comprehensive field mapping."""
    try:
        client_data = request.get_json() or {}
        
        # Initialize variables that might be referenced later
        insurance_validation_result = None

        # Use comprehensive logging to ensure ALL data is captured
        # TEMPORARILY DISABLED: comprehensive logging causing timeout issues
        # if ensure_comprehensive_logging:
        #     logger.info("🔍 [COMPREHENSIVE DATA EXTRACTION] Ensuring ALL data is captured for IntakeQ")
        #     client_data = ensure_comprehensive_logging(client_data)

            # Log comprehensive data audit results
            # if "_comprehensive_logging_report" in client_data:
            #     report = client_data["_comprehensive_logging_report"]
            #     logger.info("📊 [COMPREHENSIVE AUDIT RESULTS]")
            #     logger.info(f"  • Total fields extracted: {report['total_fields_extracted']}")
            #     logger.info(f"  • Google Sheets completeness: {report['overall_completeness']['sheets_completeness_pct']}%")
            #     logger.info(f"  • IntakeQ mapping completeness: {report['overall_completeness']['intakeq_completeness_pct']}%")
            #
            #     if report.get("recommendations"):
            #         logger.info("  • Recommendations:")
            #         for rec in report["recommendations"][:3]:
            #             logger.info(f"    - {rec}")

        # Enhanced logging for comprehensive data
        logger.info("=" * 60)
        logger.info("📋 [COMPREHENSIVE INTAKEQ CLIENT CREATION]")
        logger.info(
            f"  Client: {client_data.get('first_name')} {client_data.get('last_name')}"
        )
        logger.info(f"  Preferred Name: {client_data.get('preferred_name')}")
        logger.info(f"  Email: {client_data.get('email')}")
        logger.info(f"  Payment Type: {client_data.get('payment_type')}")
        logger.info(f"  Response ID: {client_data.get('response_id')}")
        logger.info(f"  Total Fields Received: {len(client_data)}")

        # Log data completeness
        has_phq9 = bool(
            client_data.get("phq9_scores")
            and any(
                client_data["phq9_scores"].values()
                if isinstance(client_data["phq9_scores"], dict)
                else []
            )
        )
        has_gad7 = bool(
            client_data.get("gad7_scores")
            and any(
                client_data["gad7_scores"].values()
                if isinstance(client_data["gad7_scores"], dict)
                else []
            )
        )
        has_insurance = bool(client_data.get("insurance_provider"))
        has_preferences = bool(
            client_data.get("therapist_gender_preference")
            or client_data.get("therapist_specialization")
        )
        has_substance_data = bool(
            client_data.get("alcohol_frequency")
            or client_data.get("recreational_drugs_frequency")
        )

        # Check address data completeness (to debug missing address issue)
        has_address = bool(
            client_data.get("street_address")
            or client_data.get("address")
            or client_data.get("client_address")
        )
        has_city = bool(client_data.get("city") or client_data.get("client_city"))
        has_state = bool(client_data.get("state"))
        has_zip = bool(
            client_data.get("postal_code")
            or client_data.get("zip_code")
            or client_data.get("zip")
        )

        logger.info("  Data Completeness:")
        logger.info(f"    PHQ-9 Scores: {'✓' if has_phq9 else '✗'}")
        logger.info(f"    GAD-7 Scores: {'✓' if has_gad7 else '✗'}")
        logger.info(f"    Insurance Data: {'✓' if has_insurance else '✗'}")
        logger.info(f"    Therapist Preferences: {'✓' if has_preferences else '✗'}")
        logger.info(f"    Substance Use Data: {'✓' if has_substance_data else '✗'}")
        logger.info(f"    Address Information: {'✓' if has_address else '✗'}")
        logger.info(f"      Street Address: {'✓' if has_address else '✗'}")
        logger.info(f"      City: {'✓' if has_city else '✗'}")
        logger.info(f"      State: {'✓' if has_state else '✗'}")
        logger.info(f"      Zip/Postal: {'✓' if has_zip else '✗'}")

        # Log specific address values for debugging
        if not has_address:
            logger.warning("⚠️ Missing street address - checking available fields:")
            addr_fields = ["street_address", "address", "client_address"]
            for field in addr_fields:
                value = client_data.get(field, "")
                logger.info(f"      {field}: '{value}'")

        if not has_city:
            logger.warning("⚠️ Missing city - checking available fields:")
            city_fields = ["city", "client_city"]
            for field in city_fields:
                value = client_data.get(field, "")
                logger.info(f"      {field}: '{value}'")

        # Determine which IntakeQ API key to use based on payment type and state
        payment_type = client_data.get("payment_type", "cash_pay")
        cash_pay_key = os.getenv("CASH_PAY_INTAKEQ_API_KEY")

        if payment_type == "cash_pay":
            intakeq_api_key = cash_pay_key
        else:  # insurance
            client_state = client_data.get("state", "")
            from src.utils.intakeq.state_config import get_insurance_intakeq_config
            intakeq_api_key = get_insurance_intakeq_config(client_state, 'api_key')
            if not intakeq_api_key:
                # Fallback to generic insurance key
                intakeq_api_key = os.getenv("INSURANCE_INTAKEQ_API_KEY")

        if not intakeq_api_key:
            error_msg = f"Missing IntakeQ API key for payment type: {payment_type}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        logger.info(
            f"  🔑 Using API key for: {payment_type} (length: {len(intakeq_api_key)})"
        )

        # Enhanced: Extract financial data from Nirvana response for Google Sheets  
        if payment_type == "insurance":
            if not client_data.get("insurance_provider"):
                logger.warning(f"  ⚠️ Insurance client missing insurance_provider field")
            else:
                logger.info(f"  🏥 Using insurance provider: {client_data['insurance_provider']}")
                
                # Extract financial data from Nirvana response if available
                financial_data = extract_financial_data_from_nirvana(client_data)
                if financial_data:
                    logger.info(f"  💰 Extracted financial data: {list(financial_data.keys())}")
                    client_data.update(financial_data)

        # Validate data completeness before building payload
        if validate_intakeq_data_completeness:
            validation_report = validate_intakeq_data_completeness(client_data)
            
            if not validation_report["is_complete"]:
                logger.warning(f"⚠️ Data completeness issues detected:")
                for issue in validation_report["missing_critical"]:
                    logger.warning(f"  - Missing critical: {issue}")
                for recommendation in validation_report["recommendations"]:
                    logger.info(f"  💡 Recommendation: {recommendation}")
            else:
                logger.info("✅ Data completeness validation passed")
        
        # Build comprehensive IntakeQ payload
        intakeq_payload = build_comprehensive_intakeq_payload(client_data, payment_type)

        # Validate required fields
        required_fields = ["Email", "LastName"]
        missing_fields = [
            field for field in required_fields if not intakeq_payload.get(field)
        ]

        if not intakeq_payload.get("FirstName"):
            missing_fields.append("FirstName")

        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        logger.info("  📤 Sending comprehensive payload to IntakeQ API...")
        logger.info(f"    Payload keys: {list(intakeq_payload.keys())}")
        logger.info(
            f"    Custom fields count: {len(intakeq_payload.get('CustomFields', []))}"
        )
        logger.info(
            f"    Additional info length: {len(intakeq_payload.get('AdditionalInformation', ''))}"
        )

        # Debug: Comprehensive address tracking from source to IntakeQ
        logger.info("🔍 [COMPLETE ADDRESS AUDIT] Tracking address data flow:")

        # 1. Show source client data address fields
        source_address = {
            "street_address": client_data.get("street_address"),
            "city": client_data.get("city"),
            "state": client_data.get("state"),
            "postal_code": client_data.get("postal_code"),
        }
        source_populated = sum(1 for v in source_address.values() if v)
        logger.info(f"  1. Source client_data address: {source_populated}/4 populated")
        for field, value in source_address.items():
            logger.info(f"     {field}: '{value}' {'✓' if value else '✗'}")

        # 2. Show IntakeQ payload address fields
        intakeq_address_fields = {
            "StreetAddress": intakeq_payload.get("StreetAddress"),
            "Address1": intakeq_payload.get("Address1"),
            "Address2": intakeq_payload.get("Address2"),
            "UnitNumber": intakeq_payload.get("UnitNumber"),
            "City": intakeq_payload.get("City"),
            "StateShort": intakeq_payload.get("StateShort"),
            "PostalCode": intakeq_payload.get("PostalCode"),
            "Country": intakeq_payload.get("Country"),
        }

        intakeq_populated = sum(1 for v in intakeq_address_fields.values() if v)
        logger.info(f"  2. IntakeQ payload address: {intakeq_populated}/8 populated")
        for field, value in intakeq_address_fields.items():
            logger.info(f"     {field}: '{value}' {'✓' if value else '✗'}")

        # 3. Flag any data loss
        if source_populated > 0 and intakeq_populated == 0:
            logger.error(
                "🚨 ADDRESS DATA LOSS: Source has address data but IntakeQ payload is empty!"
            )
        elif source_populated > intakeq_populated:
            logger.warning(
                f"⚠️ Possible address data loss: Source {source_populated}/4 vs IntakeQ {intakeq_populated}/8"
            )
        else:
            logger.info(
                f"✅ Address data flow: {source_populated} source fields → {intakeq_populated} IntakeQ fields"
            )

        # DEBUG: Log final demographic fields before sending to IntakeQ
        logger.info("🔍 [FINAL INTAKEQ PAYLOAD DEBUG] Demographic fields being sent to IntakeQ:")
        demographic_fields_to_check = ['FirstName', 'LastName', 'Email', 'StreetAddress', 'City', 'State', 'PostalCode', 
                                      'PrimaryInsuredGender', 'PrimaryInsuredCity', 'PrimaryInsuredState', 
                                      'PrimaryInsuredStreetAddress', 'PrimaryInsuredZipCode', 
                                      'PrimaryInsuranceHolderName', 'PrimaryInsuranceCompany']
        for field in demographic_fields_to_check:
            value = intakeq_payload.get(field, 'NOT SET')
            logger.info(f"  {field}: {value}")
        
        # Log custom fields if they exist
        if 'CustomFields' in intakeq_payload:
            logger.info(f"  CustomFields count: {len(intakeq_payload['CustomFields'])}")
            # Log relevant custom fields (address, demographic)
            for cf in intakeq_payload['CustomFields']:
                field_id = cf.get('FieldId', 'Unknown')
                value = cf.get('Value', 'No value')
                if any(keyword in str(value).lower() for keyword in ['address', 'city', 'state', 'zip', 'gender', 'name']):
                    logger.info(f"    Custom Field {field_id}: {value}")
        else:
            logger.info("  CustomFields: NOT SET")

        # Call IntakeQ API
        headers = {
            "X-Auth-Key": intakeq_api_key,
            "Content-Type": "application/json",
        }

        intakeq_response = requests.post(
            "https://intakeq.com/api/v1/clients",
            headers=headers,
            json=intakeq_payload,
            timeout=60,
        )

        logger.info(f"  📥 IntakeQ Response Status: {intakeq_response.status_code}")
        logger.info(f"  📥 Response Headers: {dict(intakeq_response.headers)}")

        if not intakeq_response.ok:
            error_text = intakeq_response.text
            logger.error("❌ IntakeQ API Error Details:")
            logger.error(f"    Status Code: {intakeq_response.status_code}")
            logger.error(f"    Response Text: {error_text}")

            # Try to parse detailed error response
            try:
                error_json = intakeq_response.json()
                logger.error(f"    Error JSON: {json.dumps(error_json, indent=2)}")
                error_msg = f"IntakeQ API error: {intakeq_response.status_code} - {error_json.get('message', error_text)}"
            except (json.JSONDecodeError, ValueError):
                error_msg = (
                    f"IntakeQ API error: {intakeq_response.status_code} - {error_text}"
                )

            return jsonify({"error": error_msg}), 500

        try:
            result = intakeq_response.json()
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse IntakeQ response as JSON: {e}")
            return jsonify({"error": "Invalid JSON response from IntakeQ"}), 500

        # Extract client ID and intake URL
        client_id = result.get("ClientId") or result.get("Id") or result.get("id")
        intake_url = result.get("intake_url") or result.get("IntakeUrl")

        if not intake_url and client_id:
            intake_url = f"https://intakeq.com/new/{client_id}"

        logger.info("  ✅ Comprehensive client created successfully")
        logger.info(f"  Client ID: {client_id}")
        logger.info(f"  Intake URL: {intake_url or 'N/A'}")
        logger.info(f"  Fields sent: {len(intakeq_payload)}")

        # ENHANCED: Use centralized data management for Google Sheets logging
        try:
            # Import the integration layer (lazy import to avoid startup issues)
            from src.services.data_flow_integration import (
                ensure_user_data_initialized,
                log_to_google_sheets_progressive,
                update_intakeq_creation_result,
            )

            response_id = client_data.get("response_id")
            if response_id:
                logger.info("🔄 [CENTRALIZED DATA] Using centralized data management")

                # Initialize/update user data with IntakeQ creation results
                intakeq_result = {
                    "ClientId": client_id,
                    "intake_url": intake_url,
                    "intakeq_response": result,
                }

                # Ensure data is initialized and add IntakeQ results
                enriched_data = ensure_user_data_initialized(response_id, client_data)
                enriched_data = update_intakeq_creation_result(
                    response_id, intakeq_result
                )

                # Log to Google Sheets using centralized data
                sheets_success = log_to_google_sheets_progressive(response_id, stage=1)

                if sheets_success:
                    logger.info(
                        "  ✅ Successfully logged via centralized data management"
                    )
                else:
                    logger.warning(
                        "  ⚠️ Centralized logging failed, falling back to legacy method"
                    )
                    # Fall back to legacy method if centralized fails
                    raise Exception("Centralized logging failed")
            else:
                logger.warning("  ⚠️ No response_id found, using legacy logging method")
                raise Exception("No response_id for centralized logging")

        except Exception as centralized_error:
            logger.warning(
                f"  ⚠️ Centralized data management failed ({centralized_error}), using legacy method"
            )

            # LEGACY: Fall back to original method if centralized fails
            if sheets_logger and sheets_logger.enabled:
                try:
                    # Start with comprehensive IntakeQ payload data (contains all structured data)
                    logger.info("🐛 ORIGINAL CLIENT_DATA BEFORE SHEETS LOGGING:")
                    logger.info(f"  Keys available: {list(client_data.keys())}")
                    key_client_fields = [
                        "first_name",
                        "last_name",
                        "email",
                        "phone",
                        "nirvana_data",
                    ]
                    for field in key_client_fields:
                        value = client_data.get(field, "NOT_FOUND")
                        if field == "nirvana_data" and value != "NOT_FOUND":
                            logger.info(
                                f"  {field}: [Contains {len(value)} chars] {str(value)[:100]}..."
                            )
                        else:
                            logger.info(f"  {field}: {value}")

                    sheets_data = client_data.copy()

                    # Enhanced: Extract and add Nirvana data to sheets_data if available
                    nirvana_data_for_sheets = None
                    # Use the same priority order as the main processing
                    for key in [
                        "nirvana_raw_response",
                        "insurance_verification_data",
                        "nirvana_response",
                        "rawNirvanaResponse",
                    ]:
                        if client_data.get(key):
                            try:
                                if isinstance(client_data[key], str):
                                    nirvana_data_for_sheets = json.loads(
                                        client_data[key]
                                    )
                                else:
                                    nirvana_data_for_sheets = client_data[key]
                                logger.info(
                                    f"  🔄 Found Nirvana data in '{key}' field for sheets logging"
                                )
                                break
                            except (json.JSONDecodeError, TypeError):
                                continue

                    if nirvana_data_for_sheets and isinstance(
                        nirvana_data_for_sheets, dict
                    ):
                        sheets_data["nirvana_data"] = nirvana_data_for_sheets
                        logger.info(
                            "  🔄 Added Nirvana data to Google Sheets logging payload"
                        )

                        # Extract key subscriber demographics for separate logging
                        subscriber_demo = nirvana_data_for_sheets.get(
                            "subscriber_demographics", {}
                        )
                        if subscriber_demo:
                            sheets_data.update(
                                {
                                    "subscriber_first_name": subscriber_demo.get(
                                        "first_name", ""
                                    ),
                                    "subscriber_last_name": subscriber_demo.get(
                                        "last_name", ""
                                    ),
                                    "subscriber_gender": subscriber_demo.get(
                                        "gender", ""
                                    ),
                                    "subscriber_member_id": subscriber_demo.get(
                                        "member_id", ""
                                    ),
                                    "subscriber_dob": subscriber_demo.get("dob", ""),
                                }
                            )

                            # Add subscriber address
                            sub_address = subscriber_demo.get("address", {})
                            if sub_address:
                                sheets_data.update(
                                    {
                                        "subscriber_street": sub_address.get(
                                            "street_line_1", ""
                                        ),
                                        "subscriber_city": sub_address.get("city", ""),
                                        "subscriber_state": sub_address.get(
                                            "state", ""
                                        ),
                                        "subscriber_zip": sub_address.get("zip", ""),
                                    }
                                )

                        logger.info("  👥 Added subscriber demographics to sheets data")

                        # FIXED: Extract Nirvana address fields for Google Sheets logging
                        # The sheets logger expects these specific field names
                        nirvana_address = None
                        
                        # Try multiple possible address locations in Nirvana data
                        address_paths = [
                            ("subscriber", "address"),           # nirvana_data.subscriber.address
                            ("demographics", "address"),        # nirvana_data.demographics.address  
                            ("address",),                       # nirvana_data.address
                            ("subscriber_demographics", "address"), # nirvana_data.subscriber_demographics.address
                        ]
                        
                        for path in address_paths:
                            try:
                                temp_address = nirvana_data_for_sheets
                                for key in path:
                                    if isinstance(temp_address, dict) and key in temp_address:
                                        temp_address = temp_address[key]
                                    else:
                                        temp_address = None
                                        break
                                
                                if isinstance(temp_address, dict) and any(temp_address.values()):
                                    nirvana_address = temp_address
                                    logger.info(f"  📍 Found Nirvana address at path: {'.'.join(path)}")
                                    break
                            except (KeyError, TypeError):
                                continue
                        
                        # Extract address fields that Google Sheets expects
                        if nirvana_address:
                            # Map Nirvana address fields to Google Sheets fields
                            address_mapping = {
                                "nirvana_street_line_1": ["street_line_1", "street1", "address_line_1", "street"],
                                "nirvana_street_line_2": ["street_line_2", "street2", "address_line_2"], 
                                "nirvana_city": ["city"],
                                "nirvana_state": ["state"],
                                "nirvana_zip": ["zip", "postal_code", "zipcode"],
                            }
                            
                            for sheets_field, possible_keys in address_mapping.items():
                                for key in possible_keys:
                                    if key in nirvana_address and nirvana_address[key]:
                                        sheets_data[sheets_field] = nirvana_address[key]
                                        logger.info(f"  📍 Mapped {key} -> {sheets_field}: {nirvana_address[key]}")
                                        break
                            
                            # Also populate main address fields if not already set
                            if not sheets_data.get("street_address") and nirvana_address.get("street_line_1"):
                                sheets_data["street_address"] = nirvana_address["street_line_1"]
                            if not sheets_data.get("city") and nirvana_address.get("city"):
                                sheets_data["city"] = nirvana_address["city"]
                            if not sheets_data.get("state") and nirvana_address.get("state"):
                                sheets_data["state"] = nirvana_address["state"]
                            if not sheets_data.get("postal_code") and nirvana_address.get("zip"):
                                sheets_data["postal_code"] = nirvana_address["zip"]
                                
                            logger.info("  📍 Successfully extracted Nirvana address fields for Google Sheets")
                        else:
                            logger.warning("  ⚠️ No Nirvana address data found in any expected location")

                    # Add insurance validation data to sheets logging
                    if insurance_validation_result:
                        sheets_data.update(
                            {
                                "insurance_provider_original": insurance_validation_result[
                                    "original_provider"
                                ],
                                "insurance_provider_corrected": insurance_validation_result[
                                    "corrected_provider"
                                ],
                                "insurance_provider_was_corrected": insurance_validation_result[
                                    "was_corrected"
                                ],
                                "insurance_provider_correction_type": insurance_validation_result[
                                    "correction_type"
                                ],
                                "insurance_provider_validation_status": insurance_validation_result[
                                    "validation_status"
                                ],
                            }
                        )

                    # Add all the structured payload data to sheets logging
                    sheets_data.update(
                        {
                            # IntakeQ response data
                            "intakeq_client_id": client_id,
                            "intakeq_intake_url": intake_url,
                            "completion_timestamp": datetime.utcnow().isoformat(),
                            "user_agent": request.headers.get("User-Agent", ""),
                            "ip_address": request.remote_addr,
                            # Core identification from payload
                            "intakeq_name": intakeq_payload.get("Name", ""),
                            "intakeq_first_name": intakeq_payload.get("FirstName", ""),
                            "intakeq_last_name": intakeq_payload.get("LastName", ""),
                            "intakeq_middle_name": intakeq_payload.get(
                                "MiddleName", ""
                            ),
                            "intakeq_email": intakeq_payload.get("Email", ""),
                            # Contact information from payload
                            "intakeq_phone": intakeq_payload.get("Phone", ""),
                            "intakeq_mobile_phone": intakeq_payload.get(
                                "MobilePhone", ""
                            ),
                            "intakeq_home_phone": intakeq_payload.get("HomePhone", ""),
                            "intakeq_work_phone": intakeq_payload.get("WorkPhone", ""),
                            # Demographics from payload
                            "intakeq_gender": intakeq_payload.get("Gender", ""),
                            "intakeq_marital_status": intakeq_payload.get(
                                "MaritalStatus", ""
                            ),
                            "intakeq_date_of_birth": intakeq_payload.get(
                                "DateOfBirth", ""
                            ),
                            # Address information from payload
                            "intakeq_street_address": intakeq_payload.get(
                                "StreetAddress", ""
                            ),
                            "intakeq_city": intakeq_payload.get("City", ""),
                            "intakeq_state": intakeq_payload.get("StateShort", ""),
                            "intakeq_postal_code": intakeq_payload.get(
                                "PostalCode", ""
                            ),
                            "intakeq_country": intakeq_payload.get("Country", ""),
                            "intakeq_unit_number": intakeq_payload.get(
                                "UnitNumber", ""
                            ),
                            # Insurance fields from payload (if insurance client)
                            "intakeq_insurance_company": intakeq_payload.get(
                                "PrimaryInsuranceCompany", ""
                            ),
                            "intakeq_insurance_policy": intakeq_payload.get(
                                "PrimaryInsurancePolicyNumber", ""
                            ),
                            "intakeq_insurance_group": intakeq_payload.get(
                                "PrimaryInsuranceGroupNumber", ""
                            ),
                            "intakeq_insurance_holder_name": intakeq_payload.get(
                                "PrimaryInsuranceHolderName", ""
                            ),
                            "intakeq_insurance_relationship": intakeq_payload.get(
                                "PrimaryInsuranceRelationship", ""
                            ),
                            "intakeq_insurance_holder_dob": intakeq_payload.get(
                                "PrimaryInsuranceHolderDateOfBirth", ""
                            ),
                            # ENHANCED: Add subscriber demographics to sheets data
                            "intakeq_primary_insured_gender": intakeq_payload.get(
                                "PrimaryInsuredGender", ""
                            ),
                            "intakeq_primary_insured_city": intakeq_payload.get(
                                "PrimaryInsuredCity", ""
                            ),
                            "intakeq_primary_insured_state": intakeq_payload.get(
                                "PrimaryInsuredState", ""
                            ),
                            "intakeq_primary_insured_zip": intakeq_payload.get(
                                "PrimaryInsuredZipCode", ""
                            ),
                            "intakeq_primary_insured_address": intakeq_payload.get(
                                "PrimaryInsuredStreetAddress", ""
                            ),
                            "intakeq_relationship_to_insured": intakeq_payload.get(
                                "PrimaryRelationshipToInsured", ""
                            ),
                            # System fields from payload
                            "intakeq_external_client_id": intakeq_payload.get(
                                "ExternalClientId", ""
                            ),
                            "intakeq_date_created": intakeq_payload.get(
                                "DateCreated", ""
                            ),
                            "intakeq_last_activity_date": intakeq_payload.get(
                                "LastActivityDate", ""
                            ),
                            # Additional information (comprehensive therapy data)
                            "intakeq_additional_information": intakeq_payload.get(
                                "AdditionalInformation", ""
                            ),
                            "intakeq_custom_fields_count": len(
                                intakeq_payload.get("CustomFields", [])
                            ),
                        }
                    )

                    # Add custom fields data in a structured way
                    custom_fields = intakeq_payload.get("CustomFields", [])
                    for field in custom_fields:
                        field_id = field.get("FieldId", "")
                        field_value = field.get("Value", "")
                        if field_id and field_value:
                            sheets_data[f"intakeq_custom_{field_id}"] = field_value

                    # Add rich therapy data for better analysis
                    additional_info = intakeq_payload.get("AdditionalInformation", "")
                    if additional_info:
                        # Extract key therapy information from the additional info
                        if "PHQ-9 Total:" in additional_info:
                            sheets_data["therapy_assessment_included"] = True
                        if "Selected Therapist:" in additional_info:
                            sheets_data["therapist_preselected"] = True
                        if "Appointment Information:" in additional_info:
                            sheets_data["appointment_scheduled"] = True
                        if "Substance Use Screening:" in additional_info:
                            sheets_data["substance_screening_completed"] = True
                        if "Insurance" in additional_info:
                            sheets_data["insurance_info_captured"] = True

                    # Add payload size and structure info for debugging
                    sheets_data.update(
                        {
                            "intakeq_payload_size": len(str(intakeq_payload)),
                            "intakeq_payload_fields_count": len(intakeq_payload),
                            "intakeq_additional_info_length": len(additional_info),
                            "payment_type": payment_type,
                            "form_version": "enhanced_comprehensive_v2",
                        }
                    )

                    # Calculate assessment totals if not already present
                    if client_data.get("phq9_scores") and not client_data.get(
                        "phq9_total"
                    ):
                        sheets_data["phq9_total"] = calculate_phq9_score(
                            client_data["phq9_scores"]
                        )
                    if client_data.get("gad7_scores") and not client_data.get(
                        "gad7_total"
                    ):
                        sheets_data["gad7_total"] = calculate_gad7_score(
                            client_data["gad7_scores"]
                        )

                    logger.info(f"  📊 Logging comprehensive data to Google Sheets...")
                    logger.info(
                        f"  📊 Data fields being logged: {len(sheets_data)} total fields"
                    )
                    logger.info(
                        f"  📊 IntakeQ payload size: {sheets_data.get('intakeq_payload_size', 0)} characters"
                    )
                    logger.info(
                        f"  📊 Custom fields captured: {sheets_data.get('intakeq_custom_fields_count', 0)}"
                    )
                    logger.info(
                        f"  📊 Additional info length: {sheets_data.get('intakeq_additional_info_length', 0)} characters"
                    )

                    # DEBUG: Log key data points to verify data retention
                    logger.info("🐛 KEY DATA POINTS FOR SHEETS LOGGING:")
                    key_fields = [
                        "first_name",
                        "last_name",
                        "email",
                        "phone",
                        "intakeq_client_id",
                        "intakeq_intake_url",
                        "payment_type",
                    ]
                    for field in key_fields:
                        value = sheets_data.get(field, "NOT_FOUND")
                        logger.info(f"  {field}: {value}")

                    # DEBUG: Log sample of custom fields
                    custom_field_keys = [
                        k for k in sheets_data.keys() if k.startswith("intakeq_custom_")
                    ]
                    if custom_field_keys:
                        logger.info(
                            f"🐛 SAMPLE CUSTOM FIELDS ({len(custom_field_keys)} total):"
                        )
                        for field in custom_field_keys[:5]:  # Show first 5
                            logger.info(f"  {field}: {sheets_data[field]}")

                    # DEBUG: Log subscriber fields specifically
                    subscriber_keys = [
                        k
                        for k in sheets_data.keys()
                        if k.startswith(("subscriber_", "intakeq_primary_insured_"))
                    ]
                    if subscriber_keys:
                        logger.info(
                            f"🐛 SUBSCRIBER FIELDS ({len(subscriber_keys)} total):"
                        )
                        for field in subscriber_keys:
                            logger.info(f"  {field}: {sheets_data[field]}")

                    # DEBUG: Check if we have demographic data from Nirvana
                    nirvana_fields = [
                        "demographics",
                        "subscriber_demographics",
                        "plan_name",
                        "payer_id",
                        "subscriber_first_name",
                        "subscriber_last_name",
                    ]
                    logger.info("🐛 NIRVANA DEMOGRAPHIC DATA IN SHEETS:")
                    for field in nirvana_fields:
                        value = sheets_data.get(field, "NOT_FOUND")
                        logger.info(
                            f"  {field}: {str(value)[:100]}{'...' if len(str(value)) > 100 else ''}"
                        )
                    
                    # DEBUG: Check financial data extraction
                    financial_fields = [
                        "copay", "deductible", "coinsurance", "out_of_pocket_max",
                        "remaining_deductible", "remaining_oop_max", "member_obligation",
                        "benefit_structure", "session_cost_dollars"
                    ]
                    logger.info("💰 FINANCIAL DATA IN SHEETS:")
                    for field in financial_fields:
                        value = sheets_data.get(field, "NOT_FOUND")
                        logger.info(f"  {field}: {value}")
                    
                    financial_data_count = sum(1 for field in financial_fields if sheets_data.get(field) not in [None, "NOT_FOUND", ""])
                    logger.info(f"💰 Total financial fields populated: {financial_data_count}/{len(financial_fields)}")

                    # Use progressive logger with legacy compatibility
                    from src.services.google_sheets_progressive_logger import (
                        progressive_logger,
                    )

                    success = progressive_logger.log_user_signup(sheets_data)
                    if success:
                        logger.info(
                            f"  ✅ Successfully logged comprehensive data via progressive logger"
                        )
                    else:
                        logger.warning(f"  ⚠️  Failed to log to progressive logger")
                except Exception as e:
                    logger.error(f"  ❌ Google Sheets logging error: {e}")
        else:
            logger.info(f"  📊 Google Sheets logging disabled")

        # Attempt automatic therapist assignment if client has therapist data
        therapist_assignment_result = None
        if client_data.get("selected_therapist"):
            try:
                logger.info(f"🎯 [AUTO ASSIGNMENT] Attempting to assign therapist...")
                selected_therapist = client_data["selected_therapist"]
                
                # Handle both string and object formats for selected_therapist
                if isinstance(selected_therapist, str):
                    therapist_name = selected_therapist
                    therapist_email = client_data.get("selected_therapist_email", "")
                elif isinstance(selected_therapist, dict):
                    therapist_name = selected_therapist.get("name", "")
                    therapist_email = selected_therapist.get("email", "")
                else:
                    therapist_name = ""
                    therapist_email = ""

                logger.info(f"  👤 Therapist: {therapist_name}")
                logger.info(f"  💳 Payment Type: {payment_type}")
                logger.info(f"  🆔 Client ID: {client_id}")

                # Import and use the Railway assignment function
                from src.api.railway_practitioner import (
                    assign_practitioner_railway_direct,
                )

                # Get client state for state-specific IntakeQ credentials
                client_state = client_data.get("state", "")

                assignment_result = assign_practitioner_railway_direct(
                    account_type=payment_type,
                    client_id=str(client_id),
                    therapist_full_name=therapist_name,
                    response_id=client_data.get("response_id"),
                    state=client_state
                )
                
                assignment_success = assignment_result.get("success", False)
                client_url = assignment_result.get("client_url")

                if assignment_success:
                    logger.info(
                        f"  ✅ Successfully assigned {therapist_name} to client {client_id}"
                    )
                    # Add client URL to sheets data for Google Sheets logging
                    if client_url and 'sheets_data' in locals():
                        sheets_data["intakeq_intake_url"] = client_url
                        logger.info(f"  📋 Added client profile URL to sheets data: {client_url}")

                    therapist_assignment_result = {
                        "success": True,
                        "therapist_name": therapist_name,
                        "client_profile_url": client_url,
                        "message": f"Successfully assigned {therapist_name}",
                    }
                else:
                    logger.warning(
                        f"  ⚠️  Failed to assign {therapist_name} to client {client_id}"
                    )
                    therapist_assignment_result = {
                        "success": False,
                        "therapist_name": therapist_name,
                        "message": f"Failed to assign {therapist_name}",
                    }

            except Exception as e:
                logger.error(f"  ❌ Auto assignment error: {str(e)}")
                therapist_assignment_result = {
                    "success": False,
                    "error": str(e),
                    "message": "Error during automatic assignment",
                }
        else:
            logger.info(f"  ℹ️  No therapist selected for automatic assignment")

        logger.info("=" * 60)

        response_data = {
            "client_id": client_id,
            "intake_url": intake_url,
            "intakeq_response": result,
        }

        if therapist_assignment_result:
            response_data["therapist_assignment"] = therapist_assignment_result

        if insurance_validation_result:
            response_data["insurance_validation"] = insurance_validation_result

        return jsonify(response_data)

    except requests.Timeout as e:
        logger.error(f"❌ [INTAKEQ API TIMEOUT] {str(e)}")
        return jsonify({"error": "IntakeQ API request timed out"}), 504
    except requests.ConnectionError as e:
        logger.error(f"❌ [INTAKEQ CONNECTION ERROR] {str(e)}")
        return jsonify({"error": "Failed to connect to IntakeQ API"}), 502
    except requests.RequestException as e:
        logger.error(f"❌ [INTAKEQ API REQUEST ERROR] {str(e)}")
        return jsonify({"error": f"Network error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"❌ [INTAKEQ CLIENT CREATION ERROR] {str(e)}")
        return jsonify({"error": str(e)}), 500


def build_comprehensive_intakeq_payload(client_data: dict, payment_type: str) -> dict:
    """
    Build comprehensive IntakeQ payload from client data.
    Maps ALL available Sol Health client data to IntakeQ API format.
    """
    # Basic client information - use legal first name for IntakeQ
    effective_first_name = client_data.get("first_name") or ""
    last_name = client_data.get("last_name") or ""

    # Build the enhanced base payload following IntakeQ API specification
    payload = {
        # Core identification
        "Name": f"{effective_first_name} {last_name}".strip(),
        "FirstName": effective_first_name,
        "LastName": last_name,
        "MiddleName": client_data.get("middle_name", ""),
        "Email": client_data.get("email", ""),
        # Contact information (normalize phone numbers - strip +1 prefix)
        "Phone": normalize_phone_number(client_data.get("phone", "")),
        "MobilePhone": normalize_phone_number(client_data.get("mobile_phone") or client_data.get("phone", "")),
        "HomePhone": normalize_phone_number(client_data.get("home_phone", "")),
        "WorkPhone": normalize_phone_number(client_data.get("work_phone", "")),
        # Demographics
        "Gender": map_gender(client_data.get("gender", "")),
        "MaritalStatus": client_data.get("marital_status", ""),
        # Enhanced Location/Address Information (priority: Nirvana > user-provided > fallbacks)
        "StateShort": client_data.get("state", "")
        or client_data.get("client_state", ""),
        "City": client_data.get("city", "") or client_data.get("client_city", ""),
        "StreetAddress": client_data.get("street_address", "")
        or client_data.get("address", "")
        or client_data.get("client_address", "")
        or safe_extract_string(client_data.get("street_line_1", "")),  # From Nirvana
        "UnitNumber": client_data.get("unit_number", "")
        or client_data.get("apt", "")
        or client_data.get("apartment", "")
        or safe_extract_string(client_data.get("street_line_2", "")),  # From Nirvana
        "PostalCode": client_data.get("postal_code", "")
        or client_data.get("zip_code", "")
        or client_data.get("zip", ""),
        "Country": client_data.get("country", "USA"),
        # Additional address fields that IntakeQ supports
        "Address1": client_data.get("street_address", "")
        or client_data.get("address", "")
        or client_data.get("client_address", "")
        or safe_extract_string(client_data.get("street_line_1", "")),  # From Nirvana
        "Address2": client_data.get("unit_number", "")
        or client_data.get("apt", "")
        or client_data.get("apartment", "")
        or safe_extract_string(client_data.get("street_line_2", "")),  # From Nirvana
        "State": client_data.get("state", "") or client_data.get("client_state", ""),
        "Zip": client_data.get("postal_code", "")
        or client_data.get("zip_code", "")
        or client_data.get("zip", ""),
        # System fields
        "Archived": False,
        "DateCreated": int(time.time() * 1000),  # Unix timestamp in milliseconds
        "LastActivityDate": int(time.time() * 1000),
        "LastActivityName": "Client Added",
    }

    # Handle date of birth conversion
    if client_data.get("date_of_birth"):
        payload["DateOfBirth"] = convert_date_to_timestamp(client_data["date_of_birth"])
    elif client_data.get("insurance_date_of_birth"):
        payload["DateOfBirth"] = convert_date_to_timestamp(
            client_data["insurance_date_of_birth"]
        )

    # Insurance information for insurance clients
    if payment_type == "insurance":
        # Check if we have Nirvana verification data to enhance the payload
        # Priority order: structured data > raw response > legacy fields
        nirvana_data = None

        # Priority order: comprehensive raw response > structured data > legacy fields
        nirvana_data_sources = [
            ("nirvana_raw_response", "comprehensive raw response"),
            ("insurance_verification_data", "insurance verification data"),
            ("nirvana_response", "nirvana response"),
            ("rawNirvanaResponse", "raw Nirvana response"),
        ]

        for field_name, description in nirvana_data_sources:
            if client_data.get(field_name):
                nirvana_data = client_data[field_name]
                logger.info(
                    f"📊 Using {field_name} for comprehensive mapping ({description})"
                )
                break

        # Also try to reconstruct from structured fields if available
        if not nirvana_data and any(
            [
                client_data.get("nirvana_demographics"),
                client_data.get("nirvana_plan_details"),
                client_data.get("nirvana_benefits"),
            ]
        ):
            logger.info("📊 Reconstructing Nirvana data from structured fields")
            nirvana_data = {
                "demographics": client_data.get("nirvana_demographics") or {},
                "plan_details": client_data.get("nirvana_plan_details") or {},
                "benefits": client_data.get("nirvana_benefits") or {},
                "address": client_data.get("nirvana_address") or {},
            }
            # Flatten structure to match expected format
            if isinstance(nirvana_data.get("demographics"), dict):
                nirvana_data.update(nirvana_data["demographics"])
            if isinstance(nirvana_data.get("plan_details"), dict):
                nirvana_data.update(nirvana_data["plan_details"])
            if isinstance(nirvana_data.get("benefits"), dict):
                nirvana_data.update(nirvana_data["benefits"])
        if nirvana_data:
            try:
                # Parse Nirvana data if it's a JSON string
                if isinstance(nirvana_data, str):
                    nirvana_data = json.loads(nirvana_data)

                # DEBUG: Log actual Nirvana data structure
                logger.info("🔍 [NIRVANA DEBUG] Actual Nirvana data structure:")
                logger.info(f"  Type: {type(nirvana_data)}")
                if isinstance(nirvana_data, dict):
                    logger.info(f"  Keys: {list(nirvana_data.keys())}")
                    # Log subscriber info if it exists
                    if 'subscriber' in nirvana_data:
                        subscriber = nirvana_data['subscriber']
                        logger.info(f"  Subscriber keys: {list(subscriber.keys()) if isinstance(subscriber, dict) else 'Not a dict'}")
                        if isinstance(subscriber, dict) and 'address' in subscriber:
                            logger.info(f"  Subscriber address: {subscriber['address']}")
                        if isinstance(subscriber, dict) and 'demographics' in subscriber:
                            logger.info(f"  Subscriber demographics: {subscriber['demographics']}")
                    # Log any other relevant keys
                    for key in ['demographics', 'address', 'coverage', 'benefits']:
                        if key in nirvana_data:
                            logger.info(f"  {key}: {type(nirvana_data[key])} - {str(nirvana_data[key])[:200]}...")

                # Use Nirvana mapper to get comprehensive address and insurance data
                from nirvana_intakeq_mapper import NirvanaIntakeQMapper

                logger.info(
                    "🔄 Using Nirvana data to enhance insurance client payload..."
                )
                nirvana_payload = NirvanaIntakeQMapper.map_nirvana_to_intakeq(
                    nirvana_data, client_data
                )
                
                # DEBUG: Log what was mapped
                logger.info("🔍 [NIRVANA MAPPING DEBUG] Fields mapped from Nirvana:")
                demographic_fields = ['FirstName', 'LastName', 'StreetAddress', 'City', 'State', 'PostalCode', 
                                    'PrimaryInsuredGender', 'PrimaryInsuredCity', 'PrimaryInsuredState', 
                                    'PrimaryInsuredStreetAddress', 'PrimaryInsuredZipCode']
                for field in demographic_fields:
                    if field in nirvana_payload:
                        logger.info(f"  {field}: {nirvana_payload[field]}")
                    else:
                        logger.info(f"  {field}: NOT MAPPED")

                # Merge Nirvana-mapped data with existing payload
                # Handle CustomFields separately to merge instead of overwrite
                nirvana_custom_fields = nirvana_payload.get("CustomFields", [])

                # Address, demographic and insurance fields - Nirvana data takes priority
                priority_fields = [
                    # Enhanced demographic fields from Nirvana
                    "FirstName",
                    "LastName",
                    "Name",
                    "Gender",
                    "DateOfBirth",
                    # Address information from Nirvana verification
                    "StreetAddress",
                    "UnitNumber",
                    "City",
                    "StateShort",
                    "PostalCode",
                    "Country",
                    "Address",
                    "Address1",
                    "Address2",
                    "State",
                    "Zip",
                    # Primary insurance information from Nirvana
                    "PrimaryInsuranceCompany",
                    "PrimaryInsurancePayerId",
                    "PrimaryInsurancePolicyNumber",
                    "PrimaryInsuranceGroupNumber",
                    "PrimaryInsurancePlan",
                    "PrimaryInsuranceHolderName",
                    "PrimaryInsuranceHolderDateOfBirth",
                    "PrimaryInsuranceRelationship",
                    "PrimaryRelationshipToInsured",
                    # Insured demographic information
                    "PrimaryInsuredGender",
                    "PrimaryInsuredCity",
                    "PrimaryInsuredZipCode",
                    "PrimaryInsuredState",
                    "PrimaryInsuredStreetAddress",
                ]

                enhanced_fields = []
                subscriber_fields = []
                for field in priority_fields:
                    if field in nirvana_payload and nirvana_payload[field]:
                        original_value = payload.get(field, "")
                        payload[field] = nirvana_payload[field]
                        enhanced_fields.append(field)

                        # Track subscriber-specific fields separately
                        if field.startswith("PrimaryInsured"):
                            subscriber_fields.append(field)
                            logger.info(
                                f"  👥 Subscriber field {field}: '{original_value}' → '{nirvana_payload[field]}'"
                            )
                        else:
                            logger.info(
                                f"  ✅ Enhanced {field}: '{original_value}' → '{nirvana_payload[field]}'"
                            )

                logger.info(
                    f"📊 Enhanced {len(enhanced_fields)} fields from Nirvana data"
                )
                logger.info(
                    f"  📝 General fields: {', '.join([f for f in enhanced_fields if not f.startswith('PrimaryInsured')])}"
                )
                if subscriber_fields:
                    logger.info(
                        f"  👥 Subscriber fields: {', '.join(subscriber_fields)}"
                    )

                # Log parent-child relationship detection
                if nirvana_payload.get("_is_child_relationship"):
                    logger.info("  🔍 Detected parent-child insurance relationship")
                    payload[
                        "_relationship_notes"
                    ] = "Patient is child of insurance subscriber"

                # Store Nirvana custom fields to merge later with comprehensive therapy data
                payload["_nirvana_custom_fields"] = nirvana_custom_fields
                logger.info(
                    f"  📋 Stored {len(nirvana_custom_fields)} Nirvana custom fields for merging"
                )

                logger.info(
                    "🎯 Successfully enhanced payload with Nirvana verification data"
                )
                logger.info("📍 Final enhanced address from Nirvana:")
                logger.info(
                    f"  StreetAddress: '{payload.get('StreetAddress', '')}' {'✓' if payload.get('StreetAddress') else '✗'}"
                )
                logger.info(
                    f"  City: '{payload.get('City', '')}' {'✓' if payload.get('City') else '✗'}"
                )
                logger.info(
                    f"  StateShort: '{payload.get('StateShort', '')}' {'✓' if payload.get('StateShort') else '✗'}"
                )
                logger.info(
                    f"  PostalCode: '{payload.get('PostalCode', '')}' {'✓' if payload.get('PostalCode') else '✗'}"
                )
                logger.info(
                    f"  Address1: '{payload.get('Address1', '')}' {'✓' if payload.get('Address1') else '✗'}"
                )

                # ENHANCED: Log subscriber address information
                logger.info("👥 Final subscriber/insured address from Nirvana:")
                logger.info(
                    f"  PrimaryInsuredStreetAddress: '{payload.get('PrimaryInsuredStreetAddress', '')}' {'✓' if payload.get('PrimaryInsuredStreetAddress') else '✗'}"
                )
                logger.info(
                    f"  PrimaryInsuredCity: '{payload.get('PrimaryInsuredCity', '')}' {'✓' if payload.get('PrimaryInsuredCity') else '✗'}"
                )
                logger.info(
                    f"  PrimaryInsuredState: '{payload.get('PrimaryInsuredState', '')}' {'✓' if payload.get('PrimaryInsuredState') else '✗'}"
                )
                logger.info(
                    f"  PrimaryInsuredZipCode: '{payload.get('PrimaryInsuredZipCode', '')}' {'✓' if payload.get('PrimaryInsuredZipCode') else '✗'}"
                )

                # Track Nirvana enhancement effectiveness
                pre_nirvana_address_fields = [
                    "street_address",
                    "city",
                    "state",
                    "postal_code",
                ]
                pre_nirvana_address_count = sum(
                    1 for field in pre_nirvana_address_fields if client_data.get(field)
                )
                post_nirvana_address_fields = [
                    "StreetAddress",
                    "City",
                    "StateShort",
                    "PostalCode",
                ]
                post_nirvana_count = sum(
                    1 for field in post_nirvana_address_fields if payload.get(field)
                )
                if post_nirvana_count > pre_nirvana_address_count:
                    logger.info(
                        f"🎉 Nirvana enhancement added {post_nirvana_count - pre_nirvana_address_count} address fields!"
                    )
                elif (
                    post_nirvana_count == pre_nirvana_address_count
                    and pre_nirvana_address_count > 0
                ):
                    logger.info("✅ Nirvana preserved existing address data")
                elif pre_nirvana_address_count == 0 and post_nirvana_count == 0:
                    logger.warning(
                        "⚠️ No address data available from either source or Nirvana"
                    )

                # Track subscriber demographics enhancement effectiveness
                subscriber_fields_populated = [
                    "PrimaryInsuredGender",
                    "PrimaryInsuredCity",
                    "PrimaryInsuredState",
                    "PrimaryInsuredZipCode",
                    "PrimaryInsuredStreetAddress",
                ]
                populated_subscriber_count = sum(
                    1 for field in subscriber_fields_populated if payload.get(field)
                )
                logger.info(
                    f"👥 Subscriber demographics: {populated_subscriber_count}/{len(subscriber_fields_populated)} fields populated"
                )
                if populated_subscriber_count > 0:
                    logger.info(
                        "✅ Successfully populated subscriber demographics from Nirvana"
                    )
                else:
                    logger.warning(
                        "⚠️ No subscriber demographics populated - check Nirvana mapping"
                    )

            except (json.JSONDecodeError, ImportError, Exception) as e:
                logger.warning(f"⚠️ Could not use Nirvana data: {str(e)}")
                # Fall back to manual insurance field mapping
                add_comprehensive_insurance_fields(payload, client_data)
        else:
            # No Nirvana data available, use manual mapping
            add_comprehensive_insurance_fields(payload, client_data)

    # External ID mapping
    if client_data.get("response_id"):
        payload["ExternalClientId"] = client_data["response_id"]

    # Enhanced additional information compilation
    additional_info = build_comprehensive_additional_information(
        client_data, payment_type
    )
    if additional_info:
        payload["AdditionalInformation"] = additional_info

    # Comprehensive custom fields for Sol Health specific data
    comprehensive_custom_fields = build_comprehensive_custom_fields(
        client_data, payment_type
    )

    # Merge Nirvana insurance custom fields with comprehensive therapy data
    nirvana_custom_fields = payload.pop("_nirvana_custom_fields", [])
    if nirvana_custom_fields:
        logger.info(
            f"🔗 Merging {len(nirvana_custom_fields)} Nirvana + {len(comprehensive_custom_fields)} therapy custom fields"
        )

        # Create field ID lookup for comprehensive fields to avoid duplicates
        comprehensive_field_ids = {
            field.get("FieldId")
            for field in comprehensive_custom_fields
            if field.get("FieldId")
        }

        # Add Nirvana fields that aren't already covered by comprehensive data
        for nirvana_field in nirvana_custom_fields:
            field_id = nirvana_field.get("FieldId")
            if field_id and field_id not in comprehensive_field_ids:
                comprehensive_custom_fields.append(nirvana_field)
                logger.info(f"  ➕ Added Nirvana field: {field_id}")
            elif field_id in comprehensive_field_ids:
                logger.info(
                    f"  ⚠️ Skipped duplicate field: {field_id} (using comprehensive version)"
                )

    payload["CustomFields"] = comprehensive_custom_fields
    logger.info(f"📋 Final custom fields count: {len(comprehensive_custom_fields)}")

    return payload


def add_comprehensive_insurance_fields(payload: dict, client_data: dict) -> None:
    """Add comprehensive insurance-specific fields to the payload."""
    # Primary insurance fields with provider name correction
    if client_data.get("insurance_provider"):
        insurance_provider = client_data["insurance_provider"]

        # Try to get the correct payer ID for validation
        if get_payer_id is not None:
            payer_id = get_payer_id(insurance_provider)
            if payer_id:
                logger.info(
                    f"📊 Mapped insurance provider '{insurance_provider}' to payer ID: {payer_id}"
                )
                # Store the payer ID for potential use in IntakeQ custom fields
                payload["_insurance_payer_id"] = payer_id

        payload["PrimaryInsuranceCompany"] = insurance_provider

    if client_data.get("insurance_member_id"):
        payload["PrimaryInsurancePolicyNumber"] = client_data["insurance_member_id"]

    if client_data.get("insurance_group_number"):
        payload["PrimaryInsuranceGroupNumber"] = client_data["insurance_group_number"]

    if client_data.get("insurance_holder_name"):
        payload["PrimaryInsuranceHolderName"] = client_data["insurance_holder_name"]

    if client_data.get("insurance_relationship"):
        payload["PrimaryInsuranceRelationship"] = client_data["insurance_relationship"]

    if client_data.get("insurance_holder_dob"):
        payload["PrimaryInsuranceHolderDateOfBirth"] = convert_date_to_timestamp(
            client_data["insurance_holder_dob"]
        )
    
    # Enhanced: Add subscriber/primary insured demographics from multiple sources
    # Priority: explicit subscriber/insurance_holder data > Nirvana data > client fallback
    
    # PrimaryInsuredGender (from subscriber, insurance holder, or Nirvana sex field)
    if client_data.get("subscriber_gender"):
        payload["PrimaryInsuredGender"] = map_gender(client_data["subscriber_gender"])
    elif client_data.get("insurance_holder_gender"):
        payload["PrimaryInsuredGender"] = map_gender(client_data["insurance_holder_gender"])
    elif client_data.get("nirvana_data", {}).get("subscriber_sex"):
        payload["PrimaryInsuredGender"] = map_gender(client_data["nirvana_data"]["subscriber_sex"])
    elif client_data.get("policyholder_sex"):  # Alternative Nirvana field name
        payload["PrimaryInsuredGender"] = map_gender(client_data["policyholder_sex"])
    
    # PrimaryInsuredCity
    if client_data.get("subscriber_city"):
        payload["PrimaryInsuredCity"] = client_data["subscriber_city"]
    elif client_data.get("insurance_holder_city"):
        payload["PrimaryInsuredCity"] = client_data["insurance_holder_city"]
    elif client_data.get("nirvana_data", {}).get("subscriber_city"):
        payload["PrimaryInsuredCity"] = client_data["nirvana_data"]["subscriber_city"]
    
    # PrimaryInsuredState
    if client_data.get("subscriber_state"):
        payload["PrimaryInsuredState"] = client_data["subscriber_state"]
    elif client_data.get("insurance_holder_state"):
        payload["PrimaryInsuredState"] = client_data["insurance_holder_state"]
    elif client_data.get("nirvana_data", {}).get("subscriber_state"):
        payload["PrimaryInsuredState"] = client_data["nirvana_data"]["subscriber_state"]
        
    # PrimaryInsuredZipCode
    if client_data.get("subscriber_zip"):
        payload["PrimaryInsuredZipCode"] = client_data["subscriber_zip"]
    elif client_data.get("insurance_holder_zip"):
        payload["PrimaryInsuredZipCode"] = client_data["insurance_holder_zip"]
    elif client_data.get("nirvana_data", {}).get("subscriber_zip"):
        payload["PrimaryInsuredZipCode"] = client_data["nirvana_data"]["subscriber_zip"]
        
    # PrimaryInsuredStreetAddress
    if client_data.get("subscriber_street"):
        payload["PrimaryInsuredStreetAddress"] = client_data["subscriber_street"]
    elif client_data.get("insurance_holder_address"):
        payload["PrimaryInsuredStreetAddress"] = client_data["insurance_holder_address"]
    elif client_data.get("nirvana_data", {}).get("subscriber_address"):
        payload["PrimaryInsuredStreetAddress"] = client_data["nirvana_data"]["subscriber_address"]

    # ENHANCED INSURANCE FIELDS (fixes missing primary insurance and policyholder information)

    # Policyholder Address Information (required by IntakeQ)
    if client_data.get("insurance_holder_address"):
        payload["PrimaryInsuranceHolderAddress"] = client_data[
            "insurance_holder_address"
        ]
    elif client_data.get(
        "street_address"
    ):  # Fallback to client address if holder address not provided
        payload["PrimaryInsuranceHolderAddress"] = client_data["street_address"]

    if client_data.get("insurance_holder_city"):
        payload["PrimaryInsuranceHolderCity"] = client_data["insurance_holder_city"]
    elif client_data.get("city"):  # Fallback to client city
        payload["PrimaryInsuranceHolderCity"] = client_data["city"]

    if client_data.get("insurance_holder_state"):
        payload["PrimaryInsuranceHolderState"] = client_data["insurance_holder_state"]
    elif client_data.get("state"):  # Fallback to client state
        payload["PrimaryInsuranceHolderState"] = client_data["state"]

    if client_data.get("insurance_holder_zip"):
        payload["PrimaryInsuranceHolderZip"] = client_data["insurance_holder_zip"]
    elif client_data.get("postal_code"):  # Fallback to client zip
        payload["PrimaryInsuranceHolderZip"] = client_data["postal_code"]

    # Policyholder Contact Information
    if client_data.get("insurance_holder_phone"):
        payload["PrimaryInsuranceHolderPhone"] = client_data["insurance_holder_phone"]
    elif client_data.get("phone"):  # Fallback to client phone
        payload["PrimaryInsuranceHolderPhone"] = client_data["phone"]

    # Insurance Plan Details (commonly missing)
    # Primary Insurance Plan - should map to PrimaryInsurancePlan field
    if client_data.get("insurance_plan_name"):
        payload["PrimaryInsurancePlan"] = client_data["insurance_plan_name"]
    elif client_data.get("nirvana_data", {}).get("plan_name"):
        payload["PrimaryInsurancePlan"] = client_data["nirvana_data"]["plan_name"]

    if client_data.get("insurance_employer"):
        payload["PrimaryInsuranceEmployer"] = client_data["insurance_employer"]

    # Insurance Authorization/Eligibility Information
    if client_data.get("insurance_authorization_number"):
        payload["PrimaryInsuranceAuthorizationNumber"] = client_data[
            "insurance_authorization_number"
        ]

    # Insurance Copay/Deductible Information (for reference)
    if client_data.get("copay_amount"):
        payload["PrimaryInsuranceCopayAmount"] = str(client_data["copay_amount"])

    if client_data.get("deductible_amount"):
        payload["PrimaryInsuranceDeductible"] = str(client_data["deductible_amount"])

    # Additional insurance verification data from benefits
    if client_data.get("insurance_verification_data"):
        try:
            verification_data = (
                json.loads(client_data["insurance_verification_data"])
                if isinstance(client_data["insurance_verification_data"], str)
                else client_data["insurance_verification_data"]
            )
            if verification_data and verification_data.get("subscriber"):
                subscriber = verification_data["subscriber"]
                if subscriber.get("firstName") and not payload.get(
                    "PrimaryInsuranceHolderName"
                ):
                    payload[
                        "PrimaryInsuranceHolderName"
                    ] = f"{subscriber.get('firstName', '')} {subscriber.get('lastName', '')}".strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            pass


def build_comprehensive_additional_information(
    client_data: dict, payment_type: str
) -> str:
    """Build comprehensive AdditionalInformation field with ALL available Sol Health data."""
    info_parts = []

    # Sol Health Response ID
    if client_data.get("response_id"):
        info_parts.append(f"Sol Health Response ID: {client_data['response_id']}")

    # Preferred name if different from first name
    if client_data.get("preferred_name") and client_data[
        "preferred_name"
    ] != client_data.get("first_name"):
        info_parts.append(f"Preferred Name: {client_data['preferred_name']}")

    # Mental health assessment scores with totals
    phq9_total = client_data.get("phq9_total")
    gad7_total = client_data.get("gad7_total")
    if phq9_total is not None or gad7_total is not None:
        scores = []
        if phq9_total is not None:
            scores.append(f"PHQ-9 Total: {phq9_total}")
        if gad7_total is not None:
            scores.append(f"GAD-7 Total: {gad7_total}")
        info_parts.append(f"Assessment Total Scores: {', '.join(scores)}")

    # Detailed mental health assessment scores
    phq9_scores = client_data.get("phq9_scores", {})
    if phq9_scores and isinstance(phq9_scores, dict) and any(phq9_scores.values()):
        phq9_details = []
        for question, score in phq9_scores.items():
            if score:
                phq9_details.append(f"  {question.replace('_', ' ').title()}: {score}")
        if phq9_details:
            info_parts.append(
                "PHQ-9 Depression Screening (Detailed):\n" + "\n".join(phq9_details)
            )

    gad7_scores = client_data.get("gad7_scores", {})
    if gad7_scores and isinstance(gad7_scores, dict) and any(gad7_scores.values()):
        gad7_details = []
        for question, score in gad7_scores.items():
            if score:
                gad7_details.append(f"  {question.replace('_', ' ').title()}: {score}")
        if gad7_details:
            info_parts.append(
                "GAD-7 Anxiety Screening (Detailed):\n" + "\n".join(gad7_details)
            )

    # Substance use screening
    substance_info = []
    if client_data.get("alcohol_frequency"):
        substance_info.append(
            f"Alcohol use frequency: {client_data['alcohol_frequency']}"
        )
    if client_data.get("recreational_drugs_frequency"):
        substance_info.append(
            f"Recreational drug use frequency: {client_data['recreational_drugs_frequency']}"
        )
    if substance_info:
        info_parts.append("Substance Use Screening:\n  " + "\n  ".join(substance_info))

    # Comprehensive therapy preferences
    preferences = []
    if client_data.get("therapist_gender_preference"):
        preferences.append(
            f"Therapist Gender Preference: {client_data['therapist_gender_preference']}"
        )

    # Handle both old and new field names for specializations
    specializations = (
        client_data.get("therapist_specialization")
        or client_data.get("therapist_specializes_in")
        or []
    )
    if specializations:
        if isinstance(specializations, list):
            preferences.append(f"Requested Specialties: {', '.join(specializations)}")
        else:
            preferences.append(f"Requested Specialties: {specializations}")

    lived_experiences = client_data.get("therapist_lived_experiences", [])
    if lived_experiences:
        if isinstance(lived_experiences, list):
            preferences.append(
                f"Therapist Lived Experiences Requested: {', '.join(lived_experiences)}"
            )
        else:
            preferences.append(
                f"Therapist Lived Experiences Requested: {lived_experiences}"
            )

    if preferences:
        info_parts.append(
            "Comprehensive Therapist Preferences:\n  " + "\n  ".join(preferences)
        )

    # Selected therapist information - handle both string and object formats
    if client_data.get("selected_therapist"):
        therapist = client_data["selected_therapist"]
        therapist_info = []
        
        # Handle both string and object formats for selected_therapist
        if isinstance(therapist, str):
            # If it's a string, use it directly as the therapist name
            therapist_info.append(f"Selected Therapist: {therapist}")
            # Try to get email from selected_therapist_email field
            if client_data.get("selected_therapist_email"):
                therapist_info.append(f"Therapist Email: {client_data['selected_therapist_email']}")
        elif isinstance(therapist, dict):
            # If it's a dict/object, use the object syntax
            if therapist.get("name"):
                therapist_info.append(f"Selected Therapist: {therapist['name']}")
            if therapist.get("email"):
                therapist_info.append(f"Therapist Email: {therapist['email']}")
            if therapist.get("specialties"):
                specialties_list = (
                    therapist["specialties"]
                    if isinstance(therapist["specialties"], list)
                    else []
                )
                if specialties_list:
                    therapist_info.append(
                        f"Therapist Specialties: {', '.join(specialties_list)}"
                    )
        
        if therapist_info:
            info_parts.append(
                "Selected Therapist Information:\n  " + "\n  ".join(therapist_info)
            )

    # Appointment information
    if client_data.get("appointment"):
        appointment = client_data["appointment"]
        appointment_info = []
        if appointment.get("date"):
            appointment_info.append(f"Scheduled Date: {appointment['date']}")
        if appointment.get("time"):
            appointment_info.append(f"Scheduled Time: {appointment['time']}")
        if appointment.get("timezone"):
            appointment_info.append(f"Timezone: {appointment['timezone']}")
        if appointment.get("duration"):
            appointment_info.append(
                f"Session Duration: {appointment['duration']} minutes"
            )
        if appointment_info:
            info_parts.append(
                "Appointment Information:\n  " + "\n  ".join(appointment_info)
            )

    # What brings you to therapy
    if client_data.get("what_brings_you"):
        what_brings = client_data["what_brings_you"]
        if len(what_brings) > 200:
            what_brings = what_brings[:197] + "..."
        info_parts.append(f"What brings you to therapy: {what_brings}")

    # Demographics and background
    demographics = []
    if client_data.get("age"):
        demographics.append(f"Age: {client_data['age']}")

    race_ethnicity = client_data.get("race_ethnicity", [])
    if race_ethnicity:
        if isinstance(race_ethnicity, list):
            demographics.append(f"Race/Ethnicity: {', '.join(race_ethnicity)}")
        else:
            demographics.append(f"Race/Ethnicity: {race_ethnicity}")

    lived_experiences_general = client_data.get("lived_experiences", [])
    if lived_experiences_general:
        if isinstance(lived_experiences_general, list):
            demographics.append(
                f"Lived Experiences: {', '.join(lived_experiences_general)}"
            )
        else:
            demographics.append(f"Lived Experiences: {lived_experiences_general}")

    if client_data.get("university"):
        demographics.append(f"University: {client_data['university']}")

    if demographics:
        info_parts.append("Demographics:\n  " + "\n  ".join(demographics))

    # Safety screening and matching preferences
    if client_data.get("safety_screening"):
        info_parts.append(f"Safety Screening: {client_data['safety_screening']}")

    if client_data.get("matching_preference"):
        info_parts.append(f"Matching Preference: {client_data['matching_preference']}")

    # Referral and tracking information
    tracking_info = []
    if client_data.get("referred_by"):
        referred_by = client_data["referred_by"]
        if isinstance(referred_by, list):
            tracking_info.append(f"Referred by: {', '.join(referred_by)}")
        else:
            tracking_info.append(f"Referred by: {referred_by}")

    if client_data.get("promo_code"):
        tracking_info.append(f"Promo Code: {client_data['promo_code']}")

    # UTM tracking data (handle both object and individual fields)
    utm_parts = []
    if client_data.get("utm") and isinstance(client_data["utm"], dict):
        utm_data = client_data["utm"]
        for field in ["utm_source", "utm_medium", "utm_campaign"]:
            if utm_data.get(field):
                utm_parts.append(f"{field}: {utm_data[field]}")
    else:
        # Fallback to individual UTM fields
        for utm_field in ["utm_source", "utm_medium", "utm_campaign"]:
            if client_data.get(utm_field):
                utm_parts.append(f"{utm_field}: {client_data[utm_field]}")

    if utm_parts:
        tracking_info.append(f"Marketing Attribution: {', '.join(utm_parts)}")

    # Timestamps
    if client_data.get("onboarding_completed_at"):
        tracking_info.append(
            f"Onboarding Completed: {client_data['onboarding_completed_at']}"
        )
    if client_data.get("survey_completed_at"):
        tracking_info.append(f"Survey Completed: {client_data['survey_completed_at']}")

    if tracking_info:
        info_parts.append("Tracking Information:\n  " + "\n  ".join(tracking_info))

    return "\n\n".join(info_parts)


def build_comprehensive_custom_fields(client_data: dict, payment_type: str) -> list:
    """Build comprehensive CustomFields array for IntakeQ with all available data."""
    custom_fields = []
    
    # Enhanced: Add preferred name if available
    if client_data.get("preferred_name"):
        custom_fields.append({
            "FieldId": "85hp",  # Preferred Name field ID from IntakeQ profile
            "Value": client_data["preferred_name"]
        })
    
    # Enhanced: Add emergency contact information if available
    if client_data.get("emergency_contact_name"):
        custom_fields.append({
            "FieldId": "EmergencyContactName",
            "Value": client_data["emergency_contact_name"]
        })
    
    if client_data.get("emergency_contact_phone"):
        custom_fields.append({
            "FieldId": "EmergencyContactPhone", 
            "Value": client_data["emergency_contact_phone"]
        })
        
    if client_data.get("emergency_contact_relationship"):
        custom_fields.append({
            "FieldId": "EmergencyContactRelationship",
            "Value": client_data["emergency_contact_relationship"] 
        })

    # Payment type field (using field ID from your configuration)
    custom_fields.append(
        {
            "FieldId": INTAKEQ_CUSTOM_FIELDS["insurance_type"],
            "Value": "Cash Pay" if payment_type == "cash_pay" else "Insurance",
        }
    )

    # For insurance clients, add comprehensive insurance-specific custom fields
    if payment_type == "insurance":
        # Insurance benefit fields
        insurance_benefit_fields = {
            "copay": client_data.get("copay"),
            "deductible": client_data.get("deductible"),
            "coinsurance": client_data.get("coinsurance"),
            "out_of_pocket_max": client_data.get("out_of_pocket_max"),
            "remaining_deductible": client_data.get("remaining_deductible"),
            "remaining_oop_max": client_data.get("remaining_oop_max"),
            "member_obligation": client_data.get("member_obligation"),
            "benefit_structure": client_data.get("benefit_structure"),
        }

        for field_name, value in insurance_benefit_fields.items():
            if value and field_name in INTAKEQ_CUSTOM_FIELDS:
                custom_fields.append(
                    {"FieldId": INTAKEQ_CUSTOM_FIELDS[field_name], "Value": str(value)}
                )

        # Insurance verification status
        if client_data.get("insurance_verified") is not None:
            verification_status = (
                "Verified"
                if client_data["insurance_verified"]
                else "Pending Verification"
            )
            custom_fields.append(
                {
                    "FieldId": INTAKEQ_CUSTOM_FIELDS["coverage_status"],
                    "Value": verification_status,
                }
            )

        # Mental health coverage status
        custom_fields.append(
            {
                "FieldId": INTAKEQ_CUSTOM_FIELDS["mental_health_coverage"],
                "Value": "Active"
                if client_data.get("insurance_verified")
                else "Pending",
            }
        )

        # Plan status
        custom_fields.append(
            {
                "FieldId": INTAKEQ_CUSTOM_FIELDS["plan_status"],
                "Value": "Active",
            }
        )

    # Assessment totals as custom fields for easy access
    if client_data.get("phq9_total") is not None:
        custom_fields.append(
            {
                "FieldId": "phq9_total_score",
                "Value": str(client_data["phq9_total"]),
            }
        )

    if client_data.get("gad7_total") is not None:
        custom_fields.append(
            {
                "FieldId": "gad7_total_score",
                "Value": str(client_data["gad7_total"]),
            }
        )

    # Substance use screening as custom fields
    if client_data.get("alcohol_frequency"):
        custom_fields.append(
            {
                "FieldId": "alcohol_use_frequency",
                "Value": client_data["alcohol_frequency"],
            }
        )

    if client_data.get("recreational_drugs_frequency"):
        custom_fields.append(
            {
                "FieldId": "drug_use_frequency",
                "Value": client_data["recreational_drugs_frequency"],
            }
        )

    # Therapist preferences as custom fields
    if client_data.get("therapist_gender_preference"):
        custom_fields.append(
            {
                "FieldId": "preferred_therapist_gender",
                "Value": client_data["therapist_gender_preference"],
            }
        )

    # Selected therapist info as custom fields - handle both string and object formats
    if client_data.get("selected_therapist"):
        therapist = client_data["selected_therapist"]
        
        # Handle both string and object formats for selected_therapist
        if isinstance(therapist, str):
            # If it's a string, use it directly as the therapist name
            custom_fields.append(
                {"FieldId": "selected_therapist_name", "Value": therapist}
            )
            # Try to get email from selected_therapist_email field
            if client_data.get("selected_therapist_email"):
                custom_fields.append(
                    {"FieldId": "selected_therapist_email", "Value": client_data["selected_therapist_email"]}
                )
        elif isinstance(therapist, dict):
            # If it's a dict/object, use the object syntax
            if therapist.get("name"):
                custom_fields.append(
                    {"FieldId": "selected_therapist_name", "Value": therapist["name"]}
                )
            if therapist.get("email"):
                custom_fields.append(
                    {"FieldId": "selected_therapist_email", "Value": therapist["email"]}
                )

    # Appointment info as custom fields
    if client_data.get("appointment"):
        appointment = client_data["appointment"]
        if appointment.get("date"):
            custom_fields.append(
                {"FieldId": "scheduled_appointment_date", "Value": appointment["date"]}
            )
        if appointment.get("time"):
            custom_fields.append(
                {"FieldId": "scheduled_appointment_time", "Value": appointment["time"]}
            )

    # Emergency contact information (if available)
    if client_data.get("emergency_contact_name"):
        custom_fields.append(
            {
                "FieldId": "EmergencyContactName",
                "Value": client_data["emergency_contact_name"],
            }
        )

    if client_data.get("emergency_contact_phone"):
        custom_fields.append(
            {
                "FieldId": "EmergencyContactPhone",
                "Value": client_data["emergency_contact_phone"],
            }
        )

    if client_data.get("emergency_contact_relationship"):
        custom_fields.append(
            {
                "FieldId": "EmergencyContactRelationship",
                "Value": client_data["emergency_contact_relationship"],
            }
        )

    # Demographics as custom fields
    if client_data.get("age"):
        custom_fields.append(
            {
                "FieldId": "client_age",
                "Value": str(client_data["age"]),
            }
        )

    return custom_fields


def map_gender(gender_input: str) -> str:
    """Map client gender input to IntakeQ expected values."""
    if not gender_input:
        return ""

    gender_lower = gender_input.lower().strip()

    # Map common variations to standard values
    gender_mapping = {
        "m": "Male",
        "male": "Male",
        "man": "Male",
        "f": "Female",
        "female": "Female",
        "woman": "Female",
        "nb": "Non-binary",
        "non-binary": "Non-binary",
        "nonbinary": "Non-binary",
        "other": "Other",
        "prefer not to say": "",
        "not specified": "",
    }

    return gender_mapping.get(gender_lower, gender_input.title())


def convert_date_to_timestamp(date_input) -> int:
    """Convert various date formats to Unix timestamp in milliseconds."""
    if isinstance(date_input, int):
        # Already a timestamp
        return date_input if date_input > 1000000000000 else date_input * 1000

    if isinstance(date_input, str):
        try:
            # Try parsing common date formats
            for fmt in [
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%d/%m/%Y",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ",
            ]:
                try:
                    dt = datetime.strptime(date_input, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue
        except (TypeError, AttributeError):
            pass

    return None


@intakeq_forms_bp.route("/intakeq/client", methods=["GET"])
def get_intakeq_client():
    """Retrieve client information from IntakeQ by email."""
    try:
        email = request.args.get("email", "").strip()
        payment_type = request.args.get("payment_type", "cash_pay").strip()
        client_state = request.args.get("state", "").strip()

        if not email:
            return jsonify({"error": "email parameter is required"}), 400

        # Log the request
        logger.info(f"🔍 [INTAKEQ CLIENT LOOKUP] {email} ({payment_type}, state: {client_state})")

        # Determine which IntakeQ API key to use based on payment type and state
        if payment_type == "cash_pay":
            intakeq_api_key = os.getenv("CASH_PAY_INTAKEQ_API_KEY")
        else:  # insurance
            from src.utils.intakeq.state_config import get_insurance_intakeq_config
            intakeq_api_key = get_insurance_intakeq_config(client_state, 'api_key')
            if not intakeq_api_key:
                # Fallback to generic insurance key
                intakeq_api_key = os.getenv("INSURANCE_INTAKEQ_API_KEY")

        if not intakeq_api_key:
            error_msg = f"Missing IntakeQ API key for payment type: {payment_type}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        # Call IntakeQ API
        params = urlencode({"email": email})
        intakeq_response = requests.get(
            f"https://intakeq.com/api/v1/clients?{params}",
            headers={
                "X-Auth-Key": intakeq_api_key,
                "Content-Type": "application/json",
            },
            timeout=60,
        )

        logger.info(f"  📥 IntakeQ Response Status: {intakeq_response.status_code}")

        if not intakeq_response.ok:
            error_text = intakeq_response.text
            error_msg = (
                f"IntakeQ API error: {intakeq_response.status_code} - {error_text}"
            )
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        result = intakeq_response.json()

        client_count = len(result) if isinstance(result, list) else (1 if result else 0)
        logger.info(f"  ✅ Found {client_count} client(s)")

        return jsonify(result)

    except requests.Timeout as e:
        logger.error(f"❌ [INTAKEQ API TIMEOUT] {str(e)}")
        return jsonify({"error": "IntakeQ API request timed out"}), 504
    except requests.ConnectionError as e:
        logger.error(f"❌ [INTAKEQ CONNECTION ERROR] {str(e)}")
        return jsonify({"error": "Failed to connect to IntakeQ API"}), 502
    except requests.RequestException as e:
        logger.error(f"❌ [INTAKEQ API REQUEST ERROR] {str(e)}")
        return jsonify({"error": f"Network error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"❌ [INTAKEQ CLIENT LOOKUP ERROR] {str(e)}")
        return jsonify({"error": str(e)}), 500


@intakeq_forms_bp.route("/intakeq_forms/mandatory_form", methods=["POST"])
def send_mandatory_form():
    """Send mandatory form to client via IntakeQ"""
    try:
        data = request.get_json() or {}

        logger.info("=== SENDING MANDATORY INTAKEQ FORM ===")
        logger.info(f"Request data: {data}")

        # Validate required fields

        # Check payment type
        payment_type = data.get("payment_type", "cash_pay")
        if payment_type not in ["cash_pay", "insurance"]:
            return (
                jsonify({"error": "payment_type must be 'cash_pay' or 'insurance'"}),
                400,
            )

        # Must have either client_id OR (client_name AND client_email)
        has_client_id = bool(data.get("client_id"))
        has_client_info = bool(data.get("client_name")) and bool(
            data.get("client_email")
        )

        if not has_client_id and not has_client_info:
            return (
                jsonify(
                    {
                        "error": "Either client_id OR both client_name and client_email are required"
                    }
                ),
                400,
            )

        # Get appropriate API key and form ID based on payment type and state
        if payment_type == "cash_pay":
            intakeq_api_key = os.getenv("CASH_PAY_INTAKEQ_API_KEY")
            mandatory_form_id = os.getenv("CASH_PAY_MANDATORY_FORM_ID")
        else:  # insurance
            # Get state from data for state-specific API key AND form ID
            client_state = data.get("state", "")
            from src.utils.intakeq.state_config import get_insurance_intakeq_config

            # Get state-specific API key
            intakeq_api_key = get_insurance_intakeq_config(client_state, 'api_key')
            if not intakeq_api_key:
                # Fallback to generic insurance key
                intakeq_api_key = os.getenv("INSURANCE_INTAKEQ_API_KEY")

            # CRITICAL: Get state-specific mandatory form ID
            # Each IntakeQ account (NJ/NY) has its own forms
            mandatory_form_id = get_insurance_intakeq_config(client_state, 'mandatory_form_id')
            if not mandatory_form_id:
                # Fallback to generic form ID
                logger.warning(f"⚠️ No state-specific mandatory form ID for {client_state}, using generic")
                mandatory_form_id = os.getenv("INSURANCE_MANDATORY_FORM_ID")

        if not intakeq_api_key:
            error_msg = f"Missing IntakeQ API key for payment type: {payment_type}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        if not mandatory_form_id:
            error_msg = f"Missing mandatory form ID for payment type: {payment_type}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 500

        logger.info(
            f"🔑 Using API key for: {payment_type} (length: {len(intakeq_api_key)})"
        )
        logger.info(f"📋 Using form ID: {mandatory_form_id}")

        # Build IntakeQ payload
        intakeq_payload = {
            "QuestionnaireId": mandatory_form_id,
        }

        # Add client identification
        if has_client_id:
            intakeq_payload["ClientId"] = data["client_id"]
            logger.info(f"👤 Using ClientId: {data['client_id']}")
        else:
            intakeq_payload["ClientName"] = data["client_name"]
            intakeq_payload["ClientEmail"] = data["client_email"]
            logger.info(
                f"👤 Using ClientName: {data['client_name']} ({data['client_email']})"
            )

        # Add practitioner ID if provided
        if data.get("practitioner_id"):
            intakeq_payload["PractitionerId"] = data["practitioner_id"]
            logger.info(f"👨‍⚕️ PractitionerId: {data['practitioner_id']}")
        elif data.get("therapist_email"):
            # If no practitioner_id but we have therapist_email, log it for reference
            logger.info(
                f"👨‍⚕️ Therapist Email (no PractitionerId): {data['therapist_email']}"
            )

        # Add phone for SMS option (normalize to strip +1 prefix)
        if data.get("client_phone"):
            intakeq_payload["ClientPhone"] = normalize_phone_number(data["client_phone"])

        # Add external client ID if provided
        if data.get("external_client_id"):
            intakeq_payload["ExternalClientId"] = data["external_client_id"]

        logger.info(f"📤 Sending payload to IntakeQ: {intakeq_payload}")

        # Call IntakeQ API
        headers = {
            "X-Auth-Key": intakeq_api_key,
            "Content-Type": "application/json",
        }

        intakeq_response = requests.post(
            "https://intakeq.com/api/v1/intakes/send",
            headers=headers,
            json=intakeq_payload,
            timeout=60,
        )

        logger.info(f"📥 IntakeQ Response Status: {intakeq_response.status_code}")

        if not intakeq_response.ok:
            error_text = intakeq_response.text
            logger.error(
                f"❌ IntakeQ API Error: {intakeq_response.status_code} - {error_text}"
            )

            try:
                error_json = intakeq_response.json()
                logger.error(f"Error details: {json.dumps(error_json, indent=2)}")
                error_msg = f"IntakeQ API error: {intakeq_response.status_code} - {error_json.get('message', error_text)}"
            except (json.JSONDecodeError, ValueError):
                error_msg = (
                    f"IntakeQ API error: {intakeq_response.status_code} - {error_text}"
                )

            return jsonify({"error": error_msg}), 500

        try:
            result = intakeq_response.json()
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse IntakeQ response as JSON: {e}")
            return jsonify({"error": "Invalid JSON response from IntakeQ"}), 500

        # Extract intake information
        intake_id = result.get("Id") or result.get("id")
        intake_url = result.get("Url") or result.get("url")
        client_id = result.get("ClientId") or result.get("clientId")
        questionnaire_id = result.get("QuestionnaireId") or result.get(
            "questionnaireId"
        )

        logger.info(f"✅ Mandatory form sent successfully!")
        logger.info(f"📋 Intake ID: {intake_id}")
        logger.info(f"🔗 Intake URL: {intake_url}")
        logger.info(f"👤 Client ID: {client_id}")

        # Update Google Sheets with mandatory form data if available
        if sheets_logger and sheets_logger.enabled and data.get("response_id"):
            try:
                mandatory_form_data = {
                    "response_id": data.get("response_id"),
                    "mandatory_form_sent": True,
                    "mandatory_form_intake_id": intake_id,
                    "mandatory_form_intake_url": intake_url,
                    "mandatory_form_sent_at": datetime.utcnow().isoformat(),
                    "payment_type": payment_type,
                }

                logger.info(f"  📊 Updating Google Sheets with mandatory form data...")
                logger.info(f"  📊 Data: {mandatory_form_data}")
                # Note: This would need a separate update method in the sheets service
                # For now, we just log the data point
                logger.info(
                    f"  ✅ Mandatory form data logged for response_id: {data.get('response_id')}"
                )
            except Exception as e:
                logger.error(f"  ❌ Mandatory form Google Sheets update error: {e}")

        # Note: Journey completion tracking now handled by progressive logger
        if data.get("response_id"):
            logger.info(f"  ✅ Form sent for response_id: {data.get('response_id')}")
        else:
            logger.warning("No response_id provided for journey completion tracking")

        logger.info("=====================================")

        return jsonify(
            {
                "success": True,
                "intake_id": intake_id,
                "intake_url": intake_url,
                "client_id": client_id,
                "questionnaire_id": questionnaire_id,
                "intakeq_response": result,
            }
        )

    except requests.Timeout as e:
        logger.error(f"❌ [INTAKEQ FORM SEND TIMEOUT] {str(e)}")
        return jsonify({"error": "IntakeQ API request timed out"}), 504
    except requests.ConnectionError as e:
        logger.error(f"❌ [INTAKEQ FORM SEND CONNECTION ERROR] {str(e)}")
        return jsonify({"error": "Failed to connect to IntakeQ API"}), 502
    except requests.RequestException as e:
        logger.error(f"❌ [INTAKEQ FORM SEND REQUEST ERROR] {str(e)}")
        return jsonify({"error": f"Network error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"❌ [INTAKEQ FORM SEND ERROR] {str(e)}")
        return jsonify({"error": str(e)}), 500
