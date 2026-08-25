# tests/electron/test_real_backend_fixture.py
import os, subprocess, pytest

def test_real_backend_starts_and_responds_to_health():
    """验证 real_backend fixture 能启动真实后端并响应 /health。"""
    r = subprocess.run(
        ["conda", "run", "-n", "sage-backend", "python", "-c", "import fastapi; print('ok')"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip("sage-backend conda env not available")

    from conftest import RealBackend
    backend = RealBackend()
    backend.start()
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{backend.url}/health", timeout=10)
        assert resp.status == 200
    finally:
        backend.stop()
