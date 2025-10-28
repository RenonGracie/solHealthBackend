#!/usr/bin/env python3
"""
Efficient Availability Checking for Therapist Matching

Optimized for:
- 14-day window only (starting 24 hours from now)
- Batch processing multiple therapists
- Minimal Google API calls
- Fast response times for matching endpoint
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from dateutil import tz

logger = logging.getLogger(__name__)


def get_efficient_availability_window(
    therapist_emails: List[str],
    payment_type: str = "cash_pay",
    timezone_name: str = "America/New_York",
    debug: bool = False,
) -> Dict[str, Dict[str, any]]:
    """
    Get availability for multiple therapists for the next 14 days only.

    Optimized approach:
    1. Calculate exact 14-day window (24 hours from now + 13 more days)
    2. Single batch API call for all therapists
    3. Return only boolean availability + session count
    4. No full day-by-day breakdown (not needed for matching)

    Args:
        therapist_emails: List of therapist email addresses
        payment_type: "insurance" (55min) or "cash_pay" (45min)
        timezone_name: Timezone for calculations
        debug: Enable detailed logging for availability analysis

    Returns:
        {
            "therapist@email.com": {
                "has_availability": True,
                "total_sessions": 24,
                "available_days": 8,
                "error": None
            },
            ...
        }
    """
    from src.utils.google.google_calendar import (
        get_busy_events_from_gcalendar,
        get_therapist_session_duration,
    )

    if not therapist_emails:
        return {}

    # Calculate exact 14-day window
    zone = tz.gettz(timezone_name)
    now = datetime.now(zone)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_date = tomorrow + timedelta(days=14)  # 14 days total

    if debug:
        logger.info("=" * 60)
        logger.info(f"🗓️ [EFFICIENT AVAILABILITY DEBUG]")
        logger.info(
            f"  Therapists: {len(therapist_emails)} ({', '.join(therapist_emails[:2])}{'...' if len(therapist_emails) > 2 else ''})"
        )
        logger.info(f"  Payment Type: {payment_type}")
        logger.info(f"  Timezone: {timezone_name}")
        logger.info(f"  Window: {tomorrow.date()} to {end_date.date()} (14 days)")
        logger.info(
            f"  Session Duration: Individual per therapist (45-55 min based on program)"
        )
        logger.info("")
    else:
        logger.info(
            f"🗓️ Checking availability window: {tomorrow.date()} to {end_date.date()}"
        )

    # Session parameters - use unified logic for all therapists
    work_start_hour, work_end_hour = 7, 22  # 7am-10pm

    try:
        # Single batch API call for all therapists
        busy_data = get_busy_events_from_gcalendar(
            therapist_emails,
            time_min=tomorrow.date().isoformat(),
            time_max=end_date.date().isoformat(),
        )

        results = {}

        for email in therapist_emails:
            try:
                # Get individual session duration for this therapist
                individual_session_minutes = get_therapist_session_duration(
                    therapist_email=email, payment_type=payment_type
                )

                calendar_busy = busy_data.get(email, {}).get("busy", [])
                availability = _calculate_14_day_availability(
                    busy_blocks=calendar_busy,
                    start_date=tomorrow,
                    end_date=end_date,
                    work_start_hour=work_start_hour,
                    work_end_hour=work_end_hour,
                    session_minutes=individual_session_minutes,
                    zone=zone,
                )

                # Add session duration and booking info to results
                availability["session_duration_minutes"] = individual_session_minutes
                availability["payment_type"] = payment_type

                results[email] = availability
                if debug:
                    logger.info(
                        f"  ✅ {email}: {availability['total_sessions']} sessions ({individual_session_minutes}min), {availability['available_days']} days available"
                    )
                else:
                    logger.debug(
                        f"  {email}: {availability['total_sessions']} sessions available"
                    )

            except Exception as e:
                logger.warning(f"  ❌ Error processing {email}: {e}")
                results[email] = {
                    "has_availability": None,  # Unknown due to error
                    "total_sessions": 0,
                    "available_days": 0,
                    "error": str(e),
                }

        if debug:
            total_available = sum(r.get("total_sessions", 0) for r in results.values())
            available_therapists = sum(
                1 for r in results.values() if r.get("has_availability")
            )
            logger.info("")
            logger.info(f"📊 BATCH SUMMARY:")
            logger.info(
                f"  Available Therapists: {available_therapists}/{len(therapist_emails)}"
            )
            logger.info(f"  Total Available Sessions: {total_available}")
            logger.info("=" * 60)

        return results

    except Exception as e:
        logger.error(f"❌ Batch availability check failed: {e}")
        # Return error state for all therapists
        return {
            email: {
                "has_availability": None,
                "total_sessions": 0,
                "available_days": 0,
                "error": str(e),
            }
            for email in therapist_emails
        }


def _calculate_14_day_availability(
    busy_blocks: List[Dict],
    start_date: datetime,
    end_date: datetime,
    work_start_hour: int,
    work_end_hour: int,
    session_minutes: int,
    zone,
) -> Dict[str, any]:
    """
    Calculate availability for exactly 14 days.

    Returns summary stats only (not full day breakdown).
    """
    from src.utils.google.google_calendar import (
        build_session_windows,
        compute_full_day_free_intervals,
    )

    total_sessions = 0
    available_days = 0

    # Check each day in the 14-day window
    current_date = start_date
    while current_date < end_date:
        year, month, day = current_date.year, current_date.month, current_date.day

        # Get free intervals for this day
        free_intervals = compute_full_day_free_intervals(
            busy_blocks, year, month, day, zone
        )

        # Filter to work hours only
        work_start = current_date.replace(hour=work_start_hour, minute=0)
        work_end = current_date.replace(hour=work_end_hour, minute=0)

        filtered_intervals = []
        for start, end in free_intervals:
            # Intersect with work hours
            interval_start = max(start, work_start)
            interval_end = min(end, work_end)

            if interval_end > interval_start:
                filtered_intervals.append((interval_start, interval_end))

        # Build sessions for this day
        if filtered_intervals:
            day_sessions = build_session_windows(
                filtered_intervals,
                session_minutes=session_minutes,
                step_minutes=60,
                booking_interval_type=None,
            )

            if day_sessions:
                total_sessions += len(day_sessions)
                available_days += 1

        current_date += timedelta(days=1)

    return {
        "has_availability": total_sessions > 0,
        "total_sessions": total_sessions,
        "available_days": available_days,
        "error": None,
    }


def check_single_therapist_availability(
    therapist_email: str,
    payment_type: str = "cash_pay",
    timezone_name: str = "America/New_York",
    debug: bool = False,
) -> Dict[str, any]:
    """
    Quick availability check for a single therapist.
    Convenience wrapper around batch function.
    """
    results = get_efficient_availability_window(
        therapist_emails=[therapist_email],
        payment_type=payment_type,
        timezone_name=timezone_name,
        debug=debug,
    )

    return results.get(
        therapist_email,
        {
            "has_availability": None,
            "total_sessions": 0,
            "available_days": 0,
            "error": "No result returned",
        },
    )


# Example usage
if __name__ == "__main__":
    # Test the efficient approach
    test_emails = ["associatetest@solhealth.com", "therapist2@example.com"]

    results = get_efficient_availability_window(
        therapist_emails=test_emails,
        payment_type="cash_pay",
        timezone_name="America/New_York",
    )

    for email, data in results.items():
        print(
            f"{email}: {data['total_sessions']} sessions, {data['available_days']} days available"
        )
