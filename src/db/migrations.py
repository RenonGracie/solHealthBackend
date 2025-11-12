# src/db/migrations.py
"""
Database migration utilities that run on application startup.
"""
import logging
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from src.db import get_db

logger = logging.getLogger(__name__)


def check_column_exists(session, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    try:
        result = session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        return result.scalar()
    except Exception as e:
        logger.error(f"Error checking column existence: {e}")
        return False


def add_lived_experiences_column(session) -> bool:
    """
    Migration: Add lived_experiences column to therapists table.
    This column stores the consolidated "Lived Experiences" array from Airtable.

    Returns:
        bool: True if migration was applied, False if already exists or failed
    """
    try:
        # Check if column already exists
        if check_column_exists(session, "therapists", "lived_experiences"):
            logger.info("✅ Migration skipped: lived_experiences column already exists")
            return False

        logger.info("🔄 Running migration: Adding lived_experiences column...")

        # Add the column
        session.execute(
            text("ALTER TABLE therapists ADD COLUMN lived_experiences TEXT[]")
        )

        # Add comment for documentation
        session.execute(
            text(
                """
                COMMENT ON COLUMN therapists.lived_experiences IS
                'Consolidated lived experiences array from Airtable Lived Experiences column'
                """
            )
        )

        session.commit()
        logger.info("✅ Migration completed: lived_experiences column added successfully")
        return True

    except ProgrammingError as e:
        logger.error(f"❌ Migration failed: {e}")
        session.rollback()
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error during migration: {e}")
        session.rollback()
        return False


def run_migrations():
    """
    Run all pending migrations on application startup.
    This function is idempotent and safe to run multiple times.
    """
    logger.info("🚀 Starting database migrations...")

    with get_db() as session:
        migrations_applied = []

        # Migration 1: Add lived_experiences column
        if add_lived_experiences_column(session):
            migrations_applied.append("lived_experiences_column")

        # Future migrations can be added here
        # if add_some_other_column(session):
        #     migrations_applied.append("some_other_migration")

        if migrations_applied:
            logger.info(f"✅ Applied {len(migrations_applied)} migration(s): {', '.join(migrations_applied)}")
        else:
            logger.info("✅ All migrations up to date")

    logger.info("🎉 Database migration check complete")
