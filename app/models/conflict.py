import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=True)
    field_name: Mapped[str] = mapped_column(String, nullable=True)
    value_a: Mapped[str] = mapped_column(String, nullable=True)
    value_b: Mapped[str] = mapped_column(String, nullable=True)
    conflict_type: Mapped[str] = mapped_column(String, nullable=True)
