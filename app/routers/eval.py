from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EvalRun, MatchJob
from app.services.eval_compatibility import run_compatibility_check_eval
from app.services.eval_matching import (
    compute_confidence_calibration,
    compute_cost_efficiency,
    compute_matching_accuracy,
)

router = APIRouter(prefix="/eval", tags=["eval"])

_BENCHMARKS_ROOT = Path(__file__).parent.parent.parent / "scripts" / "sample_data" / "benchmarks"
_AMAZON_GOOGLE_DIR = _BENCHMARKS_ROOT / "amazon_google"
_DBLP_ACM_DIR = _BENCHMARKS_ROOT / "dblp_acm"

BENCHMARK_GOLD_PATHS = {
    "amazon_google": _AMAZON_GOOGLE_DIR / "gold_matches.csv",
    "amazon_google_stratified_150": _AMAZON_GOOGLE_DIR / "gold_stratified_150.csv",
    "dblp_acm": _DBLP_ACM_DIR / "gold_matches.csv",
    "dblp_acm_stratified_150": _DBLP_ACM_DIR / "gold_stratified_150.csv",
}


class RunEvalRequest(BaseModel):
    match_job_id: str
    dataset_pair_name: str


@router.post("")
def run_eval(request: RunEvalRequest, db: Session = Depends(get_db)):
    match_job = db.get(MatchJob, request.match_job_id)
    if match_job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    gold_csv_path = BENCHMARK_GOLD_PATHS.get(request.dataset_pair_name)
    if gold_csv_path is None or not gold_csv_path.exists():
        raise HTTPException(
            status_code=422,
            detail=f"No gold-standard file available for dataset_pair_name={request.dataset_pair_name!r}",
        )

    matching_accuracy = compute_matching_accuracy(db, match_job, gold_csv_path)
    calibration = compute_confidence_calibration(db, match_job, gold_csv_path)
    cost_efficiency = compute_cost_efficiency(db, match_job)

    run_at = datetime.now(timezone.utc)
    eval_runs = [
        EvalRun(
            eval_type="matching_accuracy",
            dataset_pair_name=request.dataset_pair_name,
            metrics=matching_accuracy,
            run_at=run_at,
        ),
        EvalRun(
            eval_type="calibration",
            dataset_pair_name=request.dataset_pair_name,
            metrics=calibration,
            run_at=run_at,
        ),
        EvalRun(
            eval_type="cost_efficiency",
            dataset_pair_name=request.dataset_pair_name,
            metrics=cost_efficiency,
            run_at=run_at,
        ),
    ]
    db.add_all(eval_runs)
    db.commit()

    return {
        "match_job_id": match_job.id,
        "dataset_pair_name": request.dataset_pair_name,
        "matching_accuracy": matching_accuracy,
        "calibration": calibration,
        "cost_efficiency": cost_efficiency,
    }


@router.post("/calibration")
def run_calibration_eval():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/compatibility-check")
def run_compatibility_check_eval_endpoint(db: Session = Depends(get_db)):
    result = run_compatibility_check_eval(db)

    eval_run = EvalRun(
        eval_type="compatibility_check",
        dataset_pair_name="compatibility_test_matrix",
        metrics=result,
        run_at=datetime.now(timezone.utc),
    )
    db.add(eval_run)
    db.commit()

    return result


@router.get("/{eval_type}/history")
def get_eval_history(eval_type: str, db: Session = Depends(get_db)):
    runs = (
        db.query(EvalRun)
        .filter(EvalRun.eval_type == eval_type)
        .order_by(EvalRun.run_at.desc())
        .all()
    )

    return {
        "eval_type": eval_type,
        "count": len(runs),
        "runs": [
            {
                "id": r.id,
                "dataset_pair_name": r.dataset_pair_name,
                "metrics": r.metrics,
                "run_at": r.run_at,
            }
            for r in runs
        ],
    }
