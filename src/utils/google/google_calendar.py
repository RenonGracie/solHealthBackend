# src/utils/google/google_calendar.py - LIVE UPDATES: Caching disabled for real-time availability
from __future__ import annotations

import calendar as calmod
import json
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from dateutil import tz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Simple in-memory cache with TTL (DISABLED FOR LIVE UPDATES)
_CACHE = {}
_CACHE_TTL = 300  # 5 minutes (not used - caching disabled)

# Rate limiting
_LAST_API_CALL = {}
_MIN_TIME_BETWEEN_CALLS = 0.1  # 100ms minimum between API calls

try:
    from src.utils.logger import get_logger

    logger = get_logger()
except Exception:
    import logging

    logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

_INTERNAL_DOMAIN = "solhealth.co"
_CONTACT_EMAIL = None


def cache_key(*args, **kwargs):
    """Generate a cache key from function arguments."""
    return str(args) + str(sorted(kwargs.items()))


def with_cache(ttl_seconds=300):
    """Decorator to cache function results."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__ + cache_key(*args, **kwargs)

            # Check cache
            if key in _CACHE:
                cached_time, cached_value = _CACHE[key]
                if time.time() - cached_time < ttl_seconds:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cached_value

            # Call function and cache result
            result = func(*args, **kwargs)
            _CACHE[key] = (time.time(), result)
            return result

        return wrapper

    return decorator


def rate_limit(min_interval=0.1):
    """Decorator to rate limit function calls."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__
            now = time.time()

            if key in _LAST_API_CALL:
                elapsed = now - _LAST_API_CALL[key]
                if elapsed < min_interval:
                    sleep_time = min_interval - elapsed
                    logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)

            _LAST_API_CALL[key] = time.time()
            return func(*args, **kwargs)

        return wrapper

    return decorator


def clear_cache():
    """Clear all cached data."""
    global _CACHE
    _CACHE = {}
    logger.info("Cache cleared")


def clear_cache_for_calendar(calendar_id: str):
    """Clear cache for a specific calendar (more targeted than clearing everything)."""
    global _CACHE
    keys_to_remove = []

    for key in _CACHE:
        if calendar_id in key:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del _CACHE[key]

    logger.info(
        f"Cleared cache for calendar: {calendar_id} ({len(keys_to_remove)} entries)"
    )
    return len(keys_to_remove)


def get_therapist_session_duration(
    therapist_email: str,
    payment_type: str | None = None,
    explicit_session_minutes: int | None = None,
) -> int:
    """
    Unified function to determine session duration based on therapist program and payment type.

    Args:
        therapist_email: Therapist's email/calendar ID
        payment_type: "insurance" or "cash_pay" (will be auto-detected if None)
        explicit_session_minutes: Override duration if specified

    Returns:
        Session duration in minutes

    Logic:
        - Explicit session minutes take precedence
        - Limited Permit therapists: INSURANCE ONLY (55 minutes)
        - MFT/MHC/MSW therapists: CASH PAY ONLY (45 minutes)
        - No crossover between programs
    """
    if explicit_session_minutes:
        return explicit_session_minutes

    # Try to get therapist program from database
    therapist_program = None
    try:
        from src.db import get_db_session
        from src.db.models import Therapist

        session = get_db_session()
        try:
            therapist = (
                session.query(Therapist)
                .filter(Therapist.email == therapist_email)
                .first()
            )
            if therapist:
                therapist_program = therapist.program
        finally:
            session.close()
    except Exception as e:
        logger.warning(
            f"Could not lookup therapist program for {therapist_email}: {str(e)}"
        )

    # Determine session duration based on program (no crossover allowed)
    if therapist_program:
        if therapist_program == "Limited Permit":
            # Associates: INSURANCE ONLY - 55 minutes
            return 55
        elif therapist_program in ["MFT", "MHC", "MSW"]:
            # Graduates: CASH PAY ONLY - 45 minutes
            return 45

    # Fallback: assume cash pay if program lookup fails
    return 45


def get_therapist_payment_type(therapist_email: str) -> str:
    """
    Determine the payment type for a therapist based on their program.

    Args:
        therapist_email: Therapist's email/calendar ID

    Returns:
        "insurance" for Limited Permit, "cash_pay" for MFT/MHC/MSW

    Logic:
        - Limited Permit therapists: INSURANCE ONLY
        - MFT/MHC/MSW therapists: CASH PAY ONLY
    """
    try:
        from src.db import get_db_session
        from src.db.models import Therapist

        session = get_db_session()
        try:
            therapist = (
                session.query(Therapist)
                .filter(Therapist.email == therapist_email)
                .first()
            )
            if therapist and therapist.program:
                if therapist.program == "Limited Permit":
                    return "insurance"
                elif therapist.program in ["MFT", "MHC", "MSW"]:
                    return "cash_pay"
        finally:
            session.close()
    except Exception as e:
        logger.warning(
            f"Could not lookup therapist program for payment type detection {therapist_email}: {str(e)}"
        )

    # Fallback: assume cash pay if program lookup fails
    return "cash_pay"


def get_therapist_info(therapist_email: str) -> dict:
    """
    Get comprehensive therapist information including program, payment type, and session duration.

    Args:
        therapist_email: Therapist's email/calendar ID

    Returns:
        Dict with therapist info, program, auto-detected payment type, and session duration
    """
    try:
        from src.db import get_db_session
        from src.db.models import Therapist

        session = get_db_session()
        try:
            therapist = (
                session.query(Therapist)
                .filter(Therapist.email == therapist_email)
                .first()
            )
            if therapist:
                # Auto-detect payment type based on program
                if therapist.program == "Limited Permit":
                    payment_type = "insurance"
                    session_duration = 55
                    booking_interval = "hour_blocks"  # Must be hour-aligned
                elif therapist.program in ["MFT", "MHC", "MSW"]:
                    payment_type = "cash_pay"
                    session_duration = 45
                    booking_interval = (
                        "hour_blocks"  # Cash pay now also uses hourly alignment
                    )
                else:
                    # Unknown program - default to cash pay
                    payment_type = "cash_pay"
                    session_duration = 45
                    booking_interval = "hour_blocks"

                return {
                    "therapist_email": therapist_email,
                    "therapist_name": therapist.name,
                    "program": therapist.program,
                    "payment_type": payment_type,
                    "session_duration_minutes": session_duration,
                    "booking_interval_type": booking_interval,
                    "accepts_insurance": payment_type == "insurance",
                    "accepts_cash_pay": payment_type == "cash_pay",
                }
        finally:
            session.close()
    except Exception as e:
        logger.warning(
            f"Could not lookup therapist info for {therapist_email}: {str(e)}"
        )

    # Fallback info
    return {
        "therapist_email": therapist_email,
        "therapist_name": "Unknown",
        "program": "Unknown",
        "payment_type": "cash_pay",
        "session_duration_minutes": 45,
        "booking_interval_type": "hour_blocks",
        "accepts_insurance": False,
        "accepts_cash_pay": True,
    }


# ---------- Credentials ----------
def _build_credentials_from_env() -> service_account.Credentials | None:
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    b64 = os.environ.get("GOOGLE_CREDENTIALS_JSON_B64", "").strip()
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    if raw:
        try:
            info = json.loads(raw)
            return service_account.Credentials.from_service_account_info(
                info, scopes=_SCOPES
            )
        except Exception as e:
            logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON: {e}")

    if b64:
        import base64

        try:
            decoded = base64.b64decode(b64).decode("utf-8")
            info = json.loads(decoded)
            return service_account.Credentials.from_service_account_info(
                info, scopes=_SCOPES
            )
        except Exception as e:
            logger.error(f"Invalid GOOGLE_CREDENTIALS_JSON_B64: {e}")

    if path:
        try:
            return service_account.Credentials.from_service_account_file(
                path, scopes=_SCOPES
            )
        except Exception as e:
            logger.error(f"Failed reading GOOGLE_APPLICATION_CREDENTIALS: {e}")

    return None


