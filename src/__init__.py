# src/__init__.py
"""Sol Health Backend API with Aurora PostgreSQL."""
import logging
import os

from flask import Flask
from flask_cors import CORS

from src.api import register_blueprints
from src.config import Config
from src.db import health_check, init_db, register_cli_commands
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def create_app(config: Config) -> Flask:
    """Application factory."""
    app = Flask(__name__)

    # Convert our Config object to Flask's config format
    app.config.from_object(config)

    # Also store our config object for direct access
    app.sol_config = config

    # Setup logging
    setup_logging(app)

    # Initialize extensions
    CORS(app, origins=config.CORS_ORIGINS.split(","))

    # Initialize database - pass our config object
    logger.info("Initializing database connection...")
    try:
        init_db(app, config)  # Pass both app and config
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        logger.warning("🚨 App starting without database connection - health endpoint will show degraded status")
        # Don't raise - allow app to start for healthcheck purposes

    # Register CLI commands
    register_cli_commands(app)

    # Register blueprints
    register_blueprints(app)

    # Initialize scheduler for periodic Airtable sync
    if not config.TESTING:
        try:
            from src.services.scheduler import init_scheduler

            init_scheduler(app)
        except Exception as e:
            logger.warning(f"Failed to initialize scheduler: {str(e)}")

    # Health check endpoint
    @app.route("/health")
    def health():
        db_healthy = health_check()
        status = "healthy" if db_healthy else "degraded"

        return {
            "status": status,
            "service": "solhealth-backend",
            "database": "healthy" if db_healthy else "unhealthy",
            "version": "2.0.0",
            "environment": config.ENV,
        }, 200  # Always return 200 for healthcheck endpoint availability

    @app.route("/debug/routes")
    def list_routes():
        """Debug endpoint to see all registered routes."""
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append(
                {
                    "endpoint": rule.endpoint,
                    "methods": list(rule.methods),
                    "rule": str(rule),
                }
            )
        return {"routes": routes}

    @app.route("/debug/config")
    def debug_config():
        """Debug endpoint to check configuration (don't use in production)."""
        if config.ENV == "prod":
            return {"error": "Debug endpoints disabled in production"}, 403

        return {
            "database_host": config.PGHOST or "via DATABASE_URL",
            "database_name": config.PGDATABASE or "via DATABASE_URL",
            "database_user": config.PGUSER or "via DATABASE_URL",
            "airtable_configured": bool(config.AIRTABLE_API_KEY),
            "environment": config.ENV,
            "debug_mode": config.DEBUG,
        }

    @app.route("/debug/intakeq-env")
    def debug_intakeq_env():
        """Debug endpoint to check IntakeQ environment variables."""
        if config.ENV == "prod":
            return {"error": "Debug endpoints disabled in production"}, 403

        cash_pay_key = os.getenv("CASH_PAY_INTAKEQ_API_KEY")
        insurance_key = os.getenv("INSURANCE_INTAKEQ_API_KEY")

        return {
            "cash_pay_key_present": bool(cash_pay_key),
            "cash_pay_key_length": len(cash_pay_key) if cash_pay_key else 0,
            "cash_pay_key_start": cash_pay_key[:10] + "..." if cash_pay_key else "None",
            "insurance_key_present": bool(insurance_key),
            "insurance_key_length": len(insurance_key) if insurance_key else 0,
            "insurance_key_start": insurance_key[:10] + "..."
            if insurance_key
            else "None",
            "all_env_vars": [
                key for key in os.environ.keys() if "INTAKEQ" in key.upper()
            ],
        }

    @app.route("/debug/healthcheck")  
    def debug_healthcheck():
        """Debug endpoint to diagnose healthcheck issues."""
        import traceback
        import sys
        import os
        from datetime import datetime
        
        debug_info = {
            "timestamp": datetime.utcnow().isoformat(),
            "python_version": sys.version,
            "working_directory": os.getcwd(),
            "environment_vars": {
                "DATABASE_URL": "***MASKED***" if os.getenv("DATABASE_URL") else None,
                "PGHOST": os.getenv("PGHOST"),
                "ENV": os.getenv("ENV"),
                "PORT": os.getenv("PORT"),
            },
            "import_tests": {},
            "app_status": {},
            "database_status": {},
        }
        
        # Test critical imports
        try:
            from src.services.data_flow_integration import ensure_user_data_initialized
            debug_info["import_tests"]["data_flow_integration"] = "✅ Success"
        except Exception as e:
            debug_info["import_tests"]["data_flow_integration"] = f"❌ {str(e)}"
        
        try:
            from src.services.user_data_manager import user_data_manager
            debug_info["import_tests"]["user_data_manager"] = "✅ Success"
        except Exception as e:
            debug_info["import_tests"]["user_data_manager"] = f"❌ {str(e)}"
        
        try:
            from src.api.intakeq_forms import intakeq_forms_bp
            debug_info["import_tests"]["intakeq_forms"] = "✅ Success"
        except Exception as e:
            debug_info["import_tests"]["intakeq_forms"] = f"❌ {str(e)}"
        
        # Test database connection
        try:
            from src.db import health_check
            db_healthy = health_check()
            debug_info["database_status"]["health_check"] = "✅ Healthy" if db_healthy else "❌ Unhealthy"
        except Exception as e:
            debug_info["database_status"]["health_check"] = f"❌ Error: {str(e)}"
        
        # Test Flask app status
        debug_info["app_status"]["flask_initialized"] = "✅ Success"
        debug_info["app_status"]["cors_enabled"] = "✅ Success"
        
        # Check if database was initialized
        try:
            from src.db import engine
            debug_info["database_status"]["engine_initialized"] = "✅ Success" if engine else "❌ None"
        except Exception as e:
            debug_info["database_status"]["engine_initialized"] = f"❌ Error: {str(e)}"
        
        return debug_info, 200

    @app.route("/debug/db-status")
    def db_status():
        """Check database and data status."""
        from src.db import get_db_session
        from src.db.models import ClientResponse, SyncLog, Therapist

        session = get_db_session()
        try:
            therapist_count = session.query(Therapist).count()
            accepting_count = (
                session.query(Therapist)
                .filter(Therapist.accepting_new_clients is True)
                .count()
            )
            client_count = session.query(ClientResponse).count()
            sync_count = session.query(SyncLog).count()

            # Get last sync info
            last_sync = (
                session.query(SyncLog).order_by(SyncLog.started_at.desc()).first()
            )

            last_sync_info = None
            if last_sync:
                last_sync_info = {
                    "started_at": last_sync.started_at.isoformat()
                    if last_sync.started_at
                    else None,
                    "status": last_sync.status,
                    "records_processed": last_sync.records_processed,
                    "records_created": last_sync.records_created,
                    "records_updated": last_sync.records_updated,
                }

            return {
                "database_connected": True,
                "therapists_total": therapist_count,
                "therapists_accepting": accepting_count,
                "client_responses": client_count,
                "sync_logs": sync_count,
                "last_sync": last_sync_info,
                "needs_initial_sync": therapist_count == 0,
            }
        except Exception as e:
            logger.error(f"Error checking database status: {str(e)}")
            return {"database_connected": False, "error": str(e)}, 500
        finally:
            session.close()

    # Sync on startup if configured - Fixed for Flask 3.0+
    if config.SYNC_ON_STARTUP and not config.TESTING:
        with app.app_context():
            try:
                from src.db import get_db_session
                from src.db.models import Therapist
                from src.services.airtable_sync_service import airtable_sync_service

                # Check if we need initial sync
                session = get_db_session()
                therapist_count = session.query(Therapist).count()
                session.close()

                if therapist_count == 0:
                    logger.info(
                        "🔄 No therapists found. Starting initial Airtable sync..."
                    )
                    result = airtable_sync_service.sync_all_therapists()
                    logger.info(
                        f"✅ Startup sync completed: {result['records_processed']} records processed, "
                        f"{result['records_created']} created, {result['records_updated']} updated"
                    )
                else:
                    logger.info(
                        f"✅ Found {therapist_count} therapists in database. Skipping startup sync."
                    )

            except Exception as e:
                logger.error(f"❌ Startup sync failed: {str(e)}")
                # Don't fail startup, just log the error

    logger.info("✅ Sol Health Backend initialized successfully")
    return app
