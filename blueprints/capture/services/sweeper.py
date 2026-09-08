"""The three scheduled jobs that keep the capture tables honest.

The pipeline runs in daemon threads and the database is the source of truth.
That combination is only safe if something notices when a thread stops
existing, which is what the first job here is for.

  recover_stuck_uploads   every 5 minutes
  retry_failed_sends      every 10 minutes
  purge_old_captures      daily

WHY A SEPARATE SCHEDULER FROM THE SUBSCRIPTION ONE

``services/app_runtime/scheduler.py`` owns the billing passes and is switched on
by ``SUBSCRIPTION_SCHEDULER_ENABLED``. Hanging these jobs off that flag would
tie capture housekeeping to whether the host is the one that bills people —
two unrelated decisions. This starts its own, on its own flag, and its own
failure cannot stop billing from running.

Everything here follows the same rules as that module, for the same reasons:
off unless asked, skip the dev reloader's supervisor process, and never let an
exception escape a job (a scheduler that raises quietly stops being one).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from loguru import logger

# A thread that died with the process leaves its row at ``processing`` forever.
# Fifteen minutes is comfortably longer than any real upload (three pages, at
# most eleven model calls, each capped at 40 seconds) and short enough that a
# user does not stare at "reading…" for an afternoon.
STUCK_AFTER_MINUTES = 15

RECOVER_JOB_ID = "capture-recover-stuck"
RETRY_JOB_ID = "capture-retry-sends"
PURGE_JOB_ID = "capture-purge-old"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# 1. Stuck uploads.
# --------------------------------------------------------------------------
def recover_stuck_uploads(app) -> int:
    """Mark long-``processing`` uploads as failed. Returns how many.

    DELIBERATELY DOES NOT RESTART THEM. A crash loop that keeps re-calling a
    paid API is exactly the failure mode we cannot afford, and the difference
    between "the process restarted" and "this file crashes the worker every
    time" is not visible from here. The queue offers the user a Retry, and a
    person deciding is the right amount of friction.
    """
    from blueprints.capture.models.capture_upload import (REJECT_WORKER_LOST,
                                                          STATUS_FAILED,
                                                          STATUS_PROCESSING,
                                                          CaptureUpload)
    from models.db import db

    with app.app_context():
        try:
            cutoff = _now() - timedelta(minutes=STUCK_AFTER_MINUTES)
            rows = CaptureUpload.query.filter(
                CaptureUpload.status == STATUS_PROCESSING,
                CaptureUpload.processing_started_at < cutoff,
            ).all()
            for row in rows:
                row.status = STATUS_FAILED
                row.reject_reason = REJECT_WORKER_LOST
                row.completed_at = _now()
                row.updated_at = _now()
            if rows:
                db.session.commit()
                logger.warning(
                    "capture sweeper: {} upload(s) were stuck in processing and "
                    "have been marked failed — a worker thread died with its "
                    "process. The user can retry from the queue.", len(rows),
                )
            return len(rows)
        except Exception:
            logger.exception("capture sweeper: recovering stuck uploads raised")
            db.session.rollback()
            return 0


# --------------------------------------------------------------------------
# 2. Retrying a send that failed.
# --------------------------------------------------------------------------
def retry_failed_sends(app) -> int:
    """Re-push drafts whose destination was unreachable. Returns how many.

    Backs off exponentially on ``send_attempts``: 2, 4, 8, 16, 32 minutes. At
    MAX_SEND_ATTEMPTS it stops and leaves the draft for a person — an automatic
    retry that never gives up is how a transient outage becomes a permanent
    load on somebody else's service.
    """
    from blueprints.capture.models.capture_draft import (MAX_SEND_ATTEMPTS,
                                                         STATUS_SEND_FAILED,
                                                         CaptureDraft)
    from blueprints.capture.services import routing
    from models.db import db

    with app.app_context():
        try:
            candidates = CaptureDraft.query.filter(
                CaptureDraft.status == STATUS_SEND_FAILED,
                CaptureDraft.send_attempts < MAX_SEND_ATTEMPTS,
            ).limit(50).all()

            sent = 0
            for draft in candidates:
                wait = timedelta(minutes=2 ** max(draft.send_attempts or 0, 0))
                if draft.updated_at and draft.updated_at > _now() - wait:
                    continue
                routing.push(draft.id)
                sent += 1
            if sent:
                logger.info("capture sweeper: retried {} failed send(s)", sent)
            return sent
        except Exception:
            logger.exception("capture sweeper: retrying failed sends raised")
            db.session.rollback()
            return 0


# --------------------------------------------------------------------------
# 3. Retention.
# --------------------------------------------------------------------------
def purge_old_captures(app) -> int:
    """Delete uploads past the retention window, and their S3 objects.

    S3 OBJECTS FIRST, THEN THE ROW. An orphaned object costs a fraction of a
    cent; a row pointing at a deleted object is a broken page in somebody's
    queue.

    Drafts and audit rows go with the upload by CASCADE. Anything already
    posted is untouched — those became ``shop_expense`` rows or Module 2
    PaymentRequests and do not live in these tables, and their attachment was
    COPIED rather than moved for exactly this reason.
    """
    from blueprints.capture.models.capture_draft import CaptureDraft
    from blueprints.capture.models.capture_upload import (STATUS_PROCESSING,
                                                          STATUS_QUEUED,
                                                          CaptureUpload)
    from blueprints.capture.services import capture_ai, storage
    from models.db import db

    with app.app_context():
        try:
            cutoff = _now() - timedelta(days=capture_ai.retention_days())
            rows = (
                CaptureUpload.query.filter(
                    CaptureUpload.created_at < cutoff,
                    # Never delete something a worker may still be holding.
                    CaptureUpload.status.notin_([STATUS_QUEUED, STATUS_PROCESSING]),
                )
                .limit(200)
                .all()
            )
            if not rows:
                return 0

            for upload in rows:
                keys = [upload.s3_key]
                keys += [
                    d.page_s3_key
                    for d in CaptureDraft.query.filter_by(upload_id=upload.id).all()
                    if d.page_s3_key
                ]
                storage.delete_keys(keys)
                db.session.delete(upload)

            db.session.commit()
            logger.info(
                "capture sweeper: purged {} upload(s) older than {} days",
                len(rows), capture_ai.retention_days(),
            )
            return len(rows)
        except Exception:
            logger.exception("capture sweeper: purging old captures raised")
            db.session.rollback()
            return 0


# --------------------------------------------------------------------------
# Wiring.
# --------------------------------------------------------------------------
def start_capture_scheduler(app):
    """Start the three jobs if this process is meant to have them. Returns the
    scheduler, or None — which is the normal case outside the deployed web
    service."""
    if not _flag("CAPTURE_SCHEDULER_ENABLED", False):
        logger.debug("capture sweeper: disabled (CAPTURE_SCHEDULER_ENABLED is not set)")
        return None

    # The Flask dev reloader runs a supervisor that imports the app and then
    # forks the real one. Without this the supervisor gets a scheduler too, and
    # every code edit leaves another one behind.
    if os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true"} and (
        os.environ.get("WERKZEUG_RUN_MAIN") != "true"
    ):
        logger.debug("capture sweeper: skipping the reloader's supervisor process")
        return None

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BackgroundScheduler(daemon=True)
    common = {
        # A run still going when the next is due must not start a second one.
        "max_instances": 1,
        # If the process was suspended over several fire times, run ONCE on
        # waking rather than once per missed slot. All three jobs are
        # idempotent, so the extra runs would only be repeated work.
        "coalesce": True,
        "misfire_grace_time": 300,
    }

    scheduler.add_job(
        recover_stuck_uploads,
        trigger=IntervalTrigger(minutes=5),
        kwargs={"app": app},
        id=RECOVER_JOB_ID,
        name="Capture: recover stuck uploads",
        **common,
    )
    scheduler.add_job(
        retry_failed_sends,
        trigger=IntervalTrigger(minutes=10),
        kwargs={"app": app},
        id=RETRY_JOB_ID,
        name="Capture: retry failed sends",
        **common,
    )
    scheduler.add_job(
        purge_old_captures,
        # 03:00, before the subscription pass at 05:00 — deleting files is
        # cheap and there is no reason for the two to contend.
        trigger=CronTrigger(hour=3, minute=20),
        kwargs={"app": app},
        id=PURGE_JOB_ID,
        name="Capture: purge old captures",
        **common,
    )
    scheduler.start()
    logger.info(
        "capture sweeper: started — stuck check every 5 min, send retries every "
        "10 min, retention purge at 03:20"
    )
    return scheduler
