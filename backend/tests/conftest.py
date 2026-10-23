"""Every test gets a fresh in-memory database with 3 users, so real data is never touched:
  1 Priya (Manager), 2 Ravi (Salesperson, the client logs in as Ravi by default), 3 Asha (Admin).
Use login_as(client, user_id) to act as someone else.
(Full PostgreSQL behaviour is checked by running the API against database/schema.sql.)"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MAIL_ASYNC"] = "false"  # send notification emails before the request returns, so tests can check them

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.routers.auth import hash_password  # noqa: E402
from app.security import make_token  # noqa: E402


def login_as(client, user_id: int):
    """The next requests are made as this user (same as logging in)."""
    client.headers["Authorization"] = f"Bearer {make_token(user_id)}"
    return client


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        db.add_all([
            User(full_name="Priya Sharma", email="priya@crm.test", role="Manager", password_hash=hash_password("Password@123")),
            User(full_name="Ravi Kumar", email="ravi@crm.test", role="Salesperson", password_hash=hash_password("Password@123")),
            User(full_name="Asha Rao", email="asha@crm.test", role="Admin", password_hash=hash_password("Password@123")),
        ])
        db.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield login_as(TestClient(app), 2)  # no "with": skips startup, so the real database is never opened
    app.dependency_overrides.clear()
