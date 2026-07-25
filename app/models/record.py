import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    canonical_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=True)
