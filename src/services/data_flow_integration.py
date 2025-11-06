"""
Data Flow Integration Layer

This module provides a unified interface for managing user data flow across
the Sol Health system, including progressive logging and data centralization.

Integrates with:
- Progressive Google Sheets logging
- User data management
- IntakeQ creation tracking
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Import the progressive logger
from .google_sheets_progressive_logger import GoogleSheetsProgressiveLogger

# Global instance
_progressive_logger = None

def get_progressive_logger():
    """Get the global progressive logger instance"""
    global _progressive_logger
    if _progressive_logger is None:
        _progressive_logger = GoogleSheetsProgressiveLogger()
    return _progressive_logger

def log_nirvana_response_immediately(response_id: str, user_data: Dict[str, Any]) -> bool:
    """
    Stage 0: Log immediately after Nirvana 200 response

    This is the truly progressive first stage - logs as soon as we get
    insurance verification data from Nirvana.

    Args:
        response_id: The user's response ID
        user_data: Dictionary containing survey data + Nirvana response

    Returns:
        bool: True if logging successful
    """
    logger.info(f"📊 [IMMEDIATE] Logging Nirvana response for {response_id}")

    try:
        # Ensure response_id is in the data
        user_data["response_id"] = response_id

        # CRITICAL FIX: Store Nirvana data for later stages to access
        logger.info(f"💾 [IMMEDIATE] Storing Nirvana data in data store for {response_id}")
        store_user_data(response_id, user_data)

        # Log to Stage 0 (immediate Nirvana)
        progressive_logger = get_progressive_logger()
        success = progressive_logger.log_stage_0_nirvana_response(user_data)

        if success:
            logger.info(f"✅ [IMMEDIATE] Successfully logged Nirvana data for {response_id}")
        else:
            logger.error(f"❌ [IMMEDIATE] Failed to log Nirvana data for {response_id}")

        return success

    except Exception as e:
        logger.error(f"❌ [IMMEDIATE] Exception logging Nirvana response: {e}")
        return False

def log_to_google_sheets_progressive(response_id: str, stage: int = 1, data: Optional[Dict[str, Any]] = None) -> bool:
    """
    Progressive logging function for stages 1+ (after Stage 0 Nirvana logging)
    
    Args:
        response_id: The user's response ID
        stage: Which stage to log (1, 2, or 3)
        data: Optional additional data to merge
        
    Returns:
        bool: True if logging successful
    """
    logger.info(f"📊 [STAGE {stage}] Progressive logging for {response_id}")
    
    try:
        progressive_logger = get_progressive_logger()
        
        # Get existing user data (this should already exist from Stage 0)
        user_data = get_user_data(response_id)
        
        # Merge any additional data provided
        if data:
            user_data.update(data)
            
        # Ensure response_id is set
        user_data["response_id"] = response_id
        
        # Route to appropriate stage
        if stage == 1:
            success = progressive_logger.log_stage_1_survey_complete(user_data)
        elif stage == 2:
            success = progressive_logger.log_stage_2_therapist_confirmed(response_id, user_data)
        elif stage == 3:
            success = progressive_logger.log_stage_3_booking_complete(response_id, user_data)
        else:
            logger.error(f"❌ Invalid stage: {stage}")
            return False
            
        if success:
            logger.info(f"✅ [STAGE {stage}] Successfully updated data for {response_id}")
        else:
            logger.error(f"❌ [STAGE {stage}] Failed to update data for {response_id}")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ [STAGE {stage}] Exception in progressive logging: {e}")
        return False

def ensure_user_data_initialized(response_id: str, initial_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure user data is initialized and merge with any existing data

    In the progressive system, Stage 0 (Nirvana) may have already stored data.
    This function merges new data with existing data, preserving Nirvana fields.
    """
    logger.info(f"📋 Ensuring user data initialized for {response_id}")

    # Get any existing data (may include Nirvana data from Stage 0)
    existing_data = get_user_data(response_id)

    # Merge initial_data into existing_data (preserving existing Nirvana data)
    # New fields from initial_data will be added, but won't overwrite existing fields
    merged_data = {**existing_data, **initial_data}

    # Ensure response_id is set
    merged_data["response_id"] = response_id

    # Store the merged data
    store_user_data(response_id, merged_data)

    logger.info(f"📋 Merged data now has {len(merged_data)} fields (was {len(existing_data)}, added {len(initial_data)})")

    return merged_data

def update_intakeq_creation_result(response_id: str, intakeq_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update user data with IntakeQ creation results
    
    Args:
        response_id: The user's response ID  
        intakeq_result: IntakeQ creation result data
        
    Returns:
        Updated user data
    """
    logger.info(f"📋 Updating IntakeQ results for {response_id}")
    
    try:
        # Get existing user data
        user_data = get_user_data(response_id)
        
        # Add IntakeQ results
        user_data.update({
            "intakeq_client_id": intakeq_result.get("ClientId"),
            "intakeq_intake_url": intakeq_result.get("intake_url"),
            "intakeq_creation_timestamp": intakeq_result.get("completion_timestamp"),
            "intakeq_response": intakeq_result.get("intakeq_response", {})
        })
        
        # Store updated data (in a real system, this would persist to database/cache)
        store_user_data(response_id, user_data)
        
        return user_data
        
    except Exception as e:
        logger.error(f"❌ Failed to update IntakeQ results for {response_id}: {e}")
        return {}

# Simple in-memory data store (in production, this would be Redis/Database)
_user_data_store = {}

def get_user_data(response_id: str) -> Dict[str, Any]:
    """Get user data by response ID"""
    return _user_data_store.get(response_id, {"response_id": response_id})

def store_user_data(response_id: str, data: Dict[str, Any]) -> None:
    """Store user data by response ID"""
    _user_data_store[response_id] = data

def clear_user_data(response_id: str) -> None:
    """Clear user data (for cleanup)"""
    if response_id in _user_data_store:
        del _user_data_store[response_id]