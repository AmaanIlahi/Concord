import uuid

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=True)
    source_filename: Mapped[str] = mapped_column(String, nullable=True)
    schema_mapping: Mapped[dict] = mapped_column(JSONB, nullable=True)
    uploaded_at: Mapped[object] = mapped_column(DateTime, nullable=True)
