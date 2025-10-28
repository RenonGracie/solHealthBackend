# src/config.py - Fixed Railway PostgreSQL Configuration
"""Application configuration for Railway deployment."""
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration for Railway PostgreSQL."""

    # Environment
    ENV: str = os.getenv("ENV", "prod")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TESTING: bool = False

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key")
    )
    JWT_ACCESS_TOKEN_EXPIRES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", "3600"))

    # Railway PostgreSQL Configuration
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

    # Railway individual variables
    PGHOST: str = os.getenv("PGHOST", "")
    PGPORT: int = int(os.getenv("PGPORT", "5432"))
    PGUSER: str = os.getenv("PGUSER", "")
    PGPASSWORD: str = os.getenv("PGPASSWORD", "")
    PGDATABASE: str = os.getenv("PGDATABASE", "")

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Database URI for SQLAlchemy - Railway ONLY."""
        # Option 1: Railway's DATABASE_URL (preferred)
        if self.DATABASE_URL:
            # Fix postgres:// to postgresql:// for SQLAlchemy
            if self.DATABASE_URL.startswith("postgres://"):
                return self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
            return self.DATABASE_URL

        # Option 2: Railway's individual PG variables
        if self.PGHOST and self.PGUSER and self.PGPASSWORD and self.PGDATABASE:
            return (
                f"postgresql://{self.PGUSER}:{self.PGPASSWORD}"
                f"@{self.PGHOST}:{self.PGPORT}/{self.PGDATABASE}"
            )

        # Fallback for local development
        return "postgresql://postgres:password@localhost:5432/solhealth"

    # Airtable Configuration (REQUIRED)
    AIRTABLE_API_KEY: str = os.getenv("AIRTABLE_API_KEY", "")
    AIRTABLE_BASE_ID: str = os.getenv("AIRTABLE_BASE_ID", "")
    AIRTABLE_TABLE_ID: str = os.getenv("AIRTABLE_TABLE_ID", "Therapists")

    # IntakeQ API Configuration
    CASH_PAY_INTAKEQ_API_KEY: str = os.getenv("CASH_PAY_INTAKEQ_API_KEY", "")
    INSURANCE_INTAKEQ_API_KEY: str = os.getenv("INSURANCE_INTAKEQ_API_KEY", "")
    INTAKEQ_BASE_URL: str = os.getenv("INTAKEQ_BASE_URL", "https://intakeq.com/api/v1")
    INTAKEQ_AUTH_KEY: str = os.getenv(
        "INTAKEQ_AUTH_KEY", os.getenv("CASH_PAY_INTAKEQ_API_KEY", "")
    )

    # IntakeQ Test/Development IDs
    TEST_USER_ID: str = os.getenv("TEST_USER_ID", "")
    TEST_PRACTITIONER_ID: str = os.getenv("TEST_PRACTITIONER_ID", "")

    # IntakeQ Bot Integration
    BOT_URL: str = os.getenv("BOT_URL", "")
    INTAKEQ_SIGNUP_FORM: str = os.getenv("INTAKEQ_SIGNUP_FORM", "")
    SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID", "")

    # IntakeQ Form IDs
    CASH_PAY_MANDATORY_FORM_ID: str = os.getenv("CASH_PAY_MANDATORY_FORM_ID", "")
    INSURANCE_MANDATORY_FORM_ID: str = os.getenv("INSURANCE_MANDATORY_FORM_ID", "")

    # Insurance Verification
    NIRVANA_API_KEY: str = os.getenv("NIRVANA_API_KEY", "")
    NIRVANA_API_URL: str = os.getenv(
        "NIRVANA_API_URL", "https://coverage-api-sandbox.meetnirvana.com/v1"
    )

    # Analytics
    ANALYTICS_MEASUREMENT_ID: str = os.getenv("ANALYTICS_MEASUREMENT_ID", "")
    ANALYTICS_API_SECRET: str = os.getenv("ANALYTICS_API_SECRET", "")
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")

    # Email
    SES_FROM_EMAIL: str = os.getenv("SES_FROM_EMAIL", "noreply@solhealth.co")
    CONTACT_EMAIL: str = os.getenv("CONTACT_EMAIL", "contact@solhealth.co")

    # CORS
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,https://app.solhealth.co,https://hello.solhealth.co,https://solhealthfe-production.up.railway.app"
    )

    # Redis Cache (Optional)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")

    # Sync Configuration
    AUTO_SYNC_INTERVAL_HOURS: int = int(os.getenv("AUTO_SYNC_INTERVAL_HOURS", "6"))
    SYNC_ON_STARTUP: bool = os.getenv("SYNC_ON_STARTUP", "true").lower() == "true"

    # Google Sheets Logging (Optional)
    GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_SHEETS_CREDENTIALS: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")

    # Feature Flags
    ENABLE_INSURANCE_VERIFICATION: bool = (
        os.getenv("ENABLE_INSURANCE_VERIFICATION", "false").lower() == "true"
    )
    ENABLE_ANALYTICS: bool = os.getenv("ENABLE_ANALYTICS", "false").lower() == "true"
    ENABLE_SENTRY: bool = os.getenv("ENABLE_SENTRY", "false").lower() == "true"

    # AWS S3 for therapist media (optional)
    AWS_REGION: str = os.getenv("AWS_REGION", "")
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "")
    IS_AWS: bool = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)

    def validate_required_config(self):
        """Validate that required configuration is present."""
        missing = []

        # Database is required
        if not self.DATABASE_URL and not all(
            [self.PGHOST, self.PGUSER, self.PGPASSWORD, self.PGDATABASE]
        ):
            missing.append("DATABASE_URL or PG* variables from Railway")

        # Airtable is required for sync
        if not self.AIRTABLE_API_KEY:
            missing.append("AIRTABLE_API_KEY")
        if not self.AIRTABLE_BASE_ID:
            missing.append("AIRTABLE_BASE_ID")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

    def get_database_info(self) -> dict:
        """Get database connection information for debugging."""
        return {
            "platform": "Railway PostgreSQL",
            "database_url_present": bool(self.DATABASE_URL),
            "railway_pg_vars": {
                "PGHOST": self.PGHOST or "NOT SET",
                "PGUSER": self.PGUSER or "NOT SET",
                "PGDATABASE": self.PGDATABASE or "NOT SET",
                "PGPORT": self.PGPORT,
                "PGPASSWORD": "SET" if self.PGPASSWORD else "NOT SET",
            },
            "final_database_uri": self.SQLALCHEMY_DATABASE_URI[:50] + "..."
            if self.SQLALCHEMY_DATABASE_URI
            else "NOT SET",
        }


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    ENV = "dev"


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    ENV = "test"
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    ENV = "prod"

    def __init__(self):
        super().__init__()
        try:
            self.validate_required_config()
        except ValueError as e:
            print(f"⚠️ Configuration Warning: {str(e)}")


def get_config(env: str = None) -> Config:
    """Get configuration based on environment."""
    if env is None:
        env = os.getenv("ENV", "prod")

    configs = {
        "dev": DevelopmentConfig,
        "development": DevelopmentConfig,
        "test": TestingConfig,
        "testing": TestingConfig,
        "prod": ProductionConfig,
        "production": ProductionConfig,
    }

    config_class = configs.get(env.lower(), ProductionConfig)
    return config_class()
