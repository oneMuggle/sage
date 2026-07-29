"""SAGE_DB_PATH 环境变量集成测试"""



def test_db_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "custom-sage.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(target))
    # 重新导入以触发 __init__ 重读
    import importlib

    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    assert db.db_path == str(target)
    db.init_db()
    assert target.exists()
    db.close()


def test_db_path_default_when_no_env(monkeypatch):
    monkeypatch.delenv("SAGE_DB_PATH", raising=False)
    import importlib

    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    # 默认路径包含 'sage.db'
    assert db.db_path.endswith("sage.db")
    db.close()


def test_db_path_creates_parent_dir_when_missing(monkeypatch, tmp_path):
    """防御性 mkdir:当 SAGE_DB_PATH 的父目录不存在时, Database() 必须自动创建。

    触发场景:内网 Win7 全新安装, %APPDATA%/Sage/ 尚未被 Electron 创建,
    sqlite3.connect() 会因父目录不存在而抛 OperationalError。修复后防御性
    mkdir(parents=True, exist_ok=True) 确保目录存在。
    """
    # 构造一个深层嵌套的、尚不存在的路径
    nested = tmp_path / "a" / "b" / "c" / "sage.db"
    assert not nested.parent.exists()

    monkeypatch.setenv("SAGE_DB_PATH", str(nested))
    import importlib

    from backend.data import database
    importlib.reload(database)

    db = database.Database()
    # __init__ 应当已创建父目录
    assert nested.parent.exists()
    assert nested.parent.is_dir()

    # init_db 也应能成功(sqlite3.connect 不会因为父目录缺失而失败)
    db.init_db()
    assert nested.exists()
    db.close()

