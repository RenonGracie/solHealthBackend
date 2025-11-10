"""
Comprehensive Data Logger for Sol Health

Ensures ALL demographic, address, and insurance information is logged to:
1. Google Sheets (progressive logging)
2. IntakeQ profile creation

This module provides verification and enhancement functions to guarantee
no data is lost and everything is properly mapped.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

logger = logging.getLogger(__name__)


class ComprehensiveDataLogger:
    """
    Ensures comprehensive data logging to both Google Sheets and IntakeQ.
    
    Provides verification, enhancement, and audit capabilities to guarantee
    ALL available data is captured and logged appropriately.
    """
    
    # Master list of ALL possible data fields from Nirvana and user input
    ALL_DEMOGRAPHIC_FIELDS = {
        # Basic Demographics
        "first_name", "last_name", "middle_name", "preferred_name", "full_name",
        "email", "phone", "mobile_phone", "home_phone", "work_phone",
        "date_of_birth", "dob", "age", "gender", "marital_status",
        
        # Address Information
        "street_address", "street_line_1", "street_line_2", "address_line_1", "address_line_2",
        "city", "state", "postal_code", "zip_code", "zip", "country",
        "unit_number", "apt", "apartment", "suite",
        
        # Enhanced Demographics
        "race_ethnicity", "lived_experiences", "university", "referred_by",
        "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
        
        # Nirvana Enhanced Address
        "nirvana_street_line_1", "nirvana_street_line_2", "nirvana_city", 
        "nirvana_state", "nirvana_zip", "nirvana_country",
        
        # Nirvana Demographics
        "nirvana_first_name", "nirvana_last_name", "nirvana_dob", "nirvana_gender",
        "nirvana_member_id", "nirvana_phone",
    }
    
    ALL_INSURANCE_FIELDS = {
        # Basic Insurance
        "payment_type", "insurance_provider", "insurance_member_id", 
        "insurance_date_of_birth", "insurance_phone", "group_number",
        
        # Nirvana Insurance Details
        "plan_name", "plan_status", "coverage_status", "mental_health_coverage",
        "insurance_type", "group_id", "payer_id", "relationship_to_subscriber",
        "benefit_structure", "plan_begin_date", "plan_end_date", "eligibility_end_date",
        
        # Financial Information
        "copay", "copayment", "coinsurance", "deductible", "remaining_deductible",
        "out_of_pocket_max", "oop_max", "remaining_oop_max", 
        "member_obligation", "payer_obligation", "session_cost_dollars",
        "pre_deductible_member_obligation", "post_deductible_member_obligation",
        "sessions_before_deductible_met", "sessions_before_oop_max_met",
        
        # Telehealth Specific
        "telehealth_copay", "telehealth_coinsurance", "telehealth_benefit_structure",
        "telehealth_member_obligation",
        
        # Insurance Provider Correction
        "insurance_provider_original", "insurance_provider_corrected",
        "insurance_provider_was_corrected", "insurance_provider_correction_type",
        "insurance_provider_validation_status",
    }
    
    ALL_SUBSCRIBER_FIELDS = {
        # Subscriber Demographics (for family plans)
        "subscriber_first_name", "subscriber_last_name", "subscriber_dob", 
        "subscriber_gender", "subscriber_member_id", "subscriber_phone",
        "subscriber_street_address", "subscriber_city", "subscriber_state", 
        "subscriber_zip", "subscriber_country",
        
        # Nirvana Subscriber Details
        "nirvana_subscriber_first_name", "nirvana_subscriber_last_name",
        "nirvana_subscriber_dob", "nirvana_subscriber_gender",
        "nirvana_subscriber_street_line_1", "nirvana_subscriber_street_line_2",
        "nirvana_subscriber_city", "nirvana_subscriber_state", "nirvana_subscriber_zip",
        
        # Policyholder Information
        "nirvana_policyholder_name", "nirvana_policyholder_first_name",
        "nirvana_policyholder_last_name", "nirvana_policyholder_relationship",
        "nirvana_policyholder_street_address", "nirvana_policyholder_city",
        "nirvana_policyholder_state", "nirvana_policyholder_zip_code",
        "nirvana_policyholder_date_of_birth", "nirvana_policyholder_sex",
    }
    
    ALL_ASSESSMENT_FIELDS = {
        # PHQ-9 Assessment
        "phq9_scores", "phq9_total_score",
        "phq9_pleasure_doing_things", "phq9_feeling_down", "phq9_trouble_falling",
        "phq9_feeling_tired", "phq9_poor_appetite", "phq9_feeling_bad_about_yourself",
        "phq9_trouble_concentrating", "phq9_moving_or_speaking_so_slowly", "phq9_suicidal_thoughts",
        
        # GAD-7 Assessment
        "gad7_scores", "gad7_total_score",
        "gad7_feeling_nervous", "gad7_not_control_worrying", "gad7_worrying_too_much",
        "gad7_trouble_relaxing", "gad7_being_so_restless", "gad7_easily_annoyed", "gad7_feeling_afraid",
        
        # Additional Assessments
        "alcohol_frequency", "recreational_drugs_frequency", "safety_screening",
        "what_brings_you", "matching_preference",
    }
    
    ALL_THERAPY_FIELDS = {
        # Therapist Preferences
        "therapist_gender_preference", "therapist_specialization", "therapist_lived_experiences",
        "therapist_specializes_in",
        
        # Matched Therapist
        "matched_therapist_id", "matched_therapist_name", "matched_therapist_email",
        "match_score", "matched_specialties", "therapist_confirmed",
        "therapist_confirmation_timestamp", "alternative_therapists_offered",
    }
    
    ALL_TRACKING_FIELDS = {
        # Journey Tracking
        "response_id", "journey_id", "stage_completed", "stage_0_timestamp",
        "stage_1_timestamp", "stage_2_timestamp", "stage_3_timestamp", "last_updated",
        
        # UTM and Tracking
        "utm_source", "utm_medium", "utm_campaign", "signup_timestamp",
        "completion_timestamp", "user_agent", "ip_address",
        "onboarding_completed_at", "survey_completed_at",
        
        # System Metadata
        "environment", "api_version", "frontend_version", "created_at", "updated_at",
        "sol_health_response_id",
    }
    
    @classmethod
    def get_all_possible_fields(cls) -> Set[str]:
        """Get set of ALL possible fields that should be captured"""
        return (
            cls.ALL_DEMOGRAPHIC_FIELDS | 
            cls.ALL_INSURANCE_FIELDS | 
            cls.ALL_SUBSCRIBER_FIELDS |
            cls.ALL_ASSESSMENT_FIELDS |
            cls.ALL_THERAPY_FIELDS |
            cls.ALL_TRACKING_FIELDS
        )
    
    @classmethod
    def extract_all_available_data(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract ALL available data from any payload source.
        
        This function ensures NOTHING is missed by checking all possible
        field names and data structures.
        """
        logger.info("🔍 [COMPREHENSIVE DATA EXTRACTION] Starting exhaustive data capture")
        
        extracted_data = {
            "_extraction_timestamp": datetime.utcnow().isoformat(),
            "_data_sources_found": [],
            "_fields_extracted": 0
        }
        
        # 1. Direct field extraction
        all_possible_fields = cls.get_all_possible_fields()
        
        for field in all_possible_fields:
            if field in payload:
                extracted_data[field] = payload[field]
                extracted_data["_fields_extracted"] += 1
        
        # 2. Nested Nirvana data extraction
        nirvana_sources = [
            "nirvana_data", "nirvana_raw_response", "insurance_verification_data",
            "nirvana_response", "rawNirvanaResponse"
        ]
        
        for source in nirvana_sources:
            nirvana_data = payload.get(source)
            if nirvana_data:
                extracted_data["_data_sources_found"].append(source)
                
                # Parse JSON string if needed
                if isinstance(nirvana_data, str):
                    try:
                        nirvana_data = json.loads(nirvana_data)
                    except json.JSONDecodeError:
                        continue
                
                if isinstance(nirvana_data, dict):
                    # Extract from root level
                    for field in all_possible_fields:
                        if field in nirvana_data and field not in extracted_data:
                            extracted_data[field] = nirvana_data[field]
                            extracted_data["_fields_extracted"] += 1
                    
                    # Extract from demographics section
                    demographics = nirvana_data.get("demographics", {})
                    if demographics:
                        extracted_data["_data_sources_found"].append("nirvana_demographics")
                        for field, value in demographics.items():
                            nirvana_field = f"nirvana_{field}"
                            if nirvana_field not in extracted_data:
                                extracted_data[nirvana_field] = value
                                extracted_data["_fields_extracted"] += 1
                            
                            # Also store with original field name if not present
                            if field not in extracted_data:
                                extracted_data[field] = value
                                extracted_data["_fields_extracted"] += 1
                        
                        # Extract nested address
                        address = demographics.get("address", {})
                        if address:
                            for addr_field, value in address.items():
                                nirvana_addr_field = f"nirvana_{addr_field}"
                                if nirvana_addr_field not in extracted_data:
                                    extracted_data[nirvana_addr_field] = value
                                    extracted_data["_fields_extracted"] += 1

                                # Also extract to top-level if not present (e.g., country)
                                if addr_field not in extracted_data and value:
                                    extracted_data[addr_field] = value
                                    extracted_data["_fields_extracted"] += 1
                    
                    # Extract from subscriber_demographics section
                    subscriber_demo = nirvana_data.get("subscriber_demographics", {})
                    if subscriber_demo:
                        extracted_data["_data_sources_found"].append("nirvana_subscriber_demographics")
                        for field, value in subscriber_demo.items():
                            subscriber_field = f"subscriber_{field}"
                            nirvana_subscriber_field = f"nirvana_subscriber_{field}"
                            
                            if subscriber_field not in extracted_data:
                                extracted_data[subscriber_field] = value
                                extracted_data["_fields_extracted"] += 1
                            if nirvana_subscriber_field not in extracted_data:
                                extracted_data[nirvana_subscriber_field] = value
                                extracted_data["_fields_extracted"] += 1
                        
                        # Extract subscriber address
                        subscriber_address = subscriber_demo.get("address", {})
                        if subscriber_address:
                            for addr_field, value in subscriber_address.items():
                                subscriber_addr_field = f"subscriber_{addr_field}"
                                nirvana_subscriber_addr_field = f"nirvana_subscriber_{addr_field}"
                                
                                if subscriber_addr_field not in extracted_data:
                                    extracted_data[subscriber_addr_field] = value
                                    extracted_data["_fields_extracted"] += 1
                                if nirvana_subscriber_addr_field not in extracted_data:
                                    extracted_data[nirvana_subscriber_addr_field] = value
                                    extracted_data["_fields_extracted"] += 1
                    
                    # Extract telehealth data
                    telehealth = nirvana_data.get("telehealth", {})
                    if telehealth:
                        extracted_data["_data_sources_found"].append("nirvana_telehealth")
                        for field, value in telehealth.items():
                            telehealth_field = f"telehealth_{field}"
                            if telehealth_field not in extracted_data:
                                extracted_data[telehealth_field] = value
                                extracted_data["_fields_extracted"] += 1
                
                # CRITICAL: Store raw Nirvana data for reference AND as nirvana_data
                # Google Sheets logger expects nested structure at data["nirvana_data"]
                extracted_data["nirvana_raw_data"] = nirvana_data
                extracted_data["nirvana_data"] = nirvana_data  # Preserve nested structure
                break  # Use first available Nirvana source
        
        # 3. Extract from nested client_data, survey_data, etc.
        nested_sources = [
            "client_data", "survey_data", "assessment_data", "user_data",
            "response_data", "form_data", "intake_data"
        ]
        
        for source in nested_sources:
            nested_data = payload.get(source)
            if nested_data and isinstance(nested_data, dict):
                extracted_data["_data_sources_found"].append(source)
                
                for field in all_possible_fields:
                    if field in nested_data and field not in extracted_data:
                        extracted_data[field] = nested_data[field]
                        extracted_data["_fields_extracted"] += 1
        
        # 4. Data conversion and standardization
        cls._standardize_extracted_data(extracted_data)
        
        logger.info(f"✅ [COMPREHENSIVE EXTRACTION] Extracted {extracted_data['_fields_extracted']} fields")
        logger.info(f"📊 Data sources used: {extracted_data['_data_sources_found']}")
        
        return extracted_data
    
    @classmethod
    def _standardize_extracted_data(cls, data: Dict[str, Any]) -> None:
        """Standardize and convert data types for consistency"""
        
        # Convert financial fields from cents to dollars
        financial_fields = [
            "copay", "copayment", "deductible", "remaining_deductible",
            "out_of_pocket_max", "oop_max", "remaining_oop_max",
            "member_obligation", "payer_obligation", "session_cost_dollars"
        ]
        
        for field in financial_fields:
            value = data.get(field)
            if value is not None and isinstance(value, int) and value > 100:
                # Assume values > 100 are in cents
                data[f"{field}_dollars"] = round(value / 100, 2)
                data[field] = value  # Keep original for reference
        
        # Standardize date formats
        date_fields = [
            "date_of_birth", "dob", "insurance_date_of_birth",
            "nirvana_dob", "subscriber_dob", "nirvana_subscriber_dob",
            "nirvana_policyholder_date_of_birth"
        ]
        
        for field in date_fields:
            if field in data and data[field]:
                # Ensure consistent date format (leave as-is, IntakeQ handles conversion)
                pass
        
        # Standardize insurance provider names (title case)
        insurance_name_fields = [
            "insurance_provider", "plan_name", "nirvana_plan_name"
        ]
        
        for field in insurance_name_fields:
            if field in data and isinstance(data[field], str) and data[field].isupper():
                data[field] = data[field].title()
    
    @classmethod
    def verify_google_sheets_mapping(cls, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify that extracted data will be properly logged to Google Sheets.
        
        Returns verification report with any missing mappings.
        """
        logger.info("🔍 [GOOGLE SHEETS VERIFICATION] Checking data mapping completeness")
        
        # Import the Google Sheets logger to get current headers
        try:
            from ..services.google_sheets_progressive_logger import GoogleSheetsProgressiveLogger
            sheets_logger = GoogleSheetsProgressiveLogger()
            current_headers = set(sheets_logger._get_comprehensive_headers())
        except ImportError:
            logger.warning("Could not import Google Sheets logger for verification")
            return {"error": "Could not verify Google Sheets mapping"}
        
        verification_report = {
            "total_extracted_fields": len([k for k in extracted_data.keys() if not k.startswith("_")]),
            "google_sheets_headers": len(current_headers),
            "fields_will_be_logged": 0,
            "fields_missing_from_sheets": [],
            "critical_fields_status": {},
            "recommendations": []
        }
        
        # Check which extracted fields will be logged
        logged_fields = []
        missing_fields = []
        
        for field, value in extracted_data.items():
            if not field.startswith("_") and value is not None:
                if field in current_headers:
                    logged_fields.append(field)
                    verification_report["fields_will_be_logged"] += 1
                else:
                    missing_fields.append(field)
        
        verification_report["fields_missing_from_sheets"] = missing_fields
        
        # Check critical field categories
        critical_categories = {
            "demographics": ["first_name", "last_name", "email", "phone", "date_of_birth"],
            "address": ["street_address", "city", "state", "postal_code"],
            "insurance": ["insurance_provider", "plan_name", "member_obligation", "copay"],
            "nirvana_demographics": ["nirvana_first_name", "nirvana_last_name", "nirvana_dob"],
            "nirvana_address": ["nirvana_street_line_1", "nirvana_city", "nirvana_state"],
            "financial": ["copay", "deductible", "member_obligation", "benefit_structure"]
        }
        
        for category, fields in critical_categories.items():
            category_status = {
                "total_fields": len(fields),
                "available_in_data": 0,
                "will_be_logged": 0,
                "missing_from_sheets": []
            }
            
            for field in fields:
                if field in extracted_data and extracted_data[field] is not None:
                    category_status["available_in_data"] += 1
                    if field in current_headers:
                        category_status["will_be_logged"] += 1
                    else:
                        category_status["missing_from_sheets"].append(field)
            
            verification_report["critical_fields_status"][category] = category_status
        
        # Generate recommendations
        if missing_fields:
            verification_report["recommendations"].append(
                f"Add {len(missing_fields)} missing fields to Google Sheets headers"
            )
        
        total_critical_missing = sum(
            len(status["missing_from_sheets"]) 
            for status in verification_report["critical_fields_status"].values()
        )
        
        if total_critical_missing > 0:
            verification_report["recommendations"].append(
                f"Priority: Add {total_critical_missing} critical fields to ensure complete logging"
            )
        
        logger.info(f"📊 Will log {verification_report['fields_will_be_logged']} fields to Google Sheets")
        if missing_fields:
            logger.warning(f"⚠️ {len(missing_fields)} fields may not be logged to Google Sheets")
            logger.info(f"Missing fields: {missing_fields[:10]}{'...' if len(missing_fields) > 10 else ''}")
        
        return verification_report
    
    @classmethod 
    def verify_intakeq_mapping(cls, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify that extracted data will be properly mapped to IntakeQ profile.
        
        Returns verification report with mapping completeness.
        """
        logger.info("🔍 [INTAKEQ VERIFICATION] Checking IntakeQ mapping completeness")
        
        verification_report = {
            "total_extracted_fields": len([k for k in extracted_data.keys() if not k.startswith("_")]),
            "intakeq_mappings_available": 0,
            "critical_intakeq_fields": {},
            "custom_fields_will_be_created": 0,
            "recommendations": []
        }
        
        # Critical IntakeQ fields mapping
        critical_intakeq_mappings = {
            "Name": ["first_name", "last_name"],
            "FirstName": ["first_name", "nirvana_first_name"],
            "LastName": ["last_name", "nirvana_last_name"],
            "Email": ["email"],
            "Phone": ["phone", "mobile_phone"],
            "DateOfBirth": ["date_of_birth", "dob", "nirvana_dob"],
            "Gender": ["gender", "nirvana_gender"],
            "Address/StreetAddress": ["street_address", "nirvana_street_line_1"],
            "City": ["city", "nirvana_city"],
            "StateShort": ["state", "nirvana_state"],
            "PostalCode": ["postal_code", "zip", "nirvana_zip"],
            "PrimaryInsuranceCompany": ["insurance_provider", "plan_name", "nirvana_plan_name"],
            "PrimaryInsurancePolicyNumber": ["insurance_member_id", "nirvana_member_id"]
        }
        
        for intakeq_field, source_fields in critical_intakeq_mappings.items():
            field_status = {
                "intakeq_field": intakeq_field,
                "source_options": source_fields,
                "available_sources": [],
                "will_be_mapped": False
            }
            
            for source_field in source_fields:
                if source_field in extracted_data and extracted_data[source_field] is not None:
                    field_status["available_sources"].append(source_field)
                    field_status["will_be_mapped"] = True
                    verification_report["intakeq_mappings_available"] += 1
                    break  # Use first available source
            
            verification_report["critical_intakeq_fields"][intakeq_field] = field_status
        
        # Count custom fields that will be created
        insurance_custom_fields = [
            "copay", "coinsurance", "remaining_deductible", "total_deductible",
            "remaining_oop_max", "oop_max", "member_obligation", "payer_obligation",
            "insurance_type", "benefit_structure", "plan_status", "coverage_status"
        ]
        
        for field in insurance_custom_fields:
            if field in extracted_data and extracted_data[field] is not None:
                verification_report["custom_fields_will_be_created"] += 1
        
        # Generate recommendations
        unmapped_critical = [
            field for field, status in verification_report["critical_intakeq_fields"].items()
            if not status["will_be_mapped"]
        ]
        
        if unmapped_critical:
            verification_report["recommendations"].append(
                f"Missing data for critical IntakeQ fields: {unmapped_critical}"
            )
        
        logger.info(f"✅ {verification_report['intakeq_mappings_available']} critical IntakeQ fields will be mapped")
        logger.info(f"🔧 {verification_report['custom_fields_will_be_created']} custom fields will be created")
        
        if unmapped_critical:
            logger.warning(f"⚠️ Missing data for: {unmapped_critical}")
        
        return verification_report
    
    @classmethod
    def generate_comprehensive_logging_report(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a comprehensive report on data logging completeness.
        
        This function provides a complete audit of what will be logged where.
        """
        logger.info("📊 [COMPREHENSIVE LOGGING REPORT] Generating complete data audit")
        
        # Extract all available data
        extracted_data = cls.extract_all_available_data(payload)
        
        # Verify Google Sheets mapping
        sheets_verification = cls.verify_google_sheets_mapping(extracted_data)
        
        # Verify IntakeQ mapping  
        intakeq_verification = cls.verify_intakeq_mapping(extracted_data)
        
        comprehensive_report = {
            "audit_timestamp": datetime.utcnow().isoformat(),
            "total_fields_extracted": extracted_data["_fields_extracted"],
            "data_sources_found": extracted_data["_data_sources_found"],
            
            "google_sheets_logging": sheets_verification,
            "intakeq_mapping": intakeq_verification,
            
            "overall_completeness": {
                "fields_available": extracted_data["_fields_extracted"],
                "will_log_to_sheets": sheets_verification["fields_will_be_logged"],
                "will_map_to_intakeq": intakeq_verification["intakeq_mappings_available"],
                "sheets_completeness_pct": round(
                    (sheets_verification["fields_will_be_logged"] / max(extracted_data["_fields_extracted"], 1)) * 100, 1
                ),
                "intakeq_completeness_pct": round(
                    (intakeq_verification["intakeq_mappings_available"] / len(intakeq_verification["critical_intakeq_fields"])) * 100, 1
                )
            },
            
            "recommendations": (
                sheets_verification.get("recommendations", []) +
                intakeq_verification.get("recommendations", [])
            ),
            
            "_extracted_data_sample": {
                k: v for k, v in list(extracted_data.items())[:20] 
                if not k.startswith("_")
            }
        }
        
        logger.info(f"📊 COMPREHENSIVE REPORT SUMMARY:")
        logger.info(f"  Fields extracted: {comprehensive_report['total_fields_extracted']}")
        logger.info(f"  Google Sheets completeness: {comprehensive_report['overall_completeness']['sheets_completeness_pct']}%")
        logger.info(f"  IntakeQ completeness: {comprehensive_report['overall_completeness']['intakeq_completeness_pct']}%")
        
        if comprehensive_report["recommendations"]:
            logger.info(f"  Recommendations: {len(comprehensive_report['recommendations'])}")
            for i, rec in enumerate(comprehensive_report["recommendations"][:3], 1):
                logger.info(f"    {i}. {rec}")
        
        return comprehensive_report


def ensure_comprehensive_logging(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to ensure comprehensive logging to both Google Sheets and IntakeQ.
    
    This function should be called before any logging operations to guarantee
    ALL available data is captured and properly mapped.
    
    Args:
        payload: Raw data payload from any source
        
    Returns:
        Enhanced payload with comprehensive data extraction and logging report
    """
    logger.info("🚀 [ENSURE COMPREHENSIVE LOGGING] Starting comprehensive data capture")
    
    # Extract all available data
    comprehensive_data = ComprehensiveDataLogger.extract_all_available_data(payload)
    
    # Generate logging report
    logging_report = ComprehensiveDataLogger.generate_comprehensive_logging_report(payload)
    
    # Merge with original payload, prioritizing comprehensive extraction
    enhanced_payload = {**payload, **comprehensive_data}
    
    # Add logging report for debugging
    enhanced_payload["_comprehensive_logging_report"] = logging_report
    
    logger.info("✅ [COMPREHENSIVE LOGGING] Enhancement complete")
    logger.info(f"📊 Enhanced payload with {comprehensive_data['_fields_extracted']} additional fields")

    return enhanced_payload


def validate_nirvana_data_structure(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that incoming Nirvana data matches the expected structure.

    This function checks if the Nirvana data is in the correct format for
    Google Sheets logging and warns about any structural mismatches.

    Args:
        payload: Incoming data from Nirvana callback

    Returns:
        Validation report with warnings and recommendations
    """
    logger.info("🔍 [NIRVANA VALIDATION] Validating Nirvana data structure")

    validation_report = {
        "nirvana_data_found": False,
        "nirvana_location": None,
        "expected_structure_present": True,
        "missing_sections": [],
        "warnings": [],
        "recommendations": []
    }

    # Check where Nirvana data is located
    nirvana_keys = ["nirvana_data", "nirvana_response", "nirvana_raw_response",
                    "insurance_verification_data", "rawNirvanaResponse"]

    for key in nirvana_keys:
        if key in payload:
            validation_report["nirvana_data_found"] = True
            validation_report["nirvana_location"] = key
            nirvana_data = payload[key]

            # Parse if string
            if isinstance(nirvana_data, str):
                try:
                    import json
                    nirvana_data = json.loads(nirvana_data)
                except json.JSONDecodeError:
                    validation_report["warnings"].append(
                        f"Nirvana data at '{key}' is a string but cannot be parsed as JSON"
                    )
                    validation_report["expected_structure_present"] = False
                    continue

            if isinstance(nirvana_data, dict):
                # Check expected sections
                expected_sections = {
                    "plan_name": "Insurance plan name",
                    "group_id": "Insurance group ID",
                    "payer_id": "Payer ID",
                    "demographics": "Member demographics (nested)",
                    "subscriber_demographics": "Subscriber demographics (nested)"
                }

                for section, description in expected_sections.items():
                    if section not in nirvana_data:
                        validation_report["missing_sections"].append(f"{section} ({description})")

                # Validate nested demographics structure
                if "demographics" in nirvana_data:
                    demographics = nirvana_data["demographics"]
                    if not isinstance(demographics, dict):
                        validation_report["warnings"].append(
                            "demographics is not a dict - expected nested structure"
                        )
                    elif "address" not in demographics:
                        validation_report["warnings"].append(
                            "demographics.address is missing"
                        )

                # Validate nested subscriber_demographics structure
                if "subscriber_demographics" in nirvana_data:
                    sub_demo = nirvana_data["subscriber_demographics"]
                    if not isinstance(sub_demo, dict):
                        validation_report["warnings"].append(
                            "subscriber_demographics is not a dict - expected nested structure"
                        )
                    elif "address" not in sub_demo:
                        validation_report["warnings"].append(
                            "subscriber_demographics.address is missing"
                        )

            break

    # Generate recommendations
    if not validation_report["nirvana_data_found"]:
        validation_report["recommendations"].append(
            "❌ CRITICAL: No Nirvana data found in payload. Expected one of: " + ", ".join(nirvana_keys)
        )
        logger.error("❌ [NIRVANA VALIDATION] No Nirvana data found in payload")

    if validation_report["missing_sections"]:
        validation_report["recommendations"].append(
            f"⚠️ Missing {len(validation_report['missing_sections'])} expected sections: " +
            ", ".join(validation_report["missing_sections"])
        )
        logger.warning(f"⚠️ [NIRVANA VALIDATION] Missing sections: {validation_report['missing_sections']}")

    if validation_report["warnings"]:
        validation_report["recommendations"].append(
            f"⚠️ {len(validation_report['warnings'])} structural warnings detected"
        )
        for warning in validation_report["warnings"]:
            logger.warning(f"⚠️ [NIRVANA VALIDATION] {warning}")

    if not validation_report["missing_sections"] and not validation_report["warnings"] and validation_report["nirvana_data_found"]:
        validation_report["recommendations"].append(
            "✅ Nirvana data structure is valid and complete"
        )
        logger.info("✅ [NIRVANA VALIDATION] Nirvana data structure is valid")

    return validation_report