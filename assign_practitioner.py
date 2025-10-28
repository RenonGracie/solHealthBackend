#!/usr/bin/env python3
"""
IntakeQ Practitioner Assignment - Railway Native Interface

This module provides a simple interface for assigning practitioners to clients in IntakeQ.
Runs Selenium directly in Railway Docker environment with headless Chrome.
Accepts the exact inputs you specified: account_type, client_id, and therapist_full_name.
"""

import json
import logging
from typing import Any, Dict, Union

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def assign_practitioner(
    account_type: str, client_id: str, therapist_full_name: str, headless: bool = True
) -> bool:
    """
    Assign a practitioner to a client in IntakeQ

    Args:
        account_type: "cash_pay" or "insurance"
        client_id: IntakeQ Client ID (e.g., "5781")
        therapist_full_name: Full name of therapist (e.g., "Catherine Burnett")
        headless: Whether to run browser in headless mode (default: True)

    Returns:
        bool: True if successful, False otherwise

    Example:
        success = assign_practitioner("insurance", "5781", "Catherine Burnett")
    """
    try:
        # Validate account type
        if account_type not in ["cash_pay", "insurance"]:
            logger.error(
                f"Invalid account_type: {account_type}. Must be 'cash_pay' or 'insurance'"
            )
            return False

        # Validate inputs
        if not client_id or not therapist_full_name:
            logger.error("client_id and therapist_full_name are required")
            return False

        logger.info(
            f"Assigning client ID {client_id} to {therapist_full_name} in {account_type} account"
        )

        # Use Railway-native Selenium automation
        from intakeq_selenium_bot import IntakeQSeleniumBot

        bot = IntakeQSeleniumBot(headless=headless)
        success = bot.assign_client_to_practitioner(
            account_type=account_type,
            client_id=str(client_id),
            practitioner_name=therapist_full_name,
        )

        if success:
            logger.info(
                f"✅ Successfully assigned client ID {client_id} to {therapist_full_name}"
            )
        else:
            logger.error(
                f"❌ Failed to assign client ID {client_id} to {therapist_full_name}"
            )

        return success

    except Exception as e:
        logger.error(f"Error in assign_practitioner: {str(e)}")
        return False


def assign_practitioner_from_json(
    json_data: Union[str, Dict[str, Any]], headless: bool = True
) -> bool:
    """
    Assign practitioner using JSON input

    Args:
        json_data: JSON string or dictionary with keys: account_type, client_id, therapist_full_name
        headless: Whether to run browser in headless mode

    Returns:
        bool: True if successful, False otherwise

    Example JSON:
        {
            "account_type": "insurance",
            "client_id": "5781",
            "therapist_full_name": "Catherine Burnett"
        }
    """
    try:
        # Parse JSON if string
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data

        # Extract required fields
        account_type = data.get("account_type")
        client_id = data.get("client_id")
        therapist_full_name = data.get("therapist_full_name")

        return assign_practitioner(
            account_type, client_id, therapist_full_name, headless
        )

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {str(e)}")
        return False
    except KeyError as e:
        logger.error(f"Missing required field: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error in assign_practitioner_from_json: {str(e)}")
        return False


# Convenience functions for specific account types
def assign_insurance_practitioner(
    client_id: str, therapist_full_name: str, headless: bool = True
) -> bool:
    """Assign practitioner in insurance account"""
    return assign_practitioner("insurance", client_id, therapist_full_name, headless)


def assign_cash_pay_practitioner(
    client_id: str, therapist_full_name: str, headless: bool = True
) -> bool:
    """Assign practitioner in cash pay account"""
    return assign_practitioner("cash_pay", client_id, therapist_full_name, headless)


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2:
        # JSON input mode
        try:
            json_input = sys.argv[1]
            success = assign_practitioner_from_json(json_input, headless=False)
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"Error with JSON input: {e}")
            sys.exit(1)

    elif len(sys.argv) == 4:
        # Individual arguments mode
        account_type = sys.argv[1]
        client_id = sys.argv[2]
        therapist_full_name = sys.argv[3]

        success = assign_practitioner(
            account_type, client_id, therapist_full_name, headless=False
        )
        sys.exit(0 if success else 1)

    else:
        print("Usage:")
        print("  JSON mode:")
        print(
            '    python assign_practitioner.py \'{"account_type": "insurance", "client_id": "5781", "therapist_full_name": "Catherine Burnett"}\''
        )
        print("")
        print("  Individual arguments:")
        print('    python assign_practitioner.py insurance 5781 "Catherine Burnett"')
        print("")
        print("  Account types: insurance, cash_pay")
        sys.exit(1)
