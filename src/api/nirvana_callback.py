"""
Nirvana Callback API

Handles immediate callbacks from Lambda after successful Nirvana verification.
Enables truly progressive logging by capturing insurance data as soon as Nirvana responds.
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Import the immediate logging function
from src.services.data_flow_integration import log_nirvana_response_immediately

# Import comprehensive data capture utilities
from src.utils.progressive_data_capture import enhance_nirvana_callback_data
from src.utils.comprehensive_data_logger import ensure_comprehensive_logging

nirvana_callback_bp = Blueprint("nirvana_callback", __name__)

@nirvana_callback_bp.route("/nirvana/verified", methods=["POST"])
def handle_nirvana_verified():
    """
    Handle immediate Nirvana verification callback

    Called by Lambda immediately after Nirvana returns 200 with insurance data.
    This enables truly progressive logging - we log to Google Sheets as soon as
    we have insurance verification, not waiting for IntakeQ or other steps.
    """
    logger.info("=" * 60)
    logger.info("📞 [NIRVANA CALLBACK] Received Nirvana verification callback")
    logger.info("=" * 60)

    try:
        data = request.get_json()
        if not data:
            logger.error("❌ No JSON data received in Nirvana callback")
            return jsonify({"error": "No data provided"}), 400

        # ENHANCED LOGGING: Log the exact raw structure received from Lambda
        logger.info("🔍 [RAW DATA STRUCTURE] Logging complete incoming payload structure:")
        logger.info(f"  Total top-level keys: {len(data)}")
        logger.info(f"  Top-level keys: {list(data.keys())}")

        # Log each top-level field with its type and sample
        for key, value in data.items():
            value_type = type(value).__name__
            if isinstance(value, dict):
                sample = f"dict with {len(value)} keys: {list(value.keys())[:5]}"
            elif isinstance(value, list):
                sample = f"list with {len(value)} items"
            elif isinstance(value, str) and len(value) > 100:
                sample = f"{value[:100]}..."
            else:
                sample = value
            logger.info(f"    {key}: ({value_type}) {sample}")

        # Check specifically for Nirvana data structures
        nirvana_keys = ["nirvana_data", "nirvana_response", "nirvana_raw_response",
                        "insurance_verification_data", "rawNirvanaResponse"]
        found_nirvana_keys = [k for k in nirvana_keys if k in data]

        if found_nirvana_keys:
            logger.info(f"✅ [NIRVANA DATA FOUND] Located Nirvana data at keys: {found_nirvana_keys}")
            for key in found_nirvana_keys:
                nirvana_value = data[key]
                if isinstance(nirvana_value, dict):
                    logger.info(f"  {key} structure:")
                    logger.info(f"    Keys: {list(nirvana_value.keys())}")

                    # Check for nested demographics
                    if "demographics" in nirvana_value:
                        demo = nirvana_value["demographics"]
                        logger.info(f"    demographics keys: {list(demo.keys()) if isinstance(demo, dict) else type(demo)}")
                        if isinstance(demo, dict) and "address" in demo:
                            logger.info(f"      address keys: {list(demo['address'].keys())}")

                    # Check for nested subscriber_demographics
                    if "subscriber_demographics" in nirvana_value:
                        sub_demo = nirvana_value["subscriber_demographics"]
                        logger.info(f"    subscriber_demographics keys: {list(sub_demo.keys()) if isinstance(sub_demo, dict) else type(sub_demo)}")
                        if isinstance(sub_demo, dict) and "address" in sub_demo:
                            logger.info(f"      address keys: {list(sub_demo['address'].keys())}")
        else:
            logger.warning(f"⚠️ [NIRVANA DATA MISSING] No Nirvana data found in any expected keys")
            logger.warning(f"  Expected one of: {nirvana_keys}")
            logger.warning(f"  Received keys: {list(data.keys())}")

        logger.info("=" * 60)

        response_id = data.get("response_id")
        if not response_id:
            logger.error("❌ No response_id provided in Nirvana callback")
            return jsonify({"error": "response_id required"}), 400

        logger.info(f"📊 [PROCESSING] Starting immediate Nirvana logging for {response_id}")

        # Validate Nirvana data structure
        from src.utils.comprehensive_data_logger import validate_nirvana_data_structure
        validation_report = validate_nirvana_data_structure(data)

        logger.info("=" * 60)
        logger.info("🔍 [VALIDATION REPORT]")
        logger.info(f"  Nirvana data found: {validation_report['nirvana_data_found']}")
        if validation_report['nirvana_data_found']:
            logger.info(f"  Location: {validation_report['nirvana_location']}")
        if validation_report['missing_sections']:
            logger.warning(f"  Missing sections: {len(validation_report['missing_sections'])}")
        if validation_report['warnings']:
            logger.warning(f"  Warnings: {len(validation_report['warnings'])}")
        if validation_report['recommendations']:
            logger.info("  Recommendations:")
            for rec in validation_report['recommendations']:
                logger.info(f"    - {rec}")
        logger.info("=" * 60)

        # Use comprehensive data capture to extract ALL available data
        user_data = ensure_comprehensive_logging(data)
        
        # Log the comprehensive data audit
        if "_comprehensive_logging_report" in user_data:
            report = user_data["_comprehensive_logging_report"]
            logger.info(f"📊 Comprehensive logging report:")
            logger.info(f"  • Total fields extracted: {report['total_fields_extracted']}")
            logger.info(f"  • Google Sheets completeness: {report['overall_completeness']['sheets_completeness_pct']}%")
            logger.info(f"  • IntakeQ completeness: {report['overall_completeness']['intakeq_completeness_pct']}%")
        
        # Ensure critical fields are preserved from URL parameter  
        user_data["response_id"] = response_id
        user_data.setdefault("payment_type", data.get("payment_type", "insurance"))
        
        # Log immediately to Google Sheets (Stage 0)
        success = log_nirvana_response_immediately(response_id, user_data)
        
        if success:
            logger.info(f"✅ Successfully logged immediate Nirvana data for {response_id}")
            return jsonify({
                "success": True,
                "message": "Nirvana data logged immediately",
                "response_id": response_id,
                "stage": 0
            }), 200
        else:
            logger.error(f"❌ Failed to log immediate Nirvana data for {response_id}")
            return jsonify({
                "success": False, 
                "message": "Failed to log Nirvana data",
                "response_id": response_id
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Exception in Nirvana callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        return jsonify({
            "success": False,
            "message": f"Internal error: {str(e)}"
        }), 500

@nirvana_callback_bp.route("/nirvana/failed", methods=["POST"]) 
def handle_nirvana_failed():
    """
    Handle failed Nirvana verification callback
    
    Called when Nirvana verification fails - still log for tracking purposes.
    """
    logger.info("📞 Received Nirvana failure callback")
    
    try:
        data = request.get_json()
        response_id = data.get("response_id") if data else None
        
        if response_id:
            # Log the failure for tracking
            user_data = data.copy()
            user_data["nirvana_verification_status"] = "FAILED"
            user_data["nirvana_verification_error"] = data.get("error", "Unknown error")
            
            # Still log to track failures
            success = log_nirvana_response_immediately(response_id, user_data)
            
            logger.info(f"📊 Logged Nirvana failure for {response_id}: {success}")
        
        return jsonify({"success": True, "message": "Failure logged"}), 200
        
    except Exception as e:
        logger.error(f"❌ Exception in Nirvana failure callback: {e}")
        return jsonify({"success": False, "message": str(e)}), 500