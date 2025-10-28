# src/services/scheduler.py
"""
Scheduler service for periodic Airtable sync.
Runs background tasks to keep database updated.
"""
import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

logger = logging.getLogger(__name__)

scheduler = None


def sync_therapists_job():
    """Background job to sync therapists from Airtable."""
    try:
        logger.debug("🔄 Starting scheduled Airtable sync...")

        from src.services.airtable_sync_service import airtable_sync_service

        result = airtable_sync_service.sync_incremental(hours_back=24)

        logger.debug(f"✅ Scheduled sync completed: {result}")

        # Log significant events
        if result["records_created"] > 0 or result["records_updated"] > 0:
            logger.debug(
                f"📊 Sync summary: {result['records_created']} created, "
                f"{result['records_updated']} updated, {result['records_deleted']} deleted"
            )

    except Exception as e:
        logger.error(f"❌ Scheduled sync failed: {str(e)}")


def cleanup_old_logs_job():
    """Background job to clean up old sync logs."""
    try:
        logger.debug("🧹 Cleaning up old sync logs...")

        from datetime import datetime, timedelta

        from src.db import get_db
        from src.db.models import SyncLog

        # Keep logs for 30 days
        cutoff_date = datetime.utcnow() - timedelta(days=30)

        with get_db() as session:
            deleted_count = (
                session.query(SyncLog).filter(SyncLog.started_at < cutoff_date).delete()
            )

            if deleted_count > 0:
                logger.debug(f"🗑️ Deleted {deleted_count} old sync logs")

    except Exception as e:
        logger.error(f"❌ Log cleanup failed: {str(e)}")


def init_scheduler(app: Flask):
    """Initialize the background scheduler."""
    global scheduler

    if scheduler is not None:
        return  # Already initialized

    try:
        scheduler = BackgroundScheduler(daemon=True)

        # Get sync interval from config (default 6 hours)
        sync_interval_hours = int(os.getenv("AUTO_SYNC_INTERVAL_HOURS", 6))

        # Add sync job
        scheduler.add_job(
            func=sync_therapists_job,
            trigger=IntervalTrigger(hours=sync_interval_hours),
            id="sync_therapists",
            name="Sync therapists from Airtable",
            replace_existing=True,
        )
        logger.debug(f"📅 Scheduled Airtable sync every {sync_interval_hours} hours")

        # Add cleanup job (daily at 2 AM)
        scheduler.add_job(
            func=cleanup_old_logs_job,
            trigger="cron",
            hour=2,
            minute=0,
            id="cleanup_logs",
            name="Clean up old sync logs",
            replace_existing=True,
        )
        logger.debug("📅 Scheduled daily log cleanup at 2:00 AM")

        # Start scheduler
        scheduler.start()
        logger.debug("✅ Background scheduler started successfully")

        # Shutdown scheduler when app stops
        import atexit

        atexit.register(lambda: scheduler.shutdown() if scheduler else None)

    except Exception as e:
        logger.error(f"❌ Failed to initialize scheduler: {str(e)}")


def get_scheduler_status():
    """Get current scheduler status and jobs."""
    if not scheduler:
        return {"status": "not_initialized"}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat()
                if job.next_run_time
                else None,
                "trigger": str(job.trigger),
            }
        )

    return {"status": "running" if scheduler.running else "stopped", "jobs": jobs}


def trigger_sync_now():
    """Manually trigger a sync job."""
    if not scheduler:
        raise RuntimeError("Scheduler not initialized")

    # Add a one-time job to run immediately
    scheduler.add_job(
        func=sync_therapists_job,
        trigger="date",
        run_date=datetime.utcnow(),
        id="manual_sync",
        name="Manual sync trigger",
        replace_existing=True,
    )

    return {"message": "Sync job triggered successfully"}
