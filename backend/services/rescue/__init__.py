"""Sage Rescue —— 通用自检修基础设施（不依赖前端/renderer）。

本包提供：

- :mod:`.paths`：userData / DB / diagnostics / backups 路径解析（与 ``electron/userDataPaths.ts``
  保持同语义）。
- :mod:`.config_wizard`：端点/模型配置的读写向导，复用 ``SettingsRepository`` 与 SecretBox，
  写前备份、写后校验、写后同步 catalog。
- :mod:`.support_bundle`：不依赖后端的诊断包打包（含日志、崩溃 journal、doctor 报告、脱敏配置摘要）。
- :mod:`.compat_profile`：兼容档位（L0–L3）持久化，Electron / CLI 共享 schema。
- :mod:`.security_software`：遗留管控软件的识别与处置（停止/禁用/修改配置/绕过），按风险分级。
- :mod:`.repair`：缓存/窗口/孤儿端口/损坏配置/日志/DB 的安全修复动作。
- :mod:`.allowlist`：给 IT 的放行清单生成。

设计原则：

- 所有模块**只依赖 stdlib + 项目内模块**，不依赖 Electron/uvicorn。
- 所有修改动作先备份、全程审计、可回滚、可幂等。
- 输出默认脱敏；需要明文时显式 ``include_secrets=True`` 并警告。
"""
from __future__ import annotations
