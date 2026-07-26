from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Dataset, MatchJob
from app.services.blocking import run_blocking
from app.services.compatibility_check import run_compatibility_check

router = APIRouter(tags=["match"])


class StartMatchJobRequest(BaseModel):
    dataset_a_id: str
    dataset_b_id: str


@router.post("/match")
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


@router.get("/matches/{job_id}")
def get_matches(job_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")
