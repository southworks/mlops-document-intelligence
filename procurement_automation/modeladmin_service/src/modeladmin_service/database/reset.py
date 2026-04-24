"""Reset helpers for ModelAdmin service database schema."""

from modeladmin_service.database.connection import Base, engine


def reset_db() -> None:
    """Drop and recreate all ModelAdmin service-owned tables."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
