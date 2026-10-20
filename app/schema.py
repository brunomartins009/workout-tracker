"""Additive schema upgrades for databases created by an earlier version.

`Base.metadata.create_all()` creates missing tables but never changes tables
that already exist. When a new column is added to a model, an existing local
database needs that column added explicitly, otherwise every query on the
table fails.

Only additive, non-destructive changes belong here: `ALTER TABLE ... ADD COLUMN`
keeps every existing row, its id and its relationships. Each upgrade runs only
when the column is missing, so running this on every startup is safe.

An upgrade may also carry a one-time data backfill. It runs in the same
transaction as the ALTER TABLE and only when the column is created, never on
later startups.

If the schema ever needs destructive changes (renaming, dropping or changing
column types), this file should be replaced by a real migration tool such as
Alembic instead of growing into one.
"""

from sqlalchemy import inspect, text

from app.database import Base
from app.models import TARGET_REPETITIONS_MAX, TARGET_SETS_MAX, UNCLASSIFIED, target_range_check


def _target_column(table_constraint_prefix, column, maximum):
    """Definition of a target column, with the same named CHECK as the model."""
    return (
        f"INTEGER CONSTRAINT {table_constraint_prefix}_{column}_range "
        f"CHECK ({target_range_check(column, maximum)})"
    )


# (table, column, column definition used by ALTER TABLE ... ADD COLUMN,
#  optional SQL run once, right after the column is created)
# SQLite only accepts a NOT NULL column on a table with rows when the column
# also has a default, which is what existing rows receive.
COLUMN_UPGRADES = [
    ("exercises", "muscle_group", f"VARCHAR(100) NOT NULL DEFAULT '{UNCLASSIFIED}'", None),
    ("exercises", "muscle_subgroup", f"VARCHAR(100) NOT NULL DEFAULT '{UNCLASSIFIED}'", None),
    # Sessions recorded before sessions could be "in progress" are finished
    # workouts: they become completed, using their last update as completion
    # time. Sessions created afterwards start with NULL (in progress), and this
    # backfill never runs again because the column then already exists.
    ("workouts", "completed_at", "DATETIME", "UPDATE workouts SET completed_at = updated_at"),
    # Targets of sets and repetitions. Existing template exercises and session
    # exercises get NULL (no target): nothing is invented for older data.
    (
        "workout_template_exercises",
        "target_sets",
        _target_column("ck_workout_template_exercise", "target_sets", TARGET_SETS_MAX),
        None,
    ),
    (
        "workout_template_exercises",
        "target_repetitions",
        _target_column("ck_workout_template_exercise", "target_repetitions", TARGET_REPETITIONS_MAX),
        None,
    ),
    (
        "workout_exercises",
        "target_sets",
        _target_column("ck_workout_exercise", "target_sets", TARGET_SETS_MAX),
        None,
    ),
    (
        "workout_exercises",
        "target_repetitions",
        _target_column("ck_workout_exercise", "target_repetitions", TARGET_REPETITIONS_MAX),
        None,
    ),
]


def pending_schema_changes(engine):
    """What `create_all()` and `upgrade_schema()` would add to an existing database.

    Returns descriptions such as "column workouts.completed_at" (names from the
    schema only, never data). Empty when the database is up to date, and for a
    new database without tables: there is nothing in it to protect yet.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return []

    changes = [f"table {table.name}" for table in Base.metadata.sorted_tables if table.name not in existing_tables]
    for table, column, _definition, _backfill in COLUMN_UPGRADES:
        # A missing table is created by create_all() with all its columns.
        if table in existing_tables and column not in {
            existing_column["name"] for existing_column in inspector.get_columns(table)
        }:
            changes.append(f"column {table}.{column}")
    return changes


def upgrade_schema(engine):
    """Add model columns that are missing from an existing database."""
    with engine.connect() as connection:
        # Python's sqlite3 driver does not open a transaction before DDL such
        # as ALTER TABLE, so a failing backfill would leave its column created
        # (and the backfill would never run again). Opening the transaction
        # explicitly makes every ALTER TABLE and its backfill succeed or roll
        # back together.
        connection.exec_driver_sql("BEGIN")
        try:
            for table, column, definition, backfill in COLUMN_UPGRADES:
                existing_columns = {
                    existing_column["name"]
                    for existing_column in inspect(connection).get_columns(table)
                }
                if column not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                    if backfill is not None:
                        connection.execute(text(backfill))
        except Exception:
            connection.rollback()
            raise
        connection.commit()
