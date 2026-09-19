"""SQLAlchemy declarative base.

Table definitions are added phase-by-phase against the conceptual schema in
docs/EduPath_System_Design.md §28. Phase 1 only establishes the base class and
the two foundation tables needed to prove the migration framework works
(users, and a schema-version marker is handled by Alembic itself).
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
