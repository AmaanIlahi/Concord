import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Conflict, Dataset, Match, MatchJob, Record

logger = logging.getLogger(__name__)

RETENTION_HOURS = 24


def run_ttl_cleanup(db: Session, retention_hours: int = RETENTION_HOURS) -> dict:
    """Deletes datasets (and everything that references them) older than
    retention_hours. No FK ON DELETE CASCADE is configured, so this deletes in
    dependency order: conflicts -> matches -> match_jobs -> records -> datasets."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

    stale_dataset_ids = [
        row.id
        for row in db.query(Dataset.id).filter(Dataset.uploaded_at < cutoff).all()
    ]

    if not stale_dataset_ids:
        return {"deleted_datasets": 0, "deleted_records": 0, "deleted_match_jobs": 0, "deleted_matches": 0, "deleted_conflicts": 0}

    stale_job_ids = [
        row.id
        for row in db.query(MatchJob.id)
        .filter(
            (MatchJob.dataset_a_id.in_(stale_dataset_ids))
            | (MatchJob.dataset_b_id.in_(stale_dataset_ids))
        )
        .all()
    ]

    stale_match_ids = [
        row.id for row in db.query(Match.id).filter(Match.job_id.in_(stale_job_ids)).all()
    ]

    deleted_conflicts = (
        db.query(Conflict).filter(Conflict.match_id.in_(stale_match_ids)).delete(synchronize_session=False)
        if stale_match_ids
        else 0
    )
    deleted_matches = (
        db.query(Match).filter(Match.job_id.in_(stale_job_ids)).delete(synchronize_session=False)
        if stale_job_ids
        else 0
    )
    deleted_match_jobs = (
        db.query(MatchJob).filter(MatchJob.id.in_(stale_job_ids)).delete(synchronize_session=False)
        if stale_job_ids
        else 0
    )
    deleted_records = (
        db.query(Record).filter(Record.dataset_id.in_(stale_dataset_ids)).delete(synchronize_session=False)
    )
    deleted_datasets = (
        db.query(Dataset).filter(Dataset.id.in_(stale_dataset_ids)).delete(synchronize_session=False)
    )

    db.commit()

    result = {
        "deleted_datasets": deleted_datasets,
        "deleted_records": deleted_records,
        "deleted_match_jobs": deleted_match_jobs,
        "deleted_matches": deleted_matches,
        "deleted_conflicts": deleted_conflicts,
    }
    logger.info("TTL cleanup (retention=%dh): %s", retention_hours, result)
    return result
