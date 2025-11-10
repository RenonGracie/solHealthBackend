"""
Admin endpoints for database management and debugging.
"""
import logging
import os
from flask import Blueprint, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

try:
    from src.db import get_engine
except ImportError:
    # Fallback for when db module is not available
    def get_engine():
        raise ImportError("Database engine not available")

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/db/add-mandatory-form-columns", methods=["POST"])
def add_mandatory_form_columns():
    """Add mandatory form tracking columns to client_responses table."""
    try:
        # Check if running in production
        env = os.getenv("ENV", "dev")
        if env == "prod":
            return jsonify({"error": "Admin endpoints disabled in production"}), 403

        engine = get_engine()
        
        logger.info("🔄 Adding mandatory form columns to client_responses table...")
        
        # SQL commands to add the new columns
        add_columns_sql = [
            "ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS intakeq_intake_url VARCHAR;",
            "ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS mandatory_form_sent BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS mandatory_form_intake_id VARCHAR;",
            "ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS mandatory_form_intake_url VARCHAR;",
            "ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS mandatory_form_sent_at TIMESTAMP;",
        ]
        
        # SQL commands to add indexes for better performance
        add_indexes_sql = [
            "CREATE INDEX IF NOT EXISTS idx_client_responses_mandatory_form_sent ON client_responses (mandatory_form_sent);",
            "CREATE INDEX IF NOT EXISTS idx_client_responses_mandatory_form_intake_id ON client_responses (mandatory_form_intake_id);",
        ]
        
        results = {
            "columns_added": [],
            "indexes_added": [],
            "errors": []
        }
        
        with engine.connect() as conn:
            # Add columns
            for sql in add_columns_sql:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    column_name = sql.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0]
                    results["columns_added"].append(column_name)
                    logger.info(f"✅ Added column: {column_name}")
                except Exception as e:
                    error_msg = f"Error adding column: {str(e)}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
            
            # Add indexes
            for sql in add_indexes_sql:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    index_name = sql.split("CREATE INDEX IF NOT EXISTS ")[1].split(" ")[0]
                    results["indexes_added"].append(index_name)
                    logger.info(f"✅ Added index: {index_name}")
                except Exception as e:
                    error_msg = f"Error adding index: {str(e)}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
            
            # Verify the columns were added
            verification_sql = """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'client_responses' 
                AND column_name IN (
                    'intakeq_intake_url', 
                    'mandatory_form_sent', 
                    'mandatory_form_intake_id', 
                    'mandatory_form_intake_url', 
                    'mandatory_form_sent_at'
                )
                ORDER BY column_name;
            """
            
            result = conn.execute(text(verification_sql))
            columns_info = []
            for row in result:
                columns_info.append({
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": row[2],
                    "column_default": row[3]
                })
            
            results["verified_columns"] = columns_info
        
        if results["errors"]:
            logger.warning(f"⚠️ Some operations failed: {results['errors']}")
            return jsonify({
                "success": False,
                "message": "Database schema update completed with some errors",
                "details": results
            }), 207  # 207 Multi-Status
        else:
            logger.info("✅ All mandatory form columns added successfully!")
            return jsonify({
                "success": True,
                "message": "Database schema updated successfully",
                "details": results
            })
    
    except SQLAlchemyError as e:
        logger.error(f"❌ Database error during schema update: {str(e)}")
        return jsonify({
            "error": f"Database error: {str(e)}"
        }), 500
    
    except Exception as e:
        logger.error(f"❌ Unexpected error during schema update: {str(e)}")
        return jsonify({
            "error": f"Unexpected error: {str(e)}"
        }), 500


