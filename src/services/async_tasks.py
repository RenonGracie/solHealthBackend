"""
Async Task Processing for Post-Booking Operations

Handles background tasks that should run after successful booking confirmation:
- Selenium practitioner assignment
- Google Sheets comprehensive logging
- Other non-critical post-booking operations
"""
import logging
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AsyncTaskProcessor:
    """Handles async execution of post-booking tasks."""

    def __init__(self):
        self.logger = logger

    def execute_post_booking_tasks(
        self, task_data: Dict[str, Any], appointment_id: str, client_response_id: str
    ):
        """
        Execute all post-booking tasks asynchronously.

        Args:
            task_data: Dictionary containing all data needed for tasks
            appointment_id: Local appointment ID
            client_response_id: Client response ID
        """

        def run_tasks():
            self.logger.info("=" * 50)
            self.logger.info(
                f"🔄 [ASYNC CHECKPOINT 1] Starting background tasks for appointment {appointment_id}"
            )
            self.logger.info(f"  Client Response ID: {client_response_id}")
            self.logger.info(f"  Task data keys: {list(task_data.keys())}")
            self.logger.info(f"  Response ID in task_data: {task_data.get('response_id')}")
            self.logger.info(f"  comprehensive_data present: {bool(task_data.get('comprehensive_data'))}")
            if task_data.get('comprehensive_data'):
                self.logger.info(f"  comprehensive_data fields: {len(task_data.get('comprehensive_data', {}))}")
            self.logger.info("=" * 50)

            # Task 1: Selenium Practitioner Assignment
            self.logger.info("🤖 [ASYNC CHECKPOINT 2] Starting Selenium practitioner assignment...")
            selenium_success = self._run_selenium_assignment(task_data)
            self.logger.info(f"  Selenium assignment result: {'✅ Success' if selenium_success else '❌ Failed'}")

            # Task 2: Google Sheets Comprehensive Logging
            self.logger.info("📊 [ASYNC CHECKPOINT 3] Starting Google Sheets Stage 3 logging...")
            sheets_success = self._run_google_sheets_logging(task_data)
            self.logger.info(f"  Google Sheets logging result: {'✅ Success' if sheets_success else '❌ Failed'}")

            # Task 3: Any other post-booking operations can be added here

            # Log completion
            self.logger.info(
                f"✅ [ASYNC POST-BOOKING] Completed background tasks for appointment {appointment_id}"
            )
            self.logger.info(
                f"  Selenium Assignment: {'✅' if selenium_success else '❌'}"
            )
            self.logger.info(
                f"  Google Sheets Logging: {'✅' if sheets_success else '❌'}"
            )

        # Execute in background thread
        thread = threading.Thread(target=run_tasks, daemon=True)
        thread.start()

        self.logger.info(
            f"🚀 [ASYNC POST-BOOKING] Background tasks started for appointment {appointment_id}"
        )

    def _run_selenium_assignment(self, task_data: Dict[str, Any]) -> bool:
        """Execute Selenium practitioner assignment."""
        try:
            # Check if selenium is disabled via environment variable
            import os
            if os.getenv("DISABLE_SELENIUM_BOT", "false").lower() == "true":
                self.logger.info("⚠️ [ASYNC] Selenium bot disabled via DISABLE_SELENIUM_BOT env var")
                client_response_id = task_data.get("response_id")
                if client_response_id:
                    self._update_practitioner_assignment_status(client_response_id, "disabled")
                return False

            self.logger.info("🤖 [ASYNC] Running Selenium practitioner assignment...")

            # Extract client response ID for status updates
            client_response_id = task_data.get("response_id")

            # Add delay to allow IntakeQ to process the newly created client
            import time
            delay_seconds = 10
            self.logger.info(f"⏳ [ASYNC] Waiting {delay_seconds} seconds for IntakeQ to process new client...")
            time.sleep(delay_seconds)
            self.logger.info("✅ [ASYNC] Delay complete, proceeding with Selenium assignment")

            # Import with error handling
            try:
                from src.api.railway_practitioner import assign_practitioner_railway_direct
            except ImportError as import_err:
                self.logger.error(f"❌ [ASYNC] Failed to import railway_practitioner: {import_err}")
                client_response_id = task_data.get("response_id")
                if client_response_id:
                    self._update_practitioner_assignment_status(client_response_id, "failed")
                return False

            # Extract data needed for selenium
            account_type = task_data.get("account_type")
            intakeq_client_id = task_data.get("intakeq_client_id")
            therapist_name = task_data.get("therapist_name")
            client_state = task_data.get("state")  # Client state for state-specific credentials

            self.logger.info(f"🤖 [ASYNC] Selenium Parameters:")
            self.logger.info(f"  account_type: {account_type}")
            self.logger.info(f"  client_id: {intakeq_client_id}")
            self.logger.info(f"  therapist_name: {therapist_name}")
            self.logger.info(f"  client_response_id: {client_response_id}")
            self.logger.info(f"  state: {client_state}")

            # Call the Railway selenium bot to assign practitioner
            selenium_result = assign_practitioner_railway_direct(
                account_type=account_type,
                client_id=str(intakeq_client_id),
                therapist_full_name=therapist_name,
                response_id=client_response_id,
                state=client_state  # Pass state for state-specific IntakeQ credentials
            )
            
            selenium_success = selenium_result.get("success", False)
            client_url = selenium_result.get("client_url")

            # Update the practitioner assignment status in the database
            self._update_practitioner_assignment_status(
                client_response_id,
                "completed" if selenium_success else "failed"
            )
            
            # Store client URL in task data for Google Sheets logging
            if client_url:
                task_data["intakeq_intake_url"] = client_url
                self.logger.info(f"📋 [ASYNC] Captured client profile URL: {client_url}")

            if selenium_success:
                self.logger.info(
                    f"🎉 [ASYNC] Successfully assigned {therapist_name} to client {intakeq_client_id} via Selenium"
                )
                if client_url:
                    self.logger.info(f"📋 [ASYNC] Client profile URL: {client_url}")
                return True
            else:
                self.logger.error(
                    f"❌ [ASYNC] Failed to assign practitioner via Selenium"
                )
                return False

        except Exception as e:
            self.logger.error(
                f"❌ [ASYNC] Error in Selenium practitioner assignment: {str(e)}"
            )
            # Update status to failed on exception
            client_response_id = task_data.get("response_id")
            if client_response_id:
                self._update_practitioner_assignment_status(client_response_id, "failed")
            
            traceback.print_exc()
            return False
    
    def _update_practitioner_assignment_status(self, client_response_id: str, status: str):
        """Update the practitioner assignment status in the database."""
        session = None
        try:
            # Get Flask app instance and create app context for database operations
            from flask import current_app
            from src.db import get_db_session
            from src.db.models import ClientResponse
            
            # Import the Flask app
            try:
                from app import app as flask_app
            except ImportError:
                # Fallback to creating app if direct import fails
                from src.app import create_app
                flask_app = create_app()
            
            # Run database operations within Flask app context
            with flask_app.app_context():
                session = get_db_session()
                client_response = session.query(ClientResponse).filter_by(id=client_response_id).first()
                
                if client_response:
                    client_response.practitioner_assignment_status = status
                    session.commit()
                    self.logger.info(f"✅ [ASYNC] Updated practitioner assignment status to: {status}")
                else:
                    self.logger.warning(f"⚠️ [ASYNC] Client response not found for status update: {client_response_id}")
                
        except Exception as e:
            self.logger.error(f"❌ [ASYNC] Failed to update practitioner assignment status: {str(e)}")
        finally:
            if session:
                session.close()

    def _run_google_sheets_logging(self, task_data: Dict[str, Any]) -> bool:
        """Execute Google Sheets comprehensive logging."""
        try:
            self.logger.info("=" * 50)
            self.logger.info(
                "📊 [ASYNC SHEETS CHECKPOINT 1] Starting Google Sheets Stage 3 logging"
            )

            from src.services.google_sheets_progressive_logger import progressive_logger

            # Extract comprehensive data for logging
            comprehensive_data = task_data.get("comprehensive_data", {})
            response_id = task_data.get("response_id") or comprehensive_data.get(
                "response_id"
            )

            self.logger.info(f"  Response ID: {response_id}")
            self.logger.info(f"  comprehensive_data present: {bool(comprehensive_data)}")
            self.logger.info(f"  comprehensive_data fields: {len(comprehensive_data)}")

            if not comprehensive_data:
                self.logger.error(
                    "❌ [ASYNC SHEETS CHECKPOINT ERROR] Missing comprehensive_data"
                )
                self.logger.error(f"  task_data keys: {list(task_data.keys())}")
                return False

            if not response_id:
                self.logger.error(
                    "❌ [ASYNC SHEETS CHECKPOINT ERROR] Missing response_id"
                )
                self.logger.error(f"  task_data.response_id: {task_data.get('response_id')}")
                self.logger.error(f"  comprehensive_data.response_id: {comprehensive_data.get('response_id')}")
                return False

            self.logger.info(f"  Progressive logger enabled: {progressive_logger.enabled}")
            self.logger.info(f"  Google Sheets ID: {progressive_logger.sheet_id}")
            self.logger.info("=" * 50)

            # Log Stage 3: Final booking completion
            self.logger.info("📊 [ASYNC SHEETS CHECKPOINT 2] Calling progressive_logger.log_stage_3_booking_complete()")
            success = progressive_logger.log_stage_3_booking_complete(
                response_id, comprehensive_data
            )

            if success:
                self.logger.info("=" * 50)
                self.logger.info(
                    "✅ [ASYNC SHEETS CHECKPOINT 3] Stage 3 booking completion data logged to Google Sheets successfully"
                )
                self.logger.info("=" * 50)
                return True
            else:
                self.logger.error("=" * 50)
                self.logger.error(
                    "❌ [ASYNC SHEETS CHECKPOINT ERROR] Failed to log Stage 3 data to Google Sheets"
                )
                self.logger.error("=" * 50)
                return False

        except Exception as e:
            self.logger.error("=" * 50)
            self.logger.error(f"❌ [ASYNC SHEETS CHECKPOINT EXCEPTION] Error in Google Sheets logging")
            self.logger.error(f"  Error type: {type(e).__name__}")
            self.logger.error(f"  Error message: {str(e)}")
            import traceback
            self.logger.error(f"  Traceback: {traceback.format_exc()}")
            self.logger.error("=" * 50)
            return False


# Global instance
async_task_processor = AsyncTaskProcessor()
