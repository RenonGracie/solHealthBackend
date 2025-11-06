#!/usr/bin/env python3
"""
Insurance Provider to Payer ID Mapping Utility

This module provides bidirectional mapping between insurance provider names
and Nirvana payer IDs for accurate insurance verification and data validation.
"""
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Primary mapping: Insurance Provider Name -> Nirvana Payer ID
# Based on Nirvana's payer database and common insurance providers in NJ
INSURANCE_PROVIDER_MAP = {
    # Major National Providers
    "Aetna": "60054",
    "Aetna Better Health": "60054",
    "Aetna Better Health of New Jersey": "60054",
    "Aetna Inc": "60054",
    "Cigna": "62308",
    "Cigna Healthcare": "62308",
    "Cigna Health": "62308",
    "United Healthcare": "60558",
    "United Health Care": "60558",
    "UnitedHealthcare": "60558",
    "UHC": "60558",
    "Anthem": "60512",
    "Anthem Blue Cross": "60512",
    "Anthem BCBS": "60512",
    # New Jersey Specific Providers
    "Horizon Blue Cross Blue Shield": "60495",
    "Horizon BCBS": "60495",
    "Horizon Blue Cross": "60495",
    "Horizon": "60495",
    "AmeriHealth": "60123",
    "AmeriHealth New Jersey": "60123",
    "WellCare": "60789",
    "WellCare of New Jersey": "60789",
    # Municipal/Government Plans
    "City of Newark": "64157",  # From test data
    "Newark Municipal": "64157",
    # Additional Common Providers
    "BCBS": "60495",  # Default to Horizon for NJ
    "Blue Cross Blue Shield": "60495",
    "Medicaid": "60901",
    "NJ FamilyCare": "60901",
    "Humana": "60234",
    "Kaiser Permanente": "60345",
    "Oscar Health": "60456",
    "Independence Blue Cross": "60567",
}

# Reverse mapping: Payer ID -> Canonical Provider Name
PAYER_ID_TO_PROVIDER = {
    "60054": "Aetna Better Health",
    "62308": "Cigna Healthcare",
    "60558": "United Healthcare",
    "60512": "Anthem Blue Cross",
    "60495": "Horizon Blue Cross Blue Shield",
    "60123": "AmeriHealth New Jersey",
    "60789": "WellCare of New Jersey",
    "64157": "City of Newark",
    "60901": "NJ FamilyCare",
    "60234": "Humana",
    "60345": "Kaiser Permanente",
    "60456": "Oscar Health",
    "60567": "Independence Blue Cross",
}


def get_payer_id(provider_name: str) -> Optional[str]:
    """
    Convert insurance provider name to Nirvana payer ID.

    Args:
        provider_name: Insurance provider name from user input

    Returns:
        Payer ID string if found, None if not mapped
    """
    if not provider_name or not isinstance(provider_name, str):
        return None

    # Normalize the provider name (case insensitive, strip whitespace)
    normalized_name = provider_name.strip()

    # Try exact match first
    if normalized_name in INSURANCE_PROVIDER_MAP:
        payer_id = INSURANCE_PROVIDER_MAP[normalized_name]
        logger.info(f"📊 Mapped '{provider_name}' to payer ID: {payer_id}")
        return payer_id

    # Try case-insensitive match
    for provider, payer_id in INSURANCE_PROVIDER_MAP.items():
        if provider.lower() == normalized_name.lower():
            logger.info(
                f"📊 Case-insensitive mapped '{provider_name}' to payer ID: {payer_id}"
            )
            return payer_id

    # Try partial matching for common variations
    normalized_lower = normalized_name.lower()
    for provider, payer_id in INSURANCE_PROVIDER_MAP.items():
        provider_lower = provider.lower()
        if (
            normalized_lower in provider_lower
            or provider_lower in normalized_lower
            or _fuzzy_match(normalized_lower, provider_lower)
        ):
            logger.info(
                f"📊 Fuzzy matched '{provider_name}' to '{provider}' -> payer ID: {payer_id}"
            )
            return payer_id

    logger.warning(f"⚠️ No payer ID found for insurance provider: '{provider_name}'")
    return None


def get_provider_name(payer_id: str) -> Optional[str]:
    """
    Convert Nirvana payer ID to canonical insurance provider name.

    Args:
        payer_id: Nirvana payer ID from API response

    Returns:
        Canonical provider name if found, None if not mapped
    """
    if not payer_id or not isinstance(payer_id, str):
        return None

    provider_name = PAYER_ID_TO_PROVIDER.get(payer_id)
    if provider_name:
        logger.info(f"📊 Mapped payer ID {payer_id} to provider: '{provider_name}'")
        return provider_name

    logger.warning(f"⚠️ No provider name found for payer ID: '{payer_id}'")
    return None


