# src/api/availability.py
from __future__ import annotations

import calendar as calmod
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from dateutil import tz
from flask import Blueprint, jsonify, request

from src.db import get_db_session
from src.db.models import Therapist

# Must exist in your codebase:
# get_monthly_availability(calendar_id, year, month, tzname, work_start, work_end,
#                          slot_minutes, session_minutes, payment_type, debug)
from src.utils.google.google_calendar import (
    get_daily_availability,
    get_monthly_availability,
    get_monthly_availability_efficient,
    get_therapist_session_duration,
)

availability_bp = Blueprint("availability", __name__)
logger = logging.getLogger(__name__)


# ------------------ helpers ------------------


def _parse_hhmm(s: str, fallback: Tuple[int, int]) -> Tuple[int, int]:
    try:
        hh, mm = s.split(":")
        return int(hh), int(mm)
    except Exception:
        return fallback


def _to_minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _from_minutes(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _merge_ranges(ranges: List[Tuple[str, str]]) -> List[str]:
    """
    Merge touching/overlapping HH:MM intervals to keep output concise.
    """
    if not ranges:
        return []
    rs = sorted(ranges, key=lambda r: _to_minutes(r[0]))
    merged: List[Tuple[str, str]] = [rs[0]]
    for s, e in rs[1:]:
        ls, le = merged[-1]
        if _to_minutes(s) <= _to_minutes(le):  # touching/overlap
            merged[-1] = (ls, e if _to_minutes(e) > _to_minutes(le) else le)
        else:
            merged.append((s, e))
    return [f"{a}-{b}" for a, b in merged]


def _hhmm(dt_str: str, default: str) -> str:
    # Expect "YYYY-MM-DDTHH:MM:SS±HH:MM"
    if not dt_str or "T" not in dt_str:
        return default
    return dt_str.split("T", 1)[1][:5]


def _extract_day_free_busy(
    day_payload: dict,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], str, str]:
    """
    Returns:
      free_pairs: list of ("HH:MM","HH:MM") hour blocks marked free
      busy_pairs: list of ("HH:MM","HH:MM") blocks marked busy/partial
      day_start/day_end as "HH:MM"
    We trust backend to emit 60m slots; we take only full-hour blocks for 'free' if is_free or free_ratio~1.
    Any block that is not fully free is considered busy (captures the 15:30 → next slot 16:00 logic).
    """
    if not isinstance(day_payload, dict):
        logger.warning(f"Invalid day_payload type: {type(day_payload)}")
        return [], [], "07:00", "22:00"

    # Handle both "slots" and "sessions" formats for compatibility
    slots = day_payload.get("slots", [])
    if not slots and "sessions" in day_payload:
        # Convert sessions format to slots format for processing
        sessions = day_payload.get("sessions", [])
        slots = []
        for session in sessions:
            slots.append(
                {
                    "start": session.get("start", ""),
                    "end": session.get("end", ""),
                    "is_free": True,
                    "free_ratio": 1.0,
                }
            )

    free_pairs: List[Tuple[str, str]] = []
    busy_pairs: List[Tuple[str, str]] = []

    for s in slots:
        if not isinstance(s, dict):
            continue
        st = _hhmm(s.get("start", ""), "")
        en = _hhmm(s.get("end", ""), "")
        if not st or not en:
            continue
        # Only consider on-the-hour blocks as bookable slots
        if st.endswith(":00") and en.endswith(":00"):
            if s.get("is_free") or (s.get("free_ratio", 0) >= 0.999):
                free_pairs.append((st, en))
            else:
                busy_pairs.append((st, en))
        else:
            # Any partial-hour block contributes to busy ranges (prevents showing the overlapping hour slot)
            if st and en:
                busy_pairs.append((st, en))

    summary = day_payload.get("summary", {})
    dstart = _hhmm(summary.get("day_start", ""), "07:00")
    dend = _hhmm(summary.get("day_end", ""), "22:00")
    return free_pairs, busy_pairs, dstart, dend


