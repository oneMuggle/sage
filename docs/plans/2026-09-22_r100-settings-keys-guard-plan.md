# R100 批次计划 —— SettingsRepository KEYS 白名单守卫（AST 静态扫描测试）

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r100-keys-guard`（基于 origin/main 54af0ee0）

## 背景

R94 复盘的 Zotero 断链（#1377）根因之一：`zotero_db_path` 未入
`SettingsRepository.KEYS` 白名单 —— `set()` 抛 ValueError 被路由吞掉、
`get()` 静默返回 None，配置写入假成功。总账（r99）建议增加 fail-fast
守卫，本批落地为**守卫测试**（不改生产代码）。

## 批次内容

新增 `backend/tests/unit/test_settings_keys_guard.py`（3 用例）：

1. `test_settings_keys_all_in_whitelist` —— AST 全仓扫描 backend 生产代码
   （排除 tests/），追踪 `x = SettingsRepository()` 赋值变量上的
   `.get/.set/.get_json/.set_json` 字符串字面量键，断言全部入白名单；
   违规时 fail 消息直接列出文件与缺失键清单。
2. `test_known_keys_present_in_whitelist` —— 历史踩坑键抽样回归
   （zotero_db_path / app_settings / permission_mode）。
3. `test_unknown_key_get_returns_none_and_set_raises` —— 锁定白名单语义
   本身（未收录键 get→None、set→ValueError），作为守卫存在依据。

注意：变量追踪只认 `SettingsRepository()` 直接实例化赋值 —— `repo` 等
通用名被 agent/run/project 仓储复用，按名追踪会大量误报（本批实测修正）。

## 验证矩阵

- 本机独立脚本（纯 stdlib 复刻扫描逻辑）验证：全仓仅发现 3 个设置键
  （app_settings / network_policy / zotero_db_path），均在白名单内 → CI 绿。
- py_compile + CI 同款 ruff 0.4.4 全过（UP038/PT011 已修）。
- 完整 pytest 走 CI Backend job。

## 不做

- 不改生产代码；KEYS 白名单启动期运行时校验（需 import 全路由面）暂缓，
  AST 守卫已覆盖同一风险面且零成本。