@admin_bp.route("/admin/db/check-mandatory-form-columns", methods=["GET"])
def check_mandatory_form_columns():
    """Check if mandatory form columns exist in client_responses table."""
    try:
        engine = get_engine()
        
        with engine.connect() as conn:
            # Check which columns exist
            check_sql = """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'client_responses' 
                AND column_name IN (
                    'intakeq_intake_url', 
                    'mandatory_form_sent', 
                    'mandatory_form_intake_id', 
                    'mandatory_form_intake_url', 
                    'mandatory_form_sent_at'
                )
                ORDER BY column_name;
            """
            
            result = conn.execute(text(check_sql))
            existing_columns = []
            for row in result:
                existing_columns.append({
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": row[2],
                    "column_default": row[3]
                })
            
            required_columns = [
                'intakeq_intake_url', 
                'mandatory_form_sent', 
                'mandatory_form_intake_id', 
                'mandatory_form_intake_url', 
                'mandatory_form_sent_at'
            ]
            
            existing_column_names = [col["column_name"] for col in existing_columns]
            missing_columns = [col for col in required_columns if col not in existing_column_names]
            
            return jsonify({
                "existing_columns": existing_columns,
                "missing_columns": missing_columns,
                "schema_ready": len(missing_columns) == 0,
                "total_required": len(required_columns),
                "total_existing": len(existing_columns)
            })
    
    except Exception as e:
        logger.error(f"❌ Error checking mandatory form columns: {str(e)}")
        return jsonify({
            "error": f"Database error: {str(e)}"
        }), 500


@admin_bp.route("/admin/environment/intakeq-forms", methods=["GET"])  
def check_intakeq_forms_env():
    """Check if the new IntakeQ form environment variables are set."""
    env = os.getenv("ENV", "dev")
    if env == "prod":
        return jsonify({"error": "Admin endpoints disabled in production"}), 403
        
    cash_pay_form_id = os.getenv("CASH_PAY_MANDATORY_FORM_ID")
    insurance_form_id = os.getenv("INSURANCE_MANDATORY_FORM_ID")  # Generic fallback
    nj_insurance_form_id = os.getenv("NJ_INSURANCE_MANDATORY_FORM_ID")
    ny_insurance_form_id = os.getenv("NY_INSURANCE_MANDATORY_FORM_ID")

    return jsonify({
        "cash_pay_form_id": {
            "present": bool(cash_pay_form_id),
            "value": cash_pay_form_id or "Not set"
        },
        "insurance_form_id": {
            "present": bool(insurance_form_id),
            "value": insurance_form_id or "Not set",
            "note": "Generic fallback - prefer state-specific IDs below"
        },
        "nj_insurance_form_id": {
            "present": bool(nj_insurance_form_id),
            "value": nj_insurance_form_id or "Not set (falls back to insurance_form_id)",
            "env_var": "NJ_INSURANCE_MANDATORY_FORM_ID"
        },
        "ny_insurance_form_id": {
            "present": bool(ny_insurance_form_id),
            "value": ny_insurance_form_id or "Not set (falls back to insurance_form_id)",
            "env_var": "NY_INSURANCE_MANDATORY_FORM_ID"
        },
        "ready_for_mandatory_forms": bool(cash_pay_form_id and (nj_insurance_form_id or insurance_form_id) and (ny_insurance_form_id or insurance_form_id))
    })


