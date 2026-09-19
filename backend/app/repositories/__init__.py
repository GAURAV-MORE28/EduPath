"""Repository / data-access layer.

Thin wrappers around SQLAlchemy sessions, one module per aggregate root, kept
separate from service logic so services stay testable without a database.
Concrete repositories are added by the phase that first needs to persist that
aggregate (design §28 table list).
"""
