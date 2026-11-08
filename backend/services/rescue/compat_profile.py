"""兼容档位（安全模式）持久化。

``compat.json`` 是机器本地状态（不进用户配置、不跨设备同步），Electron / CLI 共享 schema：

- ``schema``：整数版本号（当前 1）
- ``level``：0-3（L0=正常，L1=保守渲染，L2=最小窗口，L3=实验单进程）
- ``flags``：Chromium 开关列表（仅由 Electron 消费）
- ``app``：应用功能裁剪开关（petWindow/previewHost/browserBridge/updateCheck）
- ``reason``：最近一次档位变化的原因
- ``updatedAt``：最近一次档位变化的时间（ISO 8601 UTC）

本模块提供纯函数 + IO 函数；Electron 与 CLI 各用其纯函数部分保证行为一致。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from backend.services.rescue.paths import compat_profile_path

logger = logging.getLogger(__name__)

#: schema 版本号（变更时同步更新两端读写代码）
CURRENT_SCHEMA = 1

#: 档位范围
LEVEL_MIN = 0
LEVEL_MAX = 3

#: 各档位的 Chromium 开关（追加到现有 Win7 flags 之上）
LEVEL_FLAGS: Dict[int, tuple] = {
    0: (),
    1: (
        "disable-gpu-compositing",
        "disable-accelerated-2d-canvas",
    ),
    2: (
        "disable-gpu-compositing",
        "disable-accelerated-2d-canvas",
        "disable-site-isolation-trials",
    ),
    3: (
        "disable-gpu-compositing",
        "disable-accelerated-2d-canvas",
        "disable-site-isolation-trials",
        "single-process",
    ),
}

#: 各档位的应用功能裁剪
LEVEL_APP_FEATURES: Dict[int, Dict[str, bool]] = {
    0: {"petWindow": True, "previewHost": True, "browserBridge": True, "updateCheck": True},
    1: {"petWindow": False, "previewHost": False, "browserBridge": True, "updateCheck": True},
    2: {"petWindow": False, "previewHost": False, "browserBridge": False, "updateCheck": True},
    3: {"petWindow": False, "previewHost": False, "browserBridge": False, "updateCheck": False},
}


def new_profile(*, level: int = 0, reason: str = "") -> Dict[str, Any]:
    """构造默认兼容档位。"""
    if not (LEVEL_MIN <= level <= LEVEL_MAX):
        raise ValueError(f"level 必须在 {LEVEL_MIN}-{LEVEL_MAX} 之间，收到: {level}")
    return {
        "schema": CURRENT_SCHEMA,
        "level": level,
        "flags": list(LEVEL_FLAGS[level]),
        "app": dict(LEVEL_APP_FEATURES[level]),
        "reason": reason,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def bump_level(current: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    """档位 +1（上限 LEVEL_MAX）。不修改入参。"""
    next_level = min(LEVEL_MAX, (current.get("level") or 0) + 1)
    bumped = new_profile(level=next_level, reason=reason)
    bumped["stableBoots"] = current.get("stableBoots", 0)
    return bumped


def reset_level(*, reason: str = "") -> Dict[str, Any]:
    """回到 L0。"""
    return new_profile(level=0, reason=reason)


def read_profile(user_data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """读取兼容档位；文件不存在或 schema 不兼容时返回默认 L0。"""
    path = compat_profile_path(user_data_dir)
    if not path.is_file():
        return new_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return new_profile()
    if not isinstance(data, dict) or data.get("schema") != CURRENT_SCHEMA:
        return new_profile()
    level = data.get("level")
    if not isinstance(level, int) or not (LEVEL_MIN <= level <= LEVEL_MAX):
        return new_profile()
    return data


def write_profile(
    profile: Dict[str, Any], user_data_dir: Optional[Path] = None
) -> Path:
    """写入兼容档位；自动创建父目录，并使用临时文件原子替换。"""
    path = compat_profile_path(user_data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def set_level(
    level: int,
    *,
    reason: str = "",
    user_data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """设置档位并持久化。返回新 profile。"""
    profile = new_profile(level=level, reason=reason)
    write_profile(profile, user_data_dir)
    return profile


def effective_flags(profile: Dict[str, Any]) -> list:
    """返回当前档位应追加的 Chromium 开关。"""
    level = profile.get("level", 0)
    return list(LEVEL_FLAGS.get(level, ()))


def effective_app_features(profile: Dict[str, Any]) -> Dict[str, bool]:
    """返回当前档位的应用功能裁剪开关。"""
    level = profile.get("level", 0)
    return dict(LEVEL_APP_FEATURES.get(level, LEVEL_APP_FEATURES[0]))
