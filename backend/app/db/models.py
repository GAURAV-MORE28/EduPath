"""Foundation-layer ORM models.

Only the tables needed to prove the migration framework and session-boundary
work in Phase 1 (design §28: `User`). Every other table in the conceptual
schema (`LearnerProfile`, `Skill`, `SkillEdge`, ...) is added by the phase that
owns it (2, 3, 4, ...), not here.
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consent_flags: Mapped[dict] = mapped_column(JSON, default=dict)
