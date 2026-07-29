from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.ttl_cleanup import run_ttl_cleanup

router = APIRouter(tags=["admin"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/admin/cleanup")
def trigger_cleanup(db: Session = Depends(get_db)):
    return run_ttl_cleanup(db)