def _days_iter(month_obj) -> List[Tuple[str, dict]]:
    """
    Accepts:
      - dict keyed by "1"/"01"/"21" → payload
      - list of {"date":"YYYY-MM-DD", ...}
    Returns sorted [("DD", payload), ...]
    """
    if isinstance(month_obj, dict):
        items = []
        for k, v in month_obj.items():
            try:
                day_num = int(str(k))
                items.append((f"{day_num:02d}", v))
            except Exception:
                if isinstance(k, str) and len(k) >= 10 and k[4] == "-" and k[7] == "-":
                    try:
                        day_num = int(k[8:10])
                        items.append((f"{day_num:02d}", v))
                    except Exception:
                        continue
        items.sort(key=lambda x: int(x[0]))
        return items

    if isinstance(month_obj, list):
        items = []
        for d in month_obj:
            datestr = d.get("date", "")
            if len(datestr) >= 10 and datestr[4] == "-" and datestr[7] == "-":
                dd = datestr[8:10]
                items.append((dd, d))
        items.sort(key=lambda x: int(x[0]))
        return items

    return []


def _map_payment_type(pmt: str | None) -> str:
    if not pmt:
        return "cash_pay"
    p = pmt.strip().lower()
    if p in ("ins", "insurance"):
        return "insurance"
    if p in ("oop", "cash_pay", "cash"):
        return "cash_pay"
    return p  # already a proper value


def _derive_session_minutes(
    therapist_email: str, payment_type: str, explicit_session: int | None
) -> int:
    """Use unified session duration logic"""
    return get_therapist_session_duration(
        therapist_email=therapist_email,
        payment_type=payment_type,
        explicit_session_minutes=explicit_session,
    )


def _month_offsets(year: int, month: int, n: int) -> List[Tuple[int, int]]:
    """Return [(year, month), (year, month+1), ...] length n."""
    out = []
    y, m = year, month
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def _date_of(year: int, month: int, dd: str) -> datetime:
    return datetime(year, month, int(dd))


def _within(date_dt: datetime, start_dt: datetime, end_dt: datetime) -> bool:
    return start_dt.date() <= date_dt.date() <= end_dt.date()


# ------------------ endpoint ------------------


