from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["match"])


@router.post("/match")
def start_match_job():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/match-jobs/{job_id}/compatibility")
def get_match_job_compatibility(job_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/matches/{job_id}")
def get_matches(job_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")
