import os

os.environ["MINDLOOP_DATABASE_URL"] = "sqlite+aiosqlite:///./test_mindloop.db"
os.environ["MINDLOOP_FOCUS_ACTIVITY_THRESHOLD_SECONDS"] = "20"
os.environ["MINDLOOP_FOCUS_COOLDOWN_SECONDS"] = "300"

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
async def database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