@availability_bp.route("/therapists/<therapist_email>/availability", methods=["GET"])
def get_therapist_availability(therapist_email: str):
    """
    Default behavior:
      - Derives session minutes from pmt (INS→55, OOP→45); slot_minutes default 60
      - Fetches **this month + next 2 months**
      - Two presentation modes via `mode=`:
          mode=exp  → Expanded: show entire 3 months
          mode=cmp  → Compact: show a rolling 16-day window (today + 15 days)
      - `view=text` → terminal-friendly single-line/day with busy and slots
      - `view=compact` → small JSON with merged busy + per-hour 'slots'
      - (no view) → original monthly JSON(s) from get_monthly_availability
    """
    try:
        tzname = request.args.get("timezone", "America/New_York")
        now_tz = datetime.now(tz.gettz(tzname))

        # start month (defaults to "this month" in tz)
        start_year = int(request.args.get("year", now_tz.year))
        start_month = int(request.args.get("month", now_tz.month))

        # months to fetch (3 by default)
        months_count = max(1, int(request.args.get("months", 3)))

        # mode: 'exp' (3 full months) or 'cmp' (rolling 16 days)
        mode = (request.args.get("mode") or "exp").lower()
        if mode not in ("exp", "cmp"):
            mode = "exp"

        # pmt: INS/OOP shorthands accepted
        payment_type = _map_payment_type(
            request.args.get("payment_type") or request.args.get("pmt")
        )

        # timings
        work_start = _parse_hhmm(request.args.get("work_start", "07:00"), (7, 0))
        work_end = _parse_hhmm(request.args.get("work_end", "22:00"), (22, 0))
        slot_minutes = int(request.args.get("slot_minutes", 60))  # keep hour grid
        session_minutes = request.args.get("session_minutes")
        session_minutes = int(session_minutes) if session_minutes else None
        session_minutes = _derive_session_minutes(
            therapist_email, payment_type, session_minutes
        )

        # toggles
        live_check = request.args.get("live", "false").lower() == "true"
        debug_mode = request.args.get("debug", "false").lower() == "true"
        view = (request.args.get("view") or "").lower()

        logger.info(
            f"[Avail] {therapist_email} start={start_year}-{start_month:02d} months={months_count} "
            f"tz={tzname} pmt={payment_type} slot={slot_minutes}m session={session_minutes}m "
            f"mode={mode} live={live_check} debug={debug_mode}"
        )

        # Clear cache if live check requested
        if live_check:
            logger.info("🔄 Live check requested - clearing cache for fresh data")
            try:
                from src.utils.google.google_calendar import clear_cache_for_calendar

                cleared_count = clear_cache_for_calendar(therapist_email)
                logger.info(f"  Cleared {cleared_count} cache entries for live check")
            except ImportError:
                logger.warning("  Cache clearing function not available")

        # fetch months
        months_meta: List[Tuple[int, int]] = _month_offsets(
            start_year, start_month, months_count
        )
        raw_months: List[Dict] = []
        for y, m in months_meta:
            try:
                data = get_monthly_availability_efficient(
                    calendar_id=therapist_email,
                    year=y,
                    month=m,
                    tzname=tzname,
                    work_start=work_start,
                    work_end=work_end,
                    slot_minutes=slot_minutes,
                    session_minutes=None,  # Will be auto-detected
                    payment_type=None,  # Will be auto-detected
                    debug=debug_mode,
                    force_fresh=live_check,
                )
                if isinstance(data, dict):
                    data.setdefault("_source_month", {"year": y, "month": m})

                    # Add has_bookable_sessions field to each day for frontend coloring logic
                    days = data.get("days", {})
                    for day_key, day_data in days.items():
                        if isinstance(day_data, dict):
                            sessions = day_data.get("sessions", [])
                            day_data["has_bookable_sessions"] = len(sessions) > 0

                    raw_months.append(data)
                else:
                    logger.warning(
                        f"get_monthly_availability returned non-dict for {therapist_email} {y}-{m:02d}: {type(data)}"
                    )
                    # Add empty month placeholder
                    raw_months.append(
                        {
                            "days": {},
                            "error": "Invalid data format",
                            "_source_month": {"year": y, "month": m},
                        }
                    )
            except Exception as e:
                logger.error(
                    f"Failed to get availability for {therapist_email} {y}-{m:02d}: {str(e)}"
                )
                # Add error month placeholder
                raw_months.append(
                    {
                        "days": {},
                        "error": str(e),
                        "_source_month": {"year": y, "month": m},
                    }
                )

        # ---------- view=text ----------
        if view == "text":
            header = (
                f"[{therapist_email}] tz={tzname} work={work_start[0]:02d}:{work_start[1]:02d}-"
                f"{work_end[0]:02d}:{work_end[1]:02d} slot={slot_minutes}m session={session_minutes}m "
                f"payment={payment_type} mode={mode}"
            )
            lines: List[str] = [header]

            # Range limits for cmp (16 days rolling)
            cmp_start = now_tz
            cmp_end = now_tz + timedelta(days=15)

            for month_payload in raw_months:
                src = month_payload.get("_source_month", {})
                y = src.get("year")
                m = src.get("month")
                if not y or not m:
                    continue
                month_name = calmod.month_name[m]
                if mode == "exp":
                    lines.append(f"\n[{month_name} {y}]")

                month_obj = month_payload.get("days") or month_payload
                for dd, payload in _days_iter(month_obj):
                    try:
                        d_int = int(dd)
                        this_date = datetime(y, m, d_int, tzinfo=tz.gettz(tzname))
                    except Exception:
                        continue

                    # apply cmp window filter
                    if mode == "cmp" and not _within(this_date, cmp_start, cmp_end):
                        continue

                    dow = this_date.strftime("%a")

                    try:
                        free_pairs, busy_pairs, dstart, dend = _extract_day_free_busy(
                            payload
                        )
                        busy_str = (
                            ", ".join(_merge_ranges(busy_pairs)) if busy_pairs else "—"
                        )
                        # Bookable appointment slots: exactly the free full-hour blocks (HH:00-HH:00)
                        slots_str = (
                            ", ".join([f"{s}-{e}" for (s, e) in free_pairs])
                            if free_pairs
                            else "—"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Error processing day {dd} for {therapist_email}: {str(e)}"
                        )
                        if debug_mode:
                            logger.debug(f"Payload: {payload}")
                        busy_str = "ERROR"
                        slots_str = "ERROR"

                    # single line per day
                    if mode == "exp":
                        lines.append(
                            f"{dd} {dow} | busy: {busy_str} | slots: {slots_str}"
                        )
                    else:  # cmp
                        # include month abbrev (fits better for cross-month 16-day window)
                        lines.append(
                            f"{dd} {calmod.month_abbr[m]} {y} {dow} | busy: {busy_str} | slots: {slots_str}"
                        )

            text = "\n".join(lines) + "\n"
            return text, 200, {"Content-Type": "text/plain; charset=utf-8"}

        # ---------- view=compact (compact JSON across months or 16-day window) ----------
        if view == "compact":
            out_days = []
            cmp_start = now_tz
            cmp_end = now_tz + timedelta(days=15)

            for month_payload in raw_months:
                src = month_payload.get("_source_month", {})
                y = src.get("year")
                m = src.get("month")
                if not y or not m:
                    continue
                month_obj = month_payload.get("days") or month_payload
                for dd, payload in _days_iter(month_obj):
                    try:
                        d_int = int(dd)
                        this_date = datetime(y, m, d_int, tzinfo=tz.gettz(tzname))
                    except Exception:
                        continue

                    if mode == "cmp" and not _within(this_date, cmp_start, cmp_end):
                        continue

                    try:
                        free_pairs, busy_pairs, dstart, dend = _extract_day_free_busy(
                            payload
                        )
                        out_days.append(
                            {
                                "date": this_date.strftime("%Y-%m-%d"),
                                "dow": this_date.strftime("%a"),
                                "work": f"{dstart}-{dend}",
                                "busy": _merge_ranges(busy_pairs),
                                "slots": [f"{s}-{e}" for (s, e) in free_pairs],
                            }
                        )
                    except Exception as e:
                        logger.warning(
                            f"Error processing day {dd} for {therapist_email} in compact view: {str(e)}"
                        )
                        if debug_mode:
                            logger.debug(f"Payload: {payload}")
                        out_days.append(
                            {
                                "date": this_date.strftime("%Y-%m-%d"),
                                "dow": this_date.strftime("%a"),
                                "work": "07:00-22:00",
                                "busy": ["ERROR"],
                                "slots": [],
                                "error": str(e),
                            }
                        )

            return jsonify(
                {
                    "format": "compact",
                    "mode": mode,
                    "meta": {
                        "timezone": tzname,
                        "slot_minutes": slot_minutes,
                        "session_minutes": session_minutes,
                        "payment_type": payment_type,
                        "therapist": therapist_email,
                    },
                    "days": out_days
                    if mode == "cmp"
                    else {
                        # group compact days by month for exp if you prefer; keeping flat list is simplest
                        "all": out_days
                    },
                }
            )

        # ---------- default: raw JSON (original), but for 3 months ----------
        # Get therapist information for unified response
        therapist_info = None
        booking_info = None

        try:
            with get_db_session() as db:
                therapist = (
                    db.query(Therapist)
                    .filter(Therapist.email == therapist_email)
                    .first()
                )
                if therapist:
                    # Determine supported payment types based on program
                    program = (
                        getattr(therapist, "program", "") or "MFT"
                    )  # Default to graduate
                    if program == "Limited Permit":
                        # Associates: insurance only (55min)
                        supported_payment_types = ["insurance"]
                    else:
                        # Graduates: both insurance (55min) and cash_pay (45min)
                        supported_payment_types = ["insurance", "cash_pay"]

                    therapist_info = {
                        "email": therapist.email,
                        "name": getattr(therapist, "intern_name", "")
                        or getattr(therapist, "name", ""),
                        "program": program,
                        "accepting_new_clients": getattr(
                            therapist, "accepting_new_clients", True
                        ),
                    }

                    booking_info = {
                        "session_duration_minutes": session_minutes,
                        "payment_type": payment_type,
                        "supported_payment_types": supported_payment_types,
                        "timezone": tzname,
                    }
        except Exception as e:
            logger.warning(f"Could not fetch therapist info for {therapist_email}: {e}")
            # Provide fallback info
            therapist_info = {
                "email": therapist_email,
                "name": "",
                "program": "Unknown",
                "accepting_new_clients": True,
            }
            booking_info = {
                "session_duration_minutes": session_minutes,
                "payment_type": payment_type,
                "supported_payment_types": ["insurance", "cash_pay"],
                "timezone": tzname,
            }

        return jsonify(
            {
                "months": raw_months,
                "therapist_info": therapist_info,
                "booking_info": booking_info,
            }
        )

    except Exception as e:
        logger.exception("availability error")
        return jsonify({"error": str(e)}), 500


