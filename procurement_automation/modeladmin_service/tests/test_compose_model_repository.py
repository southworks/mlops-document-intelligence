from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modeladmin_service.database.models import Base
from modeladmin_service.repositories.compose_model_repository import ComposeModelRepository


def _create_repo(tmp_path):
    db_path = tmp_path / "compose-models.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    return session, ComposeModelRepository(session)


def test_create_and_get_by_id(tmp_path):
    session, repo = _create_repo(tmp_path)
    try:
        created = repo.create(
            compose_model_id="compose-live-v1",
            version_number=1,
            dataset_version_id=None,
            classifier_model_id="classifier-v1",
            status="ready",
            adi_model_name="procurement-compose.v1",
        )

        assert created.compose_model_id == "compose-live-v1"
        assert created.version_number == 1
        assert created.status == "ready"

        loaded = repo.get_by_id("compose-live-v1")
        assert loaded is not None
        assert loaded.compose_model_id == "compose-live-v1"
    finally:
        session.close()


def test_activate_sets_single_active_model(tmp_path):
    session, repo = _create_repo(tmp_path)
    try:
        repo.create(compose_model_id="compose-a", version_number=1, status="ready")
        repo.create(compose_model_id="compose-b", version_number=2, status="ready")

        first_active = repo.activate("compose-a")
        assert first_active is not None
        assert first_active.is_active is True

        second_active = repo.activate("compose-b")
        assert second_active is not None
        assert second_active.is_active is True

        model_a = repo.get_by_id("compose-a")
        model_b = repo.get_by_id("compose-b")
        assert model_a is not None and model_b is not None
        assert model_a.is_active is False
        assert model_b.is_active is True
        assert model_b.activated_at is not None
    finally:
        session.close()


def test_list_all_orders_latest_first_and_excludes_failed(tmp_path):
    session, repo = _create_repo(tmp_path)
    try:
        base = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
        model_a = repo.create(compose_model_id="compose-a", version_number=1, status="ready")
        model_b = repo.create(compose_model_id="compose-b", version_number=2, status="composing")
        model_hidden = repo.create(compose_model_id="compose-hidden", version_number=3, status="failed")

        model_a.created_at = base
        model_b.created_at = base + timedelta(days=1)
        model_hidden.created_at = base + timedelta(days=2)
        session.commit()

        items = repo.list_all()
        ids = [item.compose_model_id for item in items]
        assert ids == ["compose-b", "compose-a"]
    finally:
        session.close()
