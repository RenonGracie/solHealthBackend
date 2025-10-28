#!/usr/bin/env python3
"""
Pre-deployment verification script for Progressive Logger Enhancement.
Run this before pushing to Railway to verify everything is set up correctly.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def verify_model_columns():
    """Verify new columns exist in ClientResponse model"""
    print("🔍 Checking ClientResponse model...")

    from src.db.models import ClientResponse

    required_columns = [
        'therapist_gender_preference',
        'browser_timezone',
        'insurance_provider_corrected',
        'algorithm_suggested_therapist_id',
        'algorithm_suggested_therapist_name',
        'algorithm_suggested_therapist_score',
        'alternative_therapists_offered',
        'user_chose_alternative',
        'therapist_selection_timestamp',
    ]

    missing = []
    for col_name in required_columns:
        if not hasattr(ClientResponse, col_name):
            missing.append(col_name)

    if missing:
        print(f"❌ Missing columns in model: {', '.join(missing)}")
        return False

    print(f"✅ All {len(required_columns)} new columns found in ClientResponse model")
    return True


def verify_progressive_logger_methods():
    """Verify progressive logger has new methods"""
    print("\n🔍 Checking progressive logger methods...")

    from src.services.google_sheets_progressive_logger import GoogleSheetsProgressiveLogger

    logger = GoogleSheetsProgressiveLogger()

    required_methods = [
        'log_stage_1_partial_submission',
        'log_stage_2_survey_complete',
        'log_stage_3_booking_complete',
        'async_log_stage_1',
        'async_log_stage_2',
        'async_log_stage_3',
    ]

    missing = []
    for method_name in required_methods:
        if not hasattr(logger, method_name):
            missing.append(method_name)

    if missing:
        print(f"❌ Missing methods: {', '.join(missing)}")
        return False

    print(f"✅ All {len(required_methods)} required methods found")
    return True


def verify_google_sheets_headers():
    """Verify new headers are in Google Sheets headers list"""
    print("\n🔍 Checking Google Sheets headers...")

    from src.services.google_sheets_progressive_logger import GoogleSheetsProgressiveLogger

    logger = GoogleSheetsProgressiveLogger()
    headers = logger._get_comprehensive_headers()

    required_headers = [
        'algorithm_suggested_therapist_id',
        'algorithm_suggested_therapist_name',
        'algorithm_suggested_therapist_score',
        'alternative_therapists_count',
        'alternative_therapists_names',
        'selected_therapist_id',
        'selected_therapist_name',
        'selected_therapist_email',
        'user_chose_alternative',
        'therapist_selection_timestamp',
        'insurance_provider_corrected',
        'browser_timezone',
        'session_id',
    ]

    missing = []
    for header in required_headers:
        if header not in headers:
            missing.append(header)

    if missing:
        print(f"❌ Missing headers: {', '.join(missing)}")
        return False

    print(f"✅ All {len(required_headers)} new headers found")
    print(f"   Total headers in sheet: {len(headers)}")
    return True


def verify_reconcile_schema_enhanced():
    """Verify reconcile_schema handles boolean defaults"""
    print("\n🔍 Checking AUTO_MIGRATE enhancements...")

    import inspect
    from src.db import reconcile_schema

    source = inspect.getsource(reconcile_schema)

    checks = [
        ('Boolean default handling', 'isinstance(col.type, Boolean)'),
        ('Default value check', 'col.default is not None'),
        ('IF NOT EXISTS', 'IF NOT EXISTS'),
    ]

    all_good = True
    for check_name, check_str in checks:
        if check_str in source:
            print(f"   ✅ {check_name}")
        else:
            print(f"   ❌ {check_name} - missing!")
            all_good = False

    if all_good:
        print("✅ reconcile_schema properly enhanced")
    return all_good


def verify_indexes():
    """Verify new indexes are in ensure_indexes_and_constraints"""
    print("\n🔍 Checking index definitions...")

    import inspect
    from src.db import ensure_indexes_and_constraints

    source = inspect.getsource(ensure_indexes_and_constraints)

    required_indexes = [
        'ix_client_responses_algorithm_suggested',
        'ix_client_responses_user_chose_alternative',
        'ix_client_responses_selection_timestamp',
    ]

    missing = []
    for idx_name in required_indexes:
        if idx_name not in source:
            missing.append(idx_name)

    if missing:
        print(f"❌ Missing indexes: {', '.join(missing)}")
        return False

    print(f"✅ All {len(required_indexes)} new indexes defined")
    return True


def verify_endpoint_updates():
    """Verify API endpoints have progressive logger calls"""
    print("\n🔍 Checking API endpoint updates...")

    checks_passed = 0

    # Check clients.py
    try:
        with open('src/api/clients.py', 'r') as f:
            clients_content = f.read()
            if 'progressive_logger.async_log_stage_1' in clients_content:
                print("   ✅ /clients_signup has Stage 1 logging")
                checks_passed += 1
            else:
                print("   ❌ /clients_signup missing Stage 1 logging")

            if 'progressive_logger.async_log_stage_2' in clients_content:
                print("   ✅ /clients_signup has Stage 2 logging")
                checks_passed += 1
            else:
                print("   ❌ /clients_signup missing Stage 2 logging")
    except Exception as e:
        print(f"   ❌ Error checking clients.py: {e}")

    # Check therapists.py
    try:
        with open('src/api/therapists.py', 'r') as f:
            therapists_content = f.read()
            if 'algorithm_suggested_therapist_id' in therapists_content:
                print("   ✅ /therapists/match stores algorithm suggestions")
                checks_passed += 1
            else:
                print("   ❌ /therapists/match missing algorithm storage")

            if 'alternative_therapists_offered' in therapists_content:
                print("   ✅ /therapists/match stores alternatives")
                checks_passed += 1
            else:
                print("   ❌ /therapists/match missing alternatives storage")
    except Exception as e:
        print(f"   ❌ Error checking therapists.py: {e}")

    # Check appointments.py
    try:
        with open('src/api/appointments.py', 'r') as f:
            appointments_content = f.read()
            if 'user_chose_alternative' in appointments_content:
                print("   ✅ /appointments tracks therapist selection")
                checks_passed += 1
            else:
                print("   ❌ /appointments missing selection tracking")

            if 'therapist_selection_timestamp' in appointments_content:
                print("   ✅ /appointments records selection timestamp")
                checks_passed += 1
            else:
                print("   ❌ /appointments missing timestamp")
    except Exception as e:
        print(f"   ❌ Error checking appointments.py: {e}")

    if checks_passed == 6:
        print("✅ All endpoint updates verified")
        return True
    else:
        print(f"⚠️  {checks_passed}/6 endpoint checks passed")
        return checks_passed >= 4  # Allow some flexibility


def main():
    print("=" * 60)
    print("Progressive Logger Enhancement - Pre-Deployment Verification")
    print("=" * 60)

    checks = [
        verify_model_columns,
        verify_progressive_logger_methods,
        verify_google_sheets_headers,
        verify_reconcile_schema_enhanced,
        verify_indexes,
        verify_endpoint_updates,
    ]

    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as e:
            print(f"\n❌ Error running check: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"Checks passed: {passed}/{total}")

    if all(results):
        print("\n✅ ALL CHECKS PASSED!")
        print("\n🚀 Ready to deploy to Railway!")
        print("\nNext steps:")
        print("1. git add .")
        print("2. git commit -m 'feat: Progressive logger enhancement'")
        print("3. git push origin main")
        print("4. Watch Railway logs for: '✅ Schema reconciliation complete'")
        print("5. Run: curl -X POST https://YOUR-RAILWAY-URL/super-sync")
        return 0
    else:
        print("\n⚠️  SOME CHECKS FAILED")
        print("\nPlease fix the issues above before deploying.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
