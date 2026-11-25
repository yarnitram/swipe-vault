"""RQ task entrypoints and worker runner with interrupted-job recovery (FR-09, AC-14)."""

import logging
import uuid

from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import select

from app.adapters.sources.crawler import execute_scan_source_job
from app.db import session_scope
from app.models import Job, utcnow
from app.services.ingestion import execute_ingest_job, log_job_event
from app.settings import get_settings

logger = logging.getLogger("swipevault.worker")


def run_ingest_job(job_id_str: str) -> None:
    job_id = uuid.UUID(job_id_str)
    with session_scope() as db:
        execute_ingest_job(db, job_id)


def run_scan_job(job_id_str: str) -> None:
    job_id = uuid.UUID(job_id_str)
    with session_scope() as db:
        execute_scan_source_job(db, job_id)


def recover_interrupted_jobs() -> int:
    """Re-run any jobs left in ``running`` state after an unexpected worker restart."""
    recovered = 0
    with session_scope() as db:
        stuck = db.scalars(select(Job).where(Job.state == "running")).all()
        stuck_items = [(j.id, j.type) for j in stuck]
        for job in stuck:
            job.state = "queued"
            job.heartbeat_at = utcnow()
            log_job_event(
                db,
                job,
                "warning",
                "worker_recovery",
                "Job was interrupted by worker restart; recovering safely",
            )
            db.commit()
        for jid, jtype in stuck_items:
            if jtype == "scan_source":
                execute_scan_source_job(db, jid)
            else:
                execute_ingest_job(db, jid)
            recovered += 1
    return recovered


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    settings = get_settings()
    count = recover_interrupted_jobs()
    if count:
        logger.info("Recovered %d interrupted job(s)", count)
    conn = Redis.from_url(settings.redis_url)
    queue = Queue(settings.rq_queue_name, connection=conn)
    worker = SimpleWorker([queue], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