@availability_bp.route("/therapists/availability/batch", methods=["POST"])
def availability_batch():
    """
    Prefetch up to 10 therapists in one request.
    Body JSON:
      {
        "emails": ["a@x", "b@y", ...],
        "year": 2025,
        "month": 8,
        "timezone": "America/Chicago",
        "work_start": "07:00",
        "work_end": "21:00",
        "slot_minutes": 60,
        "session_minutes": 45,
        "payment_type": "cash_pay"
      }
    """
    try:
        data = request.get_json() or {}
        emails: List[str] = data.get("emails", [])[:10]
        now = datetime.now()
        year = int(data.get("year", now.year))
        month = int(data.get("month", now.month))
        tzname = data.get("timezone", "America/New_York")
        slot_minutes = int(data.get("slot_minutes", 60))
        session_minutes = data.get("session_minutes")
        session_minutes = int(session_minutes) if session_minutes else None
        payment_type = (data.get("payment_type") or "").strip().lower() or None
        debug_mode = data.get("debug", False)
        live_check = data.get("live", False)

        work_start = _parse_hhmm(data.get("work_start", "07:00"), (7, 0))
        work_end = _parse_hhmm(data.get("work_end", "22:00"), (22, 0))

        # Log batch request
        logger.info(f"📅 [BATCH AVAILABILITY REQUEST]")
        logger.info(
            f"  Therapists: {len(emails)} ({', '.join(emails[:3])}{'...' if len(emails) > 3 else ''})"
        )
        logger.info(f"  Period: {year}-{month:02d}")
        logger.info(f"  Timezone: {tzname}")
        logger.info(f"  Payment: {payment_type or 'cash_pay'}")
        logger.info(f"  Debug mode: {debug_mode}")

        out: Dict[str, dict] = {}
        successful = 0

        for email in emails:
            try:
                out[email] = get_monthly_availability_efficient(
                    calendar_id=email,
                    year=year,
                    month=month,
                    tzname=tzname,
                    work_start=work_start,
                    work_end=work_end,
                    slot_minutes=slot_minutes,
                    session_minutes=None,  # Will be auto-detected
                    payment_type=None,  # Will be auto-detected
                    debug=debug_mode,
                    force_fresh=live_check,
                )
                successful += 1
            except Exception as e:
                logger.warning(f"  ⚠️ Failed for {email}: {str(e)}")
                out[email] = {"error": str(e)}

        logger.info(f"  ✅ Processed {successful}/{len(emails)} therapists successfully")

        return jsonify(out)
    except Exception as e:
        logger.error(f"❌ [BATCH AVAILABILITY ERROR]: {str(e)}")
        return jsonify({"error": str(e)}), 500