def _get_base_credentials() -> service_account.Credentials:
    creds = _build_credentials_from_env()
    if creds:
        return creds

    # Try local file
    try:
        from src.utils.google.credentials import get_credentials

        return get_credentials()
    except Exception:
        pass

    raise RuntimeError("No Google credentials found")


def _get_service(subject_email: str | None = None):
    creds = _get_base_credentials()
    if subject_email:
        try:
            creds = creds.with_subject(subject_email)
        except Exception as e:
            logger.error(f"Failed to set subject for domain-wide delegation: {e}")
            raise
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _is_internal_calendar(calendar_id: str) -> bool:
    return isinstance(calendar_id, str) and calendar_id.lower().endswith(
        f"@{_INTERNAL_DOMAIN}"
    )


def _to_rfc3339_day_bounds(d: str, end: bool, timezone_offset: str = "+00:00") -> str:
    """
    Convert a date string to RFC3339 format with day bounds.

    Args:
        d: Date string in YYYY-MM-DD format
        end: If True, use end of day (23:59:59), otherwise start of day (00:00:00)
        timezone_offset: Timezone offset string (e.g., "-08:00" for PT, "-05:00" for ET)
                        Defaults to UTC (+00:00) for backward compatibility

    Returns:
        RFC3339 formatted datetime string

    Note: Using the correct timezone is CRITICAL for OOO blocks to work properly.
    If a therapist blocks 9am-5pm PT, the query must use PT bounds, not UTC bounds.
    """
    return f"{d}T{'23:59:59' if end else '00:00:00'}{timezone_offset}"


def _coerce_date_string(value: datetime | str, fallback_fmt: str = "%Y-%m-%d") -> str:
    if isinstance(value, datetime):
        return value.strftime(fallback_fmt)
    return value


def _get_timezone_offset(tzname: str, ref_date: datetime | None = None) -> str:
    """
    Get timezone offset string for a given timezone name.

    Args:
        tzname: Timezone name (e.g., "America/Los_Angeles", "America/New_York")
        ref_date: Reference datetime to determine offset (accounts for DST).
                 If None, uses current time.

    Returns:
        Timezone offset string in RFC3339 format (e.g., "-08:00", "-05:00", "+00:00")
    """
    zone = tz.gettz(tzname)
    if not zone:
        logger.warning(f"Unknown timezone {tzname}, defaulting to UTC")
        return "+00:00"

    # Use ref_date if provided, otherwise use current time
    ref_dt = ref_date if ref_date else datetime.now(zone)

    # Ensure ref_dt has timezone info
    if ref_dt.tzinfo is None:
        ref_dt = zone.localize(ref_dt) if hasattr(zone, 'localize') else ref_dt.replace(tzinfo=zone)
    else:
        ref_dt = ref_dt.astimezone(zone)

    # Get UTC offset for this timezone at the reference date
    offset = ref_dt.strftime("%z")  # Returns format like "-0800" or "-0500"

    # Convert to RFC3339 format: "-08:00" instead of "-0800"
    if len(offset) == 5:  # format: +/-HHMM
        return f"{offset[:3]}:{offset[3:]}"
    return "+00:00"  # Fallback to UTC


# ---------- Calendar list (rate limiting disabled) ----------
# @rate_limit(min_interval=0.2)  # Rate limiting disabled for live updates
def insert_email_to_gcalendar(calendar_id: str) -> None:
    """Add calendar to list with rate limiting disabled."""
    service = _get_service()
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
        logger.info(f"calendarList.insert succeeded for {calendar_id}")
    except HttpError as e:
        if e.resp.status == 403 and "rateLimitExceeded" in str(e):
            logger.warning(f"Rate limit hit for {calendar_id}, skipping")
        elif e.resp.status == 409:  # Already exists
            logger.debug(f"Calendar {calendar_id} already in list")
        else:
            logger.info(f"calendarList.insert failed for {calendar_id}: {e}")
    finally:
        try:
            service.close()
        except Exception:
            pass


