"""Database engine + session management.

Schema ownership: schema.sql is loaded by Postgres on first container boot.
init_db() only verifies connectivity — it does NOT create tables.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from api.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def init_db() -> None:
    """Verify the DB is reachable. DDL is owned by schema.sql."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✓ Database connection verified")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
