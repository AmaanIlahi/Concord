from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Dataset, Record
from app.services.file_parsing import UnsupportedFileType, parse_upload
from app.services.schema_mapping import infer_schema_mapping

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("")
def upload_dataset(file: UploadFile, db: Session = Depends(get_db)):
    content = file.file.read()

    try:
        rows = parse_upload(file.filename, content)
    except UnsupportedFileType as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not rows:
        raise HTTPException(status_code=422, detail="File contains no rows")

    headers = list(rows[0].keys())
    schema_mapping = infer_schema_mapping(headers, rows)

    dataset = Dataset(
        name=file.filename,
        source_filename=file.filename,
        schema_mapping=schema_mapping,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(dataset)
    db.flush()

    for row in rows:
        canonical_json = {
            canonical_field: row.get(source_column)
            for canonical_field, source_column in schema_mapping.items()
        }
        db.add(Record(dataset_id=dataset.id, raw_json=row, canonical_json=canonical_json))

    db.commit()

    return {
        "dataset_id": dataset.id,
        "row_count": len(rows),
        "schema_mapping": schema_mapping,
    }


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    sample_records = (
        db.query(Record).filter(Record.dataset_id == dataset_id).limit(3).all()
    )

    return {
        "id": dataset.id,
        "name": dataset.name,
        "source_filename": dataset.source_filename,
        "schema_mapping": dataset.schema_mapping,
        "uploaded_at": dataset.uploaded_at,
        "sample_records": [
            {"raw_json": r.raw_json, "canonical_json": r.canonical_json}
            for r in sample_records
        ],
    }
