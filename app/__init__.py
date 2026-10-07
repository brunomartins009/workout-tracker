from pathlib import Path

from flask import Flask

from app.database import db


def create_app(test_config=None):
    """Create and configure the Workout Tracker Flask application."""
    app = Flask(__name__, instance_relative_config=True)

    default_database_path = Path(app.instance_path) / "workout_tracker.db"
    app.config.from_mapping(
        DATABASE_URL=f"sqlite:///{default_database_path.as_posix()}",
        SECRET_KEY="development-only-secret-key",
    )

    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    # Registers mapped models in Base.metadata before creating the local schema.
    from app import models  # noqa: F401

    from app.schema import upgrade_schema

    with app.app_context():
        db.create_all()
        # create_all() does not add new columns to existing tables; this adds
        # them without touching existing rows.
        upgrade_schema(db.engine)

    from app.exercise_library import sync_exercise_library_command

    app.cli.add_command(sync_exercise_library_command)

    from app.routes.exercises import bp as exercises_bp
    from app.routes.workouts import bp as workouts_bp

    app.register_blueprint(exercises_bp)
    app.register_blueprint(workouts_bp)

    return app
