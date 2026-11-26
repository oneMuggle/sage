"""浏览器多账号管理（方案 2026-11-20 browser-multi-account）。

在既有 ``credential_vault``（按 domain 单一凭据）之上增加「账号」维度：

- 账号注册表落 SQLite ``browser_accounts``（domain + label 唯一）。
- 凭据沿用 vault：命名账号的 key 为 ``domain::account_id``，默认账号继续用
  平铺 ``domain`` key（零迁移，完全向后兼容）。
- 切换 = 快照当前账号状态 → 清空浏览器 cookie/localStorage → 注入目标账号
  → 刷新页面。单浏览器实例内毫秒级热切换（方案 A：Cookie State Swap），
  同一时刻浏览器只携带一个账号的登录态，账号间不串号。

安全口径与 vault 一致：明文凭据只在单次切换调用的内存中存在；落库走
SecretBox；list 接口不回显值。

py3.8 纪律：本模块同时服务 main 与 release/win7 — stdlib only。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.data.database import _SQLITE_LOCK, get_database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserAccount:
    """一个浏览器账号（同 domain 下可多条）。"""

    id: str
    label: str
    domain: str
    color: Optional[str]
    notes: Optional[str]
    is_default: bool
    created_at: int
    updated_at: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "domain": self.domain,
            "color": self.color,
            "notes": self.notes,
            "is_default": self.is_default,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SwitchResult:
    """账号切换结果。"""

    ok: bool
    account_id: str = ""
    label: str = ""
    domain: str = ""
    swapped_domains: Optional[List[str]] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "account_id": self.account_id,
            "label": self.label,
            "domain": self.domain,
            "swapped_domains": self.swapped_domains or [],
            "message": self.message,
        }


def _row_to_account(row: Any) -> BrowserAccount:
    return BrowserAccount(
        id=row["id"],
        label=row["label"],
        domain=row["domain"],
        color=row["color"],
        notes=row["notes"],
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class BrowserAccountService:
    """账号注册表 CRUD + 浏览器 cookie/localStorage 热切换编排。

    进程级单例：``browser_account_service``。``_active`` 按 ``browser_id``
    追踪当前激活账号（进程内状态，后端重启后清空，首次切换时重建）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: browser_id → account_id（当前激活账号）
        self._active: Dict[str, str] = {}

    # ── 内部工具 ──────────────────────────────────────────────

    def _conn(self) -> Any:
        return get_database().get_connection()

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return (domain or "").strip().lower()

    # ── 账号 CRUD ─────────────────────────────────────────────

    def create_account(
        self,
        label: str,
        domain: str,
        color: Optional[str] = None,
        notes: Optional[str] = None,
        is_default: bool = False,
    ) -> BrowserAccount:
        """新建账号；同 domain + label 重复时抛 ``ValueError``。"""
        label = (label or "").strip()
        domain = self._normalize_domain(domain)
        if not label:
            raise ValueError("create_account: label 不能为空")
        if not domain:
            raise ValueError("create_account: domain 不能为空")
        now = int(time.time() * 1000)
        account = BrowserAccount(
            id=str(uuid.uuid4()),
            label=label,
            domain=domain,
            color=(color or "").strip() or None,
            notes=(notes or "").strip() or None,
            is_default=bool(is_default),
            created_at=now,
            updated_at=now,
        )
        with _SQLITE_LOCK:
            conn = self._conn()
            existing = conn.execute(
                "SELECT id FROM browser_accounts WHERE label = ? AND domain = ?",
                (label, domain),
            ).fetchone()
            if existing:
                raise ValueError(f"create_account: 域名 {domain} 下已存在账号 {label!r}")
            if is_default:
                # 每域名最多一个默认账号
                conn.execute(
                    "UPDATE browser_accounts SET is_default = 0 WHERE domain = ?",
                    (domain,),
                )
            conn.execute(
                """INSERT INTO browser_accounts
                   (id, label, domain, color, notes, is_default, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account.id,
                    account.label,
                    account.domain,
                    account.color,
                    account.notes,
                    1 if account.is_default else 0,
                    account.created_at,
                    account.updated_at,
                ),
            )
            conn.commit()
        return account

    def list_accounts(self, domain: Optional[str] = None) -> List[BrowserAccount]:
        """列出账号（可按 domain 过滤），默认账号排前。

        列表前先执行懒迁移：既有平铺 vault 凭据（多账号功能之前保存的）若
        尚无登记的默认账号，自动登记为「默认账号」，保证老用户能在账号池里
        看到并切回原账号。
        """
        self.ensure_legacy_accounts(domain)
        sql = "SELECT * FROM browser_accounts"
        params: Tuple[Any, ...] = ()
        if domain:
            sql += " WHERE domain = ?"
            params = (self._normalize_domain(domain),)
        sql += " ORDER BY is_default DESC, created_at ASC"
        rows = self._conn().execute(sql, params).fetchall()
        return [_row_to_account(row) for row in rows]

    def ensure_legacy_accounts(self, domain: Optional[str] = None) -> int:
        """为既有平铺 vault 凭据补登记默认账号（幂等）；返回新建数量。"""
        try:
            from backend.tools.credential_vault import list_credentials

            entries = list_credentials()
        except Exception:  # noqa: BLE001 — 凭据枚举失败不阻断账号列表
            logger.warning("读取 vault 枚举失败，跳过默认账号懒迁移", exc_info=True)
            return 0
        target_domain = self._normalize_domain(domain) if domain else ""
        created = 0
        for entry in entries:
            if entry.get("account_id") is not None:
                continue  # 命名账号条目，无需迁移
            if entry.get("kind") != "cookie":
                continue
            entry_domain = self._normalize_domain(str(entry.get("domain") or ""))
            if not entry_domain:
                continue
            if target_domain and entry_domain != target_domain:
                continue
            existing = self._conn().execute(
                "SELECT id FROM browser_accounts WHERE domain = ? AND is_default = 1 LIMIT 1",
                (entry_domain,),
            ).fetchone()
            if existing:
                continue
            try:
                self.create_account(label="默认账号", domain=entry_domain, is_default=True)
                created += 1
            except ValueError:
                # 并发登记撞唯一约束：视为已存在
                continue
        return created


    def get_account(self, account_id: str) -> Optional[BrowserAccount]:
        if not account_id:
            return None
        row = self._conn().execute(
            "SELECT * FROM browser_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return _row_to_account(row) if row else None

    def get_default_account(self, domain: str) -> Optional[BrowserAccount]:
        """取某 domain 的默认账号。"""
        domain = self._normalize_domain(domain)
        if not domain:
            return None
        row = self._conn().execute(
            "SELECT * FROM browser_accounts WHERE domain = ? AND is_default = 1 "
            "ORDER BY created_at ASC LIMIT 1",
            (domain,),
        ).fetchone()
        return _row_to_account(row) if row else None

    def update_account(
        self,
        account_id: str,
        label: Optional[str] = None,
        color: Optional[str] = None,
        notes: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> BrowserAccount:
        """更新账号元数据；无该账号抛 ``KeyError``。"""
        account = self.get_account(account_id)
        if account is None:
            raise KeyError(f"update_account: 账号 {account_id!r} 不存在")
        new_label = (label or "").strip() if label is not None else account.label
        if not new_label:
            raise ValueError("update_account: label 不能为空")
        new_color = account.color if color is None else ((color or "").strip() or None)
        new_notes = account.notes if notes is None else ((notes or "").strip() or None)
        new_default = account.is_default if is_default is None else bool(is_default)
        now = int(time.time() * 1000)
        with _SQLITE_LOCK:
            conn = self._conn()
            if new_label != account.label:
                dup = conn.execute(
                    "SELECT id FROM browser_accounts WHERE label = ? AND domain = ? AND id != ?",
                    (new_label, account.domain, account_id),
                ).fetchone()
                if dup:
                    raise ValueError(
                        f"update_account: 域名 {account.domain} 下已存在账号 {new_label!r}"
                    )
            if new_default and not account.is_default:
                conn.execute(
                    "UPDATE browser_accounts SET is_default = 0 WHERE domain = ?",
                    (account.domain,),
                )
            conn.execute(
                """UPDATE browser_accounts
                   SET label = ?, color = ?, notes = ?, is_default = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    new_label,
                    new_color,
                    new_notes,
                    1 if new_default else 0,
                    now,
                    account_id,
                ),
            )
            conn.commit()
        return BrowserAccount(
            id=account.id,
            label=new_label,
            domain=account.domain,
            color=new_color,
            notes=new_notes,
            is_default=new_default,
            created_at=account.created_at,
            updated_at=now,
        )

    def delete_account(self, account_id: str, delete_credentials: bool = True) -> bool:
        """删除账号（及其命名 vault 凭据）；返回是否确有删除。

        若该账号正被某浏览器激活，尽力清空该浏览器中该域名的登录态
        （cookie + localStorage），避免"账号已删、浏览器仍在线"。
        """
        account = self.get_account(account_id)
        if account is None:
            return False
        # 先处理激活中的浏览器会话（尽力而为，不阻断删除）
        with self._lock:
            active_browsers = [
                browser_id
                for browser_id, active_id in self._active.items()
                if active_id == account_id
            ]
        if active_browsers:
            self._clear_active_browser(account, active_browsers)
        with _SQLITE_LOCK:
            conn = self._conn()
            conn.execute("DELETE FROM browser_accounts WHERE id = ?", (account_id,))
            conn.commit()
        if delete_credentials:
            try:
                from backend.tools.credential_vault import delete_credential

                delete_credential(account.domain, account_id=account_id)
            except Exception:  # noqa: BLE001 — 凭据清理失败不阻断注册表删除
                logger.warning("删除账号凭据失败: %s", account_id, exc_info=True)
        with self._lock:
            for browser_id, active_id in list(self._active.items()):
                if active_id == account_id:
                    del self._active[browser_id]
        return True

    def _clear_active_browser(
        self, account: BrowserAccount, browser_ids: List[str]
    ) -> None:
        """尽力清空激活该账号的浏览器中的 cookie（浏览器级）与域名 localStorage。"""
        import contextlib

        from backend.tools.browser_cdp import BrowserCDPError, cdp_command, get_browser_manager

        manager = get_browser_manager()
        for browser_id in browser_ids:
            with contextlib.suppress(BrowserCDPError):
                session = manager.get(browser_id)
                if session is None:
                    continue
                cdp_command(session, "Network.clearBrowserCookies", {})
                self._clear_open_page_storage(session, account.domain)

    # ── 激活状态追踪 ──────────────────────────────────────────

    def get_active_account(self, browser_id: str) -> Optional[BrowserAccount]:
        """返回某浏览器当前激活的账号（进程内追踪）。"""
        with self._lock:
            account_id = self._active.get(browser_id or "")
        if not account_id:
            return None
        return self.get_account(account_id)

    # ── 切换编排 ──────────────────────────────────────────────

    def switch_account(
        self,
        target_account_id: str,
        browser_id: Optional[str] = None,
        owner: str = "",
    ) -> SwitchResult:
        """切换到目标账号：快照当前 → 清空 → 注入目标 → 刷新。

        ``browser_id=None`` 时：``owner`` 非空按该聊天会话的归属解析，空则
        解析唯一用户会话（设置页等无上下文调用方的旧语义）。
        切换失败时尽力回滚到切换前快照。
        """
        from backend.tools.browser_cdp import BrowserCDPError, get_browser_manager
        from backend.tools.credential_vault import (
            load_credential,
            load_storage_origins,
        )

        account = self.get_account(target_account_id)
        if account is None:
            return SwitchResult(
                ok=False,
                message=f"账号 {target_account_id!r} 不存在",
            )
        manager = get_browser_manager()
        try:
            if browser_id:
                session = manager.require(browser_id, owner=owner)
            elif owner:
                session = manager.resolve_owned(owner)
            else:
                session = manager.get(None)
        except BrowserCDPError:
            return SwitchResult(
                ok=False,
                account_id=account.id,
                label=account.label,
                domain=account.domain,
                message="浏览器未运行：请先打开浏览器（browser_launch / browser_login）",
            )
        if session is None:
            return SwitchResult(
                ok=False,
                account_id=account.id,
                label=account.label,
                domain=account.domain,
                message="未找到唯一活动的浏览器会话，请显式指定 browser_id",
            )

        # 1. 快照当前激活账号状态（失败不阻断切换，仅告警）
        current_id = self._active.get(session.browser_id)
        snapshot_error = ""
        if current_id and current_id != account.id:
            try:
                self.snapshot_account_state(current_id, session)
            except Exception as exc:  # noqa: BLE001 — 快照失败不阻断切换
                snapshot_error = str(exc)[:200]
                logger.warning("切换前快照失败: %s", exc, exc_info=True)

        # 2. 解析目标凭据
        try:
            cookies = load_credential(
                account.domain, account_id=self._vault_account_id(account)
            ) or []
            origins = load_storage_origins(
                account.domain, account_id=self._vault_account_id(account)
            )
        except Exception as exc:  # noqa: BLE001 — 凭据解密失败按空处理
            logger.warning("读取目标账号凭据失败: %s", exc, exc_info=True)
            cookies, origins = [], []

        # 3. 清空 + 注入（失败则用切换前快照回滚浏览器状态）
        swapped: List[str] = []
        try:
            swapped = self._apply_state(session, account, cookies, origins)
        except Exception as exc:  # noqa: BLE001 — 注入失败尝试回滚
            logger.warning("账号状态注入失败: %s", exc, exc_info=True)
            rollback_ok = self._rollback_to_account(current_id, session)
            message = f"账号状态注入失败：{str(exc)[:200]}"
            if current_id and not rollback_ok:
                message += "；浏览器可能已处于登出状态，请重新切换或登录"
            return SwitchResult(
                ok=False,
                account_id=account.id,
                label=account.label,
                domain=account.domain,
                message=message,
            )

        # 4. 追踪激活状态
        with self._lock:
            self._active[session.browser_id] = account.id

        message = f"已切换到「{account.label}」（{account.domain}）"
        if not cookies:
            message += "；该账号暂无存储凭据，请先登录"
        if snapshot_error:
            message += f"；切换前快照失败：{snapshot_error}"
        return SwitchResult(
            ok=True,
            account_id=account.id,
            label=account.label,
            domain=account.domain,
            swapped_domains=swapped,
            message=message,
        )

    @staticmethod
    def _vault_account_id(account: BrowserAccount) -> Optional[str]:
        """默认账号 → vault 平铺 key（None）；命名账号 → account.id。"""
        return None if account.is_default else account.id

    def _rollback_to_account(self, account_id: Optional[str], session: Any) -> bool:
        """切换失败回滚：从 vault 用切换前账号快照把浏览器状态重新注入。

        返回是否回滚成功；失败尽力而为（不抛，调用方据此提示用户）。
        """
        if not account_id:
            return False
        import contextlib

        from backend.tools.credential_vault import load_credential, load_storage_origins

        account = self.get_account(account_id)
        if account is None:
            return False
        try:
            cookies = (
                load_credential(account.domain, account_id=self._vault_account_id(account))
                or []
            )
            origins = load_storage_origins(
                account.domain, account_id=self._vault_account_id(account)
            )
            with contextlib.suppress(Exception):  # 回滚尽力而为
                self._apply_state(session, account, cookies, origins)
            return True
        except Exception:  # noqa: BLE001 — 回滚失败不覆盖原始错误
            logger.warning("账号切换回滚失败: %s", account_id, exc_info=True)
            return False

    def resolve_vault_account_id(self, account_id: Optional[str]) -> Optional[str]:
        """把账号注册表 ID 解析为 vault 维度 ID（默认账号 → None）。

        供 web_fetch / download 等凭据消费方使用：它们拿到的是账号 UUID，
        需要转成 vault 的 ``account_id`` 参数口径。未知账号按命名账号原样
        返回（让下游走 ``domain::id`` 查找，找不到自然 not_found）。
        """
        account_id = (account_id or "").strip() or None
        if not account_id:
            return None
        account = self.get_account(account_id)
        if account is None:
            return account_id
        return self._vault_account_id(account)

    def snapshot_account_state(
        self, account_id: str, session: Any = None
    ) -> List[str]:
        """把浏览器当前 cookie/localStorage 快照保存回指定账号。

        返回被保存的 cookie domain 列表；无浏览器 / 无 cookie 返回空列表。
        """
        from backend.tools.browser_cdp import BrowserCDPError, cdp_command, get_browser_manager
        from backend.tools.credential_vault import (
            cookie_domain_matches,
            save_credential,
            save_storage_state,
        )

        account = self.get_account(account_id)
        if account is None:
            return []
        if session is None:
            try:
                session = get_browser_manager().get(None)
            except BrowserCDPError:
                return []
        if session is None:
            return []

        try:
            result = cdp_command(session, "Storage.getCookies", {})
        except BrowserCDPError:
            return []
        raw_cookies = result.get("cookies") or []

        # 只保存归属该账号 domain 的 cookie（含跨子域认证 cookie）
        account_bare = account.domain.lstrip(".")
        allowed: List[Dict[str, Any]] = []
        for item in raw_cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cdomain = str(item.get("domain") or "").lower()
            if not cdomain:
                continue
            bare = cdomain.lstrip(".")
            if (
                cookie_domain_matches(bare, account.domain)
                or cookie_domain_matches(account_bare, cdomain)
                or bare == account_bare
                or bare.endswith("." + account_bare)
            ):
                allowed.append(item)
        if not allowed:
            return []

        origins = self._capture_open_page_storage(session, account.domain)
        saved: List[str] = []
        try:
            if origins:
                save_storage_state(
                    account.domain,
                    allowed,
                    origins,
                    account_id=self._vault_account_id(account),
                )
            else:
                save_credential(
                    account.domain,
                    allowed,
                    account_id=self._vault_account_id(account),
                )
            saved.append(account.domain)
        except Exception:  # noqa: BLE001 — 单个账号保存失败不阻断
            logger.warning("账号快照保存失败: %s", account_id, exc_info=True)
        return saved

    def _capture_open_page_storage(
        self, session: Any, domain: str
    ) -> List[Dict[str, Any]]:
        """读取当前浏览器所有 http(s) 页面的 localStorage，过滤归属 domain 的 origin。"""
        from backend.tools.browser_cdp import BrowserCDPError, cdp_command

        try:
            targets = cdp_command(session, "Target.getTargets", {})
        except BrowserCDPError:
            return []
        origins: List[Dict[str, Any]] = []
        seen: set = set()
        for info in targets.get("targetInfos") or []:
            if not isinstance(info, dict) or info.get("type") != "page":
                continue
            url = str(info.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            origin = self._origin_of(url)
            if not origin or origin in seen:
                continue
            if not self._origin_belongs(origin, domain):
                continue
            seen.add(origin)
            storage = self._read_page_local_storage(session, str(info.get("targetId") or ""))
            if storage:
                origins.append({"origin": origin, "localStorage": storage})
        return origins

    def _apply_state(
        self,
        session: Any,
        account: BrowserAccount,
        cookies: List[Dict[str, Any]],
        origins: List[Dict[str, Any]],
    ) -> List[str]:
        """清空浏览器状态 → 注入目标账号 cookie/localStorage → 刷新页面。"""
        from backend.tools.browser_cdp import cdp_command
        from backend.tools.credential_vault import normalize_cookie_for_cdp

        # 清空所有 cookie（浏览器级）
        cdp_command(session, "Network.clearBrowserCookies", {})

        # 注入 cookie（浏览器级 Storage.setCookies）
        cdp_cookies = [
            normalize_cookie_for_cdp(c)
            for c in cookies
            if isinstance(c, dict) and c.get("name") and c.get("domain")
        ]
        if cdp_cookies:
            cdp_command(session, "Storage.setCookies", {"cookies": cdp_cookies})

        # 清空所有页面 localStorage 后注入目标账号快照
        # 只清/刷新归属账号 domain 的页面：无关站点的 localStorage 与标签页
        # 不受影响（cookie 仍按设计浏览器级清空——同一时刻只携带一个账号态）。
        self._clear_open_page_storage(session, account.domain)
        for origin_item in origins:
            origin = str(origin_item.get("origin") or "")
            storage = origin_item.get("localStorage") or {}
            if not origin or not isinstance(storage, dict):
                continue
            self._write_origin_local_storage(session, origin, storage)

        self._reload_pages(session, account.domain)
        return [account.domain]

    def _clear_open_page_storage(self, session: Any, domain: str) -> None:
        from backend.tools.browser_cdp import BrowserCDPError, cdp_command

        try:
            targets = cdp_command(session, "Target.getTargets", {})
        except BrowserCDPError:
            return
        clear_js = "(function(){try{window.localStorage.clear();}catch(e){}return ''})()"
        for info in targets.get("targetInfos") or []:
            if not isinstance(info, dict) or info.get("type") != "page":
                continue
            url = str(info.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            origin = self._origin_of(url)
            if not origin or not self._origin_belongs(origin, domain):
                continue
            try:
                cdp_command(
                    session,
                    "Runtime.evaluate",
                    {"expression": clear_js, "returnByValue": True},
                    target_id=str(info.get("targetId") or ""),
                )
            except BrowserCDPError:
                continue

    def _write_origin_local_storage(
        self, session: Any, origin: str, storage: Dict[str, str]
    ) -> None:
        """把 origin 的 localStorage 快照写入一个同 origin 页面（无则跳过）。"""
        import json as _json

        from backend.tools.browser_cdp import BrowserCDPError, cdp_command

        try:
            targets = cdp_command(session, "Target.getTargets", {})
        except BrowserCDPError:
            return
        for info in targets.get("targetInfos") or []:
            if not isinstance(info, dict) or info.get("type") != "page":
                continue
            url = str(info.get("url") or "")
            if self._origin_of(url) != origin:
                continue
            # 通过 JSON 字面量注入，避免拼接转义问题
            items_json = _json.dumps(storage, ensure_ascii=False)
            js = (
                "(function(){try{var items=" + items_json + ";"
                "for(var k in items){window.localStorage.setItem(k, items[k]);}"
                "return '';}catch(e){return ''}})()"
            )
            try:
                cdp_command(
                    session,
                    "Runtime.evaluate",
                    {"expression": js, "returnByValue": True},
                    target_id=str(info.get("targetId") or ""),
                )
            except BrowserCDPError:
                continue
            return

    def _reload_pages(self, session: Any, domain: str) -> None:
        from backend.tools.browser_cdp import BrowserCDPError, cdp_command

        try:
            targets = cdp_command(session, "Target.getTargets", {})
        except BrowserCDPError:
            return
        for info in targets.get("targetInfos") or []:
            if not isinstance(info, dict) or info.get("type") != "page":
                continue
            url = str(info.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            origin = self._origin_of(url)
            if not origin or not self._origin_belongs(origin, domain):
                continue
            try:
                cdp_command(
                    session,
                    "Page.reload",
                    {"ignoreCache": False},
                    target_id=str(info.get("targetId") or ""),
                )
            except BrowserCDPError:
                continue

    def _read_page_local_storage(self, session: Any, target_id: str) -> Dict[str, str]:
        import json as _json

        from backend.tools.browser_cdp import BrowserCDPError, cdp_command

        if not target_id:
            return {}
        js = (
            "(function(){try{var out={};var ls=window.localStorage;"
            "for(var i=0;i<ls.length;i++){var k=ls.key(i);out[k]=ls.getItem(k);}"
            "return JSON.stringify(out);}catch(e){return ''}})()"
        )
        try:
            result = cdp_command(
                session,
                "Runtime.evaluate",
                {"expression": js, "returnByValue": True},
                target_id=target_id,
            )
        except BrowserCDPError:
            return {}
        value = (result.get("result") or {}).get("value")
        if not isinstance(value, str) or not value:
            return {}
        try:
            parsed = _json.loads(value)
        except ValueError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str) and v != ""}

    @staticmethod
    def _origin_of(url: str) -> str:
        from urllib.parse import urlsplit

        try:
            parts = urlsplit(url)
        except ValueError:
            return ""
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        if scheme not in ("http", "https") or not host:
            return ""
        port = parts.port
        if port and not (
            (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        ):
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"

    @staticmethod
    def _origin_belongs(origin: str, domain: str) -> bool:
        from urllib.parse import urlsplit

        from backend.tools.credential_vault import cookie_domain_matches

        try:
            host = (urlsplit(origin).hostname or "").lower()
        except ValueError:
            return False
        if not host:
            return False
        bare = (domain or "").strip().lower().lstrip(".")
        return (
            cookie_domain_matches(host, domain)
            or host == bare
            or host.endswith("." + bare)
        )


#: 进程级单例（后台 API / 工具共享激活状态追踪）
browser_account_service = BrowserAccountService()


__all__ = [
    "BrowserAccount",
    "BrowserAccountService",
    "SwitchResult",
    "browser_account_service",
]
