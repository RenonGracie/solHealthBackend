# src/db/__init__.py - Railway PostgreSQL ONLY
"""Database initialization for Railway PostgreSQL (no Alembic)."""
import logging
import os
from contextlib import contextmanager

from flask import Flask, g
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

# Ensure models are imported so Base.metadata "knows" about all tables/columns
from .models import (  # noqa
    Appointment,
    Base,
    CalendarEvent,
    ClientResponse,
    SyncLog,
    Therapist,
)

logger = logging.getLogger(__name__)

# Global engine and session factory
engine = None
SessionLocal = None


def get_database_url() -> str:
    """Get database URL - Railway ONLY, no AWS RDS."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        logger.info("✅ Using DATABASE_URL from Railway")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    pghost = os.getenv("PGHOST")
    pguser = os.getenv("PGUSER")
    pgpassword = os.getenv("PGPASSWORD")
    pgdatabase = os.getenv("PGDATABASE")
    pgport = os.getenv("PGPORT", "5432")

    if all([pghost, pguser, pgpassword, pgdatabase]):
        database_url = (
            f"postgresql://{pguser}:{pgpassword}@{pghost}:{pgport}/{pgdatabase}"
        )
        logger.info(f"✅ Using Railway PG variables: {pghost}")
        return database_url

    logger.warning("⚠️ No Railway database config found, using localhost fallback")
    return "postgresql://postgres:password@localhost:5432/solhealth"


def create_tables_safely(engine):
    """Create tables, handling any existing database objects gracefully."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    logger.debug(f"📋 Existing tables: {existing_tables}")

    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.debug("✅ Database tables created/verified successfully")

        final_tables = inspector.get_table_names()
        logger.debug(f"📋 Final tables: {final_tables}")

        expected = [
            "therapists",
            "client_responses",
            "appointments",
            "calendar_events",
            "sync_logs",
        ]
        missing = set(expected) - set(final_tables)
        if missing:
            logger.warning(f"⚠️ Missing expected tables: {missing}")
        else:
            logger.info("✅ All expected tables present")
        return True

    except Exception as e:
        logger.error(f"❌ Error creating tables: {str(e)}")
        if "already exists" in str(e).lower():
            logger.info("ℹ️ Some database objects already exist, this is OK")
            return True
        raise


def _get_sql_type_for_column(col):
    """Map a SQLAlchemy Column to a PostgreSQL SQL type string for ALTER TABLE."""
    from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
    from sqlalchemy.dialects.postgresql import ARRAY, JSON, JSONB

    coltype = col.type
    # Arrays
    if isinstance(coltype, ARRAY):
        inner = coltype.item_type
        if isinstance(inner, String):
            return "VARCHAR[]"
        if isinstance(inner, Integer):
            return "INTEGER[]"
        if isinstance(inner, Float):
            return "FLOAT[]"
        return "TEXT[]"
    # JSON/JSONB
    if isinstance(coltype, (JSONB, JSON)):
        return "JSONB"
    # Scalars
    if isinstance(coltype, String):
        return "VARCHAR"
    if isinstance(coltype, Integer):
        return "INTEGER"
    if isinstance(coltype, Float):
        return "FLOAT"
    if isinstance(coltype, Text):
        return "TEXT"
    if isinstance(coltype, DateTime):
        # store UTC-aware timestamps
        return "TIMESTAMPTZ"
    if isinstance(coltype, Boolean):
        return "BOOLEAN"
    # Fallback
    return "TEXT"


def reconcile_schema(engine):
    """Ensure existing tables have all columns declared in ORM models (additive only)."""
    try:
        insp = inspect(engine)
        # ✅ Use a transactional block that COMMITs on exit
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                table_name = table.name
                try:
                    existing_cols = {c["name"] for c in insp.get_columns(table_name)}
                except Exception:
                    # Table might not exist yet; create_all handles creation
                    continue

                for col in table.columns:
                    if col.name in existing_cols:
                        continue
                    sql_type = _get_sql_type_for_column(col)

                    # Build DDL with defaults for Boolean columns
                    ddl = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col.name} {sql_type}"

                    # Add default value for boolean columns if specified
                    from sqlalchemy import Boolean
                    if isinstance(col.type, Boolean) and col.default is not None:
                        default_val = "FALSE" if col.default.arg == False else "TRUE"
                        ddl += f" DEFAULT {default_val}"

                    try:
                        logger.debug(
                            f"🧩 Adding missing column: {table_name}.{col.name} ({sql_type})"
                        )
                        conn.execute(text(ddl))
                    except Exception as e:
                        logger.error(
                            f"Failed to add column {table_name}.{col.name}: {e}"
                        )
            logger.debug("✅ Schema reconciliation complete")
    except Exception as e:
        logger.error(f"Schema reconciliation error: {str(e)}")


