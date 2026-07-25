import uuid

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    eval_type: Mapped[str] = mapped_column(String, nullable=True)
    dataset_pair_name: Mapped[str] = mapped_column(String, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=True)
    run_at: Mapped[object] = mapped_column(DateTime, nullable=True)
