# tests/electron/_real_backend.py
import os, signal, subprocess, time, urllib.request, urllib.error
from pathlib import Path


class RealBackend:
    """启动真实 conda sage-backend 子进程，等待 /health 就绪。"""

    def __init__(self, port: int = 8765, timeout_s: int = 30):
        self.port = port
        self.timeout_s = timeout_s
        self.process = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self):
        self.process = subprocess.Popen(
            ["conda", "run", "-n", "sage-backend", "python", "-m", "backend.main"],
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**os.environ, "PYTHON_BACKEND_PORT": str(self.port)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=2) as r:
                    if r.status == 200:
                        return self.url
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"Backend failed to become healthy in {self.timeout_s}s")

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    self.process.kill()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
