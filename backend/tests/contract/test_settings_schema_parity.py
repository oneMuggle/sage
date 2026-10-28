"""Settings schema parity contract tests.

跨边界契约校验: 后端 canonicalizer 的 ALIASES / LEGAL_*_KEYS 与前端
src/entities/setting/types.ts AppSettings 类型定义一致.

目的: 新增 AppSettings 字段时, 忘记同步 LEGAL_*_KEYS 或 ALIASES 时,
pytest 立刻失败, 防止前后端 drift.

参考:
- src/entities/setting/types.ts: AppSettings / EndpointConfig / ModelSelection
- backend/data/settings_canonicalizer.py: ALIASES / LEGAL_*_KEYS
"""

from __future__ import annotations

import re

import pytest

from backend.data.settings_canonicalizer import (
    ALIASES,
    LEGAL_DISCOVERED_MODEL_KEYS,
    LEGAL_ENDPOINT_KEYS,
    LEGAL_MODEL_SELECTION_KEYS,
    LEGAL_MODEL_SELECTIONS_KEYS,
    LEGAL_ORCH_KEYS,
    LEGAL_TOP_KEYS,
    LEGAL_WIKI_KEYS,
    from_camel,
    to_camel,
)

# 前端 AppSettings 顶层字段 (camelCase).
# 修改 src/entities/setting/types.ts:AppSettings 时必须同步 LEGAL_TOP_KEYS.
EXPECTED_TOP_KEYS = frozenset(
    {
        "streaming",
        "autoMemory",
        "autoContext",  # Task 5 (2026-09-15): context window resolver toggle
        # 2026-10-28: 输出长度上限（单次回答最大生成 token 数）
        "maxOutputTokens",
        "confirmDelete",
        "endpoints",
        "modelSelections",
        "maxContext",
        "temperature",
        "timezone",  # Task 1 (2026-08-23): IANA timezone, 默认 Asia/Shanghai
        "logTimezone",  # 2026-09-17: 日志时间戳时区 ('UTC' | 'local' | IANA)
        "wiki",
        "version",
        "orch",
        # 2026-10-21: LLM 自动重试参数 — 前端用户配置必须透传, 否则 sanitizeForBackend
        # 丢弃后后端永远用默认值 (max_attempts=3, base_delay=1.0, max_delay=15.0).
        "llmRetryMaxAttempts",
        "llmRetryBaseDelayS",
        "llmRetryMaxDelayS",
        # 2026-10-22: 整轮任务 wall-clock 上限（秒）— 0 = 不限；函数式读取
        "llmTotalTimeoutS",
        # 2026-10-27: 会话标题生成专用模型 id（顶层扁平键）
        "titleModelId",
        # 2026-10-28: LLM 代理上游超时（秒）— 替代 llm_proxy_routes 硬编码 60s。
        "llmProxyTimeoutS",
    }
)


def test_legal_top_keys_matches_appsettings_interface() -> None:
    """LEGAL_TOP_KEYS 必须与 AppSettings 顶层字段 1:1 对齐."""
    assert LEGAL_TOP_KEYS == EXPECTED_TOP_KEYS


def test_legal_endpoint_keys_is_stable() -> None:
    """LEGAL_ENDPOINT_KEYS 是 EndpointConfig 9 字段 (含 Task 1 新增 protocol / modelId / localModelPath)."""
    assert (
        frozenset(
            {
                "id",
                "name",
                "baseUrl",
                "apiKey",
                "protocol",
                "modelId",
                "localModelPath",
                "discoveredModels",
                "lastDiscoveredAt",
            }
        )
        == LEGAL_ENDPOINT_KEYS
    )


def test_legal_model_selection_keys_is_stable() -> None:
    """LEGAL_MODEL_SELECTION_KEYS 是 ModelSelection 2 字段."""
    assert frozenset({"endpointId", "modelId"}) == LEGAL_MODEL_SELECTION_KEYS


def test_legal_discovered_model_keys_is_stable() -> None:
    """LEGAL_DISCOVERED_MODEL_KEYS 是 DiscoveredModel 3 字段."""
    assert (
        frozenset(
            {
                "id",
                "capabilities",
                "endpointId",
            }
        )
        == LEGAL_DISCOVERED_MODEL_KEYS
    )


def test_legal_wiki_keys_is_stable() -> None:
    """LEGAL_WIKI_KEYS 是 WikiSettings 1 字段."""
    assert frozenset({"useFolderPicker"}) == LEGAL_WIKI_KEYS


def test_legal_model_selections_obj_keys_is_stable() -> None:
    """LEGAL_MODEL_SELECTIONS_KEYS 是 modelSelections 对象 6 子字段."""
    assert (
        frozenset(
            {
                "chatModel",
                "visionModel",
                "embeddingModel",
                "ttsModel",
                "asrModel",
                "imageGenModel",
            }
        )
        == LEGAL_MODEL_SELECTIONS_KEYS
    )


