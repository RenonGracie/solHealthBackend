"""
IntakeQ API Request Utilities

Core HTTP client functions for IntakeQ appointment booking integration.
Works with existing client creation APIs in /intakeq/create-client and /intakeq/client.
Based on documentation: IntakeQ_Integration_Documentation.md
"""
import logging
from typing import Any, Dict, Optional

import requests

from src.config import get_config

logger = logging.getLogger(__name__)

# Get configuration
config = get_config()

# Configuration from config.py
INTAKEQ_BASE_URL = config.INTAKEQ_BASE_URL
CASH_PAY_API_KEY = config.CASH_PAY_INTAKEQ_API_KEY
INSURANCE_API_KEY = config.INSURANCE_INTAKEQ_API_KEY


def get_api_key_for_payment_type(payment_type: str) -> str:
    """Get appropriate API key based on payment type"""
    if payment_type == "insurance":
        return INSURANCE_API_KEY
    return CASH_PAY_API_KEY


def _intakeq_get(
    path: str, params: dict = None, payment_type: str = "cash_pay"
) -> requests.Response:
    """Core GET request to IntakeQ API with payment-type specific auth"""
    url = INTAKEQ_BASE_URL + path
    headers = {"X-Auth-Key": get_api_key_for_payment_type(payment_type)}

    logger.info(f"🔄 IntakeQ GET: {url} ({payment_type})")
    response = requests.get(url=url, headers=headers, params=params)
    logger.info(f"📥 IntakeQ GET Response: {response.status_code}")

    return response


def _intakeq_post(
    path: str, data: dict, payment_type: str = "cash_pay", timeout: int | None = None
) -> requests.Response:
    """Core POST request to IntakeQ API with payment-type specific auth"""
    url = INTAKEQ_BASE_URL + path
    headers = {"X-Auth-Key": get_api_key_for_payment_type(payment_type)}

    logger.info(f"🔄 IntakeQ POST: {url} ({payment_type})")
    logger.info(f"📤 Payload keys: {list(data.keys()) if data else 'None'}")

    response = requests.post(
        url=url,
        headers=headers,
        json=data,
        timeout=timeout,
    )

    logger.info(f"📥 IntakeQ POST Response: {response.status_code}")
    return response


# Appointment Management Endpoints (focused on booking, not client creation)


def get_booking_settings(payment_type: str = "cash_pay") -> requests.Response:
    """
    Retrieves available practitioners and services for booking
    Endpoint: GET /appointments/settings
    """
    logger.info(f"⚙️ Getting IntakeQ booking settings ({payment_type})")
    return _intakeq_get("/appointments/settings", payment_type=payment_type)


def search_appointments(
    args: dict, payment_type: str = "cash_pay"
) -> requests.Response:
    """
    Searches for existing appointments
    Endpoint: GET /appointments
    """
    logger.info(f"🔍 Searching IntakeQ appointments with: {args} ({payment_type})")
    return _intakeq_get("/appointments", args, payment_type=payment_type)


def get_appointment(
    appointment_id: str, payment_type: str = "cash_pay"
) -> requests.Response:
    """
    Retrieves specific appointment details
    Endpoint: GET /appointments/{appointment_id}
    """
    logger.info(f"📅 Getting IntakeQ appointment: {appointment_id} ({payment_type})")
    return _intakeq_get(f"/appointments/{appointment_id}", payment_type=payment_type)


def create_appointment(data: dict, payment_type: str = "cash_pay") -> requests.Response:
    """
    Creates new appointments in IntakeQ system
    Endpoint: POST /appointments
    """
    logger.info(
        f"📅 Creating IntakeQ appointment for client: {data.get('ClientId', 'Unknown')} ({payment_type})"
    )
    logger.info(f"👨‍⚕️ Practitioner: {data.get('PractitionerId', 'Unknown')}")
    logger.info(f"🕐 DateTime: {data.get('UtcDateTime', 'Unknown')}")

    return _intakeq_post("/appointments", data, payment_type=payment_type)


def update_appointment(data: dict, payment_type: str = "cash_pay") -> requests.Response:
    """
    Updates existing appointments
    Endpoint: PUT /appointments
    """
    logger.info(
        f"📅 Updating IntakeQ appointment: {data.get('Id', 'Unknown')} ({payment_type})"
    )
    url = INTAKEQ_BASE_URL + "/appointments"
    headers = {"X-Auth-Key": get_api_key_for_payment_type(payment_type)}

    response = requests.put(url=url, headers=headers, json=data)
    logger.info(f"📥 IntakeQ PUT Response: {response.status_code}")
    return response


def appointment_cancellation(
    data: dict, payment_type: str = "cash_pay"
) -> requests.Response:
    """
    Cancels appointments with reason tracking
    Endpoint: POST /appointments/cancellation
    """
    logger.info(
        f"❌ Cancelling IntakeQ appointment: {data.get('Id', 'Unknown')} ({payment_type})"
    )
    return _intakeq_post("/appointments/cancellation", data, payment_type=payment_type)
