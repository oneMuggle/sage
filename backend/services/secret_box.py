"""SecretBox — app_settings 中 API Key 的静态加密（对标增强第三轮 L15）。

背景: settings 的 GET/HTTP 面已由 settings_canonicalizer.redact_secrets 脱敏
(OWASP A02:2021), 但 SQLite preferences 表里的 endpoint.apiKey 仍是明文落库 —
DB 文件随备份/网盘同步/误打包外泄即泄密。本模块提供"落库静态加密":

- Windows(含 Win7): DPAPI(crypt32 CryptProtectData, 用户级作用域) — stdlib ctypes
- macOS: login keychain(``security`` CLI generic password), 明文不落库
- Linux: secret-tool(libsecret), 探测到可用才启用
- 以上均不可用: 明文落库 + doctor ``secret_storage`` 持续告警(诚实降级)

存储格式: ``enc:<scheme>:v1:<payload>`` 前缀标记, JSON 结构不变, 仅叶子值替换。
接入点: SettingsRepository.get/set 的 app_settings 字符串层(单一咽喉点,
legacy/hex 两条 API 路径与 preferences 路由全部透明覆盖)。

测试: 环境变量 ``SAGE_SECRET_SCHEME=test`` 强制 base64 对称实现, 保证
跨平台 CI 确定性; Windows 上另有真实 DPAPI roundtrip 用例(win32 skip)。

py3.8 纪律: 本模块同时服务 main 与 release/win7 — stdlib only,
禁 PEP 604/585 运行时用法。
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 密文前缀 scheme 命名空间
_SCHEMES = ("dpapi", "keychain", "secret-tool", "test")
_PREFIX = "enc"
_VERSION = "v1"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_KEYCHAIN_SERVICE = "sage-api-key"
_SECRET_TOOL_SERVICE = "sage-api-key"

#: SAGE_SECRET_SCHEME 允许的强制值(none 不允许强制 — 会伪装成"已加密")
_ENV_SCHEMES = _SCHEMES + ("none",)


class SecretBoxError(Exception):
    """加解密失败(平台后端报错/密文损坏/账户缺失)。"""


def current_scheme() -> str:
    """解析当前可用的加密 scheme(每次调用即时解析, 测试可 monkeypatch env)。"""
    forced = os.environ.get("SAGE_SECRET_SCHEME", "").strip().lower()
    if forced in _ENV_SCHEMES:
        return forced
    if sys.platform == "win32":
        return "dpapi"
    if sys.platform == "darwin":
        return "keychain" if shutil.which("security") else "none"
    if shutil.which("secret-tool"):
        return "secret-tool"
    return "none"


def is_wrapped(value: Any) -> bool:
    """判断字符串是否已是 ``enc:`` 密文(幂等写保护)。"""
    return isinstance(value, str) and value.startswith(_PREFIX + ":")


# ==================== 平台后端 ====================


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretBoxError(f"CryptProtectData failed (err={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretBoxError(f"CryptUnprotectData failed (err={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _keychain_store(account: str, secret: str) -> None:
    # -U: 同账户已存在时更新, 避免残留旧条目
    proc = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            account,
            "-s",
            _KEYCHAIN_SERVICE,
            "-w",
            secret,
            "-U",
        ],
        capture_output=True,
        timeout=5, check=False,
    )
    if proc.returncode != 0:
        raise SecretBoxError(
            f"security add-generic-password failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )


def _keychain_load(account: str) -> str:
    proc = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", _KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        timeout=5, check=False,
    )
    if proc.returncode != 0:
        raise SecretBoxError(
            f"security find-generic-password failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout.decode("utf-8").rstrip("\r\n")


def _secret_tool_store(account: str, secret: str) -> None:
    proc = subprocess.run(
        [
            "secret-tool",
            "store",
            "--label=sage",
            "service",
            _SECRET_TOOL_SERVICE,
            "username",
            account,
        ],
        input=secret.encode("utf-8"),
        capture_output=True,
        timeout=5, check=False,
    )
    if proc.returncode != 0:
        raise SecretBoxError(
            f"secret-tool store failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )


def _secret_tool_load(account: str) -> str:
    proc = subprocess.run(
        ["secret-tool", "lookup", "service", _SECRET_TOOL_SERVICE, "username", account],
        capture_output=True,
        timeout=5, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise SecretBoxError("secret-tool lookup failed or empty")
    return proc.stdout.decode("utf-8").rstrip("\r\n")


# ==================== 加解密入口 ====================


def encrypt_secret(plaintext: str, account: str = "default") -> str:
    """加密明文 → ``enc:<scheme>:v1:<payload>``。scheme=none 原样返回(不加前缀)。"""
    scheme = current_scheme()
    if scheme == "none":
        return plaintext
    if scheme == "dpapi":
        payload = base64.b64encode(_dpapi_protect(plaintext.encode("utf-8"))).decode("ascii")
    elif scheme == "keychain":
        _keychain_store(account, plaintext)
        payload = account
    elif scheme == "secret-tool":
        _secret_tool_store(account, plaintext)
        payload = account
    elif scheme == "test":
        payload = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    else:  # pragma: no cover - current_scheme 枚举外
        raise SecretBoxError(f"unknown scheme: {scheme}")
    return f"{_PREFIX}:{scheme}:{_VERSION}:{payload}"


def decrypt_secret(stored: str) -> str:
    """解密 ``enc:`` 密文; 非密文原样返回(兼容未迁移明文)。失败抛 SecretBoxError。"""
    if not is_wrapped(stored):
        return stored
    parts = stored.split(":", 3)
    if len(parts) != 4 or parts[2] != _VERSION:
        raise SecretBoxError("malformed secret payload")
    _, scheme, _, payload = parts
    if scheme == "dpapi":
        return _dpapi_unprotect(base64.b64decode(payload)).decode("utf-8")
    if scheme == "keychain":
        return _keychain_load(payload)
    if scheme == "secret-tool":
        return _secret_tool_load(payload)
    if scheme == "test":
        return base64.b64decode(payload).decode("utf-8")
    raise SecretBoxError(f"unknown scheme: {scheme}")


# ==================== app_settings 包装 ====================


def _endpoint_account(ep: Dict[str, Any], idx: int) -> str:
    """keychain/secret-tool 的稳定账户名: 优先 endpoint.id, 缺省退化为下标。"""
    return "ep-%s" % (ep.get("id") if ep.get("id") else idx)


def _iter_endpoint_lists(data: Dict[str, Any]) -> List[List[Any]]:
    """yield app_settings 里的 endpoints 列表(扁平 + llm 嵌套两种 schema)。"""
    lists: List[List[Any]] = []
    for container in (data.get("endpoints"), (data.get("llm") or {}).get("endpoints")
                      if isinstance(data.get("llm"), dict) else None):
        if isinstance(container, list):
            lists.append(container)
    return lists


def wrap_app_settings(data: Any) -> Any:
    """把 endpoints[*].apiKey 明文就地加密(scheme=none 时原样)。非 dict 原样返回。"""
    if not isinstance(data, dict):
        return data
    for endpoints in _iter_endpoint_lists(data):
        for idx, ep in enumerate(endpoints):
            if not isinstance(ep, dict):
                continue
            key = ep.get("apiKey")
            if isinstance(key, str) and key and not is_wrapped(key):
                try:
                    ep["apiKey"] = encrypt_secret(key, _endpoint_account(ep, idx))
                except Exception:
                    # fail-open: 加密失败保留明文, doctor secret_storage 会告警
                    logger.warning(
                        "SecretBox: encrypt failed for endpoint %s (kept plaintext)",
                        ep.get("id") or idx,
                    )
    return data


def unwrap_app_settings(data: Any) -> Any:
    """把 endpoints[*].apiKey 密文就地解密为内存明文。单条失败置空串(不投毒)。"""
    if not isinstance(data, dict):
        return data
    for endpoints in _iter_endpoint_lists(data):
        for idx, ep in enumerate(endpoints):
            if not isinstance(ep, dict):
                continue
            key = ep.get("apiKey")
            if isinstance(key, str) and is_wrapped(key):
                try:
                    ep["apiKey"] = decrypt_secret(key)
                except Exception:
                    logger.error(
                        "SecretBox: decrypt failed for endpoint %s (key cleared, re-enter in settings)",
                        ep.get("id") or idx,
                    )
                    ep["apiKey"] = ""
    return data


def wrap_settings_json(raw: Optional[str]) -> Optional[str]:
    """字符串层包装(SettingsRepository.set 用): 解析 JSON → 加密 → 回写。"""
    if raw is None:
        return raw
    try:
        import json

        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    wrapped = wrap_app_settings(data)
    return json.dumps(wrapped, ensure_ascii=False)


def unwrap_settings_json(raw: Optional[str]) -> Optional[str]:
    """字符串层解包(SettingsRepository.get 用): 解析 JSON → 解密 → 回写。"""
    if raw is None:
        return raw
    try:
        import json

        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    unwrapped = unwrap_app_settings(data)
    return json.dumps(unwrapped, ensure_ascii=False)


def migrate_plaintext_settings() -> Dict[str, Any]:
    """启动期迁移: 读 app_settings(已透明解密) → 重加密回写。

    幂等; scheme=none 时为 no-op(明文保留, doctor 告警)。统计基于**原始行**
    (绕过 get 的透明解密), 否则加密计数恒为 0。读路径失败/DB 未就绪一律 fail-open。
    """
    import json as _json

    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()

    def _read_raw() -> Optional[Dict[str, Any]]:
        try:
            row = repo._conn().execute(
                "SELECT value FROM preferences WHERE key = ?", ("app_settings",)
            ).fetchone()
        except Exception:  # noqa: BLE001 — DB 未就绪等, fail-open
            return None
        if row is None or not row["value"]:
            return None
        try:
            data = _json.loads(row["value"])
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    before_raw = _read_raw()
    if before_raw is None:
        return {"skipped": "no_settings", "scheme": current_scheme()}
    before = _secret_stats(before_raw)
    if before["plaintext"] == 0:
        # 幂等: 全部已加密(或 scheme=none 无前缀) → 不做无谓写
        return {
            "scheme": current_scheme(),
            "plaintext_before": 0,
            "wrapped_after": before["wrapped"],
            "encrypted_now": 0,
        }
    repo.set_json("app_settings", before_raw, category="general")
    after = _secret_stats(_read_raw() or {})
    return {
        "scheme": current_scheme(),
        "plaintext_before": before["plaintext"],
        "wrapped_after": after["wrapped"],
        "encrypted_now": max(0, after["wrapped"] - before["wrapped"]),
    }


def _secret_stats(data: Dict[str, Any]) -> Dict[str, int]:
    total = wrapped = 0
    for endpoints in _iter_endpoint_lists(data):
        for ep in endpoints:
            if isinstance(ep, dict) and isinstance(ep.get("apiKey"), str) and ep.get("apiKey"):
                total += 1
                if is_wrapped(ep["apiKey"]):
                    wrapped += 1
    return {"total": total, "wrapped": wrapped, "plaintext": total - wrapped}
