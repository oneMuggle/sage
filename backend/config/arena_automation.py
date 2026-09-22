"""Configuration model for the arena automation feature.

Nested sub-models (registration / draw / proxy / token_window) map 1:1 to the
``arena_automation.yaml`` sections. Every sub-model forbids unknown keys: a
typo must degrade the whole config to "disabled defaults" at load time (see
``load_arena_config``), never fail open.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

#: Default config file, next to config.yaml in backend/config/
DEFAULT_CONFIG_PATH = Path(__file__).parent / "arena_automation.yaml"


class _StrictModel(BaseModel):
    """Base: unknown keys are rejected so typos degrade instead of failing open."""

    class Config:  # Pydantic v1 compat — also works in v2
        extra = "forbid"


class RegistrationConfig(_StrictModel):
    """Batch account registration (plan §5.8)."""

    enabled: bool = False
    concurrency: int = Field(default=3, ge=1, le=10)
    mail_timeout_sec: int = 90
    domains: List[str] = Field(default_factory=list)


class DrawConfig(_StrictModel):
    """Automated draw loop (plan §2.2/§2.3/§5.8, P4)."""

    enabled: bool = False
    keep_pattern: str = ""
    require_reasoning: bool = False
    #: 命中失败时的动作：archive(归档) / delete(删号) / keep(保留继续用)
    miss_action: str = "archive"
    #: 429 阶梯到该档（或命中 CF）就中止本轮换 IP；None = 不换
    switch_level: Optional[int] = None
    #: 抽卡线程等 token 窗口出新票的上限（秒）；超时本轮失败「token 窗口不可用」
    token_wait_sec: float = Field(default=8.0, ge=0.5, le=120.0)
    #: 全局最小建会话间隔（秒），所有账号共用（§2.3 双层节奏）
    base_gap_sec: float = Field(default=2.0, ge=0.0, le=300.0)
    #: reCAPTCHA 全局拒绝数达到阈值 → 熔断冷却 + 建议 token 窗口换 IP（纪律 10）
    reject_threshold: int = Field(default=10, ge=1, le=1000)
    #: 熔断冷却时长（秒）
    cooldown_sec: float = Field(default=120.0, ge=1.0, le=3600.0)


class ProxyConfig(_StrictModel):
    """Proxy pool / dynamic-proxy API for arena traffic (plan §5.6)."""

    enabled: bool = False
    api_url: str = ""
    api_token: str = ""
    pool_text: str = ""
    rotation: str = "per_account"
    protocol: str = "http"
    country: str = ""
    order: str = "sequential"


class TokenWindowConfig(_StrictModel):
    """Token age gate before rotating an account (P3)."""

    enabled: bool = False
    max_age_sec: float = 110.0
    use_proxy: bool = False
    #: 隐藏窗口轮询 state 的间隔（秒）；取票等待 <3s 依赖窗口 warm mint
    poll_interval_sec: float = Field(default=2.0, ge=0.5, le=60.0)


class ArenaAutomationConfig(_StrictModel):
    """All values read from arena_automation.yaml at startup."""

    enabled: bool = False
    max_accounts: int = Field(default=5, ge=1, le=20)
    max_concurrent_sessions: int = Field(default=2, ge=1, le=10)
    mail_provider: str = "tenminmail"
    mail_api_key: Optional[str] = None
    account_idle_timeout_sec: int = 300
    probe_evidence_cap: int = 500
    failure_isolation_threshold: int = 3
    manual_captcha_timeout_sec: int = 180
    probe_backend: str = "python"  # "python" or "node"
    #: 运行时数据目录（注册 job 导出文件等）；空 = 系统临时目录
    data_dir: str = ""

    registration: RegistrationConfig = Field(default_factory=RegistrationConfig)
    draw: DrawConfig = Field(default_factory=DrawConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    token_window: TokenWindowConfig = Field(default_factory=TokenWindowConfig)


def load_arena_config(path: Optional[Path] = None) -> ArenaAutomationConfig:
    """Read arena_automation.yaml; any failure falls back to defaults (disabled).

    Fail-safe by design: a malformed config file must never block backend
    startup, and the feature must stay off unless explicitly enabled. Unknown
    keys / out-of-range values raise ValidationError under ``extra=forbid``
    and degrade exactly the same way.
    """
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return ArenaAutomationConfig()
    except OSError as exc:
        logger.warning("arena_automation.yaml 读取失败（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()
    except yaml.YAMLError as exc:
        logger.warning("arena_automation.yaml 解析失败（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()
    if not isinstance(raw, dict):
        logger.warning("arena_automation.yaml 顶层不是映射（使用默认配置）")
        return ArenaAutomationConfig()
    try:
        return ArenaAutomationConfig(**raw)
    except ValidationError as exc:
        logger.warning("arena_automation.yaml 字段非法（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()


#: Backwards-compatible alias (P0 name, still used by main.py lifespan).
load_arena_automation_config = load_arena_config
