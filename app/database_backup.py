"""Verified backup of the SQLite database, made before a schema upgrade.

`create_app()` upgrades an existing database in place on startup. When an
upgrade is pending, it first calls `backup_database()`, and the upgrade only
runs if a backup was made and verified. If anything fails, the error is
raised and the application does not start.

The copy uses SQLite's online backup API instead of copying the file: in WAL
mode, committed changes may still be only in the `-wal` file, which a file
copy would miss or capture half-written. The API copies one consistent state
of the database, with every committed change and nothing uncommitted.

Backups are written to a `backups` folder next to the database
(`instance/backups/` for the real one) and are never deleted or overwritten
by the application.
"""

import sqlite3
from contextlib import suppress
from datetime import datetime
from pathlib import Path


BACKUP_FOLDER_NAME = "backups"


class DatabaseBackupError(RuntimeError):
    """The backup could not be made or verified, so the upgrade must not run."""


def backup_database(engine, now=None):
    """Copy the database into a new, verified backup file and return its path."""
    database_path = _database_path(engine)
    backup_folder = database_path.parent / BACKUP_FOLDER_NAME
    try:
        backup_folder.mkdir(exist_ok=True)
        backup_path = _reserve_backup_path(backup_folder, database_path, now or datetime.now())
    except OSError as error:
        raise DatabaseBackupError(f"Could not create a backup file in {backup_folder}.") from error

    try:
        _copy_database(engine, backup_path)
        _verify_backup(engine, backup_path)
    except Exception as error:
        # The file was created by this attempt and is not a usable backup;
        # leaving it would let it be mistaken for one later.
        with suppress(OSError):
            backup_path.unlink()
        raise DatabaseBackupError(f"The backup {backup_path.name} could not be made or verified.") from error
    return backup_path


def _database_path(engine):
    database = engine.url.database
    if engine.dialect.name != "sqlite" or not database or database == ":memory:":
        raise DatabaseBackupError("Only a SQLite database stored in a file can be backed up.")
    return Path(database)


def _reserve_backup_path(backup_folder, database_path, now):
    """Create an empty file with a new name, so no existing backup is ever overwritten.

    Mode "x" fails if the file exists, even if another process creates it at
    the same moment; the next free suffix is then tried.
    """
    base_name = f"{database_path.stem}.before-upgrade-{now.strftime('%Y%m%d-%H%M%S')}"
    for attempt in range(1, 1000):
        suffix = "" if attempt == 1 else f"-{attempt}"
        backup_path = backup_folder / f"{base_name}{suffix}{database_path.suffix}"
        try:
            with open(backup_path, "xb"):
                return backup_path
        except FileExistsError:
            continue
    raise DatabaseBackupError(f"No free backup file name for {base_name}.")


def _copy_database(engine, backup_path):
    # The source is read through the application's engine; only the backup
    # file gets a connection of its own.
    source = engine.raw_connection()
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.driver_connection.backup(target)
            # A copy of a WAL database is in WAL mode too, and would keep
            # -wal/-shm files next to it once opened. The rollback journal
            # makes the backup a single self-contained file.
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
    finally:
        source.close()


def _verify_backup(engine, backup_path):
    """The backup opens, passes SQLite's integrity check and has every table and row."""
    if backup_path.stat().st_size == 0:
        raise DatabaseBackupError("The backup file is empty.")

    # Read-only: verifying must not change the backup.
    backup = sqlite3.connect(f"{backup_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = backup.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise DatabaseBackupError("The backup failed SQLite's integrity check.")
        backup_rows = _row_counts(backup)
    finally:
        backup.close()

    source = engine.raw_connection()
    try:
        source_rows = _row_counts(source.driver_connection)
    finally:
        source.close()
    if backup_rows != source_rows:
        raise DatabaseBackupError("The backup does not have the same tables and rows as the database.")


def _row_counts(connection):
    """Number of rows of each table: compared, never logged, so no data leaves the database."""
    table_names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        name: connection.execute(f"SELECT count(*) FROM {_quoted_identifier(name)}").fetchone()[0]
        for name in table_names
    }


def _quoted_identifier(name):
    escaped_name = name.replace('"', '""')
    return f'"{escaped_name}"'
