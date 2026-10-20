import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

# PostgreSQL:  DATABASE_URL=postgresql+psycopg://crm_user:crm_pass@localhost:5432/crm_db   (see example.env)
# If not set, a local SQLite file is used so the API can still start for a quick look.
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./crm_local.db"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Gives each API request its own DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
