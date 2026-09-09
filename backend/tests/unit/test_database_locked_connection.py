"""B2: Database.get_connection() 加锁代理的行为测试。

背景: 全进程共享单个 sqlite3 连接 (check_same_thread=False), 此前只有
部分调用方 (@with_db_lock handler / SqliteStorageAdapter._sync_X) 手工
加锁, Session/Message/memory 等仓库方法被工具 executor 线程 /
asyncio.to_thread / APScheduler 并发调用时完全无锁 —— 存在游标交错、
事务互踩风险。B2 把锁下沉到连接代理, 所有经 get_connection() 的访问
统一串行化。
"""

import threading

import pytest

from backend.data.database import _SQLITE_LOCK, Database

pytestmark = pytest.mark.unit


def _make_db(tmp_path):
    db = Database(str(tmp_path / "lock-test.db"))
    conn = db.get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    return db


def test_proxy_reentrant_with_sqlite_lock(tmp_path):
    """with _SQLITE_LOCK 块内经代理再访问不应自死锁 (RLock 同线程可重入)。

    这是锁从 threading.Lock 换成 RLock 的根本原因: 既有 handler 的
    `with _SQLITE_LOCK:` 块内会调用走代理的仓库方法 —— 不可重入锁会
    立即自死锁。
    """
    db = _make_db(tmp_path)
    conn = db.get_connection()
    with _SQLITE_LOCK:
        conn.execute("INSERT INTO t (v) VALUES (?)", ("a",))
        conn.commit()
    row = conn.execute("SELECT v FROM t").fetchone()
    assert row["v"] == "a"


def test_proxy_stable_identity(tmp_path):
    """get_connection() 多次调用返回同一代理对象, 身份比较不破坏。"""
    db = _make_db(tmp_path)
    assert db.get_connection() is db.get_connection()


def test_proxy_cursor_forwarding(tmp_path):
    """代理 cursor 透传 lastrowid / row_factory 语义。"""
    db = _make_db(tmp_path)
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
    conn.commit()
    assert cur.lastrowid >= 1
    row = conn.execute("SELECT v FROM t WHERE id = ?", (cur.lastrowid,)).fetchone()
    assert row["v"] == "x"


def test_multithreaded_access_consistent(tmp_path):
    """多线程并发经代理写入不丢数据、不抛交叉异常。"""
    db = _make_db(tmp_path)
    workers = 8
    loops = 50
    errors = []

    def worker(n: int) -> None:
        try:
            conn = db.get_connection()
            for i in range(loops):
                conn.execute("INSERT INTO t (v) VALUES (?)", (f"w{n}-{i}",))
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    conn = db.get_connection()
    count = conn.execute("SELECT COUNT(*) AS c FROM t").fetchone()["c"]
    assert count == workers * loops
