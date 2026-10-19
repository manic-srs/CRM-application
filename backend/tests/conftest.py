"""Every test gets a fresh in-memory database with 2 users, so real data is never touched.
(Full MySQL behaviour is checked by running the API against database/schema.sql + seed-data.sql.)"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.routers.auth import hash_password  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        db.add_all([
            User(full_name="Priya Sharma", email="priya@crm.test", role="Manager", password_hash=hash_password("Password@123")),
            User(full_name="Ravi Kumar", email="ravi@crm.test", role="Salesperson", password_hash=hash_password("Password@123")),
        ])
        db.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)  # no "with": skips startup, so the real database is never opened
    app.dependency_overrides.clear()