# ---------- Get busy events (cached and rate limited) ----------
# CACHING DISABLED FOR LIVE UPDATES
# @with_cache(ttl_seconds=60)  # Cache for 1 minute (reduced from 5 minutes)
# @rate_limit(min_interval=0.5)  # Max 2 requests per second
def get_busy_events_from_gcalendar(
    calendar_ids: list[str],
    time_min: datetime | str | None = None,
    time_max: datetime | str | None = None,
    raise_error: bool = False,
    timezone_offset: str | None = None,
) -> dict[str, Any]:
    """
    Get busy times with caching and rate limiting.

    Args:
        calendar_ids: List of calendar email addresses
        time_min: Start date/datetime for query
        time_max: End date/datetime for query
        raise_error: Whether to raise errors or return empty dict
        timezone_offset: Timezone offset string (e.g., "-08:00" for PT, "-05:00" for ET).
                        If None, defaults to UTC. IMPORTANT: Use therapist's timezone to
                        avoid missing OOO blocks that span into next UTC day.

    Returns:
        Dict mapping calendar_id to busy blocks
    """
    if not time_min or not time_max:
        logger.error("get_busy_events_from_gcalendar requires time_min and time_max")
        return {}

    start_date = _coerce_date_string(time_min)
    end_date = _coerce_date_string(time_max)

    # Use timezone offset if provided, otherwise default to UTC
    tz_offset = timezone_offset if timezone_offset else "+00:00"
    tmin = _to_rfc3339_day_bounds(start_date, end=False, timezone_offset=tz_offset)
    tmax = _to_rfc3339_day_bounds(end_date, end=True, timezone_offset=tz_offset)

    # Log timezone usage for debugging OOO block issues
    if timezone_offset:
        logger.info(f"🌍 [TIMEZONE FIX] Using timezone offset {tz_offset} for freebusy query")
    else:
        logger.debug(f"⚠️ [TIMEZONE] Using default UTC for freebusy query (may miss events in other timezones)")

    def _fetch_with_retry(
        ids: list[str], use_impersonation: bool, retries=3
    ) -> dict[str, Any] | None:
        if not ids:
            return {}

        for attempt in range(retries):
            service = _get_service(_CONTACT_EMAIL if use_impersonation else None)
            try:
                body = {
                    "timeMin": tmin,
                    "timeMax": tmax,
                    "items": [{"id": cid} for cid in ids],
                }

                logger.info(f"🔍 [RAW API REQUEST] Google Calendar freebusy query:")
                logger.info(f"  Time range: {tmin} to {tmax}")
                logger.info(f"  Calendar IDs: {list(ids)}")
                logger.info(f"  Request body: {body}")

                result = service.freebusy().query(body=body).execute()

                logger.info(f"🔍 [RAW API RESPONSE] Google Calendar freebusy response:")
                logger.info(f"  Full response: {json.dumps(result, indent=2)}")

                calendars_data = result.get("calendars", {})
                for cal_id, cal_data in calendars_data.items():
                    busy_events = cal_data.get("busy", [])
                    logger.info(
                        f"  📅 Calendar {cal_id}: {len(busy_events)} busy blocks"
                    )
                    for i, event in enumerate(busy_events, 1):
                        logger.info(f"    {i}. {event['start']} → {event['end']}")

                return calendars_data
            except HttpError as e:
                if e.resp.status == 403 and "rateLimitExceeded" in str(e):
                    wait_time = (
                        2**attempt
                    ) * 2  # Exponential backoff: 2, 4, 8 seconds
                    logger.warning(
                        f"Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"freebusy.query error: {e}")
                    if raise_error:
                        raise
                    return None
            finally:
                try:
                    service.close()
                except Exception:
                    pass

        logger.error(f"Failed after {retries} retries")
        return None

    internal = [c for c in calendar_ids if _is_internal_calendar(c)]
    external = [c for c in calendar_ids if not _is_internal_calendar(c)]

    out: dict[str, Any] = {}

    if internal:
        d = _fetch_with_retry(internal, use_impersonation=True)
        if d:
            out.update(d)

    if external:
        # Don't try to add external calendars to list - often causes rate limits
        # Just query them directly
        d = _fetch_with_retry(external, use_impersonation=False)
        if d:
            out.update(d)

    return out


# ---------- Availability calculations ----------
def month_bounds(year: int, month: int, tzname: str) -> Tuple[str, str, tz.tzfile]:
    zone = tz.gettz(tzname)
    first = datetime(year, month, 1, 0, 0, 0, tzinfo=zone)
    next_first = datetime(
        year + (1 if month == 12 else 0),
        (1 if month == 12 else month + 1),
        1,
        0,
        0,
        0,
        tzinfo=zone,
    )
    return first.strftime("%Y-%m-%d"), next_first.strftime("%Y-%m-%d"), zone


def overlap_seconds(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0.0, (end - start).total_seconds())


def compute_day_availability(
    busy_blocks: List[Dict],
    year: int,
    month: int,
    day: int,
    zone,
    work_start: Tuple[int, int],
    work_end: Tuple[int, int],
) -> Dict[str, Any]:
    ws_h, ws_m = work_start
    we_h, we_m = work_end
    day_start = datetime(year, month, day, ws_h, ws_m, tzinfo=zone)
    day_end = datetime(year, month, day, we_h, we_m, tzinfo=zone)
    work_secs = (day_end - day_start).total_seconds()

    if work_secs <= 0:
        return {
            "free_ratio": 0.0,
            "free_secs": 0,
            "busy_secs": 0,
            "segments": [],
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
        }

    busy_secs = 0.0
    segments: List[Dict[str, Any]] = []

    for b in busy_blocks:
        # CRITICAL FIX: Ensure busy blocks are properly parsed and converted to the same timezone as work hours
        bs_str = b["start"]
        be_str = b["end"]

        # Parse busy block times - Google returns these in UTC by default
        if "Z" in bs_str or "+00:00" in bs_str:
            # UTC format from Google Calendar
            bs = datetime.fromisoformat(bs_str.replace("Z", "+00:00"))
            be = datetime.fromisoformat(be_str.replace("Z", "+00:00"))
        else:
            # Already has timezone info
            bs = datetime.fromisoformat(bs_str)
            be = datetime.fromisoformat(be_str)

        # CRITICAL: Convert to the same timezone as work hours for accurate comparison
        bs = bs.astimezone(zone)
        be = be.astimezone(zone)

        # Calculate overlap with work hours
        seg = overlap_seconds(day_start, day_end, bs, be)
        if seg > 0:
            busy_secs += seg
            segments.append(
                {
                    "start": max(day_start, bs).isoformat(),
                    "end": min(day_end, be).isoformat(),
                    "seconds": seg,
                }
            )

    free_secs = max(0.0, work_secs - busy_secs)
    return {
        "free_ratio": free_secs / work_secs if work_secs else 0.0,
        "free_secs": int(free_secs),
        "busy_secs": int(busy_secs),
        "segments": segments,
        "day_start": day_start.isoformat(),
        "day_end": day_end.isoformat(),
    }


def build_hour_slots(
    year: int,
    month: int,
    day: int,
    zone,
    work_start: Tuple[int, int],
    work_end: Tuple[int, int],
    busy_segments: List[Dict],
    slot_minutes: int = 60,
    free_threshold: float = 1.0,
) -> List[Dict[str, Any]]:
    ws_h, ws_m = work_start
    we_h, we_m = work_end
    start = datetime(year, month, day, ws_h, ws_m, tzinfo=zone)
    end = datetime(year, month, day, we_h, we_m, tzinfo=zone)

    busy: List[Tuple[datetime, datetime]] = [
        (
            datetime.fromisoformat(s["start"]).astimezone(zone),
            datetime.fromisoformat(s["end"]).astimezone(zone),
        )
        for s in busy_segments
    ]

    slots = []
    cur = start
    step = timedelta(minutes=slot_minutes)

    while cur < end:
        s_end = min(cur + step, end)
        slot_len = (s_end - cur).total_seconds()
        busy_in_slot = sum(overlap_seconds(cur, s_end, bs, be) for bs, be in busy)
        free_ratio = max(0.0, (slot_len - busy_in_slot) / slot_len)
        slots.append(
            {
                "start": cur.isoformat(),
                "end": s_end.isoformat(),
                "free_ratio": free_ratio,
                "is_free": free_ratio >= free_threshold,
            }
        )
        cur = s_end

    return slots


def compute_full_day_free_intervals(
    busy_blocks: List[Dict], year: int, month: int, day: int, zone
) -> List[Tuple[datetime, datetime]]:
    day_start = datetime(year, month, day, 0, 0, tzinfo=zone)
    day_end = day_start + timedelta(days=1)

    intervals: List[Tuple[datetime, datetime]] = []
    for b in busy_blocks:
        bs = datetime.fromisoformat(b["start"]).astimezone(zone)
        be = datetime.fromisoformat(b["end"]).astimezone(zone)
        s = max(day_start, bs)
        e = min(day_end, be)
        if e > s:
            intervals.append((s, e))

    intervals.sort(key=lambda t: t[0])
    merged: List[Tuple[datetime, datetime]] = []

    for s, e in intervals:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    free: List[Tuple[datetime, datetime]] = []
    cur = day_start

    for s, e in merged:
        if cur < s:
            free.append((cur, s))
        cur = max(cur, e)

    if cur < day_end:
        free.append((cur, day_end))

    return free


def compute_business_hours_free_intervals(
    busy_blocks: List[Dict], business_start: datetime, business_end: datetime, zone
) -> List[Tuple[datetime, datetime]]:
    """
    Compute free intervals within business hours only.
    This ensures sessions are only offered during working hours (e.g., 7 AM - 10 PM).
    """
    intervals: List[Tuple[datetime, datetime]] = []
    for b in busy_blocks:
        bs = datetime.fromisoformat(b["start"]).astimezone(zone)
        be = datetime.fromisoformat(b["end"]).astimezone(zone)
        # Only consider busy blocks that overlap with business hours
        s = max(business_start, bs)
        e = min(business_end, be)
        if e > s:
            intervals.append((s, e))

    intervals.sort(key=lambda t: t[0])
    merged: List[Tuple[datetime, datetime]] = []

    for s, e in intervals:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    free: List[Tuple[datetime, datetime]] = []
    cur = business_start

    for s, e in merged:
        if cur < s:
            free.append((cur, s))
        cur = max(cur, e)

    if cur < business_end:
        free.append((cur, business_end))

    return free


def build_session_windows(
    free_intervals: List[Tuple[datetime, datetime]],
    session_minutes: int,
    step_minutes: int | None = None,
    payment_type: str | None = None,
    therapist_email: str | None = None,
    booking_interval_type: str | None = None,
) -> List[Dict[str, str]]:
    if step_minutes is None:
        step_minutes = 60

    step = timedelta(minutes=step_minutes)

    # Auto-detect payment type if therapist email provided
    if therapist_email and not payment_type:
        payment_type = get_therapist_payment_type(therapist_email)

    # Get therapist booking interval preference if not explicitly provided
    if therapist_email and not booking_interval_type:
        therapist_info = get_therapist_info(therapist_email)
        booking_interval_type = therapist_info.get(
            "booking_interval_type", "hour_blocks"
        )

    # Default to hour blocks if still not set
    if not booking_interval_type:
        booking_interval_type = "hour_blocks"

    # Determine step intervals based on booking_interval_type setting
    if booking_interval_type == "flexible_periods":
        # Flexible periods: Use 30-minute intervals for cash pay, default intervals otherwise
        if payment_type and str(payment_type).strip().lower() == "cash_pay":
            step = timedelta(minutes=30)
        else:
            step = timedelta(minutes=step_minutes)
    else:
        # Hour blocks (default): Always use hour intervals regardless of payment type
        step = timedelta(minutes=60)

    required_free_time = timedelta(
        minutes=session_minutes
    )  # Only need session duration free

    actual_session_duration = timedelta(minutes=session_minutes)  # 45 or 55 minutes
    sessions: List[Dict[str, str]] = []

    for start, end in free_intervals:
        # Calculate the duration of this free interval
        interval_duration = (end - start).total_seconds() / 60  # in minutes

        # Skip intervals that are too short for a session
        if interval_duration < session_minutes:
            continue

        cur = start

        # Use smart session placement based on booking interval type
        if (
            booking_interval_type == "flexible_periods"
            and payment_type
            and str(payment_type).strip().lower() == "cash_pay"
        ):
            # Flexible periods for cash pay: use smart two-tier session placement with 30-min intervals
            interval_sessions = []  # Track sessions for this interval

            # TIER 1: Try standard 30-minute boundary alignment first
            cur_aligned = cur

            # Round UP to next 30-minute boundary that's within the free interval
            if cur_aligned.minute == 0 or cur_aligned.minute == 30:
                # Already on a 30-minute boundary, use as-is
                pass
            elif cur_aligned.minute < 30:
                # Round up to XX:30
                cur_aligned = cur_aligned.replace(minute=30, second=0, microsecond=0)
            else:
                # Round up to next hour
                cur_aligned = cur_aligned.replace(
                    minute=0, second=0, microsecond=0
                ) + timedelta(hours=1)

            # Ensure the aligned start is still within the free interval
            if cur_aligned < start:
                # If our alignment put us before the start, move to next valid boundary
                if start.minute <= 0:
                    cur_aligned = start.replace(minute=0, second=0, microsecond=0)
                elif start.minute <= 30:
                    cur_aligned = start.replace(minute=30, second=0, microsecond=0)
                else:
                    cur_aligned = start.replace(
                        minute=0, second=0, microsecond=0
                    ) + timedelta(hours=1)

            # Try to place sessions at standard boundaries
            while cur_aligned < end:
                if cur_aligned + required_free_time <= end:
                    interval_sessions.append(
                        {
                            "start": cur_aligned.isoformat(),
                            "end": (cur_aligned + actual_session_duration).isoformat(),
                        }
                    )
                cur_aligned += step

            # TIER 2: If no standard boundary sessions fit, try exact-fit placement
            if not interval_sessions and interval_duration >= session_minutes:
                # Use exact start time of free period for tight-fit scenarios
                exact_start = start
                if exact_start + actual_session_duration <= end:
                    interval_sessions.append(
                        {
                            "start": exact_start.isoformat(),
                            "end": (exact_start + actual_session_duration).isoformat(),
                        }
                    )

            # Add all sessions found for this interval
            sessions.extend(interval_sessions)
        else:
            # Hour blocks or insurance: Align to hour boundaries
            # First, try to align to hour boundaries within this interval
            hour_aligned_start = cur.replace(minute=0, second=0, microsecond=0)

            # If the hour boundary is before the start of free time, move to next hour
            if hour_aligned_start < start:
                hour_aligned_start += timedelta(hours=1)

            # For hour blocks, only place sessions at hour boundaries
            if booking_interval_type == "hour_blocks":
                # Place sessions only at hour boundaries
                cur_hour = hour_aligned_start
                while cur_hour + required_free_time <= end:
                    sessions.append(
                        {
                            "start": cur_hour.isoformat(),
                            "end": (cur_hour + actual_session_duration).isoformat(),
                        }
                    )
                    cur_hour += timedelta(
                        hours=1
                    )  # Always step by 1 hour for hour blocks

                # FALLBACK: If no hour-aligned sessions fit in this interval, try relaxed placement
                # This ensures availability when slots show free time but strict alignment fails
                interval_sessions_count = len([s for s in sessions if start.isoformat() <= s["start"] < end.isoformat()])
                if interval_sessions_count == 0 and interval_duration >= session_minutes:
                    # Try to fit session in the available interval even if not perfectly aligned
                    flexible_start = start
                    if flexible_start + required_free_time <= end:
                        sessions.append(
                            {
                                "start": flexible_start.isoformat(),
                                "end": (flexible_start + actual_session_duration).isoformat(),
                            }
                        )
            else:
                # Insurance or other: Try to align to hour boundaries but allow flexible placement
                if hour_aligned_start + required_free_time <= end:
                    sessions.append(
                        {
                            "start": hour_aligned_start.isoformat(),
                            "end": (
                                hour_aligned_start + actual_session_duration
                            ).isoformat(),
                        }
                    )
                    # Continue stepping from hour boundaries
                    cur = hour_aligned_start + step
                    while cur + required_free_time <= end:
                        sessions.append(
                            {
                                "start": cur.isoformat(),
                                "end": (cur + actual_session_duration).isoformat(),
                            }
                        )
                        cur += step
                else:
                    # If we can't align to hour boundary, use the actual free period
                    # Align to 15-minute boundaries for cleaner scheduling
                    if cur.minute % 15 != 0:
                        next_quarter = ((cur.minute // 15) + 1) * 15
                        if next_quarter >= 60:
                            cur = cur.replace(
                                minute=0, second=0, microsecond=0
                            ) + timedelta(hours=1)
                    else:
                        cur = cur.replace(minute=next_quarter, second=0, microsecond=0)

                    # Now step through the available time with smaller increments for flexibility
                    quarter_step = timedelta(minutes=15)
                    while cur + required_free_time <= end:
                        sessions.append(
                            {
                                "start": cur.isoformat(),
                                "end": (cur + actual_session_duration).isoformat(),
                            }
                        )
                        cur += quarter_step

                    # FALLBACK: If no sessions fit with 15-min alignment, try the exact free period
                    interval_sessions_count = len([s for s in sessions if start.isoformat() <= s["start"] < end.isoformat()])
                    if interval_sessions_count == 0 and interval_duration >= session_minutes:
                        # Use the start of the free interval directly
                        if start + required_free_time <= end:
                            sessions.append(
                                {
                                    "start": start.isoformat(),
                                    "end": (start + actual_session_duration).isoformat(),
                                }
                            )

    return sessions


# ---------- Daily availability functions ----------


def day_bounds(
    year: int, month: int, day: int, tzname: str
) -> Tuple[str, str, tz.tzfile]:
    """Get start/end bounds for a single day in the specified timezone."""
    zone = tz.gettz(tzname)
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    return day_start.strftime("%Y-%m-%d"), day_end.strftime("%Y-%m-%d"), zone


def get_daily_availability(
    *,
    calendar_id: str,
    year: int,
    month: int,
    day: int,
    tzname: str,
    work_start: Tuple[int, int] = (7, 0),
    work_end: Tuple[int, int] = (21, 0),
    slot_minutes: int = 60,
    session_minutes: int | None = None,
    payment_type: str | None = None,
    booking_interval_type: str | None = None,
    debug: bool = False,
    force_fresh: bool = False,
) -> Dict[str, Any]:
    """Get availability for a single day (efficient single-day API call)."""

    # TIMEZONE FIX: Query Google Calendar and build sessions ENTIRELY in EST
    # All therapists are in America/New_York timezone
    est_zone = tz.gettz("America/New_York")

    # Get day bounds in EST (therapist's timezone), not user's timezone
    tmin, tmax, zone = day_bounds(year, month, day, "America/New_York")

    # Reference date for timezone calculations
    ref_date = datetime(year, month, day, tzinfo=est_zone)

    # Keep times in EST - do NOT convert to user's timezone
    display_work_start = work_start  # Keep EST hours
    display_work_end = work_end      # Keep EST hours

    if debug:
        logger.info(
            f"🕒 Daily availability for {year}-{month:02d}-{day:02d} (user viewing in {tzname})"
        )
        logger.info(
            f"  EST business hours: {work_start[0]:02d}:{work_start[1]:02d}-{work_end[0]:02d}:{work_end[1]:02d}"
        )
        logger.info(
            f"  Querying Google Calendar with EST bounds: {tmin} to {tmax}"
        )
        logger.info(
            f"  Sessions will be returned in EST timezone (frontend converts to {tzname})"
        )

    # Clear cache if force_fresh requested
    if force_fresh:
        clear_cache_for_calendar(calendar_id)
        logger.info(f"🔄 Force refresh requested - cleared cache for {calendar_id}")

    # Get busy times for just this single day
    # CRITICAL FIX: Pass EST timezone offset for correct OOO block queries
    tz_offset = _get_timezone_offset("America/New_York", ref_date)
    fb = get_busy_events_from_gcalendar(
        [calendar_id],
        time_min=tmin,
        time_max=tmax,
        timezone_offset=tz_offset
    )
    cal_info = fb.get(calendar_id, {})
    busy = cal_info.get("busy", [])

    if debug:
        logger.info(
            f"  Found {len(busy)} busy blocks for {calendar_id} on {year}-{month:02d}-{day:02d}"
        )

    # Get therapist info for session duration
    effective_session_minutes = get_therapist_session_duration(
        therapist_email=calendar_id,
        payment_type=payment_type,
        explicit_session_minutes=session_minutes,
    )

    # TIMEZONE FIX: Build working hours in EST timezone (not user's timezone)
    # Frontend will handle conversion to user's local timezone for display
    est_zone = tz.gettz("America/New_York")
    day_start = datetime(
        year, month, day, display_work_start[0], display_work_start[1], tzinfo=est_zone
    )
    day_end = datetime(
        year, month, day, display_work_end[0], display_work_end[1], tzinfo=est_zone
    )

    # Generate slots for the day (in EST timezone)
    slots = build_hour_slots(
        year=year,
        month=month,
        day=day,
        zone=est_zone,  # TIMEZONE FIX: Use EST instead of user's zone
        work_start=display_work_start,
        work_end=display_work_end,
        busy_segments=busy,
        slot_minutes=slot_minutes,
        free_threshold=1.0,
    )

    # Get therapist info for payment type and detailed logging
    therapist_info = get_therapist_info(calendar_id)
    auto_detected_payment_type = therapist_info["payment_type"]

    if debug:
        logger.info(
            f"  Therapist: {therapist_info['therapist_name']} ({therapist_info['program']})"
        )
        logger.info(f"  Auto-detected payment type: {auto_detected_payment_type}")
        logger.info(f"  Session duration: {effective_session_minutes} minutes")
        logger.info(
            f"  Booking interval type: {therapist_info['booking_interval_type']}"
        )

    # Compute free intervals within business hours and build sessions (in EST timezone)
    free_for_day = compute_business_hours_free_intervals(busy, day_start, day_end, est_zone)
    sessions = build_session_windows(
        free_for_day,
        session_minutes=effective_session_minutes,
        step_minutes=60,
        payment_type=auto_detected_payment_type,  # Use auto-detected type
        therapist_email=calendar_id,
        booking_interval_type=booking_interval_type,
    )

    # Build response in same format as monthly availability
    day_payload = {
        "slots": slots,
        "sessions": sessions,
        "summary": {
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
            "session_count": len(sessions),
        },
    }

    if debug:
        logger.info(f"  Generated {len(sessions)} available sessions")

    return {
        "days": {day: day_payload},
        "therapist_info": {
            **therapist_info,  # Include all auto-detected therapist info
            "timezone": tzname,
            "working_hours": f"{display_work_start[0]:02d}:{display_work_start[1]:02d}-{display_work_end[0]:02d}:{display_work_end[1]:02d}",
        },
    }


# ---------- Efficient monthly availability (compiled from daily calls) ----------


def get_monthly_availability_efficient(
    *,
    calendar_id: str,
    year: int,
    month: int,
    tzname: str,
    work_start: Tuple[int, int] = (7, 0),
    work_end: Tuple[int, int] = (21, 0),
    slot_minutes: int = 60,
    session_minutes: int | None = None,
    payment_type: str | None = None,
    debug: bool = False,
    force_fresh: bool = False,
) -> Dict[str, Any]:
    """Get monthly availability by compiling daily calls (efficient approach)."""

    import calendar as calmod

    if debug:
        logger.info(
            f"📅 [EFFICIENT MONTHLY] Compiling from daily calls for {calendar_id}"
        )
        logger.info(f"  Period: {year}-{month:02d} in timezone {tzname}")

    # Get number of days in the month
    days_in_month = calmod.monthrange(year, month)[1]

    # Compile daily availability for each day
    monthly_days = {}
    total_sessions = 0
    days_with_availability = 0

    for day in range(1, days_in_month + 1):
        try:
            # Get daily availability for this specific day
            daily_data = get_daily_availability(
                calendar_id=calendar_id,
                year=year,
                month=month,
                day=day,
                tzname=tzname,
                work_start=work_start,
                work_end=work_end,
                slot_minutes=slot_minutes,
                session_minutes=session_minutes,
                payment_type=payment_type,
                debug=False,  # Don't spam debug logs for each day
                force_fresh=force_fresh,
            )

            # Extract the day's data from the daily response
            day_data = daily_data.get("days", {}).get(day, {})
            if day_data:
                monthly_days[day] = day_data
                session_count = len(day_data.get("sessions", []))
                total_sessions += session_count
                if session_count > 0:
                    days_with_availability += 1

                if debug:
                    logger.info(f"  Day {day:2d}: {session_count} sessions available")

        except Exception as e:
            logger.error(f"Error compiling day {day} for {calendar_id}: {str(e)}")
            # Add empty day data to prevent breaking
            monthly_days[day] = {
                "date": f"{year}-{month:02d}-{day:02d}",
                "slots": [],
                "sessions": [],
                "summary": {"error": str(e)},
            }

    # Get therapist info once for the entire month
    therapist_info = None
    effective_session_minutes = None
    try:
        from src.db import get_db_session
        from src.db.models import Therapist

        with get_db_session() as db:
            therapist = (
                db.query(Therapist).filter(Therapist.email == calendar_id).first()
            )
            if therapist:
                therapist_info = {
                    "email": therapist.email,
                    "name": getattr(therapist, "intern_name", "")
                    or getattr(therapist, "name", ""),
                    "program": getattr(therapist, "program", "") or "MFT",
                    "accepting_new_clients": getattr(
                        therapist, "accepting_new_clients", True
                    ),
                }
    except Exception as e:
        logger.warning(f"Could not fetch therapist info for {calendar_id}: {e}")

    # Get session duration
    effective_session_minutes = get_therapist_session_duration(
        therapist_email=calendar_id,
        payment_type=payment_type,
        explicit_session_minutes=session_minutes,
    )

    # Determine supported payment types based on therapist program
    if therapist_info and therapist_info.get("program"):
        program = therapist_info["program"]
        if program == "Limited Permit":
            supported_payment_types = ["insurance"]
        elif program in ["MFT", "MHC", "MSW"]:
            supported_payment_types = ["cash_pay", "insurance"]
        else:
            supported_payment_types = ["cash_pay"]
    else:
        supported_payment_types = ["cash_pay"]

    if debug:
        logger.info(
            f"  ✅ Compiled {days_with_availability}/{days_in_month} days with availability"
        )
        logger.info(f"  📊 Total sessions: {total_sessions}")

    # Build response in same format as original function
    return {
        "meta": {
            "calendar_id": calendar_id,
            "year": year,
            "month": month,
            "tzname": tzname,
            "work_start": work_start,
            "work_end": work_end,
            "slot_minutes": slot_minutes,
            "session_minutes": effective_session_minutes,
            "payment_type": payment_type,
            "compilation_method": "daily_calls",  # Indicates this was compiled from daily calls
        },
        "days": monthly_days,
        "therapist_info": therapist_info
        or {
            "email": calendar_id,
            "name": "Unknown",
            "program": "Unknown",
            "accepting_new_clients": "Unknown",
        },
        "booking_info": {
            "session_duration_minutes": effective_session_minutes,
            "payment_type": payment_type,
            "supported_payment_types": supported_payment_types,
            "timezone": tzname,
            "work_hours": {
                "start": f"{work_start[0]:02d}:{work_start[1]:02d}",
                "end": f"{work_end[0]:02d}:{work_end[1]:02d}",
            },
            "slot_duration_minutes": slot_minutes,
        },
    }


# ---------- High-level API (caching disabled for live updates) ----------
# @with_cache(ttl_seconds=60)  # Cache for 1 minute (reduced from 5 minutes)
def get_monthly_availability(
    *,
    calendar_id: str,
    year: int,
    month: int,
    tzname: str,
    work_start: Tuple[int, int] = (7, 0),
    work_end: Tuple[int, int] = (21, 0),
    slot_minutes: int = 60,
    session_minutes: int | None = None,
    payment_type: str | None = None,
    debug: bool = False,
    force_fresh: bool = False,
) -> Dict[str, Any]:
    """Get monthly availability with caching.

    Note: work_start and work_end are always interpreted as EST business hours (7am-10pm EST),
    but results are converted to the user's requested timezone (tzname) for display.
    """
    # ALWAYS force fresh data since caching is disabled for live updates
    clear_cache_for_calendar(calendar_id)
    logger.info(
        f"🔄 LIVE UPDATES: Always fetching fresh data for {calendar_id} (caching disabled)"
    )

    # TIMEZONE FIX: Query Google Calendar and build sessions ENTIRELY in EST
    # All therapists are in America/New_York timezone
    # Frontend will handle conversion to user's local timezone for display
    est_zone = tz.gettz("America/New_York")

    # Get month bounds in EST (therapist's timezone), not user's timezone
    # This ensures we query the correct day range for the therapist's calendar
    tmin, tmax, zone = month_bounds(year, month, "America/New_York")

    # Create a reference time to calculate timezone offset for OOO block queries
    ref_date = datetime(year, month, 1, tzinfo=est_zone)

    # Keep times in EST - do NOT convert to user's timezone
    # This prevents double conversion (backend converts + frontend converts again)
    display_work_start = work_start  # Keep EST hours
    display_work_end = work_end      # Keep EST hours

    logger.info(f"🕒 Building availability in EST (frontend will convert to {tzname} for display):")
    logger.info(
        f"  EST business hours: {work_start[0]:02d}:{work_start[1]:02d}-{work_end[0]:02d}:{work_end[1]:02d}"
    )
    logger.info(
        f"  Querying Google Calendar with EST bounds: {tmin} to {tmax}"
    )
    logger.info(
        f"  Sessions will be returned in EST timezone"
    )

    # Get busy times (this is cached and rate limited)
    # CRITICAL FIX: Pass EST timezone offset for correct OOO block queries
    tz_offset = _get_timezone_offset("America/New_York", ref_date)
    fb = get_busy_events_from_gcalendar(
        [calendar_id],
        time_min=tmin,
        time_max=tmax,
        timezone_offset=tz_offset
    )
    cal_info = fb.get(calendar_id, {})
    busy = cal_info.get("busy", [])

    # Enhanced debugging for calendar availability
    is_debug_therapist = calendar_id.lower() in [
        "adam.hirsch@solhealth.co",
        "katie.ross@solhealth.co",
        "ahirsch@solhealth.co",
        "kross@solhealth.co",
    ]
    should_debug = debug or is_debug_therapist

    if should_debug:
        logger.info("=" * 80)
        logger.info(f"📅 [DETAILED AVAILABILITY DEBUG] {calendar_id}")
        logger.info(f"  Period: {year}-{month:02d} in timezone {tzname}")
        logger.info(f"  Query Range: {tmin} to {tmax}")

        # Check if data is from cache
        cache_lookup_key = f"get_busy_events_from_gcalendar{cache_key([calendar_id], time_min=tmin, time_max=tmax)}"
        is_cached = cache_lookup_key in _CACHE
        if is_cached:
            cache_age = time.time() - _CACHE[cache_lookup_key][0]
            logger.info(f"  📊 Cache Status: HIT (age: {cache_age:.1f}s)")
        else:
            logger.info(f"  📊 Cache Status: MISS (fresh API call)")

        logger.info("")
        logger.info("🕐 WORKING HOURS ANALYSIS:")
        logger.info(
            f"  EST Business Hours: {work_start[0]:02d}:{work_start[1]:02d}-{work_end[0]:02d}:{work_end[1]:02d} EST"
        )
        logger.info(f"  Display Timezone: {tzname}")
        logger.info(
            f"  Display Hours: {display_work_start[0]:02d}:{display_work_start[1]:02d}-{display_work_end[0]:02d}:{display_work_end[1]:02d}"
        )

        # Calculate days in month first
        days_in_month = calmod.monthrange(year, month)[1]

        # Calculate theoretical maximums
        work_hours_per_day = (work_end[0] - work_start[0]) + (
            (work_end[1] - work_start[1]) / 60
        )
        theoretical_slots_per_day = int(work_hours_per_day * (60 / slot_minutes))
        theoretical_total_slots = theoretical_slots_per_day * days_in_month

        logger.info(f"  Work Hours Per Day: {work_hours_per_day:.1f} hours")
        logger.info(
            f"  Theoretical Slots Per Day: {theoretical_slots_per_day} ({slot_minutes}min slots)"
        )
        logger.info(f"  Days in Month: {days_in_month}")
        logger.info(f"  Max Possible Slots: {theoretical_total_slots}")

        # Log busy events summary
        logger.info("")
        logger.info(f"🚫 BLOCKED EVENTS SUMMARY:")
        logger.info(f"  Total Blocked Events Found: {len(busy)}")

        if busy:
            logger.info("  Event Details:")
            for i, event in enumerate(busy, 1):
                try:
                    start_dt = datetime.fromisoformat(event["start"])
                    end_dt = datetime.fromisoformat(event["end"])
                    duration = (end_dt - start_dt).total_seconds() / 3600  # hours

                    # Convert to display timezone
                    start_local = start_dt.astimezone(tz.gettz(tzname))
                    end_local = end_dt.astimezone(tz.gettz(tzname))

                    logger.info(
                        f"    {i}. {start_local.strftime('%Y-%m-%d %H:%M')} - {end_local.strftime('%H:%M')} ({duration:.1f}h)"
                    )
                except Exception as e:
                    logger.info(f"    {i}. [Parse Error: {event}] ({e})")
        else:
            logger.info("  No blocked events found!")

        logger.info("")
        logger.info("📊 DAY-BY-DAY BREAKDOWN:")

    # Calculate days in month (needed for non-debug mode too)
    if not should_debug:
        days_in_month = calmod.monthrange(year, month)[1]

    out: Dict[str, Any] = {
        "meta": {
            "calendar_id": calendar_id,
            "year": year,
            "month": month,
            "timezone": tzname,
            "work_start": f"{display_work_start[0]:02d}:{display_work_start[1]:02d}",
            "work_end": f"{display_work_end[0]:02d}:{display_work_end[1]:02d}",
            "slot_minutes": slot_minutes,
        },
        "days": {},
    }

    # Track totals for debugging
    debug_totals = {
        "total_available_sessions": 0,
        "total_available_days": 0,
        "total_blocked_hours": 0,
        "days_with_no_availability": 0,
    }

    for d in range(1, days_in_month + 1):
        summary = compute_day_availability(
            busy, year, month, d, zone, display_work_start, display_work_end
        )
        slots = build_hour_slots(
            year,
            month,
            d,
            zone,
            display_work_start,
            display_work_end,
            summary["segments"],
            slot_minutes,
        )
        day_payload: Dict[str, Any] = {"summary": summary, "slots": slots}

        # Enhanced day-by-day debugging
        if should_debug:
            day_date = datetime(year, month, d, tzinfo=zone)
            day_name = day_date.strftime("%A")

            # Count available slots for this day
            available_slots = sum(1 for slot in slots if slot.get("is_free", False))

            logger.info(f"")
            logger.info(f"  📅 {year}-{month:02d}-{d:02d} ({day_name}):")
            logger.info(f"    Theoretical Slots: {theoretical_slots_per_day}")

            # Show blocked events for this specific day
            day_blocked_events = []
            for event in busy:
                try:
                    event_start = datetime.fromisoformat(event["start"])
                    event_end = datetime.fromisoformat(event["end"])
                    event_date = event_start.date()

                    if event_date == day_date.date() or (
                        event_start.date() <= day_date.date() <= event_end.date()
                    ):
                        # Convert to local timezone for display
                        start_local = event_start.astimezone(zone)
                        end_local = event_end.astimezone(zone)
                        duration_hours = (
                            event_end - event_start
                        ).total_seconds() / 3600

                        day_blocked_events.append(
                            {
                                "start": start_local,
                                "end": end_local,
                                "duration": duration_hours,
                            }
                        )
                        debug_totals["total_blocked_hours"] += duration_hours
                except Exception:
                    pass

            if day_blocked_events:
                logger.info(f"    Blocked Events: {len(day_blocked_events)}")
                for i, blocked in enumerate(day_blocked_events, 1):
                    logger.info(
                        f"      🚫 {i}. {blocked['start'].strftime('%H:%M')}-{blocked['end'].strftime('%H:%M')} ({blocked['duration']:.1f}h)"
                    )
            else:
                logger.info(f"    Blocked Events: None")

            logger.info(
                f"    Available Slots: {available_slots}/{theoretical_slots_per_day}"
            )
            logger.info(f"    Free Ratio: {summary['free_ratio']:.2%}")

            if available_slots > 0:
                debug_totals["total_available_days"] += 1
                available_slot_times = [
                    slot["start"] for slot in slots if slot.get("is_free", False)
                ]
                if available_slot_times:
                    times_display = [
                        datetime.fromisoformat(t).strftime("%H:%M")
                        for t in available_slot_times[:5]
                    ]
                    more_indicator = (
                        f" + {len(available_slot_times) - 5} more"
                        if len(available_slot_times) > 5
                        else ""
                    )
                    logger.info(
                        f"    Available Times: {', '.join(times_display)}{more_indicator}"
                    )
            else:
                debug_totals["days_with_no_availability"] += 1

        # Get therapist information for enhanced response
        therapist_info = None
        try:
            from src.db import get_db_session
            from src.db.models import Therapist

            session = get_db_session()
            try:
                therapist = (
                    session.query(Therapist)
                    .filter(Therapist.email == calendar_id)
                    .first()
                )
                if therapist:
                    therapist_info = {
                        "email": therapist.email,
                        "name": therapist.name,
                        "program": therapist.program,
                        "accepting_new_clients": therapist.accepting_new_clients,
                    }
            finally:
                session.close()
        except Exception as e:
            logger.warning(
                f"Could not lookup therapist info for {calendar_id}: {str(e)}"
            )

        # Get therapist info and auto-detect payment type
        therapist_info = get_therapist_info(calendar_id)
        auto_detected_payment_type = therapist_info["payment_type"]

        # Determine session length using unified logic
        effective_session_minutes = get_therapist_session_duration(
            therapist_email=calendar_id,
            payment_type=auto_detected_payment_type,
            explicit_session_minutes=session_minutes,
        )

        if effective_session_minutes:
            free_for_day = compute_full_day_free_intervals(busy, year, month, d, zone)
            sessions = build_session_windows(
                free_for_day,
                session_minutes=effective_session_minutes,
                step_minutes=60,
                payment_type=auto_detected_payment_type,
                therapist_email=calendar_id,
                booking_interval_type=None,  # Use therapist's default setting
            )
            day_payload["sessions"] = sessions

        out["days"][d] = day_payload

        # Count available sessions for debug totals
        if should_debug:
            debug_totals["total_available_sessions"] += len(
                day_payload.get("sessions", [])
            )

    # Final debug summary
    if should_debug:
        logger.info("")
        logger.info("📊 FINAL AVAILABILITY SUMMARY:")
        logger.info(
            f"  Total Available Sessions: {debug_totals['total_available_sessions']}"
        )
        logger.info(
            f"  Days with Availability: {debug_totals['total_available_days']}/{days_in_month}"
        )
        logger.info(
            f"  Days with NO Availability: {debug_totals['days_with_no_availability']}/{days_in_month}"
        )
        logger.info(
            f"  Total Blocked Hours: {debug_totals['total_blocked_hours']:.1f} hours"
        )
        logger.info(f"  Max Theoretical Sessions: {theoretical_total_slots}")

        if debug_totals["total_available_sessions"] == 0:
            logger.warning(
                "⚠️  WARNING: No availability found despite theoretical capacity!"
            )
            logger.warning("   Check if blocked events are covering all working hours")
        elif debug_totals["total_available_sessions"] < (
            theoretical_total_slots * 0.1
        ):  # Less than 10% of theoretical
            logger.warning(
                f"⚠️  WARNING: Very low availability ({debug_totals['total_available_sessions']}/{theoretical_total_slots} = {debug_totals['total_available_sessions']/theoretical_total_slots:.1%})"
            )

        logger.info("=" * 80)

    # Add therapist metadata and booking information to response
    out["therapist_info"] = therapist_info or {
        "email": calendar_id,
        "name": "Unknown",
        "program": "Unknown",
        "accepting_new_clients": "Unknown",
    }

    out["booking_info"] = {
        "session_duration_minutes": effective_session_minutes,
        "payment_type": payment_type,
        "timezone": tzname,
        "work_hours": {
            "start": f"{work_start[0]:02d}:{work_start[1]:02d}",
            "end": f"{work_end[0]:02d}:{work_end[1]:02d}",
        },
        "slot_duration_minutes": slot_minutes,
    }

    # Determine supported payment types based on therapist program
    if therapist_info and therapist_info.get("program"):
        program = therapist_info["program"]
        if program == "Limited Permit":
            supported_payment_types = ["insurance"]
        elif program in ["MFT", "MHC", "MSW"]:
            supported_payment_types = ["cash_pay", "insurance"]
        else:
            supported_payment_types = ["cash_pay"]  # default
    else:
        supported_payment_types = ["cash_pay"]  # fallback

    out["booking_info"]["supported_payment_types"] = supported_payment_types

    return out


# @with_cache(ttl_seconds=60)  # Cache for 1 minute (reduced from 5 minutes)
def get_monthly_sessions(
    *,
    calendar_id: str,
    year: int,
    month: int,
    tzname: str,
    payment_type: str | None = None,
    session_minutes: int | None = None,
    work_start: Tuple[int, int] = (7, 0),
    work_end: Tuple[int, int] = (21, 0),
) -> List[Dict[str, str]]:
    """Get monthly sessions with caching disabled for live updates."""
    data = get_monthly_availability_efficient(
        calendar_id=calendar_id,
        year=year,
        month=month,
        tzname=tzname,
        work_start=work_start,
        work_end=work_end,
        slot_minutes=60,
        session_minutes=session_minutes,
        payment_type=payment_type,
    )
    sessions: List[Dict[str, str]] = []
    for payload in data.get("days", {}).values():
        sessions.extend(payload.get("sessions", []))
    sessions.sort(key=lambda x: x["start"])
    return sessions


# ---------- Calendar Event Creation (with Google Meets support) ----------
# @rate_limit(min_interval=0.5)  # Rate limiting disabled for live updates
def create_gcalendar_event(
    summary: str,
    start_time: datetime,
    attendees: List[Dict[str, str]],
    duration_minutes: int = 45,
    description: str = None,
    join_url: str = None,
    timezone_name: str = "UTC",
    send_updates: str = "all",
    create_meets_link: bool = True,
) -> Dict[str, Any] | None:
    """
    Create a Google Calendar event with optional Google Meets link.
    Based on legacy_google_calendar.py implementation.

    Args:
        summary: Event title/summary
        start_time: Event start datetime (should be timezone-aware)
        attendees: List of attendees with 'email' and 'name' keys
        duration_minutes: Event duration in minutes (default 45)
        description: Event description (supports HTML)
        join_url: Custom meeting URL (overrides Google Meets creation)
        timezone_name: Timezone name for the event (default UTC)
        send_updates: Send calendar notifications ('all', 'externalOnly', 'none')
        create_meets_link: Auto-create Google Meets link if join_url not provided

    Returns:
        Dict with event data including Google Meets link, or None if failed
    """
    logger.info(f"🔄 Creating Google Calendar event: {summary}")
    logger.info(f"  Start time: {start_time}")
    logger.info(f"  Duration: {duration_minutes} minutes")
    logger.info(f"  Attendees: {[a.get('email') for a in attendees]}")
    logger.info(f"  Create Meets: {create_meets_link}")

    service = _get_service(_CONTACT_EMAIL)

    try:
        # Calculate end time
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Convert times to ISO format with timezone (following legacy pattern)
        if start_time.tzinfo is None:
            logger.warning("⚠️ start_time has no timezone info, assuming UTC")
            start_time = start_time.replace(tzinfo=timezone.utc)

        start_time_iso = start_time.astimezone(timezone.utc).isoformat()
        end_time_iso = end_time.astimezone(timezone.utc).isoformat()

        logger.info(f"  ISO start: {start_time_iso}")
        logger.info(f"  ISO end: {end_time_iso}")

        # Build event object (based on legacy implementation)
        event = {
            "summary": summary,
            "description": description
            or f"Sol Health therapy appointment with {', '.join([a.get('name', a.get('email', 'Unknown')) for a in attendees])}",
            "start": {
                "dateTime": start_time_iso,
                "timeZone": timezone_name,
            },
            "end": {
                "dateTime": end_time_iso,
                "timeZone": timezone_name,
            },
            "attendees": [
                {
                    "email": attendee["email"],
                    "displayName": attendee.get("name", attendee["email"]),
                    "responseStatus": "accepted",
                }
                for attendee in attendees
            ],
            "reminders": {"useDefault": True},
        }

        # Add Google Meets link or custom join URL (from legacy implementation)
        conference_data_version = 0
        if join_url:
            # Custom meeting URL provided
            logger.info(f"  Using custom join URL: {join_url}")
            event["conferenceData"] = {
                "entryPoints": [
                    {
                        "entryPointType": "video",
                        "uri": join_url,
                        "label": "meet.google.com"
                        if "meet.google.com" in join_url
                        else "Sol Health Video Call",
                    }
                ],
                "conferenceSolution": {
                    "key": {
                        "type": "hangoutsMeet"
                        if "meet.google.com" in join_url
                        else "addOn"
                    },
                    "name": "Google Meet"
                    if "meet.google.com" in join_url
                    else "Sol Health Video Call",
                },
            }
            conference_data_version = 1
        elif create_meets_link:
            # Auto-create Google Meets link
            logger.info("  Auto-creating Google Meets link")
            event["conferenceData"] = {
                "createRequest": {
                    "requestId": f"sol-health-{int(start_time.timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            conference_data_version = 1

        # Create the event with timeout protection
        logger.info("  📤 Sending event to Google Calendar API...")
        import signal

        def calendar_timeout_handler(signum, frame):
            raise TimeoutError("Google Calendar API timeout")

        # Set 10-second timeout for calendar creation
        signal.signal(signal.SIGALRM, calendar_timeout_handler)
        signal.alarm(10)

        try:
            created_event = (
                service.events()
                .insert(
                    calendarId="primary",
                    body=event,
                    sendUpdates=send_updates,
                    supportsAttachments=True,
                    conferenceDataVersion=conference_data_version,
                )
                .execute()
            )
        except TimeoutError:
            logger.warning(
                "⚠️ Google Calendar API timeout - proceeding without calendar event"
            )
            return {"success": False, "error": "Calendar API timeout", "timeout": True}
        finally:
            signal.alarm(0)  # Cancel the timeout

        # Extract Google Meets link from response
        meets_link = None
        if created_event.get("conferenceData") and created_event["conferenceData"].get(
            "entryPoints"
        ):
            for entry_point in created_event["conferenceData"]["entryPoints"]:
                if entry_point.get("entryPointType") == "video":
                    meets_link = entry_point.get("uri")
                    break

        event_id = created_event.get("id")
        event_link = created_event.get("htmlLink")

        logger.info("✅ Google Calendar event created successfully")
        logger.info(f"  Event ID: {event_id}")
        logger.info(f"  Event Link: {event_link}")
        logger.info(f"  Google Meets Link: {meets_link or 'None'}")

        return {
            "success": True,
            "event_id": event_id,
            "event_link": event_link,
            "meets_link": meets_link,
            "event_data": created_event,
            "summary": summary,
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "attendees": attendees,
        }

    except HttpError as e:
        logger.error(f"❌ Failed to create Google Calendar event: {e}")
        logger.error(f"  Error details: {str(e)}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Unexpected error creating calendar event: {e}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        try:
            service.close()
        except Exception:
            pass


# @rate_limit(min_interval=0.3)  # Rate limiting disabled for live updates
def update_gcalendar_event(
    event_id: str,
    start_time: datetime = None,
    duration_minutes: int = 45,
    timezone_name: str = "UTC",
    summary: str = None,
    description: str = None,
    attendees: List[Dict[str, str]] = None,
) -> Dict[str, Any] | None:
    """
    Update an existing Google Calendar event.
    Based on legacy implementation with enhancements.

    Args:
        event_id: ID of the event to update
        start_time: New event start time (optional)
        duration_minutes: Event duration in minutes
        timezone_name: Timezone for the event
        summary: New event title (optional)
        description: New event description (optional)
        attendees: New attendees list (optional)

    Returns:
        Dict with updated event data or None if failed
    """
    logger.info(f"🔄 Updating Google Calendar event: {event_id}")

    service = _get_service(_CONTACT_EMAIL)

    try:
        # First get the existing event
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        # Update fields if provided
        if start_time:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            event["start"] = {
                "dateTime": start_time.astimezone(timezone.utc).isoformat(),
                "timeZone": timezone_name,
            }
            event["end"] = {
                "dateTime": (start_time + timedelta(minutes=duration_minutes))
                .astimezone(timezone.utc)
                .isoformat(),
                "timeZone": timezone_name,
            }

        if summary:
            event["summary"] = summary

        if description:
            event["description"] = description

        if attendees:
            event["attendees"] = [
                {
                    "email": attendee["email"],
                    "displayName": attendee.get("name", attendee["email"]),
                    "responseStatus": "accepted",
                }
                for attendee in attendees
            ]

        # Update the event
        updated_event = (
            service.events()
            .update(
                calendarId="primary",
                eventId=event_id,
                body=event,
                sendUpdates="all",
                supportsAttachments=True,
                conferenceDataVersion=1 if event.get("conferenceData") else 0,
            )
            .execute()
        )

        logger.info(f"✅ Google Calendar event updated: {event_id}")
        return {"success": True, "event_data": updated_event}

    except HttpError as e:
        logger.error(f"❌ Failed to update Google Calendar event: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Unexpected error updating calendar event: {e}")
        return {"success": False, "error": str(e)}
    finally:
        try:
            service.close()
        except Exception:
            pass
 