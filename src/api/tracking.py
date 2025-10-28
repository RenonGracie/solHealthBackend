# src/api/tracking.py
"""User journey tracking API endpoints."""
import logging

from flask import Blueprint, jsonify, request

from src.services.google_sheets_progressive_logger import progressive_logger

logger = logging.getLogger(__name__)

tracking_bp = Blueprint("tracking", __name__)


@tracking_bp.route("/track-dropout", methods=["POST"])
def track_dropout():
    """Track when user drops out of flow"""
    data = request.get_json()
    response_id = data.get("response_id")
    stage = data.get("stage")
    reason = data.get("reason", "")

    if not response_id or not stage:
        return jsonify({"error": "response_id and stage required"}), 400

    # Log dropout information (this could be enhanced with specific dropout tracking)
    logger.info(f"📊 [DROPOUT] {response_id} at stage: {stage}, reason: {reason}")

    # Note: Progressive logger focuses on successful flow progression
    # Dropout tracking could be added as a separate feature if needed

    return jsonify({"success": True})


@tracking_bp.route("/track-completion", methods=["POST"])
def track_completion():
    """Track when user completes the entire journey"""
    data = request.get_json()
    response_id = data.get("response_id")

    if not response_id:
        return jsonify({"error": "response_id required"}), 400

    # Note: Journey completion is now tracked automatically at Stage 3 (booking completion)
    # This endpoint could be used for additional completion metadata if needed
    logger.info(f"📊 [COMPLETION] {response_id} - journey completed")

    return jsonify({"success": True})


@tracking_bp.route("/journey-analytics", methods=["GET"])
def get_journey_analytics():
    """Get analytics on user journeys"""
    try:
        if not progressive_logger.enabled:
            return jsonify(
                {
                    "error": "Journey tracking is disabled",
                    "total_journeys": 0,
                    "completed": 0,
                    "incomplete": 0,
                    "failed": 0,
                    "conversion_rate": 0.0,
                }
            )

        # Basic analytics - this could be enhanced to actually query the sheets
        return jsonify(
            {
                "total_journeys": 0,
                "completed": 0,
                "incomplete": 0,
                "failed": 0,
                "conversion_rate": 0.0,
                "message": "Analytics data would be fetched from Google Sheets in full implementation",
            }
        )
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return jsonify({"error": str(e)}), 500


@tracking_bp.route("/track-booking-context", methods=["POST"])
def track_booking_context():
    """Track detailed booking context from frontend"""
    data = request.get_json()
    response_id = data.get("response_id")

    if not response_id:
        return jsonify({"error": "response_id required"}), 400

    try:
        # Extract detailed data for enhanced tracking
        booking_data = data.get("data", {})

        # Log rich booking context
        logger.info(f"📊 [Frontend Booking Context] {response_id}")
        logger.info(f"  Client: {booking_data.get('client_data', {})}")
        logger.info(f"  Therapist: {booking_data.get('therapist_data', {})}")
        logger.info(f"  Booking: {booking_data.get('booking_context', {})}")

        # Note: Booking started tracking now happens automatically at Stage 2 (appointment booking)

        # Store the rich context data for potential future use
        # This could be enhanced to store in a separate detailed tracking table

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error tracking booking context: {e}")
        return jsonify({"error": str(e)}), 500


@tracking_bp.route("/track-interaction", methods=["POST"])
def track_interaction():
    """Track user interactions for detailed analytics"""
    data = request.get_json()
    response_id = data.get("response_id")
    interaction_type = data.get("interaction_type")

    if not response_id or not interaction_type:
        return jsonify({"error": "response_id and interaction_type required"}), 400

    try:
        interaction_data = data.get("data", {})

        # Log interaction for analytics
        logger.info(f"📊 [Frontend Interaction] {response_id} - {interaction_type}")
        logger.info(f"  Data: {interaction_data}")

        # This could be enhanced to track specific interactions in Google Sheets
        # For now, we log for debugging and future enhancement

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error tracking interaction: {e}")
        return jsonify({"error": str(e)}), 500


@tracking_bp.route("/track-incomplete", methods=["POST"])
def track_incomplete():
    """Track incomplete user information (e.g., unsupported state)"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    try:
        reason = data.get("reason", "unsupported_state")
        user_data = data.get("user_data", {})
        
        # Add additional context like user agent and IP address if available
        if hasattr(request, 'user_agent'):
            user_data["user_agent"] = str(request.user_agent)
        if hasattr(request, 'remote_addr'):
            user_data["ip_address"] = request.remote_addr
            
        logger.info(f"📋 [INCOMPLETE] Tracking incomplete user: reason={reason}")
        
        # Log to Google Sheets
        success = progressive_logger.log_incomplete_user(user_data, reason)
        
        if success:
            return jsonify({"success": True, "message": "Incomplete user logged successfully"})
        else:
            return jsonify({"success": False, "message": "Failed to log incomplete user"}), 500
            
    except Exception as e:
        logger.error(f"Error tracking incomplete user: {e}")
        return jsonify({"error": str(e)}), 500


@tracking_bp.route("/journey-summary/<response_id>", methods=["GET"])
def get_journey_summary(response_id: str):
    """Get complete journey data for a user"""
    try:
        # Note: Journey summary would need to be implemented for progressive logger if needed
        summary = (
            None  # Could implement: progressive_logger.get_journey_summary(response_id)
        )

        if summary:
            return jsonify({"success": True, "journey": summary})
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Journey not found or tracking disabled",
                    }
                ),
                404,
            )

    except Exception as e:
        logger.error(f"Error getting journey summary: {e}")
        return jsonify({"error": str(e)}), 500
