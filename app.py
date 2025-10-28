#!/usr/bin/env python
"""Railway deployment entry point for Sol Health Backend."""
import logging
import os
import sys

from src import create_app
from src.config import get_config

# Set up basic logging first
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main application entry point with error handling."""
    try:
        logger.info("🚀 Starting Sol Health Backend...")

        # Get port from environment (Railway automatically sets this)
        port = int(os.getenv("PORT", 8080))
        logger.info(f"🔌 Port from environment: {port}")

        # Print environment info for debugging
        logger.info(f"📍 Environment: {os.getenv('ENV', 'prod')}")

        # Check database connection info
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            logger.info("🗄️ DATABASE_URL: SET (Railway PostgreSQL)")
            # Fix postgres:// to postgresql:// for SQLAlchemy
            if database_url.startswith("postgres://"):
                os.environ["DATABASE_URL"] = database_url.replace(
                    "postgres://", "postgresql://", 1
                )
                logger.info("✅ Fixed DATABASE_URL format for SQLAlchemy")
        else:
            # Check for individual PG variables
            pghost = os.getenv("PGHOST")
            if pghost:
                logger.info(f"🗄️ Using Railway PG variables: {pghost}")
            else:
                logger.warning("⚠️ No Railway database variables found")

        logger.info(
            f"🗂️ Airtable API Key: {'SET' if os.getenv('AIRTABLE_API_KEY') else 'NOT SET'}"
        )

        # Create app using imported modules

        # Get configuration
        env = os.getenv("ENV", "prod")
        logger.info(f"⚙️ Loading config for environment: {env}")
        config = get_config(env)

        # Create Flask app
        logger.info("🏗️ Creating Flask application...")
        app = create_app(config)

        logger.info(f"✅ Application created successfully!")
        logger.info(f"🌍 Starting server on 0.0.0.0:{port}")

        # For Railway, we should use gunicorn in production
        # But for debugging, let's use Flask's built-in server
        if env == "prod" and os.getenv("USE_GUNICORN", "false").lower() == "true":
            # This would be handled by the Procfile/start command
            logger.info("Running in production mode with gunicorn")
        else:
            # Development/debugging mode
            app.run(
                host="0.0.0.0",
                port=port,
                debug=False,  # Never use debug=True in production
                use_reloader=False,  # Disable reloader in production
            )

    except ImportError as e:
        logger.error(f"❌ Import Error: {str(e)}")
        logger.error("Make sure all dependencies are installed")
        sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Startup Error: {str(e)}")
        logger.error("Full error details:", exc_info=True)

        # Try to provide helpful debugging info
        if "psycopg2" in str(e) or "postgresql" in str(e).lower():
            logger.error("\n🔍 Database Connection Debug:")
            logger.error(
                f"  DATABASE_URL: {'SET' if os.getenv('DATABASE_URL') else 'NOT SET'}"
            )
            logger.error(f"  PGHOST: {os.getenv('PGHOST', 'NOT SET')}")
            logger.error(f"  PGDATABASE: {os.getenv('PGDATABASE', 'NOT SET')}")

        sys.exit(1)


# Create the app instance for Gunicorn
# Get configuration
env = os.getenv("ENV", "prod")
config = get_config(env)

# Create Flask app instance that Gunicorn can find
app = create_app(config)

if __name__ == "__main__":
    main()
