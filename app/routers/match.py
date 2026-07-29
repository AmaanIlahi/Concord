from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conflict, Dataset, Match, MatchJob, Record
from app.services.blocking import run_blocking
from app.services.compatibility_check import run_compatibility_check
from app.services.finalize import run_finalize
from app.services.hybrid_scoring import run_hybrid_scoring
from app.services.llm_judge import run_llm_judge
from app.services.rate_limit import rate_limit_match

router = APIRouter(tags=["match"])


class StartMatchJobRequest(BaseModel):
    dataset_a_id: str
    dataset_b_id: str


@router.post("/match", dependencies=[Depends(rate_limit_match)])
def start_match_job(request: StartMatchJobRequest, db: Session = Depends(get_db)):
    if request.dataset_a_id == request.dataset_b_id:
        raise HTTPException(
            status_code=422,
            detail="dataset_a_id and dataset_b_id must be different datasets",
        )

    dataset_a = db.get(Dataset, request.dataset_a_id)
    dataset_b = db.get(Dataset, request.dataset_b_id)

    if dataset_a is None or dataset_b is None:
        raise HTTPException(status_code=404, detail="One or both datasets not found")

    compatibility_check = run_compatibility_check(db, dataset_a, dataset_b)

    match_job = MatchJob(
        dataset_a_id=dataset_a.id,
        dataset_b_id=dataset_b.id,
        compatibility_check=compatibility_check,
        created_at=datetime.now(timezone.utc),
        status="rejected_incompatible" if compatibility_check["verdict"] == "incompatible" else "pending",
    )
    db.add(match_job)
    db.commit()

    if compatibility_check["verdict"] == "incompatible":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Datasets are not compatible for matching",
                "match_job_id": str(match_job.id),
                "compatibility_check": compatibility_check,
            },
        )

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "compatibility_check": compatibility_check,
    }


@router.get("/match-jobs/{job_id}/compatibility")
def get_match_job_compatibility(job_id: str, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "compatibility_check": match_job.compatibility_check,
    }


@router.post("/match-jobs/{job_id}/block")
def run_blocking_step(job_id: str, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    if match_job.status != "pending":
        raise HTTPException(
            status_code=422,
            detail=f"Match job status must be 'pending' to run blocking, got '{match_job.status}'",
        )

    match_count = run_blocking(db, match_job.id, match_job.dataset_a_id, match_job.dataset_b_id)
    match_job.status = "blocking_complete"
    db.commit()

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "candidate_pairs_created": match_count,
    }


@router.post("/match-jobs/{job_id}/score")
def run_scoring_step(job_id: str, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    if match_job.status != "blocking_complete":
        raise HTTPException(
            status_code=422,
            detail=f"Match job status must be 'blocking_complete' to run scoring, got '{match_job.status}'",
        )

    results = run_hybrid_scoring(db, match_job)
    match_job.status = "scoring_complete"
    db.commit()

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "scored_pairs": results,
    }


@router.post("/match-jobs/{job_id}/judge")
def run_judge_step(job_id: str, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    if match_job.status != "scoring_complete":
        raise HTTPException(
            status_code=422,
            detail=f"Match job status must be 'scoring_complete' to run judging, got '{match_job.status}'",
        )

    judged_count = run_llm_judge(db, match_job)
    match_job.status = "judging_complete"
    db.commit()

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "judged_pairs": judged_count,
    }


@router.post("/match-jobs/{job_id}/finalize")
def run_finalize_step(job_id: str, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    if match_job.status != "judging_complete":
        raise HTTPException(
            status_code=422,
            detail=f"Match job status must be 'judging_complete' to finalize, got '{match_job.status}'",
        )

    tally = run_finalize(db, match_job)
    match_job.status = "complete"
    db.commit()

    return {
        "match_job_id": match_job.id,
        "status": match_job.status,
        "final_status_tally": tally,
    }


@router.get("/matches/{job_id}")
def get_matches(job_id: str, status: str | None = Query(default=None), db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    query = db.query(Match).filter(Match.job_id == job_id)
    if status is not None:
        query = query.filter(Match.final_status == status)
    matches = query.all()

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()}

    match_ids = [m.id for m in matches]
    conflicts_by_match_id: dict = {}
    if match_ids:
        for conflict in db.query(Conflict).filter(Conflict.match_id.in_(match_ids)).all():
            conflicts_by_match_id.setdefault(conflict.match_id, []).append(conflict)

    def serialize_record(record: Record | None) -> dict | None:
        if record is None:
            return None
        return {"id": record.id, "canonical_json": record.canonical_json}

    results = []
    for match in matches:
        results.append(
            {
                "match_id": match.id,
                "record_a": serialize_record(records_by_id.get(match.record_a_id)),
                "record_b": serialize_record(records_by_id.get(match.record_b_id)),
                "blocking_score": match.blocking_score,
                "hybrid_score": match.hybrid_score,
                "llm_verdict": match.llm_verdict,
                "final_status": match.final_status,
                "conflicts": [
                    {
                        "field_name": c.field_name,
                        "value_a": c.value_a,
                        "value_b": c.value_b,
                        "conflict_type": c.conflict_type,
                    }
                    for c in conflicts_by_match_id.get(match.id, [])
                ],
            }
        )

    return {
        "match_job_id": job_id,
        "status_filter": status,
        "count": len(results),
        "matches": results,
    }
