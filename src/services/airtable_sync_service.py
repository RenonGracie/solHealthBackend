# src/services/airtable_sync_service.py
"""
Service to sync therapist data from Airtable to Aurora PostgreSQL.
Replaces the old CSV-based approach with live database updates.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyairtable import Table
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.db import get_db
from src.db.models import SyncLog, Therapist

logger = logging.getLogger(__name__)


class AirtableSyncService:
    """Service for syncing Airtable data to PostgreSQL."""

    def __init__(self):
        """Initialize Airtable connection."""
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")
        self.table_id = os.getenv("AIRTABLE_TABLE_ID", "Therapists")

        if not all([self.api_key, self.base_id]):
            logger.debug("Airtable credentials not configured - Airtable sync disabled")
            self.table = None
            self.enabled = False
            return

        self.table = Table(self.api_key, self.base_id, self.table_id)
        self.enabled = True
        logger.debug(f"AirtableSyncService initialized for base {self.base_id}")

    def sync_all_therapists(self, force_update: bool = False) -> Dict[str, Any]:
        """
        Perform a full sync of all therapists from Airtable.
        """
        if not hasattr(self, 'enabled') or not self.enabled:
            logger.debug("Airtable sync disabled - skipping sync")
            return {
                "status": "skipped",
                "records_processed": 0,
                "records_created": 0,
                "records_updated": 0,
                "message": "Airtable credentials not configured"
            }
        sync_start = datetime.utcnow()

        with get_db() as session:
            # Create sync log entry
            sync_log = SyncLog(
                sync_type="full_sync", status="running", started_at=sync_start
            )
            session.add(sync_log)
            session.commit()

            try:
                # Fetch all records from Airtable
                logger.debug("Fetching all therapist records from Airtable...")
                airtable_records = self.table.all()

                stats = {
                    "records_processed": 0,
                    "records_created": 0,
                    "records_updated": 0,
                    "records_deleted": 0,
                    "errors": [],
                }

                # Get existing therapist IDs from database
                existing_ids = set(row[0] for row in session.query(Therapist.id).all())

                airtable_ids = set()

                # Process each Airtable record
                for record in airtable_records:
                    try:
                        record_id = record["id"]
                        airtable_ids.add(record_id)

                        therapist_data = self._map_airtable_to_therapist(
                            record["fields"], record_id
                        )

                        # Skip if missing required fields
                        if not therapist_data.get("email") or not therapist_data.get(
                            "intern_name"
                        ):
                            logger.warning(
                                f"Skipping record {record_id}: missing email or name"
                            )
                            continue

                        # Check if record exists
                        existing_therapist = (
                            session.query(Therapist)
                            .filter(Therapist.id == record_id)
                            .first()
                        )

                        if existing_therapist:
                            # Update existing record
                            if force_update or self._should_update_record(
                                existing_therapist, record
                            ):
                                self._update_therapist(
                                    existing_therapist, therapist_data
                                )
                                stats["records_updated"] += 1
                                logger.debug(
                                    f"Updated therapist: {therapist_data['email']}"
                                )
                        else:
                            # Create new record
                            new_therapist = Therapist(**therapist_data)
                            session.add(new_therapist)
                            stats["records_created"] += 1
                            logger.debug(
                                f"Created therapist: {therapist_data['email']}"
                            )

                        stats["records_processed"] += 1

                    except Exception as e:
                        error_msg = f"Error processing record {record.get('id', 'unknown')}: {str(e)}"
                        logger.error(error_msg)
                        stats["errors"].append(error_msg)

                # Delete therapists that no longer exist in Airtable
                deleted_ids = existing_ids - airtable_ids
                if deleted_ids:
                    deleted_count = (
                        session.query(Therapist)
                        .filter(Therapist.id.in_(deleted_ids))
                        .delete(synchronize_session=False)
                    )
                    stats["records_deleted"] = deleted_count
                    logger.debug(
                        f"Deleted {deleted_count} therapists no longer in Airtable"
                    )

                # Commit all changes
                session.commit()

                # Update sync log
                sync_end = datetime.utcnow()
                sync_log.status = "success" if not stats["errors"] else "partial"
                sync_log.completed_at = sync_end
                sync_log.duration_seconds = (sync_end - sync_start).total_seconds()
                sync_log.records_processed = stats["records_processed"]
                sync_log.records_created = stats["records_created"]
                sync_log.records_updated = stats["records_updated"]
                sync_log.records_deleted = stats["records_deleted"]

                if stats["errors"]:
                    sync_log.error_message = "\n".join(
                        stats["errors"][:10]
                    )  # First 10 errors

                session.commit()

                logger.debug(f"Sync completed: {stats}")
                return stats

            except Exception as e:
                # Update sync log with error
                sync_log.status = "error"
                sync_log.completed_at = datetime.utcnow()
                sync_log.error_message = str(e)
                session.commit()

                logger.error(f"Sync failed: {str(e)}")
                raise

    def sync_incremental(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Sync only records modified in the last N hours.

        Args:
            hours_back: How many hours back to check for modifications

        Returns:
            Dictionary with sync results
        """
        sync_start = datetime.utcnow()
        cutoff_time = sync_start - timedelta(hours=hours_back)

        with get_db() as session:
            sync_log = SyncLog(
                sync_type="incremental", status="running", started_at=sync_start
            )
            session.add(sync_log)
            session.commit()

            try:
                # Fetch records modified since cutoff
                # Note: Airtable doesn't have built-in filtering by modification time
                # We'll fetch all and filter, or implement a more sophisticated approach
                logger.debug(f"Fetching records modified since {cutoff_time}")

                # For now, get all records and filter by last_modified
                # In production, you might want to implement a more efficient approach
                airtable_records = self.table.all()

                stats = {
                    "records_processed": 0,
                    "records_created": 0,
                    "records_updated": 0,
                    "records_deleted": 0,
                    "errors": [],
                }

                for record in airtable_records:
                    try:
                        # Check if record was modified recently
                        # This is a simplified check - in production you'd want better tracking
                        record_id = record["id"]

                        existing_therapist = (
                            session.query(Therapist)
                            .filter(Therapist.id == record_id)
                            .first()
                        )

                        if not existing_therapist or self._should_update_record(
                            existing_therapist, record
                        ):
                            therapist_data = self._map_airtable_to_therapist(
                                record["fields"], record_id
                            )

                            if not therapist_data.get(
                                "email"
                            ) or not therapist_data.get("intern_name"):
                                continue

                            if existing_therapist:
                                self._update_therapist(
                                    existing_therapist, therapist_data
                                )
                                stats["records_updated"] += 1
                            else:
                                new_therapist = Therapist(**therapist_data)
                                session.add(new_therapist)
                                stats["records_created"] += 1

                            stats["records_processed"] += 1

                    except Exception as e:
                        error_msg = f"Error processing record {record.get('id', 'unknown')}: {str(e)}"
                        logger.error(error_msg)
                        stats["errors"].append(error_msg)

                session.commit()

                # Update sync log
                sync_end = datetime.utcnow()
                sync_log.status = "success" if not stats["errors"] else "partial"
                sync_log.completed_at = sync_end
                sync_log.duration_seconds = (sync_end - sync_start).total_seconds()
                sync_log.records_processed = stats["records_processed"]
                sync_log.records_created = stats["records_created"]
                sync_log.records_updated = stats["records_updated"]

                if stats["errors"]:
                    sync_log.error_message = "\n".join(stats["errors"][:10])

                session.commit()

                logger.debug(f"Incremental sync completed: {stats}")
                return stats

            except Exception as e:
                sync_log.status = "error"
                sync_log.completed_at = datetime.utcnow()
                sync_log.error_message = str(e)
                session.commit()

                logger.error(f"Incremental sync failed: {str(e)}")
                raise

    def _map_airtable_to_therapist(
        self, fields: Dict[str, Any], record_id: str
    ) -> Dict[str, Any]:
        """Map Airtable fields to Therapist model fields."""
        # Parse states
        states_raw = fields.get("States", "")
        if isinstance(states_raw, str):
            states = [s.strip() for s in states_raw.split(",") if s.strip()]
        elif isinstance(states_raw, list):
            states = states_raw
        else:
            states = []

        # Helper function to parse array fields
        def parse_array_field(value):
            if isinstance(value, str):
                return [s.strip() for s in value.split(",") if s.strip()]
            elif isinstance(value, list):
                return value
            return []

        return {
            "id": record_id,
            "email": fields.get("Email", "").strip(),
            "intern_name": fields.get("Name", "").strip(),
            "calendar_email": fields.get("Calendar", fields.get("Email", "")).strip(),
            "accepting_new_clients": fields.get("Accepting New Clients") == "Yes",
            "cohort": fields.get("Cohort", "").strip(),
            "program": fields.get("Program", "").strip(),
            "max_caseload": self._parse_number(fields.get("Max Caseload", 0)),
            "current_caseload": self._parse_number(
                fields.get("Current Caseload", 0), is_float=True
            ),
            "states": states,
            "age": fields.get("Age", "").strip(),
            "gender": fields.get("Gender", "").strip(),
            "identities_as": fields.get("Identities as (Gender)", "").strip(),
            "ethnicity": parse_array_field(fields.get("Ethnicity", "")),
            # Experience flags
            "gender_experience": fields.get(
                "Gender: Do you have experience and/or interest in working with individuals who do not identify as cisgender? (i.e. transgender, gender fluid, etc.) ",
                "",
            ),
            "lgbtq_experience": fields.get(
                "Sexual Orientation: Do you have experience and/or interest in working with individuals who are part of the LGBTQ+ community?",
                "",
            ),
            "neurodivergence_experience": fields.get(
                "Neurodivergence: Do you have experience and/or interest in working with individuals who are neurodivergent? ",
                "",
            ),
            "risk_experience": fields.get(
                "Risk: Do you have experience and/or interest in working with higher-risk clients? ",
                "",
            ),
            # Specialties
            "religion": parse_array_field(
                fields.get(
                    "Religion: Please select the religions you have experience working with and/or understanding of. ",
                    "",
                )
            ),
            "diagnoses": parse_array_field(
                fields.get(
                    "Diagnoses: Please select the diagnoses you have experience and/or interest in working with",
                    "",
                )
            ),
            "therapeutic_orientation": parse_array_field(
                fields.get(
                    "Therapeutic Orientation: Please select the modalities you most frequently utilize. ",
                    "",
                )
            ),
            "specialities": parse_array_field(
                fields.get(
                    "Specialities: Please select any specialities you have experience and/or interest in working with. ",
                    "",
                )
            ),
            "diagnoses_specialities": parse_array_field(
                fields.get("Diagnoses + Specialties", "")
            ),
            # Personal characteristics
            "social_media_affected": fields.get(
                "Social Media: Have you ever been negatively affected by social media?"
            )
            == "Yes",
            "family_household": fields.get(
                "Traditional vs. Non-traditional family household", ""
            ),
            "culture": fields.get("Individualist vs. Collectivist culture", ""),
            "places": fields.get("Many places or only one or two places?", ""),
            "immigration_background": fields.get("Immigration Background", ""),
            "has_children": fields.get("Children: Do you have children?") == "Yes",
            "married": fields.get("Marriage: Are you / have ever been married?")
            == "Yes",
            "caretaker_role": fields.get(
                "Caretaker Role: Have you ever been in a caretaker role?"
            )
            == "Yes",
            "lgbtq_part": fields.get("LGBTQ+: Are you a part of the LGBTQ+ community?")
            == "Yes",
            "performing_arts": fields.get(
                "Performing/Visual Arts: Do you currently participate / have participated in any performing or visual art activities?"
            )
            == "Yes",
            # Bio and flags
            "biography": fields.get("Intro Bios (Shortened)", "").strip(),
            "first_generation": fields.get(
                "Are you a first generation college student?"
            )
            == "Yes",
            "has_job": fields.get(
                "Do you currently have a full-time or part-time job (apart from your internship)?"
            )
            == "Yes",
            "calendar_synced": fields.get("Calendar Synced") == "checked",
            # Media URLs
            "image_link": fields.get("Profile Image URL", "").strip() or None,
            "welcome_video_link": fields.get("Welcome Video", "").strip() or None,
            "greetings_video_link": fields.get("Greetings Video", "").strip() or None,
            # Timestamps
            "airtable_last_modified": datetime.utcnow(),  # We don't have this from Airtable API
        }

    def _parse_number(self, value: Any, is_float: bool = False) -> float:
        """Parse a number from various formats."""
        if not value:
            return 0.0 if is_float else 0

        try:
            if is_float:
                return float(str(value))
            else:
                return int(float(str(value)))
        except (ValueError, TypeError):
            return 0.0 if is_float else 0

    def _should_update_record(self, existing: Therapist, airtable_record: dict) -> bool:
        """
        Determine if a record should be updated.
        For now, always update. In production, you might check timestamps.
        """
        return True

    def _update_therapist(self, therapist: Therapist, data: Dict[str, Any]):
        """Update existing therapist with new data."""
        for key, value in data.items():
            if hasattr(therapist, key):
                setattr(therapist, key, value)

        therapist.updated_at = datetime.utcnow()

    def get_sync_status(self) -> Dict[str, Any]:
        """Get the status of recent sync operations."""
        with get_db() as session:
            # Get last 10 sync logs
            recent_syncs = (
                session.query(SyncLog)
                .order_by(SyncLog.started_at.desc())
                .limit(10)
                .all()
            )

            # Get therapist count
            therapist_count = session.query(Therapist).count()
            accepting_count = (
                session.query(Therapist)
                .filter(Therapist.accepting_new_clients == True)
                .count()
            )

            return {
                "therapist_count": therapist_count,
                "accepting_therapists": accepting_count,
                "recent_syncs": [
                    {
                        "id": sync.id,
                        "sync_type": sync.sync_type,
                        "status": sync.status,
                        "started_at": sync.started_at.isoformat(),
                        "completed_at": sync.completed_at.isoformat()
                        if sync.completed_at
                        else None,
                        "duration_seconds": sync.duration_seconds,
                        "records_processed": sync.records_processed,
                        "records_created": sync.records_created,
                        "records_updated": sync.records_updated,
                        "records_deleted": sync.records_deleted,
                        "error_message": sync.error_message,
                    }
                    for sync in recent_syncs
                ],
            }


# Create singleton instance
airtable_sync_service = AirtableSyncService()
