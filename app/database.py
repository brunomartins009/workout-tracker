from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the SQLAlchemy engine and the request-scoped database session."""

    def init_app(self, app):
        engine = create_engine(app.config["DATABASE_URL"])

        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", self._enable_sqlite_foreign_keys)

        self.engine = engine
        self.session = scoped_session(
            sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        )
        app.extensions["database"] = self
        app.teardown_appcontext(lambda _exception: self.session.remove())

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def drop_all(self):
        Base.metadata.drop_all(self.engine)


db = Database()
