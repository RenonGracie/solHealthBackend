# src/db/models.py — with state→timezone inference + bio/religion aliases
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# 👇 add this utility (place your provided mapping at src/utils/states.py)
try:
    from src.utils.state_utils import get_state_abbreviation, get_state_timezone
except Exception:
    # very safe fallbacks if utils aren’t available for any reason
    def get_state_abbreviation(x: str) -> str:
        return (x or "").strip().upper()

    def get_state_timezone(abbr: str) -> str:
        return "US/Eastern"


Base = declarative_base()


class Therapist(Base):
    __tablename__ = "therapists"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    calendar = Column(String)

    accepting_new_clients = Column(String)
    cohort = Column(String)
    program = Column(String, index=True)
    max_caseload = Column(Integer, default=0)
    current_caseload = Column(Float, default=0.0)

    # raw csv + parsed
    states = Column(Text)
    states_array = Column(ARRAY(String))

    # demographics
    age = Column(String)
    gender = Column(String)
    identities_as = Column(String)
    ethnicity = Column(Text)

    # experience
    gender_experience = Column(Text)
    sexual_orientation_experience = Column(Text)
    neurodivergence_experience = Column(Text)
    risk_experience = Column(Text)

    # professional
    religion = Column(Text)
    diagnoses = Column(Text)
    therapeutic_orientation = Column(Text)
    internal_therapeutic_orientation = Column(Text)
    specialities = Column(Text)
    diagnoses_specialties = Column(Text)
    diagnoses_specialties_array = Column(ARRAY(String))

    # personal
    social_media_affected = Column(String)
    family_household = Column(String)
    culture = Column(String)
    places = Column(String)
    immigration_background = Column(String)

    has_children = Column(String)
    married = Column(String)
    caretaker_role = Column(String)
    lgbtq_part = Column(String)
    performing_arts = Column(String)

    # content
    intro_bio = Column(Text)  # short bio (aka “bio” for UI)
    welcome_video = Column(String)

    last_modified = Column(String)
    first_generation = Column(String)
    has_job = Column(String)
    calendar_synced = Column(String)

    # integrations
    intakeq_practitioner_id = Column(String, unique=True, index=True)
    google_calendar_id = Column(String, index=True)

    # priority for corporate matching control (low, medium, high)
    priority = Column(String, default="low", index=True)

    # preferred IANA tz; if missing we'll infer from states_array
    timezone = Column(String, default="US/Eastern")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_program_accepting", "program", "accepting_new_clients"),
        Index("idx_states_array_gin", "states_array", postgresql_using="gin"),
        Index(
            "idx_diag_specs_array_gin",
            "diagnoses_specialties_array",
            postgresql_using="gin",
        ),
    )

    # ---- helpers ---------------------------------------------------------
    def inferred_timezone(self) -> str:
        """Return the stored timezone, or infer from first state in states_array."""
        if self.timezone and self.timezone.strip():
            return self.timezone
        try:
            state = (self.states_array or [None])[0]
            if not state and self.states:
                # crude split for CSV fallback
                parts = [p.strip() for p in self.states.split(",") if p.strip()]
                state = parts[0] if parts else None
            abbr = get_state_abbreviation(state or "")
            tz = get_state_timezone(abbr) if abbr else "US/Eastern"
            return tz or "US/Eastern"
        except Exception:
            return "US/Eastern"

    # new helpers for primary state/timezone
    def primary_state(self) -> Optional[str]:
        """
        Return the first state from states_array (normalized to abbr), or None.
        """
        arr = getattr(self, "states_array", None) or []
        if arr:
            return get_state_abbreviation(arr[0])
        raw = (getattr(self, "states", None) or "").strip()
        if raw:
            token = raw.split(",")[0].strip()
            return get_state_abbreviation(token)
        return None

    def primary_timezone(self) -> str:
        """
        Map primary state to an IANA timezone (coarse).
        """
        st = self.primary_state()
        return get_state_timezone(st) if st else "US/Eastern"

    def to_dict(self) -> dict:
        def is_true(v) -> bool:
            return str(v).strip().lower() in {"true", "t", "yes", "y", "1", "checked"}

        orientation_text = (self.therapeutic_orientation or "").strip() or (
            self.internal_therapeutic_orientation or ""
        ).strip()
        therapeutic_orientation_list = [
            x.strip() for x in orientation_text.split(",") if x.strip()
        ]

        # alias “bio” and “religious_experience” for the UI contract
        bio_val = self.intro_bio or ""
        religious_experience_val = self.religion  # keep simple alias; same content

        return {
            "id": self.id,
            "name": self.name,
            "intern_name": self.name,
            "email": self.email,
            "calendar": self.calendar,
            "calendar_email": self.calendar,
            "accepting_new_clients": is_true(self.accepting_new_clients),
            "cohort": self.cohort,
            "program": self.program,
            "max_caseload": self.max_caseload,
            "current_caseload": self.current_caseload,
            "states": self.states_array or [],
            "states_raw": self.states,
            "states_array": self.states_array or [],
            "age": self.age,
            "gender": self.gender,
            "identities_as": self.identities_as,
            "ethnicity": self.ethnicity,
            "therapeutic_orientation": therapeutic_orientation_list,
            # specialties/diagnoses fields expected by frontend
            "specialities": self.specialities,
            "diagnoses": self.diagnoses,
            "diagnoses_specialities": self.diagnoses_specialties,
            "diagnoses_specialties": self.diagnoses_specialties,
            "diagnoses_specialties_array": self.diagnoses_specialties_array or [],
            "welcome_video": self.welcome_video,
            # 👇 new/clarified
            "bio": bio_val,
            "biography": bio_val,
            "religion": self.religion,
            "religious_experience": religious_experience_val,
            "intakeq_practitioner_id": self.intakeq_practitioner_id,
            "google_calendar_id": self.google_calendar_id,
            "priority": self.priority,
            "timezone": self.inferred_timezone(),
            "primary_timezone": self.primary_timezone(),
        }


