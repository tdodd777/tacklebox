import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tacklebox.config import settings
from tacklebox.db import get_db
from tacklebox.main import app

# Replace only the database name (last path segment) not the username
_base = settings.DATABASE_URL.rsplit("/", 1)[0]
TEST_DB_URL = f"{_base}/tacklebox_test"

TABLES = [
    "stop_blocks",
    "subagent_events",
    "notifications",
    "session_context",
    "tool_events",
    "sessions",
]


@pytest.fixture(autouse=True)
async def _setup_and_clean():
    """Create tables before test, truncate after."""
    engine = create_async_engine(TEST_DB_URL)
    from tacklebox.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        for table in TABLES:
            await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def client(_setup_and_clean):
    """FastAPI test client wired to the test database."""
    engine = _setup_and_clean
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
