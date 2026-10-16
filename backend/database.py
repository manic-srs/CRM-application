"""Database connection.

Reads DATABASE_URL from the .env file.
- Until the MySQL database is ready, it uses a local SQLite file (crm.db), so the APIs work right away.
- For MySQL, set in .env:  DATABASE_URL=mysql+pymysql://USER:PASSWORD@localhost:3306/crm_db
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")

# SQLite needs this extra setting; MySQL does not.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Gives each API request its own database session, and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