@availability_bp.route(
    "/therapists/<therapist_email>/availability-status", methods=["GET"]
)
def get_therapist_availability_status(therapist_email: str):
    """
    Quick availability status check - returns just a boolean and count.
    Useful for real-time checks on therapist matching pages.

    Query parameters:
    - live: true/false (bypass cache for real-time check)
    - payment_type: insurance/cash_pay
    - month: optional (defaults to current month)
    - year: optional (defaults to current year)
    """
    try:
        # Parse parameters
        now = datetime.now()
        year = int(request.args.get("year", now.year))
        month = int(request.args.get("month", now.month))
        payment_type = (request.args.get("payment_type") or "cash_pay").strip().lower()
        live_check = request.args.get("live", "false").lower() == "true"
        debug_mode = request.args.get("debug", "false").lower() == "true"

        # Determine session duration using unified logic
        session_minutes = get_therapist_session_duration(
            therapist_email=therapist_email, payment_type=payment_type
        )

        logger.info(
            f"🔍 [AVAILABILITY STATUS] {therapist_email} (live: {live_check}, debug: {debug_mode})"
        )

        # Clear cache if live check requested
        if live_check:
            try:
                from src.utils.google.google_calendar import clear_cache_for_calendar

                cleared_count = clear_cache_for_calendar(therapist_email)
                logger.info(
                    f"  Cleared {cleared_count} cache entries for live status check"
                )
            except ImportError:
                logger.warning("  Cache clearing function not available")

        # Get availability data
        data = get_monthly_availability_efficient(
            calendar_id=therapist_email,
            year=year,
            month=month,
            tzname="America/New_York",  # Default timezone
            work_start=(7, 0),
            work_end=(22, 0),
            slot_minutes=60,
            session_minutes=session_minutes,
            payment_type=payment_type,
            debug=debug_mode,
            force_fresh=live_check,
        )

        # Count available sessions
        total_sessions = 0
        available_days = 0

        for day_data in data.get("days", {}).values():
            day_sessions = day_data.get("sessions", [])
            if day_sessions:
                total_sessions += len(day_sessions)
                available_days += 1

        has_availability = total_sessions > 0

        result = {
            "therapist_email": therapist_email,
            "has_availability": has_availability,
            "has_bookable_sessions": has_availability,  # Alias for consistency
            "total_sessions": total_sessions,
            "available_days": available_days,
            "period": f"{year}-{month:02d}",
            "payment_type": payment_type,
            "live_check": live_check,
            "checked_at": datetime.now().isoformat(),
        }

        if has_availability:
            logger.info(
                f"  ✅ Available: {total_sessions} sessions across {available_days} days"
            )
        else:
            logger.info(f"  ❌ No availability found")

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ [AVAILABILITY STATUS ERROR] {therapist_email}: {str(e)}")
        return (
            jsonify(
                {
                    "error": str(e),
                    "therapist_email": therapist_email,
                    "has_availability": None,  # Unknown due to error
                }
            ),
            500,
        )


