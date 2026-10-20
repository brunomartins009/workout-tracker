"""Verified backup of the database before a pending schema upgrade (create_app).

Every database here is a temporary file. The "previous" database has the
schema of an earlier version: no template tables and no workouts.completed_at,
so starting the application has an upgrade to apply.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime

import pytest
from sqlalchemy import create_engine

import app.database_backup as database_backup
import app.schema as schema
from app import create_app
from app.database import Base, db
from app.database_backup import DatabaseBackupError, backup_database
from app.schema import pending_schema_changes


TIMESTAMP = "'2026-10-01 10:00:00.000000'"
PRIVATE_NAME = "Treino particular da Ana"


@pytest.fixture
def previous_database(tmp_path):
    database_path = tmp_path / "workout_tracker.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in ("workout_templates", "workout_template_exercises")
        ],
    )
    engine.dispose()

    connection = sqlite3.connect(database_path)
    connection.execute("ALTER TABLE workouts DROP COLUMN completed_at")
    connection.execute(
        f"INSERT INTO exercises (id, name, muscle_group, muscle_subgroup, created_at, updated_at) VALUES (1, 'Supino', 'Peito', 'Peitoral médio', {TIMESTAMP}, {TIMESTAMP})"
    )
    connection.execute(
        f"INSERT INTO workouts (id, date, name, created_at, updated_at) VALUES (1, '2026-10-01', ?, {TIMESTAMP}, {TIMESTAMP})",
        (PRIVATE_NAME,),
    )
    connection.execute(
        f"INSERT INTO workout_exercises (id, workout_id, exercise_id, position, created_at, updated_at) VALUES (1, 1, 1, 1, {TIMESTAMP}, {TIMESTAMP})"
    )
    connection.execute(
        f"INSERT INTO workout_sets (id, workout_exercise_id, position, repetitions, weight_kg, created_at, updated_at) VALUES (1, 1, 1, 10, 22.5, {TIMESTAMP}, {TIMESTAMP})"
    )
    connection.commit()
    connection.close()
    return database_path


def start_and_stop(database_path):
    try:
        app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"})
    except Exception:
        # The engine was created before the failure; its connections are closed
        # here, as stopping the process would.
        db.engine.dispose()
        raise
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def backups(database_path):
    folder = database_path.parent / "backups"
    return sorted(folder.iterdir()) if folder.exists() else []


def snapshot(database_path):
    """Schema and every row, read without changing the file."""
    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    result = {
        "schema": connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall(),
        "rows": {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in tables},
        "integrity": connection.execute("PRAGMA integrity_check").fetchall(),
        "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
    }
    connection.close()
    return result


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workout_columns(database_path):
    connection = sqlite3.connect(database_path)
    names = {row[1] for row in connection.execute("PRAGMA table_info(workouts)")}
    connection.close()
    return names


# No pending upgrade


def test_new_and_up_to_date_databases_start_without_a_backup(tmp_path):
    database_path = tmp_path / "workout_tracker.db"

    start_and_stop(database_path)  # new database: nothing to protect yet
    after_first_start = snapshot(database_path)
    start_and_stop(database_path)  # up to date: nothing pending

    assert backups(database_path) == []
    assert not (tmp_path / "backups").exists()
    after_second_start = snapshot(database_path)
    assert after_second_start == after_first_start
    assert after_second_start["integrity"] == [("ok",)]


def test_pending_changes_describe_only_what_the_startup_would_add(previous_database):
    engine = create_engine(f"sqlite:///{previous_database.as_posix()}")

    assert pending_schema_changes(engine) == [
        "table workout_templates",
        "table workout_template_exercises",
        "column workouts.completed_at",
    ]
    engine.dispose()

    start_and_stop(previous_database)

    engine = create_engine(f"sqlite:///{previous_database.as_posix()}")
    assert pending_schema_changes(engine) == []
    engine.dispose()


# Pending upgrade


def test_pending_upgrade_is_backed_up_and_verified_before_the_schema_changes(previous_database, monkeypatch, caplog):
    before = snapshot(previous_database)
    seen_by_the_upgrade = {}
    original_create_all = db.create_all

    def create_all_after_checking():
        # The first schema change of the startup: the backup must already exist.
        seen_by_the_upgrade["backups"] = backups(previous_database)
        seen_by_the_upgrade["database"] = snapshot(previous_database)
        original_create_all()

    monkeypatch.setattr(db, "create_all", create_all_after_checking)

    with caplog.at_level(logging.WARNING):
        start_and_stop(previous_database)

    [backup_path] = backups(previous_database)
    assert seen_by_the_upgrade["backups"] == [backup_path]
    assert seen_by_the_upgrade["database"] == before
    assert backup_path.name.startswith("workout_tracker.before-upgrade-")
    assert backup_path.suffix == ".db"
    # The backup is the database as it was, verified, in one self-contained file.
    backup = snapshot(backup_path)
    assert backup["schema"] == before["schema"]
    assert backup["rows"] == before["rows"]
    assert backup["integrity"] == [("ok",)]
    assert backup["journal_mode"] == "delete"
    assert [path.name for path in backup_path.parent.iterdir()] == [backup_path.name]
    # Then the database was upgraded.
    assert "completed_at" in workout_columns(previous_database)
    # The log names the backup and the pending changes, never the data.
    assert backup_path.name in caplog.text
    assert "column workouts.completed_at" in caplog.text
    assert PRIVATE_NAME not in caplog.text


def test_later_startups_make_no_new_backup(previous_database):
    start_and_stop(previous_database)
    [first_backup] = backups(previous_database)
    content = file_hash(first_backup)
    after_upgrade = snapshot(previous_database)

    start_and_stop(previous_database)

    assert backups(previous_database) == [first_backup]
    assert file_hash(first_backup) == content
    assert snapshot(previous_database) == after_upgrade
    assert after_upgrade["integrity"] == [("ok",)]


# Failures


def make_backups_folder_unusable(database_path, monkeypatch):
    # A file where the folder should be: the folder cannot be created.
    (database_path.parent / "backups").write_bytes(b"")


def fail_copying(database_path, monkeypatch):
    def failing_copy(engine, backup_path):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(database_backup, "_copy_database", failing_copy)


@pytest.mark.parametrize("make_backup_fail", [make_backups_folder_unusable, fail_copying])
def test_failed_backup_stops_the_startup_before_any_change(previous_database, monkeypatch, make_backup_fail):
    content = file_hash(previous_database)
    make_backup_fail(previous_database, monkeypatch)

    with pytest.raises(DatabaseBackupError):
        start_and_stop(previous_database)

    assert file_hash(previous_database) == content
    assert "completed_at" not in workout_columns(previous_database)
    backups_folder = previous_database.parent / "backups"
    if backups_folder.is_dir():
        assert list(backups_folder.iterdir()) == []  # no unusable file left behind


original_copy_database = database_backup._copy_database


def corrupt_the_copy(engine, backup_path):
    backup_path.write_bytes(b"not a database " * 512)


def copy_without_the_sets(engine, backup_path):
    original_copy_database(engine, backup_path)
    connection = sqlite3.connect(backup_path)
    connection.execute("DELETE FROM workout_sets")
    connection.commit()
    connection.close()



@pytest.mark.parametrize("bad_copy", [corrupt_the_copy, copy_without_the_sets])
def test_backup_failing_verification_stops_the_startup(previous_database, monkeypatch, bad_copy):
    content = file_hash(previous_database)
    monkeypatch.setattr(database_backup, "_copy_database", bad_copy)

    with pytest.raises(DatabaseBackupError):
        start_and_stop(previous_database)

    assert file_hash(previous_database) == content
    assert "completed_at" not in workout_columns(previous_database)
    # The file that failed verification is not left to pass for a backup.
    assert backups(previous_database) == []


def test_failed_upgrade_keeps_the_backup_and_does_not_restore_it(previous_database, monkeypatch, caplog):
    before = snapshot(previous_database)
    monkeypatch.setattr(
        schema,
        "COLUMN_UPGRADES",
        [("workouts", "completed_at", "DATETIME", "UPDATE workouts SET no_such_column = 1")],
    )

    with caplog.at_level(logging.ERROR), pytest.raises(Exception, match="no_such_column"):
        start_and_stop(previous_database)

    [backup_path] = backups(previous_database)
    backup = snapshot(backup_path)
    assert backup["rows"] == before["rows"]
    assert backup["schema"] == before["schema"]
    assert backup["integrity"] == [("ok",)]
    assert f"The backup backups/{backup_path.name} was kept" in caplog.text
    # The failed column was rolled back by upgrade_schema; nothing was restored
    # over the database (the tables created by create_all() are still there).
    assert "completed_at" not in workout_columns(previous_database)
    assert "workout_templates" in snapshot(previous_database)["rows"]


# Backup files


def test_existing_backup_names_are_never_overwritten(previous_database):
    folder = previous_database.parent / "backups"
    folder.mkdir()
    taken = folder / "workout_tracker.before-upgrade-20261019-090000.db"
    taken.write_bytes(b"an older backup")
    engine = create_engine(f"sqlite:///{previous_database.as_posix()}")

    second = backup_database(engine, now=datetime(2026, 10, 19, 9, 0, 0))
    third = backup_database(engine, now=datetime(2026, 10, 19, 9, 0, 0))
    engine.dispose()

    assert taken.read_bytes() == b"an older backup"
    assert second.name == "workout_tracker.before-upgrade-20261019-090000-2.db"
    assert third.name == "workout_tracker.before-upgrade-20261019-090000-3.db"
    assert snapshot(second)["rows"] == snapshot(third)["rows"] == snapshot(previous_database)["rows"]


def test_backup_of_a_wal_database_has_every_committed_change_and_nothing_uncommitted(previous_database):
    writer = sqlite3.connect(previous_database, isolation_level=None)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    # Without checkpoints, committed changes stay only in the -wal file, which
    # a copy of the database file would miss.
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        f"INSERT INTO exercises (id, name, muscle_group, muscle_subgroup, created_at, updated_at) VALUES (2, 'Remada', 'Costas', 'Dorsais', {TIMESTAMP}, {TIMESTAMP})"
    )
    assert (previous_database.parent / "workout_tracker.db-wal").stat().st_size > 0
    in_progress = sqlite3.connect(previous_database, isolation_level=None)
    in_progress.execute("BEGIN IMMEDIATE")
    in_progress.execute(
        f"INSERT INTO exercises (id, name, muscle_group, muscle_subgroup, created_at, updated_at) VALUES (3, 'Uncommitted', 'Costas', 'Dorsais', {TIMESTAMP}, {TIMESTAMP})"
    )
    engine = create_engine(f"sqlite:///{previous_database.as_posix()}")

    try:
        backup_path = backup_database(engine)
    finally:
        engine.dispose()
        in_progress.execute("ROLLBACK")
        in_progress.close()
        writer.close()

    backup = snapshot(backup_path)
    assert [row[1] for row in backup["rows"]["exercises"]] == ["Supino", "Remada"]
    assert backup["integrity"] == [("ok",)]
    assert backup["journal_mode"] == "delete"
    assert [path.name for path in backup_path.parent.iterdir()] == [backup_path.name]


def test_only_a_database_file_can_be_backed_up():
    engine = create_engine("sqlite://")

    with pytest.raises(DatabaseBackupError):
        backup_database(engine)
    engine.dispose()
