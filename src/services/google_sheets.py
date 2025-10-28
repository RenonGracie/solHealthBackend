import base64
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print(
        "Google API client not installed. Run: pip install google-api-python-client google-auth"
    )
    Credentials = None
    build = None
    HttpError = Exception

logger = logging.getLogger(__name__)


class GoogleSheetsLogger:
    def __init__(self):
        self.sheet_id = os.getenv("GOOGLE_SHEETS_ID")
        self.sheet_name = os.getenv("GOOGLE_SHEET_NAME", "User Signups")
        self.service = None

        # Check if we have any credentials available
        has_credentials = (
            os.getenv("GOOGLE_CREDENTIALS_JSON")
            or os.getenv("GOOGLE_CREDENTIALS_JSON_B64")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )

        self.enabled = bool(self.sheet_id and has_credentials and Credentials)

        if self.enabled:
            try:
                self._initialize_service()
            except Exception as e:
                logger.error(f"Failed to initialize Google Sheets service: {e}")
                self.enabled = False
        else:
            logger.debug(
                "Google Sheets logging disabled - missing sheet_id or credentials or dependencies"
            )

    def _initialize_service(self):
        """Initialize Google Sheets service with service account credentials"""
        try:
            # Use the same credential pattern as your Google Calendar service
            credentials = self._get_credentials()
            self.service = build(
                "sheets", "v4", credentials=credentials, cache_discovery=False
            )
            logger.debug("Google Sheets service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            self.enabled = False

    def _get_credentials(self):
        """Get Google credentials using the same pattern as google_calendar.py"""
        raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        b64 = os.getenv("GOOGLE_CREDENTIALS_JSON_B64", "").strip()
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]

        if raw:
            try:
                info = json.loads(raw)
                return Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON: {e}")

        if b64:
            try:
                decoded = base64.b64decode(b64).decode("utf-8")
                info = json.loads(decoded)
                return Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON_B64: {e}")

        if path:
            try:
                return Credentials.from_service_account_file(path, scopes=scopes)
            except Exception as e:
                logger.error(f"Failed reading GOOGLE_APPLICATION_CREDENTIALS: {e}")

        # Fallback to credentials utility if available
        try:
            from src.utils.google.credentials import get_credentials

            # Note: get_credentials uses calendar scopes, so we create new creds with sheets scope
            creds = get_credentials()
            if creds:
                # Recreate with correct scopes for Sheets
                if hasattr(creds, "_service_account_info"):
                    return Credentials.from_service_account_info(
                        creds._service_account_info, scopes=scopes
                    )
        except ImportError:
            pass

        raise RuntimeError("No Google credentials found for Sheets service")

    def _flatten_data(self, data: Dict[str, Any]) -> List[Any]:
        """Convert user data to flat row format for Google Sheets"""

        # Helper function to safely get nested values
        def safe_get(obj, *keys):
            for key in keys:
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    return ""
            return obj if obj is not None else ""

        # Helper to convert arrays to comma-separated strings
        def array_to_string(arr):
            if isinstance(arr, list):
                return ", ".join(str(x) for x in arr if x)
            return str(arr) if arr else ""

        # Current timestamp
        now = datetime.utcnow().isoformat()

        # Build comprehensive row data (83 fields as planned)
        row_data = [
            # Basic User Information
            safe_get(data, "response_id"),
            safe_get(data, "email"),
            safe_get(data, "first_name"),
            safe_get(data, "last_name"),
            safe_get(data, "preferred_name"),
            safe_get(data, "middle_name"),
            safe_get(data, "phone"),
            safe_get(data, "mobile_phone"),
            safe_get(data, "date_of_birth"),
            safe_get(data, "age"),
            safe_get(data, "gender"),
            # Address & Location
            safe_get(data, "street_address"),
            safe_get(data, "city"),
            safe_get(data, "state"),
            safe_get(data, "postal_code"),
            safe_get(data, "country"),
            # Demographics & Background
            safe_get(data, "marital_status"),
            array_to_string(safe_get(data, "race_ethnicity")),
            array_to_string(safe_get(data, "lived_experiences")),
            safe_get(data, "university"),
            safe_get(data, "referred_by"),
            # PHQ-9 Assessment
            safe_get(data, "phq9_scores", "pleasure_doing_things"),
            safe_get(data, "phq9_scores", "feeling_down"),
            safe_get(data, "phq9_scores", "trouble_falling"),
            safe_get(data, "phq9_scores", "feeling_tired"),
            safe_get(data, "phq9_scores", "poor_appetite"),
            safe_get(data, "phq9_scores", "feeling_bad_about_yourself"),
            safe_get(data, "phq9_scores", "trouble_concentrating"),
            safe_get(data, "phq9_scores", "moving_or_speaking_so_slowly"),
            safe_get(data, "phq9_scores", "suicidal_thoughts"),
            safe_get(data, "phq9_total_score"),
            # GAD-7 Assessment
            safe_get(data, "gad7_scores", "feeling_nervous"),
            safe_get(data, "gad7_scores", "not_control_worrying"),
            safe_get(data, "gad7_scores", "worrying_too_much"),
            safe_get(data, "gad7_scores", "trouble_relaxing"),
            safe_get(data, "gad7_scores", "being_so_restless"),
            safe_get(data, "gad7_scores", "easily_annoyed"),
            safe_get(data, "gad7_scores", "feeling_afraid"),
            safe_get(data, "gad7_total_score"),
            # Substance Use
            safe_get(data, "alcohol_frequency"),
            safe_get(data, "recreational_drugs_frequency"),
            # Therapist Preferences
            safe_get(data, "therapist_gender_preference"),
            array_to_string(safe_get(data, "therapist_specialization")),
            array_to_string(safe_get(data, "therapist_lived_experiences")),
            # Payment & Insurance
            safe_get(data, "payment_type"),
            safe_get(data, "insurance_provider"),
            safe_get(data, "insurance_member_id"),
            safe_get(data, "insurance_date_of_birth"),
            safe_get(data, "copay"),
            safe_get(data, "deductible"),
            safe_get(data, "coinsurance"),
            safe_get(data, "out_of_pocket_max"),
            safe_get(data, "remaining_deductible"),
            safe_get(data, "remaining_oop_max"),
            safe_get(data, "member_obligation"),
            safe_get(data, "benefit_structure"),
            safe_get(data, "session_cost_dollars"),
            safe_get(data, "payer_id"),
            # Appointment Data
            safe_get(data, "matched_therapist_id"),
            safe_get(data, "matched_therapist_name"),
            safe_get(data, "matched_therapist_email"),
            safe_get(data, "appointment_date"),
            safe_get(data, "appointment_time"),
            safe_get(data, "appointment_timezone"),
            safe_get(data, "appointment_duration"),
            safe_get(data, "appointment_type"),
            # IntakeQ Data
            safe_get(data, "intakeq_client_id"),
            safe_get(data, "intakeq_intake_url"),
            safe_get(data, "mandatory_form_sent"),
            safe_get(data, "mandatory_form_intake_id"),
            safe_get(data, "mandatory_form_intake_url"),
            safe_get(data, "mandatory_form_sent_at"),
            # Enhanced IntakeQ Insurance Fields
            safe_get(data, "intakeq_primary_insured_gender"),
            safe_get(data, "intakeq_primary_insured_city"),
            safe_get(data, "intakeq_primary_insured_state"),
            safe_get(data, "intakeq_primary_insured_zip"),
            safe_get(data, "intakeq_primary_insured_address"),
            safe_get(data, "intakeq_relationship_to_insured"),
            # Nirvana Subscriber Demographics
            safe_get(data, "subscriber_first_name"),
            safe_get(data, "subscriber_last_name"),
            safe_get(data, "subscriber_gender"),
            safe_get(data, "subscriber_member_id"),
            safe_get(data, "subscriber_dob"),
            safe_get(data, "subscriber_street"),
            safe_get(data, "subscriber_city"),
            safe_get(data, "subscriber_state"),
            safe_get(data, "subscriber_zip"),
            # Additional Context
            safe_get(data, "safety_screening"),
            safe_get(data, "matching_preference"),
            safe_get(data, "what_brings_you"),
            # Tracking Data
            safe_get(data, "sol_health_response_id"),
            safe_get(data, "onboarding_completed_at"),
            safe_get(data, "survey_completed_at"),
            safe_get(data, "utm_source"),
            safe_get(data, "utm_medium"),
            safe_get(data, "utm_campaign"),
            safe_get(data, "signup_timestamp"),
            safe_get(data, "completion_timestamp"),
            safe_get(data, "user_agent"),
            safe_get(data, "ip_address"),
            # System Metadata
            os.getenv("ENVIRONMENT", "production"),
            os.getenv("API_VERSION", "1.0"),
            os.getenv("FRONTEND_VERSION", "1.0"),
            now,  # created_at
            now,  # updated_at
        ]

        return row_data

    def _get_headers(self) -> List[str]:
        """Get header row for Google Sheets"""
        return [
            # Basic User Information (11)
            "response_id",
            "email",
            "first_name",
            "last_name",
            "preferred_name",
            "middle_name",
            "phone",
            "mobile_phone",
            "date_of_birth",
            "age",
            "gender",
            # Address & Location (5)
            "street_address",
            "city",
            "state",
            "postal_code",
            "country",
            # Demographics & Background (5)
            "marital_status",
            "race_ethnicity",
            "lived_experiences",
            "university",
            "referred_by",
            # PHQ-9 Assessment (10)
            "phq9_pleasure_doing_things",
            "phq9_feeling_down",
            "phq9_trouble_falling",
            "phq9_feeling_tired",
            "phq9_poor_appetite",
            "phq9_feeling_bad_about_yourself",
            "phq9_trouble_concentrating",
            "phq9_moving_or_speaking_so_slowly",
            "phq9_suicidal_thoughts",
            "phq9_total_score",
            # GAD-7 Assessment (8)
            "gad7_feeling_nervous",
            "gad7_not_control_worrying",
            "gad7_worrying_too_much",
            "gad7_trouble_relaxing",
            "gad7_being_so_restless",
            "gad7_easily_annoyed",
            "gad7_feeling_afraid",
            "gad7_total_score",
            # Substance Use (2)
            "alcohol_frequency",
            "recreational_drugs_frequency",
            # Therapist Preferences (3)
            "therapist_gender_preference",
            "therapist_specialization",
            "therapist_lived_experiences",
            # Payment & Insurance (13)
            "payment_type",
            "insurance_provider",
            "insurance_member_id",
            "insurance_date_of_birth",
            "copay",
            "deductible",
            "coinsurance",
            "out_of_pocket_max",
            "remaining_deductible",
            "remaining_oop_max",
            "member_obligation",
            "benefit_structure",
            "session_cost_dollars",
            "payer_id",
            # Appointment Data (8)
            "matched_therapist_id",
            "matched_therapist_name",
            "matched_therapist_email",
            "appointment_date",
            "appointment_time",
            "appointment_timezone",
            "appointment_duration",
            "appointment_type",
            # IntakeQ Data (6)
            "intakeq_client_id",
            "intakeq_intake_url",
            "mandatory_form_sent",
            "mandatory_form_intake_id",
            "mandatory_form_intake_url",
            "mandatory_form_sent_at",
            # Enhanced IntakeQ Insurance Fields (6)
            "intakeq_primary_insured_gender",
            "intakeq_primary_insured_city",
            "intakeq_primary_insured_state",
            "intakeq_primary_insured_zip",
            "intakeq_primary_insured_address",
            "intakeq_relationship_to_insured",
            # Nirvana Subscriber Demographics (9)
            "subscriber_first_name",
            "subscriber_last_name",
            "subscriber_gender",
            "subscriber_member_id",
            "subscriber_dob",
            "subscriber_street",
            "subscriber_city",
            "subscriber_state",
            "subscriber_zip",
            # Additional Context (3)
            "safety_screening",
            "matching_preference",
            "what_brings_you",
            # Tracking Data (10)
            "sol_health_response_id",
            "onboarding_completed_at",
            "survey_completed_at",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "signup_timestamp",
            "completion_timestamp",
            "user_agent",
            "ip_address",
            # System Metadata (5)
            "environment",
            "api_version",
            "frontend_version",
            "created_at",
            "updated_at",
        ]

    def ensure_header_row(self):
        """Ensure the Google Sheet has the correct header row"""
        if not self.enabled:
            return False

        try:
            # Check if sheet exists and has headers
            # Properly escape sheet name for Google Sheets API
            # For sheet names with spaces or special chars, wrap in single quotes
            # For single quotes in sheet name, double them: ' becomes ''
            if " " in self.sheet_name or "'" in self.sheet_name:
                escaped_name = self.sheet_name.replace("'", "''")
                sheet_range = f"'{escaped_name}'!1:1"
            else:
                sheet_range = f"{self.sheet_name}!1:1"
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.sheet_id, range=sheet_range)
                .execute()
            )

            values = result.get("values", [])
            headers = self._get_headers()

            if not values or values[0] != headers:
                # Write/update header row
                if " " in self.sheet_name or "'" in self.sheet_name:
                    escaped_name = self.sheet_name.replace("'", "''")
                    update_range = f"'{escaped_name}'!1:1"
                else:
                    update_range = f"{self.sheet_name}!1:1"
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=update_range,
                    valueInputOption="RAW",
                    body={"values": [headers]},
                ).execute()
                logger.debug("Google Sheets header row updated")

            return True

        except Exception as e:
            logger.error(f"Failed to ensure header row: {e}")
            return False

    def log_user_signup(self, user_data: Dict[str, Any]) -> bool:
        """Log user signup data to Google Sheets"""
        if not self.enabled:
            logger.debug("Google Sheets logging disabled")
            return False

        try:
            # Ensure headers exist
            self.ensure_header_row()

            # Convert data to row format
            row_data = self._flatten_data(user_data)

            # Append row to sheet
            if " " in self.sheet_name or "'" in self.sheet_name:
                escaped_name = self.sheet_name.replace("'", "''")
                append_range = f"'{escaped_name}'!A:A"
            else:
                append_range = f"{self.sheet_name}!A:A"
            self.service.spreadsheets().values().append(
                spreadsheetId=self.sheet_id,
                range=append_range,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row_data]},
            ).execute()

            logger.debug(
                f"Successfully logged user signup to Google Sheets: {user_data.get('email', 'unknown')}"
            )
            return True

        except HttpError as e:
            logger.error(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to log user signup to Google Sheets: {e}")
            return False


# Global instance
sheets_logger = GoogleSheetsLogger()
