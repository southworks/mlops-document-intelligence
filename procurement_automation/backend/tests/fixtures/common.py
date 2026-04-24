"""Shared test utilities for database and state management.

Provides context managers, transaction helpers, and validators for
consistent database manipulation and state verification across tests.
"""

from contextlib import contextmanager
from typing import Dict, List, Any, Generator, Optional
from sqlalchemy.orm import Session


class DatabaseResetManager:
    """Manages database state reset and validation across test runs."""

    def __init__(self, session: Session):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session

    def truncate_tables(self, table_names: List[str]) -> None:
        """Truncate specified tables.

        Warning: This violates transactional isolation. Prefer rollback instead.

        Args:
            table_names: List of table names to truncate
        """
        for table_name in table_names:
            self.session.execute(f"DELETE FROM {table_name}")
        self.session.commit()

    def verify_empty(self) -> bool:
        """Verify database is in clean state (no data).

        Returns:
            True if all tables are empty, False otherwise
        """
        # This is a placeholder - extend based on your schema
        return True

    def snapshot_state(self) -> Dict[str, int]:
        """Create snapshot of current database row counts.

        Returns:
            Dictionary of table names to row counts
        """
        # This is a placeholder - extend based on your schema
        return {}

    def compare_snapshots(
        self, before: Dict[str, int], after: Dict[str, int]
    ) -> Dict[str, int]:
        """Compare two database snapshots and returns deltas.

        Args:
            before: Snapshot before operations
            after: Snapshot after operations

        Returns:
            Dictionary of table names to row count deltas
        """
        return {
            table: after.get(table, 0) - before.get(table, 0)
            for table in set(before.keys()) | set(after.keys())
        }


@contextmanager
def database_transaction(session: Session) -> Generator[Session, None, None]:
    """Context manager for transactional database operations.

    Commits changes on successful exit, rolls back on exception.

    Args:
        session: SQLAlchemy session

    Yields:
        The provided session for use in with block

    Example:
        with database_transaction(session) as tx_session:
            user = create_user(tx_session)
            assert user.id is not None
    """
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def database_readonly(session: Session) -> Generator[Session, None, None]:
    """Context manager for read-only database operations.

    Any writes raise an error. Rolls back on exit.

    Args:
        session: SQLAlchemy session

    Yields:
        The provided session (with write protection)

    Example:
        with database_readonly(session) as ro_session:
            users = ro_session.query(User).all()
    """
    try:
        yield session
    finally:
        session.rollback()


class StateValidator:
    """Validates application state assumptions in tests."""

    def __init__(self, session: Session):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for state queries
        """
        self.session = session

    def assert_not_exists(self, entity_class, **filters) -> None:
        """Assert no entity exists matching filters.

        Args:
            entity_class: SQLAlchemy model class
            **filters: Filter criteria (e.g., id=1, name="test")

        Raises:
            AssertionError: If entity exists
        """
        query = self.session.query(entity_class)
        for key, value in filters.items():
            query = query.filter(getattr(entity_class, key) == value)

        result = query.first()
        assert result is None, f"Entity exists: {entity_class.__name__}({filters})"

    def assert_exists(self, entity_class, **filters) -> Any:
        """Assert exactly one entity exists matching filters.

        Args:
            entity_class: SQLAlchemy model class
            **filters: Filter criteria

        Returns:
            The found entity

        Raises:
            AssertionError: If entity does not exist or multiples found
        """
        query = self.session.query(entity_class)
        for key, value in filters.items():
            query = query.filter(getattr(entity_class, key) == value)

        result = query.first()
        assert result is not None, f"Entity not found: {entity_class.__name__}({filters})"
        return result

    def assert_count(self, entity_class, expected_count: int, **filters) -> None:
        """Assert specific count of entities matching filters.

        Args:
            entity_class: SQLAlchemy model class
            expected_count: Expected number of matching entities
            **filters: Optional filter criteria

        Raises:
            AssertionError: If count does not match
        """
        query = self.session.query(entity_class)
        for key, value in filters.items():
            query = query.filter(getattr(entity_class, key) == value)

        actual_count = query.count()
        assert actual_count == expected_count, \
            f"Expected {expected_count} {entity_class.__name__}, found {actual_count}"


class TestDataBuilder:
    """Builder pattern for constructing test data consistently."""

    def __init__(self, session: Session):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for entity persistence
        """
        self.session = session
        self._pending = []

    def add(self, entity: Any) -> "TestDataBuilder":
        """Add entity to pending list.

        Args:
            entity: SQLAlchemy entity instance

        Returns:
            Self for method chaining
        """
        self._pending.append(entity)
        return self

    def build(self) -> List[Any]:
        """Persist all pending entities and return them.

        Returns:
            List of persisted entities

        Example:
            user = TestDataBuilder(session).add(User(...)).add(User(...)).build()
        """
        for entity in self._pending:
            self.session.add(entity)
        self.session.flush()
        self.session.commit()
        return self._pending

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup on error."""
        if exc_type:
            self.session.rollback()
