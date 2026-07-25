from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/eval", tags=["eval"])


@router.post("")
def run_eval():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/calibration")
def run_calibration_eval():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/compatibility-check")
def run_compatibility_check_eval():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{eval_type}/history")
def get_eval_history(eval_type: str):
    raise HTTPException(status_code=501, detail="Not implemented")
