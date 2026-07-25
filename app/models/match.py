import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("match_jobs.id"), nullable=True)
    record_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("records.id"), nullable=True)
    record_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("records.id"), nullable=True)
    blocking_score: Mapped[float] = mapped_column(Float, nullable=True)
    hybrid_score: Mapped[float] = mapped_column(Float, nullable=True)
    llm_verdict: Mapped[dict] = mapped_column(JSONB, nullable=True)
    final_status: Mapped[str] = mapped_column(String, nullable=True)
