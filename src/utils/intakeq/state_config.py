"""State-aware IntakeQ configuration helper for NJ and NY insurance.

This module provides state-specific IntakeQ credentials for insurance clients.
The application uses different IntakeQ accounts for NJ and NY insurance clients.
"""
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def get_insurance_intakeq_config(state: str, config_type: str) -> str:
    """
    Get state-specific insurance IntakeQ configuration.

    The application uses different IntakeQ accounts for NJ and NY insurance clients,
    requiring state-aware credential management.

    Args:
        state: Client state ('NJ' or 'NY')
        config_type: Type of credential needed:
            - 'api_key': IntakeQ API key
            - 'username': IntakeQ login username (for Selenium automation)
            - 'password': IntakeQ login password (for Selenium automation)
            - 'mandatory_form_id': Mandatory form ID for sending intake forms

    Returns:
        State-specific configuration value from environment variables

    Raises:
        ValueError: If config_type is invalid or state is not supported

    Examples:
        >>> api_key = get_insurance_intakeq_config('NJ', 'api_key')
        >>> username = get_insurance_intakeq_config('NY', 'username')
        >>> form_id = get_insurance_intakeq_config('NY', 'mandatory_form_id')
    """
    # Validate config_type
    valid_types = ['api_key', 'username', 'password', 'mandatory_form_id']
    if config_type not in valid_types:
        raise ValueError(
            f"Invalid config_type: '{config_type}'. Must be one of {valid_types}"
        )

    # Validate state
    if state not in ['NJ', 'NY']:
        logger.warning(
            f"⚠️ Unsupported state for insurance: '{state}'. "
            f"Only 'NJ' and 'NY' are supported."
        )
        return ""

    # State-specific configuration mapping
    # NJ credentials fall back to generic INSURANCE_* env vars for backward compatibility
    # NY credentials must be explicitly set (no fallback)
    config_map = {
        'NJ': {
            'api_key': os.getenv(
                "NJ_INSURANCE_INTAKEQ_API_KEY",
                os.getenv("INSURANCE_INTAKEQ_API_KEY", "")
            ),
            'username': os.getenv(
                "NJ_INSURANCE_INTAKEQ_USR",
                os.getenv("INSURANCE_INTAKEQ_USR", "")
            ),
            'password': os.getenv(
                "NJ_INSURANCE_INTAKEQ_PAS",
                os.getenv("INSURANCE_INTAKEQ_PAS", "")
            ),
            'mandatory_form_id': os.getenv(
                "NJ_INSURANCE_MANDATORY_FORM_ID",
                os.getenv("INSURANCE_MANDATORY_FORM_ID", "")
            )
        },
        'NY': {
            'api_key': os.getenv("NY_INSURANCE_INTAKEQ_API_KEY", ""),
            'username': os.getenv("NY_INSURANCE_INTAKEQ_USR", ""),
            'password': os.getenv("NY_INSURANCE_INTAKEQ_PAS", ""),
            'mandatory_form_id': os.getenv(
                "NY_INSURANCE_MANDATORY_FORM_ID",
                os.getenv("INSURANCE_MANDATORY_FORM_ID", "")
            )
        }
    }

    value = config_map[state][config_type]

    # Log warning if credential is missing
    if not value:
        logger.error(
            f"❌ Missing {config_type} for {state} insurance IntakeQ account. "
            f"Please set {state}_INSURANCE_INTAKEQ_{config_type.upper()} environment variable."
        )
    else:
        logger.info(
            f"✅ Retrieved {config_type} for {state} insurance IntakeQ account"
        )

    return value


def get_cashpay_intakeq_config(config_type: str) -> str:
    """
    Get cash-pay IntakeQ configuration (shared account for all states).

    Args:
        config_type: Type of credential ('api_key', 'username', or 'password')

    Returns:
        Cash-pay configuration value from environment variables

    Raises:
        ValueError: If config_type is invalid
    """
    valid_types = ['api_key', 'username', 'password']
    if config_type not in valid_types:
        raise ValueError(
            f"Invalid config_type: '{config_type}'. Must be one of {valid_types}"
        )

    config_map = {
        'api_key': os.getenv("CASH_PAY_INTAKEQ_API_KEY", ""),
        'username': os.getenv("CASH_PAY_INTAKEQ_USR", ""),
        'password': os.getenv("CASH_PAY_INTAKEQ_PAS", "")
    }

    value = config_map[config_type]

    if not value:
        logger.error(
            f"❌ Missing {config_type} for cash-pay IntakeQ account. "
            f"Please set CASH_PAY_INTAKEQ_{config_type.upper()} environment variable."
        )
    else:
        logger.info(f"✅ Retrieved {config_type} for cash-pay IntakeQ account")

    return value


# Convenience function for getting correct config based on payment type and state
def get_intakeq_config(payment_type: str, state: str, config_type: str) -> str:
    """
    Get IntakeQ configuration based on payment type and state.

    Routes to the correct IntakeQ account:
    - Insurance clients: State-specific account (NJ or NY)
    - Cash-pay clients: Shared cash-pay account

    Args:
        payment_type: 'insurance' or 'cash_pay'
        state: Client state ('NJ' or 'NY')
        config_type: 'api_key', 'username', or 'password'

    Returns:
        Appropriate configuration value
    """
    if payment_type == 'insurance':
        return get_insurance_intakeq_config(state, config_type)
    else:
        return get_cashpay_intakeq_config(config_type)