def ensure_indexes_and_constraints(engine):
    """Create important indexes/uniques idempotently (safe to re-run)."""
    stmts = [
        # therapists
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_therapists_email ON therapists(email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_therapists_intakeq_prac ON therapists(intakeq_practitioner_id)",
        "CREATE INDEX IF NOT EXISTS ix_therapists_google_calendar_id ON therapists(google_calendar_id)",
        "CREATE INDEX IF NOT EXISTS ix_therapists_program_accepting ON therapists(program, accepting_new_clients)",
        # client_responses
        "CREATE INDEX IF NOT EXISTS ix_client_responses_match_status ON client_responses(match_status)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_intakeq_client_id ON client_responses(intakeq_client_id)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_state ON client_responses(state)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_city ON client_responses(city)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_postal_code ON client_responses(postal_code)",
        # Progressive logger tracking indexes
        "CREATE INDEX IF NOT EXISTS ix_client_responses_algorithm_suggested ON client_responses(algorithm_suggested_therapist_id)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_user_chose_alternative ON client_responses(user_chose_alternative)",
        "CREATE INDEX IF NOT EXISTS ix_client_responses_selection_timestamp ON client_responses(therapist_selection_timestamp)",
        # appointments
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_intakeq_id ON appointments(intakeq_appointment_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_google_event_id ON appointments(google_event_id)",
        "CREATE INDEX IF NOT EXISTS ix_appt_therapist_start ON appointments(therapist_id, start_date_iso)",
        # calendar_events
        "CREATE INDEX IF NOT EXISTS ix_cal_ev_therapist_time ON calendar_events(therapist_id, start_time)",
        "CREATE INDEX IF NOT EXISTS ix_cal_ev_intakeq_id ON calendar_events(intakeq_id)",
        "CREATE INDEX IF NOT EXISTS ix_cal_ev_google_event_id ON calendar_events(google_event_id)",
    ]
    try:
        with engine.begin() as conn:
            for ddl in stmts:
                conn.execute(text(ddl))
        logger.debug("✅ Indexes/constraints ensured")
    except Exception as e:
        logger.error(f"Index/constraint creation error: {e}")


def run_schema_bootstrap(engine):
    """
    Idempotent, safe-at-startup schema setup.
    Uses a pg advisory lock so multiple workers don't race.
    Controlled by AUTO_MIGRATE env (default: true).
    """
    auto = os.getenv("AUTO_MIGRATE", "true").lower() in {"1", "true", "yes", "on"}
    if not auto:
        logger.debug("⏭️ AUTO_MIGRATE disabled; skipping schema bootstrap")
        return

    LOCK_KEY = 834726  # stable integer key for advisory lock

    try:
        with engine.begin() as conn:
            # keep boot snappy if someone else holds the lock - reduced from 5s to 3s
            conn.execute(text("SET LOCAL lock_timeout = '3s'"))
            # take global advisory lock
            conn.execute(text(f"SELECT pg_advisory_lock({LOCK_KEY})"))

            # run the three phases; each is idempotent
            create_tables_safely(engine)
            reconcile_schema(engine)
            ensure_indexes_and_constraints(engine)

            # release advisory lock
            conn.execute(text(f"SELECT pg_advisory_unlock({LOCK_KEY})"))

        logger.debug("🛠️ Schema bootstrap complete (create + reconcile + indexes)")
    except Exception as e:
        logger.error(f"⚠️ Schema bootstrap failed (non-fatal): {e}")
        # Don't crash the app - the tables might already exist from a previous deployment
        # The app can still start and serve requests even if schema bootstrap fails


def init_db(app: Flask, config=None) -> None:
    """Initialize database connection and create tables."""
    global engine, SessionLocal

    database_url = get_database_url()
    logger.debug("🔗 Connecting to Railway PostgreSQL...")

    try:
        if "@" in database_url:
            db_parts = database_url.split("@")[1]
            logger.debug(f"📍 Database: {db_parts}")
    except Exception:
        pass

    engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )

    # Test connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection successful")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {str(e)}")
        raise

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Auto-migrate schema at startup (no manual POST needed)
    run_schema_bootstrap(engine)

    # Store
    app.extensions = getattr(app, "extensions", {})
    app.extensions["database"] = {"engine": engine, "session_factory": SessionLocal}

    app.teardown_appcontext(close_db_session)


def get_db_session() -> Session:
    """Get database session for the current request context."""
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session


@contextmanager
def get_db():
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def close_db_session(error=None):
    """Close database session at the end of request."""
    session = g.pop("db_session", None)
    if session is not None:
        try:
            if error is None:
                session.commit()
            else:
                session.rollback()
        except Exception as e:
            logger.error(f"Error during session cleanup: {str(e)}")
            session.rollback()
        finally:
            session.close()


def health_check() -> bool:
    """Check database connectivity."""
    if engine is None:
        logger.error("Database engine not initialized")
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return False


def register_cli_commands(app: Flask):
    """Register database CLI commands."""

    @app.cli.command("init-db")
    def init_db_cli():
        """Initialize the database."""
        try:
            run_schema_bootstrap(engine)
            print("✅ Database tables initialized successfully")
        except Exception as e:
            print(f"❌ Error: {str(e)}")

    @app.cli.command("db-health")
    def db_health_cli():
        """Check database health."""
        if health_check():
            print("✅ Database connection healthy")
        else:
            print("❌ Database connection failed")


# -------------------------- Helper: package JSON ---------------------------


def package_client_signup(session: Session, response_id: str) -> dict | None:
    """
    Build the IntakeQ-ready JSON for a given ClientResponse.id.
    Returns None if not found.
    """
    # .get() is legacy; fine here. Could also use session.get(ClientResponse, response_id)
    cr: ClientResponse | None = session.query(ClientResponse).get(response_id)
    if not cr:
        return None

    # Resolve matched therapist
    t: Therapist | None = None
    if cr.matched_therapist_id:
        t = session.query(Therapist).get(cr.matched_therapist_id)

    client_block = {
        "response_id": cr.id,
        "name": f"{(cr.first_name or '').strip()} {(cr.last_name or '').strip()}".strip(),
        "email": cr.email,
        "phone": cr.phone,
        "state": cr.state,
        "payment_type": cr.payment_type,
        "assessments": {"phq9_total": cr.phq9_total, "gad7_total": cr.gad7_total},
        # raw survey payload if present, else synthesize from known columns
        "answers": cr.answers
        or {
            "age": cr.age,
            "gender": cr.gender,
            "therapist_specializes_in": cr.therapist_specializes_in,
            "therapist_identifies_as": cr.therapist_identifies_as,
            "lived_experiences": cr.lived_experiences,
            "what_brings_you": cr.what_brings_you,
            "phq9_responses": cr.phq9_responses,
            "gad7_responses": cr.gad7_responses,
            "promo_code": cr.promo_code,
            "referred_by": cr.referred_by,
            "utm_source": cr.utm_source,
            "utm_medium": cr.utm_medium,
            "utm_campaign": cr.utm_campaign,
        },
        "intakeq_client_id": cr.intakeq_client_id,
    }

    matched_block = None
    if t:
        matched_block = {
            "id": t.id,
            "name": t.name,
            "email": t.email,
            "intakeq_practitioner_id": getattr(t, "intakeq_practitioner_id", None),
            "google_calendar_id": getattr(t, "google_calendar_id", None),
        }
    elif cr.matched_therapist_email or cr.matched_therapist_name:
        # use denormalized snapshot if Therapist row missing
        matched_block = {
            "id": cr.matched_therapist_id,
            "name": cr.matched_therapist_name,
            "email": cr.matched_therapist_email,
            "intakeq_practitioner_id": None,
            "google_calendar_id": None,
        }

    requested_slot = {
        "start_utc": cr.matched_slot_start.isoformat()
        if cr.matched_slot_start
        else None,
        "end_utc": cr.matched_slot_end.isoformat() if cr.matched_slot_end else None,
    }

    return {
        "client": client_block,
        "matched_therapist": matched_block,
        "requested_slot": requested_slot,
    }