class ClientResponse(Base):
    __tablename__ = "client_responses"

    id = Column(String, primary_key=True)
    email = Column(String, index=True)
    first_name = Column(String)
    last_name = Column(String)
    phone = Column(String)

    age = Column(String)
    gender = Column(String)
    state = Column(String, index=True)
    street_address = Column(String)
    city = Column(String)
    postal_code = Column(String)
    university = Column(String)

    payment_type = Column(String, index=True)
    therapist_specializes_in = Column(ARRAY(String))
    therapist_identifies_as = Column(String)
    therapist_gender_preference = Column(String)  # User's preference for therapist gender
    lived_experiences = Column(ARRAY(String))

    insurance_provider = Column(String)
    insurance_member_id = Column(String)
    insurance_date_of_birth = Column(String)
    insurance_verified = Column(Boolean)
    insurance_verification_data = Column(JSON)

    # Insurance provider validation and correction tracking
    insurance_provider_original = Column(
        String
    )  # Original user input before Nirvana correction
    insurance_provider_corrected = Column(Boolean, default=False)  # Was correction applied
    insurance_provider_corrected_at = Column(DateTime)  # When correction was applied
    insurance_payer_id = Column(String)  # Nirvana payer ID for this provider
    insurance_correction_type = Column(
        String
    )  # Type of correction: 'payer_id_mismatch', 'unmapped_input', etc.

    # SuperJson fields for comprehensive data
    session_id = Column(String)
    journey_started_at = Column(DateTime)
    survey_completed_at = Column(DateTime)
    current_stage = Column(String, default="survey_completed")

    preferred_name = Column(String)
    date_of_birth = Column(String)
    race_ethnicity = Column(ARRAY(String))

    # Nirvana insurance data
    nirvana_raw_response = Column(JSON)
    nirvana_demographics = Column(JSON)
    nirvana_address = Column(JSON)
    nirvana_plan_details = Column(JSON)
    nirvana_benefits = Column(JSON)

    # Risk levels
    phq9_risk_level = Column(String)
    gad7_risk_level = Column(String)

    # Substance screening
    alcohol_frequency = Column(String)
    recreational_drugs_frequency = Column(String)
    safety_screening = Column(String)

    # Technical metadata
    user_agent = Column(String)
    screen_resolution = Column(String)
    timezone_data = Column(String)
    browser_timezone = Column(String)  # More specific than timezone_data
    data_completeness_score = Column(Float)

    phq9_responses = Column(JSON)
    gad7_responses = Column(JSON)
    phq9_total = Column(Integer)
    gad7_total = Column(Integer)

    what_brings_you = Column(Text)

    selected_therapist = Column(String)
    selected_therapist_id = Column(String)
    selected_therapist_email = Column(String)
    matching_preference = Column(String)

    # Algorithm-suggested therapist tracking (what the matching algorithm recommended)
    algorithm_suggested_therapist_id = Column(String)  # Algorithm's #1 pick
    algorithm_suggested_therapist_name = Column(String)
    algorithm_suggested_therapist_score = Column(Float)  # Matching score
    alternative_therapists_offered = Column(JSON)  # All matches: {count, names, ids, scores}
    user_chose_alternative = Column(Boolean, default=False)  # Did user pick different than #1?
    therapist_selection_timestamp = Column(DateTime)  # When user selected their therapist

    promo_code = Column(String)
    referred_by = Column(String)
    utm_source = Column(String)
    utm_medium = Column(String)
    utm_campaign = Column(String)

    match_status = Column(String, default="unassigned", index=True)
    matched_therapist_id = Column(String, ForeignKey("therapists.id"))
    matched_therapist_email = Column(String)
    matched_therapist_name = Column(String)
    matched_slot_start = Column(DateTime)  # UTC
    matched_slot_end = Column(DateTime)  # UTC

    intakeq_client_id = Column(String, index=True)
    intakeq_intake_url = Column(String)

    # Mandatory form tracking
    mandatory_form_sent = Column(Boolean, default=False, index=True)
    mandatory_form_intake_id = Column(String, index=True)
    mandatory_form_intake_url = Column(String)
    mandatory_form_sent_at = Column(DateTime)

    # Practitioner assignment status tracking
    practitioner_assignment_status = Column(String, default="not_started", index=True)
    # Possible values: "not_started", "async_pending", "completed", "failed"

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="client_response")

    def record_assignment(self, therapist) -> None:
        """Mark a therapist as matched (pre-booking)."""
        if therapist is None:
            return
        self.match_status = "matched"
        self.matched_therapist_id = getattr(therapist, "id", None)
        self.matched_therapist_email = getattr(therapist, "email", None)
        self.matched_therapist_name = getattr(therapist, "name", None)
        self.updated_at = datetime.utcnow()

    def record_booking(
        self,
        therapist,
        start_dt_utc,
        end_dt_utc,
        intakeq_client_id: str | None = None,
    ) -> None:
        """
        Persist booking info; upgrades status to 'booked'. If therapist is provided,
        ensures the assignment fields are populated too.
        """
        if therapist is not None:
            self.record_assignment(therapist)

        self.match_status = "booked"
        self.matched_slot_start = start_dt_utc
        self.matched_slot_end = end_dt_utc
        if intakeq_client_id:
            self.intakeq_client_id = intakeq_client_id
        self.updated_at = datetime.utcnow()


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String, primary_key=True)
    client_response_id = Column(
        String, ForeignKey("client_responses.id"), nullable=False
    )
    therapist_id = Column(String, ForeignKey("therapists.id"), nullable=False)

    practitioner_email = Column(String, nullable=False)
    practitioner_name = Column(String, nullable=False)
    start_date_iso = Column(String, nullable=False)
    status = Column(String, default="scheduled")

    reminder_type = Column(String, default="email")
    send_client_email_notification = Column(Boolean, default=True)
    booked_by_client = Column(Boolean, default=True)

    intakeq_appointment_id = Column(String, unique=True, index=True)
    google_event_id = Column(String, unique=True, index=True)

    date_created = Column(Integer)
    last_modified = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    client_response = relationship("ClientResponse", back_populates="appointments")
    therapist = relationship("Therapist")

    __table_args__ = (
        Index("ix_appt_therapist_start", "therapist_id", "start_date_iso"),
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True)
    therapist_id = Column(String, ForeignKey("therapists.id"), nullable=False)
    client_response_id = Column(String, ForeignKey("client_responses.id"))

    intakeq_id = Column(String, index=True)
    google_event_id = Column(String, index=True)

    start_time = Column(DateTime, nullable=False)  # UTC
    end_time = Column(DateTime, nullable=False)  # UTC
    status = Column(String, default="scheduled", nullable=False)

    summary = Column(String(255))
    description = Column(Text)
    raw = Column(JSON)

    __table_args__ = (Index("ix_cal_ev_therapist_time", "therapist_id", "start_time"),)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    sync_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    records_processed = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_created = Column(Integer, default=0)
    records_deleted = Column(Integer, default=0)
    error_message = Column(Text)

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
