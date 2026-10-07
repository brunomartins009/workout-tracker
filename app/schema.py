"""Additive schema upgrades for databases created by an earlier version.

`Base.metadata.create_all()` creates missing tables but never changes tables
that already exist. When a new column is added to a model, an existing local
database needs that column added explicitly, otherwise every query on the
table fails.

Only additive, non-destructive changes belong here: `ALTER TABLE ... ADD COLUMN`
keeps every existing row, its id and its relationships. Each upgrade runs only
when the column is missing, so running this on every startup is safe.

If the schema ever needs destructive changes (renaming, dropping or changing
column types), this file should be replaced by a real migration tool such as
Alembic instead of growing into one.
"""

from sqlalchemy import inspect, text

from app.models import UNCLASSIFIED


# (table, column, column definition used by ALTER TABLE ... ADD COLUMN)
# SQLite only accepts a NOT NULL column on a table with rows when the column
# also has a default, which is what existing rows receive.
COLUMN_UPGRADES = [
    ("exercises", "muscle_group", f"VARCHAR(100) NOT NULL DEFAULT '{UNCLASSIFIED}'"),
    ("exercises", "muscle_subgroup", f"VARCHAR(100) NOT NULL DEFAULT '{UNCLASSIFIED}'"),
]


def upgrade_schema(engine):
    """Add model columns that are missing from an existing database."""
    with engine.begin() as connection:
        for table, column, definition in COLUMN_UPGRADES:
            existing_columns = {
                existing_column["name"]
                for existing_column in inspect(connection).get_columns(table)
            }
            if column not in existing_columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
