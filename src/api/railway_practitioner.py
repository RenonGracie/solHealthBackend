"""
Railway Practitioner Assignment API

Simple endpoint for IntakeQ practitioner assignment using Selenium.
"""

import logging
import os

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

railway_practitioner_bp = Blueprint("railway_practitioner", __name__)


@railway_practitioner_bp.route("/railway/assign-practitioner", methods=["POST"])
def assign_practitioner_railway():
    """
    Assign IntakeQ practitioner using Selenium
    
    Request Body:
    {
        "account_type": "insurance" | "cash_pay",
        "client_id": "5781", 
        "therapist_full_name": "Catherine Burnett"
    }
    """
    try:
        data = request.get_json() or {}
        
        # Validate required fields
        required = ["account_type", "client_id", "therapist_full_name"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"success": False, "message": f"Missing: {', '.join(missing)}"}), 400
        
        account_type = data["account_type"]
        if account_type not in ["cash_pay", "insurance"]:
            return jsonify({"success": False, "message": "account_type must be 'cash_pay' or 'insurance'"}), 400
            
        client_id = str(data["client_id"])
        therapist_full_name = data["therapist_full_name"]
        
        logger.info(f"🚀 Assigning {client_id} → {therapist_full_name} ({account_type})")
        
        # Check credentials exist
        user_key = f"{account_type.upper()}_INTAKEQ_USR".replace("CASH_PAY", "CASH_PAY")
        pass_key = f"{account_type.upper()}_INTAKEQ_PAS".replace("CASH_PAY", "CASH_PAY")
        
        if not os.getenv(user_key) or not os.getenv(pass_key):
            return jsonify({"success": False, "message": f"Missing credentials for {account_type}"}), 500
        
        # Execute Selenium automation
        from intakeq_selenium_bot import assign_intakeq_practitioner
        
        success, client_url = assign_intakeq_practitioner(account_type, client_id, therapist_full_name, headless=True)
        
        if success:
            # Update database with client profile URL if captured
            if client_url:
                try:
                    from src.api.clients import update_client_data
                    update_client_data(response_id="", update_data={"intakeq_intake_url": client_url})
                    logger.info(f"✅ Updated database with client profile URL: {client_url}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not update database with client URL: {e}")
            
            return jsonify({
                "success": True,
                "message": f"Successfully assigned {client_id} to {therapist_full_name}",
                "client_id": client_id,
                "therapist_full_name": therapist_full_name,
                "account_type": account_type,
                "client_profile_url": client_url or None
            })
        else:
            return jsonify({
                "success": False, 
                "message": f"Failed to assign {client_id} to {therapist_full_name}"
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Assignment error: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


def assign_practitioner_railway_direct(account_type: str, client_id: str, therapist_full_name: str, response_id: str = None) -> dict:
    """
    Direct function call for Railway Selenium assignment.
    Used by intakeq_forms.py and async_tasks.py
    
    Args:
        account_type: 'insurance' or 'cash_pay'
        client_id: IntakeQ client ID  
        therapist_full_name: Full name of therapist to assign
        response_id: Optional response ID for database update
    
    Returns:
        dict: {"success": bool, "client_url": str}
    """
    try:
        from intakeq_selenium_bot import assign_intakeq_practitioner
        
        logger.info(f"🚀 Direct Railway assignment: {client_id} → {therapist_full_name} ({account_type})")
        
        success, client_url = assign_intakeq_practitioner(account_type, client_id, therapist_full_name, headless=True)
        
        # Update database with client profile URL if captured and response_id provided
        if success and client_url and response_id:
            try:
                from src.api.clients import update_client_data
                update_client_data(response_id=response_id, update_data={"intakeq_intake_url": client_url})
                logger.info(f"✅ Updated database with client profile URL: {client_url}")
            except Exception as e:
                logger.warning(f"⚠️ Could not update database with client URL: {e}")
        
        return {
            "success": success,
            "client_url": client_url if success else None
        }
        
    except Exception as e:
        logger.error(f"❌ Direct Railway assignment error: {str(e)}")
        return {
            "success": False,
            "client_url": None
        }