@availability_bp.route(
    "/therapists/<therapist_email>/availability/daily", methods=["GET"]
)
def get_therapist_daily_availability(therapist_email: str):
    """
    Get availability for a specific date (single day).

    Query parameters:
      - date: YYYY-MM-DD format (required)
      - timezone: IANA timezone (default: America/New_York)
      - payment_type: insurance/cash_pay (default: cash_pay)
      - live: true/false - force fresh data (default: false)

    Returns:
      {
        "date": "2025-09-12",
        "day_of_week": "Friday",
        "available_slots": ["09:00", "10:00", "14:00"],
        "total_slots": 3,
        "therapist_email": "therapist@example.com",
        "timezone": "America/New_York"
      }
    """
    try:
        import calendar as calmod
        from datetime import datetime

        # Parse required date parameter
        date_str = request.args.get("date", "").strip()
        if not date_str:
            return (
                jsonify({"error": "date parameter is required (YYYY-MM-DD format)"}),
                400,
            )

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        # Other parameters
        tzname = request.args.get("timezone", "America/New_York")
        live_check = request.args.get("live", "false").lower() == "true"
        debug_mode = request.args.get("debug", "false").lower() == "true"
        booking_interval_type = request.args.get("booking_interval_type")

        # Get availability for the specific day only (payment type will be auto-detected)
        data = get_daily_availability(
            calendar_id=therapist_email,
            year=date_obj.year,
            month=date_obj.month,
            day=date_obj.day,
            tzname=tzname,
            work_start=(7, 0),
            work_end=(22, 0),
            slot_minutes=60,
            session_minutes=None,  # Will be auto-detected
            payment_type=None,  # Will be auto-detected
            booking_interval_type=booking_interval_type,
            debug=debug_mode,
            force_fresh=live_check,
        )

        # Extract the specific day's data
        day_num = date_obj.day
        day_data = data.get("days", {}).get(day_num, {})

        if not day_data:
            return jsonify(
                {
                    "date": date_str,
                    "day_of_week": calmod.day_name[date_obj.weekday()],
                    "available_slots": [],
                    "total_slots": 0,
                    "therapist_email": therapist_email,
                    "timezone": tzname,
                    "message": "No availability data for this date",
                }
            )

        # Extract sessions (available time slots)
        sessions = day_data.get("sessions", [])
        available_slots = []
        for session in sessions:
            start_time = session.get("start", "")
            try:
                # Extract HH:MM from ISO timestamp (e.g. "2025-09-15T14:00:00-04:00" -> "14:00")
                if "T" in start_time and len(start_time) > 10:
                    time_part = start_time.split("T")[1][
                        :5
                    ]  # Get time portion and first 5 chars
                    # Validate the time_part format (should be HH:MM)
                    if len(time_part) == 5 and time_part[2] == ":":
                        available_slots.append(time_part)
                    else:
                        logger.warning(
                            f"Invalid time format in session start: {start_time}"
                        )
                elif len(start_time) >= 5 and start_time[2] == ":":
                    # Already in HH:MM format
                    available_slots.append(start_time[:5])
                else:
                    logger.warning(f"Unrecognized time format in session: {start_time}")
            except Exception as e:
                logger.error(f"Error parsing session time '{start_time}': {str(e)}")
                continue

        # Get therapist info from the data response
        therapist_info = data.get("therapist_info", {})

        # Build response
        has_bookable_sessions = len(available_slots) > 0

        # Debug logging for slots vs sessions mismatch
        slots_data = day_data.get("slots", [])
        free_slots_count = len([s for s in slots_data if s.get("is_free", False) or s.get("free_ratio", 0) >= 0.999])

        if free_slots_count > 0 and not has_bookable_sessions:
            logger.warning(
                f"⚠️ AVAILABILITY MISMATCH for {therapist_email} on {date_str}: "
                f"{free_slots_count} free slots but 0 bookable sessions"
            )
        elif has_bookable_sessions:
            logger.info(
                f"✅ AVAILABILITY OK for {therapist_email} on {date_str}: "
                f"{free_slots_count} free slots, {len(available_slots)} bookable sessions"
            )

        response_data = {
            "date": date_str,
            "day_of_week": calmod.day_name[date_obj.weekday()],
            "available_slots": available_slots,
            "total_slots": len(available_slots),
            "has_bookable_sessions": has_bookable_sessions,  # Clear signal for frontend coloring
            "therapist_info": therapist_info,  # Include comprehensive therapist info
            "timezone": tzname,
        }

        # Add debug information if requested
        if debug_mode:
            # Get the raw busy blocks from Google Calendar for this specific day
            from dateutil import tz

            from src.utils.google.google_calendar import (
                day_bounds,
                get_busy_events_from_gcalendar,
                _get_timezone_offset,
            )

            # Get bounds for this specific day
            tmin, tmax, zone = day_bounds(
                date_obj.year, date_obj.month, date_obj.day, tzname
            )

            # Clear cache if live check was requested to ensure fresh data
            if live_check:
                from src.utils.google.google_calendar import clear_cache_for_calendar

                clear_cache_for_calendar(therapist_email)

            # Get busy events from Google Calendar
            # CRITICAL FIX: Pass timezone offset to avoid missing OOO blocks in evening hours
            ref_date = datetime(date_obj.year, date_obj.month, date_obj.day)
            tz_offset = _get_timezone_offset(tzname, ref_date)
            fb = get_busy_events_from_gcalendar(
                [therapist_email],
                time_min=tmin,
                time_max=tmax,
                timezone_offset=tz_offset
            )
            cal_info = fb.get(therapist_email, {})
            busy_blocks = cal_info.get("busy", [])

            # Parse busy blocks into readable format
            debug_busy_times = []
            user_zone = tz.gettz(tzname)

            logger.info(
                f"🔍 [DETAILED BUSY BLOCK ANALYSIS] Processing {len(busy_blocks)} busy blocks"
            )
            logger.info(f"  Target date: {date_str} in timezone {tzname}")
            logger.info(f"  User timezone object: {user_zone}")

            for i, busy_block in enumerate(busy_blocks, 1):
                try:
                    # Parse the busy block times
                    start_str = busy_block["start"]
                    end_str = busy_block["end"]

                    logger.info(f"  🔍 Block {i}: Processing busy block")
                    logger.info(f"    Raw start: {start_str}")
                    logger.info(f"    Raw end: {end_str}")

                    # Handle different time formats from Google Calendar
                    if "Z" in start_str or "+00:00" in start_str:
                        # UTC format from Google Calendar
                        start_dt = datetime.fromisoformat(
                            start_str.replace("Z", "+00:00")
                        )
                        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        logger.info(f"    Parsed as UTC format")
                    else:
                        # Already has timezone info
                        start_dt = datetime.fromisoformat(start_str)
                        end_dt = datetime.fromisoformat(end_str)
                        logger.info(f"    Parsed as timezone-aware format")

                    logger.info(f"    UTC datetime: {start_dt} → {end_dt}")
                    logger.info(f"    UTC timezone: {start_dt.tzinfo}")

                    # Convert to the requested timezone for display
                    start_local = start_dt.astimezone(user_zone)
                    end_local = end_dt.astimezone(user_zone)

                    logger.info(f"    Local datetime: {start_local} → {end_local}")
                    logger.info(f"    Local timezone: {start_local.tzinfo}")
                    logger.info(
                        f"    Duration: {(end_local - start_local).total_seconds() / 3600:.1f} hours"
                    )

                    # Check if this busy block overlaps with the requested date
                    overlaps_date = start_local.date() <= date_obj <= end_local.date()
                    logger.info(f"    Overlaps target date {date_obj}: {overlaps_date}")
                    logger.info(
                        f"    Start date: {start_local.date()}, End date: {end_local.date()}"
                    )

                    if overlaps_date:
                        debug_busy_times.append(
                            {
                                "start_time": start_local.strftime("%H:%M"),
                                "end_time": end_local.strftime("%H:%M"),
                                "start_date": start_local.strftime("%Y-%m-%d"),
                                "end_date": end_local.strftime("%Y-%m-%d"),
                                "duration_minutes": int(
                                    (end_local - start_local).total_seconds() / 60
                                ),
                                "duration_hours": round(
                                    (end_local - start_local).total_seconds() / 3600, 2
                                ),
                                "original_start": start_str,
                                "original_end": end_str,
                                "utc_start": start_dt.isoformat(),
                                "utc_end": end_dt.isoformat(),
                                "local_start": start_local.isoformat(),
                                "local_end": end_local.isoformat(),
                            }
                        )
                        logger.info(f"    ✅ ADDED to debug output")
                    else:
                        logger.info(f"    ❌ SKIPPED - does not overlap target date")

                except Exception as e:
                    logger.error(f"Error parsing busy block {i} {busy_block}: {str(e)}")
                    debug_busy_times.append(
                        {
                            "error": f"Failed to parse: {str(e)}",
                            "raw_block": busy_block,
                            "block_number": i,
                        }
                    )

            # Create session windows for debug output (start-end format)
            available_session_windows = []
            for session in sessions:
                start_time = session.get("start", "")
                end_time = session.get("end", "")
                try:
                    # Extract HH:MM from both start and end times
                    if "T" in start_time and len(start_time) > 10:
                        start_part = start_time.split("T")[1][:5]
                    elif len(start_time) >= 5 and start_time[2] == ":":
                        start_part = start_time[:5]
                    else:
                        start_part = start_time

                    if "T" in end_time and len(end_time) > 10:
                        end_part = end_time.split("T")[1][:5]
                    elif len(end_time) >= 5 and end_time[2] == ":":
                        end_part = end_time[:5]
                    else:
                        end_part = end_time

                    if (
                        len(start_part) == 5
                        and len(end_part) == 5
                        and start_part[2] == ":"
                        and end_part[2] == ":"
                    ):
                        available_session_windows.append(f"{start_part}-{end_part}")

                except Exception as e:
                    logger.error(
                        f"Error parsing session window '{start_time}'-'{end_time}': {str(e)}"
                    )
                    continue

            # Add debug information to response
            response_data["debug_info"] = {
                "available_session_windows": available_session_windows,
                "google_calendar_busy_blocks": debug_busy_times,
                "total_busy_blocks": len(busy_blocks),
                "working_hours": f"07:00-22:00 EST (converted to {tzname})",
                "cache_cleared": live_check,
                "raw_day_data_summary": {
                    "sessions_found": len(sessions),
                    "slots_found": len(day_data.get("slots", [])),
                    "has_summary": "summary" in day_data,
                },
            }

            if debug_busy_times:
                logger.info(
                    f"🚫 Found {len(debug_busy_times)} busy blocks for {therapist_email} on {date_str}:"
                )
                for i, block in enumerate(debug_busy_times, 1):
                    if "error" not in block:
                        logger.info(
                            f"  {i}. {block['start_time']}-{block['end_time']} ({block['duration_minutes']}min)"
                        )
            else:
                logger.info(
                    f"✅ No busy blocks found for {therapist_email} on {date_str}"
                )

        return jsonify(response_data)

    except Exception as e:
        logger.error(
            f"❌ [DAILY AVAILABILITY ERROR] {therapist_email} {date_str}: {str(e)}"
        )
        return (
            jsonify(
                {
                    "error": str(e),
                    "therapist_email": therapist_email,
                    "date": date_str if "date_str" in locals() else None,
                }
            ),
            500,
        )
