from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("")
def upload_dataset():
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")
