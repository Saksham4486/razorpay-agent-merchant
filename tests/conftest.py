import pytest
from backend.app.database import engine, Base, SessionLocal
from backend.app.seed_data import seed_catalog

@pytest.fixture(scope="module", autouse=True)
def setup_test_database():
    """
    Resets and reseeds the database once per test MODULE (file) rather than
    once per whole session. Several tests create real orders that count
    toward policy_engine.py's cumulative daily-volume ceiling; without this,
    unrelated test files' order volume leaks into each other and can cause
    an otherwise-correct high-value order to be rejected purely because of
    accumulated volume from an earlier file's tests. Module scope (rather
    than function scope) is used because some tests within a single file
    intentionally rely on state built up by earlier tests in that same file
    (e.g. the audit hash-chain verification test). policy_engine.py itself
    is untouched - this only isolates test state.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()
    yield