def test_legal_orch_keys_is_stable() -> None:
    """LEGAL_ORCH_KEYS 必须与前端 OrchSettings interface 23 键逐字同步.

    历史事故两次: 2026-09 漏 worktreeIsolation / subagentApprovalMode /
    runTokenBudget, RD15 后又漏 runWallClockLimitMinutes /
    subagentTaskTimeoutS / maxRetryOfChains, 均导致编排段任一保存 400
    且被前端静默吞掉。Round 3 (2026-09-19) 补计划前置开关
    planPreflightEnabled / planScoutEnabled。2026-10-27 补 maxToolCallsPerRun
    (同款回归: UI/OrchSettings 已有, 白名单漏加) 与 Scout/Planner 迭代预算
    maxScoutIterations / maxPlannerIterations。新增 orch 键时此处与
    canonicalizer 必须同改。
    """
    assert frozenset(
        {
            "maxConcurrentSubagents",
            "maxAggregateChars",
            "maxSubagentResultChars",
            "maxRetries",
            "maxLaneIterations",
            "maxSubagentIterations",
            "worktreeIsolation",
            "subagentApprovalMode",
            "runTokenBudget",
            "scratchRoot",
            "planPreflightEnabled",
            "planScoutEnabled",
            "runWallClockLimitMinutes",
            "subagentTaskTimeoutS",
            "maxRetryOfChains",
            # win7 专属: profile 迭代上限四键已在 OrchSettings, 必须白名单同步
            "maxPrimaryIterations",
            "maxCoderIterations",
            "maxReviewerIterations",
            "maxWriterIterations",
            # 2026-10-20 全局迭代上限 (Win7 适配: 0=按各 agent 分别设置)
            "maxIterations",
            # 2026-10-27 工具预算 + 计划前置/Planner 迭代预算
            "maxToolCallsPerRun",
            "maxScoutIterations",
            "maxPlannerIterations",
        }
    ) == LEGAL_ORCH_KEYS


def test_aliases_camel_side_subset_of_legal_keys() -> None:
    """ALIASES 翻译后的每个 camelCase 字段必须出现在某个 LEGAL_*_KEYS 里.

    否则 validate_settings_shape 会拒收合法的翻译结果.
    """
    all_legal_camel = (
        LEGAL_TOP_KEYS
        | LEGAL_ENDPOINT_KEYS
        | LEGAL_MODEL_SELECTION_KEYS
        | LEGAL_MODEL_SELECTIONS_KEYS
        | LEGAL_DISCOVERED_MODEL_KEYS
        | LEGAL_WIKI_KEYS
        # 2026-09 修复: orch 子层键进入 ALIASES (worktree_isolation 等),
        # 并集必须包含 LEGAL_ORCH_KEYS, 否则合法翻译被判为非法。
        | LEGAL_ORCH_KEYS
    )
    aliases_camel_side = frozenset(ALIASES.values())
    missing = aliases_camel_side - all_legal_camel
    assert not missing, f"ALIASES camel side not in LEGAL_*_KEYS: {missing}"


def test_legal_keys_survive_relay_snake_roundtrip() -> None:
    """白名单里的多词 camel 键必须在 ALIASES 有 snake 别名.

    Electron relay 的 ``camelToSnakeKeys``（electron/invoke.ts）把前端
    camelCase 键整体转 snake 后再 POST/PUT；后端 ``to_camel`` 只认
    ``ALIASES`` 里显式登记的 snake→camel 对。缺别名时键翻不回 camel，
    ``validate_settings_shape`` 报 400，而前端 ``saveSettings`` 的
    ``catch {}`` 会静默吞掉 —— 用户看到"改了没生效"。

    历史事故（2026-10-27）：``maxIterations`` / ``logTimezone`` /
    ``useFolderPicker`` 三键漏加别名。编排 Tab 每次保存都整体 spread 提交
    orch 段（含 maxIterations），故编排段任一保存必 400，两个新增的迭代
    预算旋钮也因此无法落库。本守卫把"漏加即回归"变成机械可检。
    """

    def snake(key: str) -> str:
        return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), key)

    for legal in (
        LEGAL_TOP_KEYS,
        LEGAL_ENDPOINT_KEYS,
        LEGAL_MODEL_SELECTION_KEYS,
        LEGAL_MODEL_SELECTIONS_KEYS,
        LEGAL_DISCOVERED_MODEL_KEYS,
        LEGAL_WIKI_KEYS,
        LEGAL_ORCH_KEYS,
    ):
        missing = {k for k in legal if snake(k) != k and snake(k) not in ALIASES}
        assert not missing, f"缺 snake 别名（relay 往返后 400）: {sorted(missing)}"


def test_aliases_is_bijective() -> None:
    """ALIASES 双向无冲突: 没有 2 个不同 snake 映射到同一 camel."""
    camels = list(ALIASES.values())
    assert len(camels) == len(set(camels))


def test_aliases_snake_side_is_actually_snake_case() -> None:
    """ALIASES key 必须都是 snake_case (含下划线)."""
    for k in ALIASES:
        assert re.match(r"^[a-z][a-z0-9_]*$", k), f"key {k!r} not snake_case"


@pytest.mark.parametrize(
    "snake_key",
    list(ALIASES.keys()),
)
def test_each_alias_translates_to_expected_camel(snake_key: str) -> None:
    """每个 ALIASES 项在 to_camel 后变成对应 camelCase."""
    input_dict = {snake_key: "x"}
    translated = to_camel(input_dict)
    expected_camel = ALIASES[snake_key]
    assert expected_camel in translated, (
        f"to_camel({input_dict}) should produce {expected_camel!r} key, "
        f"got keys: {list(translated.keys())}"
    )


@pytest.mark.parametrize(
    "camel_key",
    list(ALIASES.values()),
)
def test_each_alias_reverse_translates_to_expected_snake(camel_key: str) -> None:
    """每个 ALIASES 反向: from_camel 把 camel 翻回 snake."""
    input_dict = {camel_key: "x"}
    translated = from_camel(input_dict)
    expected_snake = next(k for k, v in ALIASES.items() if v == camel_key)
    assert expected_snake in translated, (
        f"from_camel({input_dict}) should produce {expected_snake!r} key, "
        f"got keys: {list(translated.keys())}"
    )
