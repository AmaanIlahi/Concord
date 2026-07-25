import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MatchJob(Base):
    __tablename__ = "match_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    dataset_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=True)
    compatibility_check: Mapped[dict] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, nullable=True)
