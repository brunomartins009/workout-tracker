import pytest

from app import create_app
from app.database import db


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test_workout_tracker.db"
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"})

    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def session(app):
    return db.session


@pytest.fixture
def client(app):
    return app.test_client()
