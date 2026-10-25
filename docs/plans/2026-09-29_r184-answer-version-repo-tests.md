# R184 — `backend/data/answer_version_repo.py` 单元测试（376 行，此前零覆盖）

## 背景

回答版本仓储（重新生成时旧回答整轮归档/切换恢复）没有任何测试。本轮
补齐，不改生产代码。

## 方案

- conftest autouse `setup_test_db` 提供真实临时库；SessionRepository /
  MessageRepository 造真实数据（FK 完整），不 mock SQL。
- 覆盖：turn 边界判定（锚点缺失/非最后一轮/正常）、last_user_message_id、
  list_versions 排序与 current_index、archive_turn（归档行数/消息行删除/
  message_count 回减/事件双写）、activate（新 id 恢复/当前回答再归档/
  版本行删除/未知版本 raise）、regenerate_excluded_ids、drop_excluded
  （行 .id 与事件 payload.id 两种形态）、_preview 截断、
  ArchiveOnFirstSave（首存归档一次 + 归档失败不阻断落库）。

## 验证

- `pytest tests/unit/data/test_answer_version_repo.py`
- 仓库根 `ruff check` + `ruff format`；py38 hazard 扫描

纯测试新增，无生产代码改动，不需要 win7 cherry-pick。