@admin_bp.route("/admin/test/nirvana-callback", methods=["POST"])
def test_nirvana_callback():
    """
    Test endpoint to simulate Nirvana callback with sample data.

    This endpoint allows testing the complete Nirvana → Comprehensive Logger → Google Sheets flow
    without needing to trigger an actual insurance verification.

    Usage:
        POST /admin/test/nirvana-callback
        Body: JSON with Nirvana response structure (or empty to use default sample)

    Returns:
        Detailed report showing:
        - What data was extracted
        - What fields were sent to Google Sheets
        - Which columns were populated
        - Any missing or mismatched fields
    """
    try:
        # Check if running in production
        env = os.getenv("ENV", "dev")
        if env == "prod":
            return jsonify({"error": "Admin endpoints disabled in production"}), 403

        logger.info("🧪 [TEST] Nirvana callback test endpoint called")

        # Get test data from request or use default sample
        from flask import request as flask_request
        test_data = flask_request.get_json() or {}

        # If no data provided, use comprehensive sample structure
        if not test_data or not test_data.get("nirvana_data"):
            logger.info("📋 Using default sample Nirvana data structure")
            test_data = {
                "response_id": f"test_{os.urandom(4).hex()}",
                "payment_type": "insurance",
                "nirvana_data": {
                    # Plan information
                    "plan_name": "Aetna Better Health of New Jersey",
                    "group_id": "GRP123456",
                    "payer_id": "60054",
                    "plan_status": "Active",
                    "coverage_status": "Covered",
                    "relationship_to_subscriber": "Self",
                    "insurance_type": "PPO",

                    # Member demographics
                    "demographics": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "middle_name": "Q",
                        "date_of_birth": "1990-01-15",
                        "gender": "Male",
                        "member_id": "MEM789012345",
                        "phone": "5551234567",
                        "email": "john.doe@example.com",
                        "address": {
                            "street_line_1": "123 Main Street",
                            "street_line_2": "Apt 4B",
                            "city": "Newark",
                            "state": "NJ",
                            "zip": "07102",
                            "country": "USA"
                        }
                    },

                    # Subscriber demographics (policyholder - may be same or different from member)
                    "subscriber_demographics": {
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "date_of_birth": "1988-05-20",
                        "gender": "Female",
                        "address": {
                            "street_line_1": "456 Oak Avenue",
                            "street_line_2": "",
                            "city": "Jersey City",
                            "state": "NJ",
                            "zip": "07030"
                        }
                    },

                    # Financial information
                    "copay": 3000,  # in cents = $30.00
                    "deductible": 150000,  # in cents = $1,500.00
                    "remaining_deductible": 75000,  # in cents = $750.00
                    "oop_max": 500000,  # in cents = $5,000.00
                    "remaining_oop_max": 350000,  # in cents = $3,500.00
                    "member_obligation": 3000,  # in cents = $30.00
                    "payer_obligation": 12066,  # in cents = $120.66
                    "benefit_structure": "Copay after deductible",

                    # Eligibility dates
                    "plan_begin_date": "2024-01-01",
                    "plan_end_date": "2024-12-31",
                    "eligibility_end_date": "2024-12-31"
                },

                # Insurance correction tracking (if provider name was corrected)
                "insurance_provider_original": "Aetna",
                "insurance_provider_corrected": "Aetna Better Health of New Jersey",
                "insurance_correction_type": "provider_name_enhanced"
            }

        # Import the data flow components
        from src.utils.comprehensive_data_logger import ensure_comprehensive_logging
        from src.services.data_flow_integration import log_nirvana_response_immediately
        from src.services.google_sheets_progressive_logger import progressive_logger

        # Step 1: Run comprehensive data extraction
        logger.info("=" * 60)
        logger.info("🔍 [TEST STEP 1] Running comprehensive data extraction")
        comprehensive_data = ensure_comprehensive_logging(test_data)

        extraction_report = {
            "total_fields_extracted": comprehensive_data.get("_fields_extracted", 0),
            "data_sources_found": comprehensive_data.get("_data_sources_found", []),
            "nirvana_data_present": bool(comprehensive_data.get("nirvana_data")),
            "sample_extracted_fields": {}
        }

        # Check specific Nirvana fields that should be extracted
        nirvana_check_fields = [
            "nirvana_data", "plan_name", "group_id", "payer_id",
            "first_name", "last_name", "street_address", "city", "state",
            "copay", "deductible", "member_obligation",
            "insurance_provider_original", "insurance_provider_corrected"
        ]

        for field in nirvana_check_fields:
            if field in comprehensive_data:
                value = comprehensive_data[field]
                if isinstance(value, dict):
                    extraction_report["sample_extracted_fields"][field] = f"dict with {len(value)} keys"
                elif isinstance(value, (int, float)):
                    extraction_report["sample_extracted_fields"][field] = value
                elif isinstance(value, str) and len(value) > 50:
                    extraction_report["sample_extracted_fields"][field] = f"{value[:50]}..."
                else:
                    extraction_report["sample_extracted_fields"][field] = value

        logger.info(f"✅ Extracted {extraction_report['total_fields_extracted']} fields")

        # Step 2: Flatten data for Google Sheets
        logger.info("=" * 60)
        logger.info("🔍 [TEST STEP 2] Flattening data for Google Sheets")

        # Add response_id if not present
        comprehensive_data["response_id"] = test_data.get("response_id", "test_response")

        row_data = progressive_logger._flatten_data_progressive(comprehensive_data, stage=2)
        headers = progressive_logger._get_comprehensive_headers()

        # Check which Nirvana columns got populated
        nirvana_columns_check = [
            "insurance_provider_original", "insurance_provider_corrected", "insurance_correction_type",
            "nirvana_plan_name", "nirvana_group_id", "nirvana_payer_id",
            "nirvana_plan_status", "nirvana_coverage_status", "nirvana_relationship_to_subscriber",
            "nirvana_insurance_type", "nirvana_insurance_company_name",
            "nirvana_member_id_policy_number", "nirvana_group_number", "nirvana_plan_program",
            "nirvana_policyholder_relationship", "nirvana_policyholder_name",
            "nirvana_policyholder_first_name", "nirvana_policyholder_last_name",
            "nirvana_policyholder_street_address", "nirvana_policyholder_city"
        ]

        sheets_column_values = {}
        missing_columns = []
        populated_columns = []

        for column in nirvana_columns_check:
            if column in headers:
                idx = headers.index(column)
                value = row_data[idx] if idx < len(row_data) else ""

                if value and str(value).strip():
                    populated_columns.append(column)
                    sheets_column_values[column] = value
                else:
                    missing_columns.append(column)

        logger.info(f"✅ Populated {len(populated_columns)} Nirvana columns")
        logger.info(f"⚠️  Missing {len(missing_columns)} Nirvana columns")

        # Step 3: Test actual Google Sheets logging (dry run - just analyze, don't write)
        logger.info("=" * 60)
        logger.info("🔍 [TEST STEP 3] Analyzing Google Sheets write readiness")

        sheets_ready = {
            "logger_enabled": progressive_logger.enabled,
            "sheet_id": progressive_logger.sheet_id if progressive_logger.enabled else "Not configured",
            "would_attempt_write": progressive_logger.enabled,
            "row_data_length": len(row_data),
            "headers_length": len(headers),
            "alignment": "✅ Aligned" if len(row_data) == len(headers) else f"❌ MISALIGNED (data: {len(row_data)}, headers: {len(headers)})"
        }

        logger.info("=" * 60)

        # Compile comprehensive test report
        test_report = {
            "test_id": test_data.get("response_id"),
            "test_timestamp": os.popen('date').read().strip(),
            "extraction_analysis": extraction_report,
            "google_sheets_columns": {
                "total_nirvana_columns_checked": len(nirvana_columns_check),
                "populated_columns": len(populated_columns),
                "missing_columns": len(missing_columns),
                "populated_column_names": populated_columns,
                "missing_column_names": missing_columns,
                "sample_values": sheets_column_values
            },
            "sheets_write_readiness": sheets_ready,
            "recommendations": []
        }

        # Add recommendations based on findings
        if missing_columns:
            test_report["recommendations"].append(
                f"⚠️ {len(missing_columns)} Nirvana columns are not being populated. Check field mapping in comprehensive_data_logger.py"
            )

        if not comprehensive_data.get("nirvana_data"):
            test_report["recommendations"].append(
                "❌ CRITICAL: nirvana_data structure not found in comprehensive_data. Check ensure_comprehensive_logging()"
            )

        if sheets_ready["alignment"] != "✅ Aligned":
            test_report["recommendations"].append(
                "❌ CRITICAL: Row data and headers are misaligned. This will cause incorrect Google Sheets writes."
            )

        if not sheets_ready["logger_enabled"]:
            test_report["recommendations"].append(
                "⚠️  Google Sheets logger is disabled. Set GOOGLE_SHEETS_ID and credentials to test actual writes."
            )

        if not missing_columns and comprehensive_data.get("nirvana_data"):
            test_report["recommendations"].append(
                "✅ All Nirvana columns are populated correctly! Data flow is working as expected."
            )

        logger.info("=" * 60)
        logger.info("🧪 [TEST COMPLETE] Nirvana callback test finished")
        logger.info(f"  Populated: {len(populated_columns)}/{len(nirvana_columns_check)} columns")
        logger.info(f"  Recommendations: {len(test_report['recommendations'])}")
        logger.info("=" * 60)

        return jsonify({
            "success": True,
            "message": "Nirvana callback test completed",
            "report": test_report
        }), 200

    except Exception as e:
        logger.error(f"❌ Error in Nirvana callback test: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500