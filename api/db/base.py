"""
SQLAlchemy declarative base shared by all models.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base. All ORM models inherit from this."""
