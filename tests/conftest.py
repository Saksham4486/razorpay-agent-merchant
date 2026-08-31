import pytest
from backend.app.database import engine, Base, SessionLocal
from backend.app.seed_data import seed_catalog

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Initializes SQLite tables and seeds catalog items before tests run.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()
    yield
