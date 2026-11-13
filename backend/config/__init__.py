import os


def is_web_mode() -> bool:
    """检查是否运行在 web mode（提供静态文件服务）。"""
    return os.getenv("SAGE_WEB_MODE") == "1"
