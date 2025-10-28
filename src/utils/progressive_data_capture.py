"""
Progressive Data Capture Utility

This module ensures comprehensive data capture and logging throughout the user journey,
particularly for demographics, address, and insurance information from Nirvana responses.

Key Features:
- Stage 0: Immediate Nirvana data logging (demographics + insurance)
- Enhanced data extraction from multiple sources
- Comprehensive data validation and completeness checking
- Automatic fallback to ensure no data loss
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ProgressiveDataCapture:
    """
    Utility class for comprehensive progressive data capture and validation.
    
    Ensures that demographics, address, and insurance information is properly
    captured and logged at every stage of the user journey.
    """

    @staticmethod
    def extract_comprehensive_user_data(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract comprehensive user data from any payload, prioritizing the most
        complete and accurate sources.
        
        Args:
            payload: Raw payload from Lambda, frontend, or API
            
        Returns:
            Dict with comprehensive user data for immediate logging
        """
        logger.info("📋 Extracting comprehensive user data for progressive capture")
        
        # Initialize comprehensive data dictionary
        comprehensive_data = {
            "capture_timestamp": datetime.utcnow().isoformat(),
            "data_sources_used": []
        }
        
        # 1. BASIC DEMOGRAPHICS (highest priority)
        demographics_sources = [
            ("response_data", "Response data from frontend"),
            ("client_data", "Client data from survey"),
            ("user_data", "User data from form"),
            ("nirvana_data.demographics", "Nirvana verified demographics")
        ]
        
        for source, description in demographics_sources:
            source_data = ProgressiveDataCapture._extract_nested_data(payload, source)
            if source_data:
                comprehensive_data["data_sources_used"].append(description)
                # Extract basic demographics
                comprehensive_data.update({
                    "first_name": source_data.get("first_name") or comprehensive_data.get("first_name"),
                    "last_name": source_data.get("last_name") or comprehensive_data.get("last_name"),
                    "preferred_name": source_data.get("preferred_name") or comprehensive_data.get("preferred_name"),
                    "middle_name": source_data.get("middle_name") or comprehensive_data.get("middle_name"),
                    "email": source_data.get("email") or comprehensive_data.get("email"),
                    "phone": source_data.get("phone") or comprehensive_data.get("phone"),
                    "date_of_birth": source_data.get("date_of_birth") or comprehensive_data.get("date_of_birth"),
                    "gender": source_data.get("gender") or comprehensive_data.get("gender"),
                    "age": source_data.get("age") or comprehensive_data.get("age"),
                    "marital_status": source_data.get("marital_status") or comprehensive_data.get("marital_status"),
                    "race_ethnicity": source_data.get("race_ethnicity") or comprehensive_data.get("race_ethnicity"),
                })
        
        # 2. ADDRESS INFORMATION (prioritize Nirvana verified > user input)
        address_sources = [
            ("nirvana_data.demographics.address", "Nirvana verified address"),
            ("address_data", "Direct address data"),
            ("client_data", "Client provided address"),
        ]
        
        for source, description in address_sources:
            source_data = ProgressiveDataCapture._extract_nested_data(payload, source)
            if source_data and any([
                source_data.get("street_line_1"),
                source_data.get("street_address"),
                source_data.get("city"),
                source_data.get("state")
            ]):
                if description not in comprehensive_data["data_sources_used"]:
                    comprehensive_data["data_sources_used"].append(description)
                    
                # Comprehensive address mapping
                comprehensive_data.update({
                    "street_address": source_data.get("street_line_1") or source_data.get("street_address") or comprehensive_data.get("street_address"),
                    "street_line_1": source_data.get("street_line_1") or comprehensive_data.get("street_line_1"),
                    "street_line_2": source_data.get("street_line_2") or comprehensive_data.get("street_line_2"),
                    "city": source_data.get("city") or comprehensive_data.get("city"),
                    "state": source_data.get("state") or comprehensive_data.get("state"),
                    "postal_code": source_data.get("zip") or source_data.get("postal_code") or comprehensive_data.get("postal_code"),
                    "country": source_data.get("country") or comprehensive_data.get("country", "USA"),
                })
                break  # Use first complete address source
        
        # 3. INSURANCE INFORMATION (pre-verification and post-verification)
        insurance_sources = [
            ("insurance_data", "Insurance form data"),
            ("client_data", "Client insurance info"),
            ("payment_data", "Payment processing data")
        ]
        
        for source, description in insurance_sources:
            source_data = ProgressiveDataCapture._extract_nested_data(payload, source)
            if source_data:
                if description not in comprehensive_data["data_sources_used"]:
                    comprehensive_data["data_sources_used"].append(description)
                    
                comprehensive_data.update({
                    "payment_type": source_data.get("payment_type") or comprehensive_data.get("payment_type"),
                    "insurance_provider": source_data.get("insurance_provider") or comprehensive_data.get("insurance_provider"),
                    "insurance_member_id": source_data.get("insurance_member_id") or comprehensive_data.get("insurance_member_id"),
                    "insurance_date_of_birth": source_data.get("insurance_date_of_birth") or comprehensive_data.get("insurance_date_of_birth"),
                })
        
        # 4. NIRVANA VERIFICATION DATA (post-verification)
        nirvana_response = ProgressiveDataCapture._extract_nirvana_data(payload)
        if nirvana_response:
            comprehensive_data["data_sources_used"].append("Nirvana insurance verification")
            comprehensive_data.update({
                "nirvana_data": nirvana_response,
                "nirvana_verification_status": "SUCCESS",
                "nirvana_verification_timestamp": datetime.utcnow().isoformat()
            })
            
            # Extract financial data immediately
            financial_data = ProgressiveDataCapture._extract_financial_from_nirvana(nirvana_response)
            comprehensive_data.update(financial_data)
        
        # 5. SURVEY AND ASSESSMENT DATA
        survey_sources = [
            ("survey_data", "Survey responses"),
            ("assessment_data", "Mental health assessments"),
            ("client_data", "Complete client data")
        ]
        
        for source, description in survey_sources:
            source_data = ProgressiveDataCapture._extract_nested_data(payload, source)
            if source_data:
                if description not in comprehensive_data["data_sources_used"]:
                    comprehensive_data["data_sources_used"].append(description)
                    
                # PHQ-9 and GAD-7 scores
                comprehensive_data.update({
                    "phq9_scores": source_data.get("phq9_scores") or comprehensive_data.get("phq9_scores"),
                    "phq9_total_score": source_data.get("phq9_total_score") or comprehensive_data.get("phq9_total_score"),
                    "gad7_scores": source_data.get("gad7_scores") or comprehensive_data.get("gad7_scores"),
                    "gad7_total_score": source_data.get("gad7_total_score") or comprehensive_data.get("gad7_total_score"),
                    "what_brings_you": source_data.get("what_brings_you") or comprehensive_data.get("what_brings_you"),
                    "therapist_specialization": source_data.get("therapist_specialization") or comprehensive_data.get("therapist_specialization"),
                    "therapist_gender_preference": source_data.get("therapist_gender_preference") or comprehensive_data.get("therapist_gender_preference"),
                })
        
        # 6. TRACKING AND METADATA
        tracking_sources = [
            ("tracking_data", "UTM and tracking info"),
            ("metadata", "Request metadata"),
            ("client_data", "Client tracking data")
        ]
        
        for source, description in tracking_sources:
            source_data = ProgressiveDataCapture._extract_nested_data(payload, source)
            if source_data:
                comprehensive_data.update({
                    "response_id": source_data.get("response_id") or comprehensive_data.get("response_id"),
                    "utm_source": source_data.get("utm_source") or comprehensive_data.get("utm_source"),
                    "utm_medium": source_data.get("utm_medium") or comprehensive_data.get("utm_medium"),
                    "utm_campaign": source_data.get("utm_campaign") or comprehensive_data.get("utm_campaign"),
                    "user_agent": source_data.get("user_agent") or comprehensive_data.get("user_agent"),
                    "ip_address": source_data.get("ip_address") or comprehensive_data.get("ip_address"),
                    "signup_timestamp": source_data.get("signup_timestamp") or comprehensive_data.get("signup_timestamp"),
                })
        
        # Log data completeness
        ProgressiveDataCapture._log_data_completeness(comprehensive_data)
        
        return comprehensive_data
    
    @staticmethod
    def _extract_nested_data(payload: Dict[str, Any], source_path: str) -> Optional[Dict[str, Any]]:
        """Extract nested data using dot notation (e.g., 'nirvana_data.demographics')"""
        try:
            keys = source_path.split('.')
            data = payload
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return None
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    
    @staticmethod
    def _extract_nirvana_data(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract Nirvana data from multiple possible locations in payload"""
        nirvana_fields = [
            "nirvana_data",
            "nirvana_raw_response", 
            "insurance_verification_data",
            "nirvana_response",
            "rawNirvanaResponse"
        ]
        
        for field in nirvana_fields:
            nirvana_data = payload.get(field)
            if nirvana_data:
                # Handle string JSON
                if isinstance(nirvana_data, str):
                    try:
                        import json
                        return json.loads(nirvana_data)
                    except json.JSONDecodeError:
                        continue
                elif isinstance(nirvana_data, dict):
                    return nirvana_data
        
        return None
    
    @staticmethod
    def _extract_financial_from_nirvana(nirvana_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract financial data from Nirvana response"""
        financial_data = {}
        
        # Direct financial fields
        financial_fields = [
            "copayment", "copay", "deductible", "coinsurance", 
            "out_of_pocket_max", "oop_max", "remaining_deductible", 
            "remaining_oop_max", "member_obligation", "payer_obligation",
            "benefit_structure", "session_cost_dollars", "payer_id"
        ]
        
        for field in financial_fields:
            value = nirvana_data.get(field)
            if value is not None:
                # Convert cents to dollars for display fields
                if field in ["copayment", "copay"] and isinstance(value, int):
                    financial_data["copay"] = round(value / 100, 2)
                elif field in ["deductible", "remaining_deductible", "oop_max", "remaining_oop_max", 
                              "member_obligation", "payer_obligation"] and isinstance(value, int):
                    financial_data[field] = round(value / 100, 2)
                else:
                    financial_data[field] = value
        
        # Insurance plan details
        plan_fields = [
            "plan_name", "plan_status", "coverage_status", "mental_health_coverage",
            "relationship_to_subscriber", "insurance_type", "group_id"
        ]
        
        for field in plan_fields:
            value = nirvana_data.get(field)
            if value:
                financial_data[field] = value
        
        return financial_data
    
    @staticmethod
    def _log_data_completeness(data: Dict[str, Any]) -> None:
        """Log the completeness of captured data for auditing"""
        logger.info("📊 [DATA COMPLETENESS AUDIT]")
        
        # Critical fields check
        critical_fields = [
            "first_name", "last_name", "email", "phone", 
            "street_address", "city", "state", "postal_code"
        ]
        
        populated_critical = sum(1 for field in critical_fields if data.get(field))
        logger.info(f"  Critical fields: {populated_critical}/{len(critical_fields)} populated")
        
        # Insurance fields check
        insurance_fields = [
            "payment_type", "insurance_provider", "insurance_member_id",
            "nirvana_verification_status"
        ]
        
        populated_insurance = sum(1 for field in insurance_fields if data.get(field))
        logger.info(f"  Insurance fields: {populated_insurance}/{len(insurance_fields)} populated")
        
        # Survey fields check
        survey_fields = ["phq9_scores", "gad7_scores", "what_brings_you"]
        populated_survey = sum(1 for field in survey_fields if data.get(field))
        logger.info(f"  Survey fields: {populated_survey}/{len(survey_fields)} populated")
        
        # Data sources used
        sources = data.get("data_sources_used", [])
        logger.info(f"  Data sources used: {len(sources)}")
        for i, source in enumerate(sources, 1):
            logger.info(f"    {i}. {source}")
        
        # Overall completeness
        all_fields = critical_fields + insurance_fields + survey_fields
        total_populated = sum(1 for field in all_fields if data.get(field))
        completeness_pct = (total_populated / len(all_fields)) * 100
        logger.info(f"  Overall completeness: {completeness_pct:.1f}%")


def enhance_nirvana_callback_data(callback_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance Nirvana callback data with comprehensive extraction.
    
    This function should be called from the Nirvana callback endpoint to ensure
    maximum data capture immediately after insurance verification.
    """
    logger.info("🔄 Enhancing Nirvana callback data with comprehensive extraction")
    
    # Use progressive data capture to extract everything
    comprehensive_data = ProgressiveDataCapture.extract_comprehensive_user_data(callback_data)
    
    # Merge with original callback data, prioritizing comprehensive extraction
    enhanced_data = {**callback_data, **comprehensive_data}
    
    # Ensure response_id is preserved
    enhanced_data["response_id"] = callback_data.get("response_id") or comprehensive_data.get("response_id")
    
    logger.info(f"✅ Enhanced callback data with {len(comprehensive_data)} additional fields")
    logger.info(f"📋 Data sources used: {comprehensive_data.get('data_sources_used', [])}")
    
    return enhanced_data


def validate_intakeq_data_completeness(client_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that IntakeQ client creation has all necessary demographic and insurance data.
    
    Returns a report of missing or incomplete data that should be addressed.
    """
    logger.info("🔍 Validating IntakeQ data completeness")
    
    validation_report = {
        "is_complete": True,
        "missing_critical": [],
        "missing_preferred": [],
        "data_quality_issues": [],
        "nirvana_data_available": False,
        "recommendations": []
    }
    
    # Critical fields for IntakeQ
    critical_fields = {
        "first_name": "First Name",
        "last_name": "Last Name", 
        "email": "Email Address"
    }
    
    for field, display_name in critical_fields.items():
        if not client_data.get(field):
            validation_report["missing_critical"].append(display_name)
            validation_report["is_complete"] = False
    
    # Preferred fields for complete profiles
    preferred_fields = {
        "phone": "Phone Number",
        "date_of_birth": "Date of Birth",
        "gender": "Gender",
        "street_address": "Street Address",
        "city": "City",
        "state": "State",
        "postal_code": "Postal Code"
    }
    
    for field, display_name in preferred_fields.items():
        if not client_data.get(field):
            validation_report["missing_preferred"].append(display_name)
    
    # Check for Nirvana data
    nirvana_indicators = [
        "nirvana_data", "nirvana_raw_response", "insurance_verification_data",
        "copay", "deductible", "plan_name"
    ]
    
    validation_report["nirvana_data_available"] = any(
        client_data.get(field) for field in nirvana_indicators
    )
    
    # Data quality checks
    if client_data.get("email") and "@" not in str(client_data["email"]):
        validation_report["data_quality_issues"].append("Invalid email format")
    
    if client_data.get("payment_type") == "insurance" and not validation_report["nirvana_data_available"]:
        validation_report["data_quality_issues"].append("Insurance client missing Nirvana verification data")
    
    # Generate recommendations
    if validation_report["missing_critical"]:
        validation_report["recommendations"].append("Collect missing critical fields before IntakeQ creation")
    
    if not validation_report["nirvana_data_available"] and client_data.get("payment_type") == "insurance":
        validation_report["recommendations"].append("Run insurance verification through Nirvana before IntakeQ creation")
    
    if len(validation_report["missing_preferred"]) > 3:
        validation_report["recommendations"].append("Consider collecting more demographic information for complete profile")
    
    # Log validation results
    logger.info(f"📊 Validation complete: {'✅ PASSED' if validation_report['is_complete'] else '❌ ISSUES FOUND'}")
    if validation_report["missing_critical"]:
        logger.warning(f"  Missing critical: {validation_report['missing_critical']}")
    if validation_report["missing_preferred"]:
        logger.info(f"  Missing preferred: {validation_report['missing_preferred']}")
    if validation_report["data_quality_issues"]:
        logger.warning(f"  Quality issues: {validation_report['data_quality_issues']}")
    
    return validation_report