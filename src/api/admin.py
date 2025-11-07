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