from pathlib import Path

from flask import Flask
from werkzeug.routing import IntegerConverter

from app.database import db
from app.models import SQLITE_MAX_INTEGER


class SQLiteIntegerConverter(IntegerConverter):
    """The `<int:...>` URL converter, limited to the SQLite INTEGER range.

    A larger id cannot exist, and querying it makes the SQLite driver raise
    OverflowError (an HTTP 500). With the limit, such a URL matches no route
    and is answered with 404 like any other unknown id.
    """

    def __init__(self, url_map, fixed_digits=0, min=None, max=SQLITE_MAX_INTEGER, signed=False):
        super().__init__(url_map, fixed_digits=fixed_digits, min=min, max=max, signed=signed)


def create_app(test_config=None):
    """Create and configure the Workout Tracker Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    # Must be replaced before the blueprints add their routes.
    app.url_map.converters["int"] = SQLiteIntegerConverter

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

    from app.database_backup import backup_database
    from app.schema import pending_schema_changes, upgrade_schema

    with app.app_context():
        # The upgrade changes the existing database in place, so a verified
        # backup is made first. If it cannot be made, backup_database() raises
        # and the application does not start; nothing is upgraded.
        pending_changes = pending_schema_changes(db.engine)
        backup_path = None
        if pending_changes:
            backup_path = backup_database(db.engine)
            # Only schema names and the backup's file name: no data is logged.
            app.logger.warning(
                "Schema upgrade pending (%s). Database backed up to %s/%s before upgrading.",
                ", ".join(pending_changes),
                backup_path.parent.name,
                backup_path.name,
            )
        try:
            db.create_all()
            # create_all() does not add new columns to existing tables; this adds
            # them without touching existing rows.
            upgrade_schema(db.engine)
        except Exception:
            if backup_path is not None:
                # Never restored automatically: the backup is kept for a
                # controlled recovery (see README).
                app.logger.error(
                    "Schema upgrade failed. The backup %s/%s was kept for recovery.",
                    backup_path.parent.name,
                    backup_path.name,
                )
            raise

    from app.exercise_library import sync_exercise_library_command

    app.cli.add_command(sync_exercise_library_command)

    from app.routes.exercises import bp as exercises_bp
    from app.routes.workout_templates import bp as workout_templates_bp
    from app.routes.workouts import bp as workouts_bp

    app.register_blueprint(exercises_bp)
    app.register_blueprint(workouts_bp)
    app.register_blueprint(workout_templates_bp)

    return app