def validate_and_correct_provider(
    user_input: str, nirvana_payer_id: str, nirvana_plan_name: str = None
) -> Dict[str, any]:
    """
    Compare user input with Nirvana response and return correction data.

    Args:
        user_input: Original insurance provider from user
        nirvana_payer_id: Payer ID from Nirvana response
        nirvana_plan_name: Plan name from Nirvana response (optional)

    Returns:
        Dict with validation results and correction information
    """
    result = {
        "original_provider": user_input,
        "nirvana_payer_id": nirvana_payer_id,
        "nirvana_plan_name": nirvana_plan_name,
        "corrected_provider": None,
        "was_corrected": False,
        "correction_type": None,
        "validation_status": "unknown",
    }

    # Get the user's input payer ID
    user_payer_id = get_payer_id(user_input) if user_input else None

    # Get the canonical provider name from Nirvana's payer ID
    canonical_provider = get_provider_name(nirvana_payer_id)

    # Determine the corrected provider name
    # Priority: Nirvana plan_name > Canonical provider from payer ID > Original user input
    corrected_provider = nirvana_plan_name or canonical_provider or user_input
    result["corrected_provider"] = corrected_provider

    # Determine if correction was needed
    if user_payer_id and user_payer_id == nirvana_payer_id:
        # User input was correct
        result["was_corrected"] = False
        result["correction_type"] = "no_correction_needed"
        result["validation_status"] = "correct"
        logger.info(
            f"✅ User input '{user_input}' was correct (payer ID: {nirvana_payer_id})"
        )

    elif user_payer_id and user_payer_id != nirvana_payer_id:
        # User input mapped to different payer ID - correction needed
        result["was_corrected"] = True
        result["correction_type"] = "payer_id_mismatch"
        result["validation_status"] = "corrected"
        logger.info(
            f"🔄 Corrected: '{user_input}' (payer: {user_payer_id}) → '{corrected_provider}' (payer: {nirvana_payer_id})"
        )

    elif not user_payer_id and canonical_provider:
        # User input wasn't in our mapping, but Nirvana returned valid data
        result["was_corrected"] = True
        result["correction_type"] = "unmapped_input"
        result["validation_status"] = "corrected"
        logger.info(
            f"🔄 Unmapped input corrected: '{user_input}' → '{corrected_provider}' (payer: {nirvana_payer_id})"
        )

    else:
        # No mapping available, use Nirvana's plan name if available
        if nirvana_plan_name and nirvana_plan_name != user_input:
            result["was_corrected"] = True
            result["correction_type"] = "plan_name_correction"
            result["validation_status"] = "corrected"
            logger.info(
                f"🔄 Plan name corrected: '{user_input}' → '{nirvana_plan_name}'"
            )
        else:
            result["validation_status"] = "unverified"
            logger.warning(
                f"⚠️ Unable to validate provider: '{user_input}' (payer: {nirvana_payer_id})"
            )

    return result


def _fuzzy_match(str1: str, str2: str) -> bool:
    """Simple fuzzy matching for insurance provider names."""
    # Check for common abbreviations and variations
    abbreviations = {
        "bcbs": "blue cross blue shield",
        "uhc": "united healthcare",
        "bc": "blue cross",
        "bs": "blue shield",
    }

    # Expand abbreviations
    for abbr, full in abbreviations.items():
        str1 = str1.replace(abbr, full)
        str2 = str2.replace(abbr, full)

    # Check if one string contains key words from the other
    words1 = set(str1.split())
    words2 = set(str2.split())

    # Must have at least one significant word in common
    common_words = words1.intersection(words2)
    significant_words = common_words - {
        "health",
        "care",
        "plan",
        "insurance",
        "inc",
        "llc",
    }

    return len(significant_words) > 0


def get_all_providers() -> Dict[str, str]:
    """
    Get all mapped insurance providers.

    Returns:
        Dictionary of provider names to payer IDs
    """
    return INSURANCE_PROVIDER_MAP.copy()


def get_all_payer_ids() -> Dict[str, str]:
    """
    Get all mapped payer IDs.

    Returns:
        Dictionary of payer IDs to provider names
    """
    return PAYER_ID_TO_PROVIDER.copy()


def add_provider_mapping(provider_name: str, payer_id: str) -> None:
    """
    Add a new provider mapping (for dynamic updates).

    Args:
        provider_name: Insurance provider name
        payer_id: Corresponding Nirvana payer ID
    """
    INSURANCE_PROVIDER_MAP[provider_name] = payer_id
    PAYER_ID_TO_PROVIDER[payer_id] = provider_name
    logger.info(f"📝 Added mapping: '{provider_name}' -> {payer_id}")


if __name__ == "__main__":
    # Test the mapping functions
    import logging

    logging.basicConfig(level=logging.INFO)

    # Test cases
    test_cases = [
        ("Aetna", "60054", "Should match exactly"),
        ("aetna better health", "60054", "Case insensitive match"),
        ("Horizon", "60495", "Partial match"),
        ("City of Newark", "64157", "Municipal plan"),
        ("Unknown Provider", None, "Should return None"),
    ]

    print("Testing Insurance Provider Mapping:")
    print("=" * 50)

    for provider, expected_id, description in test_cases:
        result = get_payer_id(provider)
        status = "✅" if result == expected_id else "❌"
        print(f"{status} {description}: '{provider}' -> {result}")

    print("\nTesting Validation:")
    print("=" * 30)

    # Test validation scenarios
    validation_tests = [
        ("Aetna", "60054", "Aetna Better Health", "Correct input"),
        ("Aetna", "64157", "City of Newark", "Wrong provider corrected"),
        ("Random Insurance", "62308", "Cigna Healthcare", "Unmapped input corrected"),
    ]

    for user_input, nirvana_payer, nirvana_plan, description in validation_tests:
        result = validate_and_correct_provider(user_input, nirvana_payer, nirvana_plan)
        print(f"📊 {description}:")
        print(f"   Original: {result['original_provider']}")
        print(f"   Corrected: {result['corrected_provider']}")
        print(f"   Was corrected: {result['was_corrected']}")
        print(f"   Status: {result['validation_status']}")
        print()
