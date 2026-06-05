"""
Sage 后端测试 - 共享 fixtures
"""
import os
import sys
import tempfile

import pytest
import pytest_asyncio

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import httpx

from backend.main import app


@pytest.fixture()
def tmp_db_path():
    """创建临时数据库文件，测试后自动清理"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_db_path):
    """每个测试自动使用独立临时数据库"""
    import backend.data.database as db_mod
    db_mod._db = db_mod.Database(db_path=tmp_db_path)
    db_mod._db.init_db()
    yield db_mod._db
    db_mod._db.close()
    db_mod._db = None


@pytest_asyncio.fixture
async def client():
    """提供异步 HTTP 测试客户端"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
