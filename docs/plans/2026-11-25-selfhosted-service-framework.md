# 自部署服务通用化框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「接入一个自部署服务」从「往代码里塞一个垂直子系统」收敛为「一份声明 + 一个客户端」，并让 DrawIO 生成的图直接、可交互地显示在会话里。

**Architecture:** 分三层交付。**A（P0 激活）** 只做构建与部署，让既有 DrawIO MCP 链路跑通并出图。**B（P1 富媒体）** 给 MCP 图片结果建立统一的 `RichMedia` 引用契约：后端把图片落 `MediaStore`、只把 URL 引用写进工具结果信封（不进 LLM 上下文的 base64），前端复用既有 `metadata` 提升通道渲染，并新增可交互 `SvgDiagramViewer`；同时把 Markdown 代码块的语言分发改为注册表。**C（P2 服务注册）** 引入声明式 `ExternalServiceSpec/Registry`，把 MinerU 的 8 处硬编码（配置键、字段加密、配置加载、状态路由、前端卡片）收敛为「一份声明」，新服务只需声明 + 客户端。

**Tech Stack:** Electron + React + TypeScript（`src/`，Vitest）；Python FastAPI 后端（`backend/`，pytest，conda `sage-backend`）；MCP（`@modelcontextprotocol/sdk`）；Puppeteer（DrawIO 渲染）。

**Spec:** 本文件即 spec（调研结论以 `file:line` 事实内联，见「现状调研」）。

## Global Constraints

- 后端 Python 一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，禁止系统 python / conda base。
- 前后端双分支长期共存（main + release/win7）；本特性按 main 设计，合并后 cherry-pick 到 win7（py38 + pydantic v1 适配）。
- 后端代码须兼容 Python 3.8（win7）：用 `from __future__ import annotations` + `typing.Dict/List/Optional`，禁止运行时 `X | None`。
- 密钥永不进日志/聊天/状态接口：状态只返回 `hasApiKey` 布尔；`SecretBox` 字段级加密保持幂等。
- DrawIO 图片不得以 base64 进入 LLM 上下文或 `tool_calls` 持久化（只存 `/api/v1/media/<id>` 引用）；落盘失败才回退旧 base64 行为。
- 不直接 push main；feature 分支 + conventional commits；单任务一提交。
- 统一验证命令（本 worktree）：
  - 后端：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest <paths> -q`
  - 后端静态：`/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend`
  - 前端：`npx vitest run <paths>`、`npx tsc --noEmit`
  - 架构：`/home/fz/anaconda3/envs/sage-backend/bin/python scripts/architecture_check.py`（若存在）

---

## Scope Check

P0/P1/P2 跨「构建部署 / 后端契约 + 前端渲染 / 配置加密 + 设置 UI」三个子系统。三部分都以内聚方式交付，各自可独立上线：

- **A 独立可上线**：单独就能让 DrawIO 出图（不改代码契约）。
- **B 依赖 A 的运行结果**（但代码上只依赖 MCP 图片分支）。
- **C 与 A/B 无代码依赖**（只碰 MinerU 相关配置链路）。

因此本计划按 **A → B → C** 顺序执行，可批准为「一个分支、三次逻辑提交组」，也可在 PR 阶段拆成 PR-1(A+B) 与 PR-2(C) 降低审阅体积。**默认：单分支，按任务提交，最后一次性开 PR；若审阅者要求，再拆。**

---

## 现状调研（决策依据，全部为代码事实）

1. **DrawIO 已 90% 存在**：MCP 包源码完整（`packages/drawio-mcp-server/src/index.ts`，工具名 `render_diagram`，返回 `text` + `image` 两块）；后端仅在 `packages/drawio-mcp-server/dist/index.js` 存在时注册内置 server（`backend/mcp/config.py:243-261`），并注入 `DRAWIO_BASE_URL`（默认 `http://localhost:8080`）。**缺的只是 `dist/` 和一台 draw.io 实例**：`dist/`、`node_modules/` 均不存在且已 gitignore（`.gitignore:172-173`）。
2. **MCP 图片落点**：`McpTool.execute` 把 MCP `image` 块拼成 `metadata.imageData`（base64 data URL）+ `metadata.imageFormat`，并把 `{"text","metadata"}` 作为 `content` 返回（`backend/mcp/tool.py:90-132`）。
3. **工具结果 → LLM**：`output` 优先，否则 `content`，再 `json.dumps`（`backend/core/legacy/agent.py:3457-3467`）。所以当前 DrawIO 的 base64 被序列化进 LLM 消息。
4. **工具结果 → 持久化**：`OBSERVING` 事件的 `tool_result.content` 被写入 `accumulated_tool_calls[].result`（`backend/api/legacy_routes.py:2515-2520`），最终 `json.dumps` 存 `messages.tool_calls`（`legacy_routes.py:2548-2560`）。**schema 里没有独立 metadata 字段** —— 富媒体引用必须放进 `result` 信封才能历史回读。
5. **前端实时路径**：解析 `tr.content` JSON → `parsed.metadata` 整体提升为 `ToolCall.metadata`；并单独提升 `parsed.media_ref(s)` / `parsed.api_url(s)`（`src/features/send-message/chatStreamRuntime.ts:291-311`），随后 `normalizeToolCallEnvelope`（`:327`）。
6. **前端历史路径**：`Message.tsx:193` 对回读 `tool_calls` 逐个 `normalizeToolCallEnvelope`；该函数**只在有 `metadata.blockReason` 时**提升 metadata（`src/shared/lib/toolCallEnvelope.ts:33-42`）→ 富媒体/图片历史回读会丢。
7. **既有富媒体先例**：`image_gen_tool` 返回 `output={"media_refs":[MediaRef...], "api_urls":[...]}`（`backend/tools/image_gen_tool.py:91-95`）；`MediaRef.api_url` 即 `/api/v1/media/<id>`（`media_store.py:79-81`）。`MediaStore.save(content, kind, source, metadata=None, ext=None)`（`media_store.py:152-204`）；`GET /api/v1/media/{id}` 已存在。
8. **Electron 媒体鉴权**：`<img src="/api/...">` 在 Electron 下无 Bearer 会 401，必须走 `fetchMediaBlobUrl`（IPC relay 注入 token）→ `blob:` URL（`src/features/chat/MediaAttachment.tsx:28-64`）；dev 由 Vite proxy `/api` → 8765（`vite.config.ts:103-105`）。
9. **交互查看器模板**：`MermaidDiagram.tsx` 已有平移/缩放/适应/全屏/导出 PNG+SVG 的完整实现（`:66-537`），但它耦合 mermaid 解析与源码视图。
10. **代码块分发**：`src/widgets/markdown/components.tsx:178-182` 用 `if (language === 'mermaid') / 'html'` 硬编码分发，现有测试 `Markdown.code.test.tsx` 覆盖。
11. **MinerU 硬编码面**：配置键 `mineru_service`、`load_mineru_settings()`、`SAGE_MINERU_*` env、`secret_box._MINERU_SERVICE_KEY_FIELDS` + `wrap/unwrap_mineru_service_json`、`settings_repo` 的两个 `if key == "mineru_service"` 分支、`/mineru/status` 固定形状、前端 `MineruServiceCard.tsx` / `settingsRegistry` / `mineruApi.ts`。

---

## 技术方案

### Part A — 激活 DrawIO（P0）

不改契约，只补齐构建与部署：

- 构建 `packages/drawio-mcp-server`（`npm ci && npm run build` → `dist/index.js`）。
- 提供自部署 draw.io 实例（推荐 `jgraph/drawio` 容器，监听 8080），或指向 `https://embed.diagrams.net`；通过 `DRAWIO_BASE_URL` 注入后端内置 MCP server。
- 端到端验证：LLM 触发 `mcp__drawio__render_diagram` → `metadata.imageData` → `Message.tsx` `<img>` 出图。
- 为「打包/安装包」补 drawio dist 构建钩子与文档（否则发行版永远不注册该 server）。

> P0 验证的是**基线可用**；B 会把它升级为「无 base64 + 历史可回读 + 可交互」。

### Part B — 统一富媒体契约（P1）

**契约（后端）** `backend/domain/media.py`：

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RichMedia:
    """工具产出的富媒体引用（只含 URL/元数据，绝不含 base64）。"""
    id: str
    kind: str                 # "image" | "diagram" | "audio" | "document"
    mime_type: str            # "image/svg+xml" | "image/png" | ...
    api_url: str              # "/api/v1/media/<id>"
    format: Optional[str] = None      # "svg" | "png" | ...
    title: Optional[str] = None
    source: Optional[str] = None      # "mcp:drawio" | "image_gen" | ...
    interactive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "api_url": self.api_url,
            "format": self.format,
            "title": self.title,
            "source": self.source,
            "interactive": self.interactive,
        }


def media_envelope(
    text: str,
    media: List[RichMedia],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """工具结果信封：LLM 只看到简短 text + URL 引用；前端从 metadata 渲染。"""
    refs = [m.to_dict() for m in media]
    metadata: Dict[str, Any] = {"mediaRefs": refs, "richMedia": refs}
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"text": text, "metadata": metadata}
```

`backend/mcp/tool.py` 图片分支改为「先落盘、失败再回退 base64」：

```python
import base64
from typing import List, Optional

from backend.domain.media import RichMedia, media_envelope

    def _persist_mcp_image(
        self,
        b64_data: str,
        image_format: str,
        mime_full: str,
        tool_name: str,
        store: Optional[Any] = None,
    ) -> Optional[RichMedia]:
        try:
            from backend.services.multimodal.media_store import MediaKind, MediaStore
            raw = base64.b64decode(b64_data, validate=False)
            store = store or MediaStore()
            ref = store.save(
                raw,
                MediaKind.IMAGE,
                source=f"mcp:{self._server_name}",
                metadata={"original_filename": f"{tool_name}.{image_format}", "mime_type": mime_full},
                ext=image_format,
            )
            return RichMedia(
                id=ref.id,
                kind="diagram" if image_format == "svg" else "image",
                mime_type=ref.mime_type,
                api_url=ref.api_url,
                format=image_format,
                title=tool_name,
                source=f"mcp:{self._server_name}",
                interactive=image_format == "svg",
            )
        except Exception as exc:  # noqa: BLE001 — 落盘失败不得丢图，回退 base64
            logger.warning("MCP image persist failed (server=%s tool=%s): %s", self._server_name, tool_name, exc)
            return None
```

在 `execute` 中收集 `media: List[RichMedia]`，成功且有 media 时返回 `content=media_envelope(text_output, media)`；`metadata` 仅在回退路径保留 `imageData`。

**前端契约** `src/shared/lib/richMedia.ts`（与 `to_dict()` 字段一一对应）：

```ts
export interface RichMediaRef {
  id: string;
  kind: string;
  mime_type: string;
  api_url: string;
  format?: string | null;
  title?: string | null;
  source?: string | null;
  interactive?: boolean;
}
```

`ToolCall.metadata` 增 `richMedia?: RichMediaRef[]`（复用既有 `mediaRefs` 形状）；`normalizeToolCallEnvelope` 从「只认 blockReason」放宽为「认识已知 metadata 键即提升」，并优先用 `parsed.content`（拦截信封）或 `parsed.text`（富媒体信封）作为可读 `result`。渲染侧：非交互图片复用 `MediaAttachment`；`interactive && mime_type==='image/svg+xml'` 用新 `SvgDiagramViewer`（基于 `fetchMediaBlobUrl` 的 blob URL 渲染 `<img>`，避免 `dangerouslySetInnerHTML` 的 XSS 面）。

**代码块注册表**：`components.tsx:178` 的 if/else 改为 `resolveCodeFenceRenderer(language, tier)`，默认注册 mermaid/html/默认 shiki，行为不变。

### Part C — 声明式服务注册（P2）

`backend/services/external_services/spec.py`：

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class SecretField:
    json_field: str   # "apiKey"
    account: str      # "mineru:api_key"（SecretBox account 命名空间）


@dataclass(frozen=True)
class EnvField:
    json_field: str
    env_name: str
    cast: Callable[[str], Any] = str


@dataclass(frozen=True)
class ExternalServiceSpec:
    name: str                          # "mineru"
    preference_key: str                # "mineru_service"
    route_prefix: str                  # "/mineru"
    defaults: Dict[str, Any]
    env_fields: Tuple[EnvField, ...] = ()
    secret_fields: Tuple[SecretField, ...] = ()
    probe: Optional[Callable[[Dict[str, Any]], Any]] = field(default=None)
```

注册表 `registry.py`（无 data 依赖，避免环）：

```python
_REGISTRY: Dict[str, ExternalServiceSpec] = {}


def register_service(spec: ExternalServiceSpec) -> None:
    _REGISTRY[spec.name] = spec


def get_service(name: str) -> Optional[ExternalServiceSpec]:
    return _REGISTRY.get(name)


def get_by_preference_key(key: str) -> Optional[ExternalServiceSpec]:
    return next((s for s in _REGISTRY.values() if s.preference_key == key), None)


def all_services() -> Tuple[ExternalServiceSpec, ...]:
    return tuple(_REGISTRY.values())
```

内置声明 `builtin.py` 注册 MinerU spec（含现有 defaults/env/secret/probe），由 `external_services/__init__.py` 末尾 `from .builtin import *  # noqa` 保证导入即注册。

通用能力（均以 spec 驱动，MinerU 行为保持字节级一致）：

1. `secret_box.py` 增 `wrap_service_json(spec, raw)` / `unwrap_service_json(spec, raw)`，遍历 `spec.secret_fields`；现有 `wrap_mineru_service_json` 改为薄委托。
2. `settings_repo.py` 的两个 `if key == "mineru_service"` 改为 `spec = get_by_preference_key(key)` 后通用加/解密，无 spec 则原样。
3. `config.py` 增 `load_service_settings(spec)`：defaults ← 解密后的 preferences ← env 覆盖；`load_mineru_settings()` 变薄包装。
4. `status.py` 增 `build_external_service_router(spec)`：返回 `{configured, enabled, hasApiKey, reachable, error}` 并入 `probe()` 的额外键；MinerU 的 `serverAuthMode/serverTiers/serverVersion/reason` 由 probe 返回，形状不变。
5. 前端 `src/features/settings/externalServices/registry.ts` 声明 `ExternalServiceUiSpec`，新增通用 `ExternalServiceCard`；`MineruServiceCard` 变为「配置驱动 + 可选自定义状态区」薄包装，视觉与交互不变。

**目标效果**：新增一个自部署服务 = 后端一份 `ExternalServiceSpec` + 一个 client/probe；前端一条 UI spec。无新增 `if key ==` 分支、无新增手写加密逻辑。

---

## 实施步骤

### Part A — 激活 DrawIO

#### Task A1: 构建 drawio MCP server 产物

**Files:**
- Build output: `packages/drawio-mcp-server/dist/index.js`（gitignored）
- Verify: `backend/mcp/config.py:243-261`

- [x] **Step 1: 安装依赖并构建**

```bash
cd packages/drawio-mcp-server
npm ci
npm run build
test -f dist/index.js && echo "dist OK"
```

预期：`dist/index.js` 存在。（`puppeteer` 安装需下载 Chromium；离线环境可用 `PUPPETEER_SKIP_DOWNLOAD=1` 并依赖系统 `CHROME_PATH`。）

- [x] **Step 2: 确认后端能识别内置 server**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python - <<'PY'
from backend.mcp.config import builtin_server_configs
print([s.name for s in builtin_server_configs()])
PY
```

预期：输出包含 `drawio`。

- [x] **Step 3: 提交（仅当有受版本控制的构建钩子变更时；dist 不提交）**

若本步只产生 gitignored 产物，则无提交；构建钩子变更在 A2 处理。

#### Task A2: 让发行/打包也构建 drawio dist

**Files:**
- Modify: `package.json`（新增 `build:drawio-mcp` 脚本，并挂到 `prebuild` 或 `electron:build` 之前）
- Modify: 打包脚本/CI（若打包不经过根 `prebuild`，补等价步骤）
- Docs: `docs/technical/<next>-selfhosted-service-framework.md`（在 Part A 完成后创建，编号合并时取当时最大号 +1）

- [x] **Step 1: 新增根脚本**

```json
{
  "scripts": {
    "build:drawio-mcp": "npm --prefix packages/drawio-mcp-server ci && npm --prefix packages/drawio-mcp-server run build"
  }
}
```

并把 `electron:build` 改为 `npm run build:drawio-mcp && npm run build && npm run build:electron`（保持现有顺序语义）。

- [x] **Step 2: 验证**

```bash
npm run build:drawio-mcp
test -f packages/drawio-mcp-server/dist/index.js && echo OK
```

- [x] **Step 3: 提交**

```bash
git add package.json
git commit -m "build(drawio): build bundled drawio MCP server during packaging"
```

#### Task A3: 部署/配置 draw.io 实例并端到端验证

**Files:**
- Docs: `docs/technical/<next>-selfhosted-service-framework.md`（部署说明）
- No runtime code unless配置缺口暴露

- [x] **Step 1: 起自部署 draw.io（docker 示例）**

```bash
docker run -d --name sage-drawio -p 8080:8080 jgraph/drawio
curl -sfI http://localhost:8080 | head -1
```

（无 docker 时可用 `DRAWIO_BASE_URL=https://embed.diagrams.net`。）

- [x] **Step 2: 启动桌面端（正常模式）**

```bash
npm run dev
SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python \
  ./node_modules/.bin/electron --no-sandbox .
```

- [x] **Step 3: 人工端到端**

在会话里让模型「画一个三节点流程图」，确认：
- 调用 `mcp__drawio__render_diagram`；
- 气泡内出现图像（P0 基线：`metadata.imageData` → `<img>`）；
- 断开 draw.io 后工具返回可读错误而非崩溃。

- [x] **Step 4: 记录结果到技术文档，提交**

```bash
git add docs/technical/*.md
git commit -m "docs(service): document self-hosted drawio deployment and DRAWIO_BASE_URL"
```

> ⚠️ 人工浏览器/桌面验证无法由 CI 覆盖；若本环境无法起 draw.io，须在 PR 描述中明确标注「P0 真人验证未完成」。

---

### Part B — 统一富媒体契约

#### Task B1: 后端 RichMedia 契约与信封

**Files:**
- Create: `backend/domain/media.py`
- Test: `backend/tests/domain/test_media_contract.py`（若目录不存在则用 `backend/tests/test_media_contract.py`）

**Interfaces:**
- Produces: `RichMedia(id,kind,mime_type,api_url,format,title,source,interactive).to_dict()`；`media_envelope(text, media, extra_metadata=None) -> {"text","metadata":{"mediaRefs","richMedia"}}`

- [x] **Step 1: 写失败测试**

```python
from backend.domain.media import RichMedia, media_envelope


def test_media_envelope_shape():
    m = RichMedia(
        id="abc123",
        kind="diagram",
        mime_type="image/svg+xml",
        api_url="/api/v1/media/abc123",
        format="svg",
        title="render_diagram",
        source="mcp:drawio",
        interactive=True,
    )
    env = media_envelope("渲染完成", [m])
    assert env["text"] == "渲染完成"
    assert env["metadata"]["mediaRefs"][0]["api_url"] == "/api/v1/media/abc123"
    assert env["metadata"]["richMedia"][0]["interactive"] is True
    assert "base64" not in str(env)
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/domain/test_media_contract.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `backend/domain/media.py`（代码见「技术方案 Part B」）**

- [ ] **Step 4: 运行通过**

Run: 同上 → PASS

- [x] **Step 5: 提交**

```bash
git add backend/domain/media.py backend/tests/domain/test_media_contract.py
git commit -m "feat(media): add RichMedia contract and tool media envelope"
```

#### Task B2: McpTool 图片落盘为媒体引用

**Files:**
- Modify: `backend/mcp/tool.py:88-132`（图片分支 + 返回值）
- Test: `backend/tests/mcp/test_mcp_tool_media.py`

**Interfaces:**
- Consumes: B1 `RichMedia`, `media_envelope`; `MediaStore.save(content, MediaKind, source, metadata=None, ext=None)`

- [ ] **Step 1: 写失败测试（注入临时 MediaStore）**

```python
import base64
import pytest
from backend.mcp.tool import McpTool


class _FakePool:
    def __init__(self, response):
        self._response = response
    def call_tool(self, server, tool, args):
        return self._response


def test_mcp_image_persisted_as_media_ref(monkeypatch, tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(tmp_path)
    monkeypatch.setattr(
        "backend.services.multimodal.media_store.MediaStore", lambda: store
    )
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    tool = McpTool(
        _FakePool({"content": [
            {"type": "text", "text": "ok"},
            {"type": "image", "data": png, "mimeType": "image/png"},
        ]}),
        "drawio",
        {"name": "render_diagram", "description": "", "inputSchema": {}},
    )
    res = tool.execute()
    assert res.success is True
    assert isinstance(res.content, dict)
    ref = res.content["metadata"]["mediaRefs"][0]
    assert ref["api_url"].startswith("/api/v1/media/")
    assert ref["kind"] == "image"
    assert "base64" not in str(res.content)
```

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/mcp/test_mcp_tool_media.py -q`
Expected: FAIL（仍是 imageData）

- [x] **Step 3: 实现**（按「技术方案 Part B」改 `execute` 图片分支与返回；落盘异常回退 base64）

- [x] **Step 4: 运行通过**

Run: 同上 → PASS

- [x] **Step 5: 提交**

```bash
git add backend/mcp/tool.py backend/tests/mcp/test_mcp_tool_media.py
git commit -m "feat(mcp): persist tool images to MediaStore and return URL refs"
```

#### Task B3: 前端放宽信封归一化（历史可回读）

**Files:**
- Modify: `src/shared/lib/store.ts`（`ToolCall.metadata` 增 `richMedia`）
- Create: `src/shared/lib/richMedia.ts`
- Modify: `src/shared/lib/toolCallEnvelope.ts:23-43`
- Test: `src/shared/lib/__tests__/toolCallEnvelope.test.ts`（追加用例）

**Interfaces:**
- Produces: `normalizeToolCallEnvelope` 对 `{text,metadata:{mediaRefs,richMedia}}` 提升 metadata 并把 result 变 `text`

- [x] **Step 1: 写失败测试**

```ts
it('lifts rich media envelope on history reload', () => {
  const raw = JSON.stringify({
    text: '渲染完成',
    metadata: {
      mediaRefs: [{ id: 'm1', kind: 'diagram', mime_type: 'image/svg+xml', api_url: '/api/v1/media/m1' }],
      richMedia: [{ id: 'm1', kind: 'diagram', mime_type: 'image/svg+xml', api_url: '/api/v1/media/m1', interactive: true }],
    },
  });
  const out = normalizeToolCallEnvelope({ id: 't1', name: 'mcp__drawio__render_diagram', args: {}, result: raw });
  expect(out.result).toBe('渲染完成');
  expect(out.metadata?.richMedia?.[0].api_url).toBe('/api/v1/media/m1');
});
```

- [x] **Step 2: 运行确认失败**

Run: `npx vitest run src/shared/lib/__tests__/toolCallEnvelope.test.ts`
Expected: FAIL（result 仍为 raw）

- [x] **Step 3: 实现**

```ts
const KNOWN_METADATA_KEYS = [
  'blockReason', 'blockedUrl', 'suggestedActions',
  'imageData', 'imageFormat',
  'mediaRef', 'mediaRefs', 'apiUrl', 'apiUrls', 'richMedia',
] as const;

export function normalizeToolCallEnvelope(tc: ToolCall): ToolCall {
  const raw = tc.result;
  if (typeof raw !== 'string' || !raw || raw[0] !== '{') return tc;
  let parsed: { content?: unknown; text?: unknown; metadata?: Record<string, unknown> };
  try { parsed = JSON.parse(raw); } catch { return tc; }
  const md = parsed.metadata;
  if (!md || typeof md !== 'object') return tc;
  if (!KNOWN_METADATA_KEYS.some((k) => k in md)) return tc;
  const nextResult =
    typeof parsed.content === 'string' && parsed.content
      ? parsed.content
      : typeof parsed.text === 'string'
        ? parsed.text
        : raw;
  return { ...tc, result: nextResult, metadata: { ...tc.metadata, ...md } };
}
```

- [x] **Step 4: 运行通过（含原有 blockReason 用例）**

Run: `npx vitest run src/shared/lib/__tests__/toolCallEnvelope.test.ts` → PASS

- [x] **Step 5: 提交**

```bash
git add src/shared/lib/store.ts src/shared/lib/richMedia.ts src/shared/lib/toolCallEnvelope.ts src/shared/lib/__tests__/toolCallEnvelope.test.ts
git commit -m "feat(chat): restore rich media metadata on history reload"
```

#### Task B4: SvgDiagramViewer（可交互 SVG 查看器）

**Files:**
- Create: `src/widgets/chat/SvgDiagramViewer.tsx`
- Test: `src/widgets/chat/__tests__/SvgDiagramViewer.test.tsx`

**Interfaces:**
- Props: `{ apiUrl: string; mimeType: string; title?: string; caption?: string }`
- Consumes: `fetchMediaBlobUrl`, `revokeMediaBlobUrl`, `resolveMediaUrl`（`src/shared/api/mediaApi.ts`）
- Produces: 平移/缩放/适应/全屏/下载 PNG+SVG（与 MermaidDiagram 工具条同构，但基于 `<img>`，无 innerHTML）

- [x] **Step 1: 写失败测试（渲染与下载按钮存在）**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { SvgDiagramViewer } from '../SvgDiagramViewer';

it('renders the diagram image and toolbar', async () => {
  render(<SvgDiagramViewer apiUrl="/api/v1/media/m1" mimeType="image/svg+xml" title="d" />);
  await waitFor(() => expect(screen.getByTestId('svg-diagram-img')).toBeTruthy());
  expect(screen.getByTestId('svg-diagram-download-svg')).toBeTruthy();
  expect(screen.getByTestId('svg-diagram-fullscreen-open')).toBeTruthy();
});
```

- [x] **Step 2: 运行确认失败**

Run: `npx vitest run src/widgets/chat/__tests__/SvgDiagramViewer.test.tsx`
Expected: FAIL（组件不存在）

- [x] **Step 3: 实现**

要点（复用 `MermaidDiagram` 的交互模式，但对象是 `<img>`）：
- `mediaId = apiUrl.split('/').filter(Boolean).pop()`；若 `window.electronAPI?.backendRequest` 存在 → `fetchMediaBlobUrl(mediaId, mimeType)`；否则 `resolveMediaUrl(apiUrl)`。卸载时 `revokeMediaBlobUrl`。
- 状态：`zoom`（0.4–3，步进 1.25）、`pan`、`fullscreen`；`wheel` + `ctrlKey` 原生非 passive 监听；指针拖拽；双击复位。
- 导出：PNG = 以 `<img>` 尺寸铺底画到 canvas（2x）；SVG = `fetch(src).then(r=>r.text())` 下载。全屏用 `createPortal` + ESC 关闭。
- 所有按钮 `data-testid="svg-diagram-*"`（img/zoom-in/zoom-out/fit/actual-size/download-png/download-svg/fullscreen-open/fullscreen-close）。
- 加载骨架 + 失败占位（失败时回退为可点击下载链接）。

- [x] **Step 4: 运行通过**

Run: 同上 → PASS

- [x] **Step 5: 提交**

```bash
git add src/widgets/chat/SvgDiagramViewer.tsx src/widgets/chat/__tests__/SvgDiagramViewer.test.tsx
git commit -m "feat(chat): add interactive SVG diagram viewer for tool media"
```

#### Task B5: Message 渲染接入 richMedia

**Files:**
- Modify: `src/widgets/chat/Message.tsx`（在既有 `hasImage` / `mediaRefs` 渲染旁新增分支，约 `:380-470`）
- Test: `src/widgets/chat/__tests__/Message.richMedia.test.tsx`（新建）

**Interfaces:**
- Consumes: B3 `normalizeToolCallEnvelope`（已作用于历史列表）、B4 `SvgDiagramViewer`、既有 `MediaAttachment`

- [x] **Step 1: 写失败测试**

```tsx
it('renders interactive svg via SvgDiagramViewer', () => {
  const tc = {
    id: 't1',
    name: 'mcp__drawio__render_diagram',
    args: {},
    result: JSON.stringify({
      text: 'ok',
      metadata: { richMedia: [{ id: 'm1', kind: 'diagram', mime_type: 'image/svg+xml', api_url: '/api/v1/media/m1', interactive: true }] },
    }),
  };
  render(<Message message={{ id: 'a', role: 'assistant', content: '', tool_calls: [tc] } as any} />);
  expect(screen.getByTestId('svg-diagram-img')).toBeTruthy();
});
```

- [x] **Step 2: 运行确认失败** → FAIL

- [x] **Step 3: 实现**

在工具卡渲染处读取（`getToolCalls` 已 normalize）：

```tsx
const richMedia = tc.metadata?.richMedia ?? [];
...
{richMedia.map((m) =>
  m.interactive && m.mime_type === 'image/svg+xml' ? (
    <SvgDiagramViewer key={m.id} apiUrl={m.api_url} mimeType={m.mime_type} title={m.title ?? undefined} />
  ) : (
    <MediaAttachment key={m.id} url={m.api_url} mimeType={m.mime_type} caption={m.title ?? undefined} />
  ),
)}
```

去重：若同 id 已在 `mediaRefs` 渲染过则跳过（避免 image_gen 双渲染）。

- [x] **Step 4: 运行通过（含既有 Message 相关测试）**

Run: `npx vitest run src/widgets/chat/__tests__ | grep -i message` 或全量 `npx vitest run src/widgets/chat` → PASS

- [x] **Step 5: 提交**

```bash
git add src/widgets/chat/Message.tsx src/widgets/chat/__tests__/Message.richMedia.test.tsx
git commit -m "feat(chat): render rich media refs in tool cards"
```

#### Task B6: 代码块语言分发注册表

**Files:**
- Create: `src/widgets/markdown/codeFenceRegistry.ts`
- Modify: `src/widgets/markdown/components.tsx:170-190`
- Test: `src/widgets/markdown/__tests__/Markdown.code.test.tsx`（保持既有断言全绿）

- [x] **Step 1: 写失败测试（注册表可解析 mermaid/html）**

```ts
import { resolveCodeFenceRenderer } from '../codeFenceRegistry';
it('resolves mermaid and html', () => {
  expect(resolveCodeFenceRenderer('mermaid')).toBe('mermaid');
  expect(resolveCodeFenceRenderer('HTML')).toBe('html');
  expect(resolveCodeFenceRenderer('python')).toBe('default');
});
```

- [x] **Step 2: 运行确认失败** → FAIL

- [x] **Step 3: 实现注册表并替换 if/else**（默认 mermaid/html，其余 default；大小写归一）

- [x] **Step 4: 运行既有 Markdown 代码块测试**

Run: `npx vitest run src/widgets/markdown/__tests__/Markdown.code.test.tsx` → PASS

- [x] **Step 5: 提交**

```bash
git add src/widgets/markdown/codeFenceRegistry.ts src/widgets/markdown/components.tsx src/widgets/markdown/__tests__/Markdown.code.test.tsx
git commit -m "refactor(markdown): dispatch fenced code via renderer registry"
```

#### Task B7: 端到端验证 B（DrawIO 无 base64 + 历史 + 交互）

- [ ] **Step 1: 起 draw.io + 桌面端（同 A3）**
- [ ] **Step 2**: 生成图 → 确认气泡出现**可交互** SVG（工具条可缩放/全屏/下载）。
- [ ] **Step 3**: 切换会话再切回（或重启渲染进程）→ 图仍在（历史回读）。若丢失，检查 `tool_calls[].result` 是否含 `metadata.richMedia` 且 `normalizeToolCallEnvelope` 生效。
- [ ] **Step 4**: 查数据库确认持久化的 `result` 中**无** `data:image/...;base64` 大字符串（只含 `/api/v1/media/` 引用）。
- [ ] **Step 5**: 把验证结果补进技术文档并提交（`docs(service): ...`）。

---

### Part C — 声明式服务注册

#### Task C1: Spec + Registry + 内置 MinerU 声明

**Files:**
- Create: `backend/services/external_services/__init__.py`
- Create: `backend/services/external_services/spec.py`
- Create: `backend/services/external_services/registry.py`
- Create: `backend/services/external_services/builtin.py`
- Test: `backend/tests/unit/test_external_service_registry.py`（沿用仓库既有 unit/ 布局）

**Interfaces:**
- Produces: `ExternalServiceSpec`, `register_service`, `get_service(name)`, `get_by_preference_key(key)`, `all_services()`；内置 `mineru` spec

- [ ] **Step 1: 写失败测试**

```python
from backend.services.external_services.registry import get_by_preference_key, get_service


def test_mineru_registered_as_spec():
    spec = get_service("mineru")
    assert spec is not None
    assert spec.preference_key == "mineru_service"
    assert get_by_preference_key("mineru_service") is spec
    assert any(f.json_field == "apiKey" and f.account == "mineru:api_key" for f in spec.secret_fields)
```

- [x] **Step 2: 运行确认失败** → FAIL

- [x] **Step 3: 实现 spec/registry（见技术方案 Part C）与 builtin MinerU 声明**

`builtin.py` 的 MinerU spec 字段须与现状严格一致：defaults 取 `load_mineru_settings` 现有默认值；env 取 `SAGE_MINERU_BASE_URL/API_KEY/TIER/TIMEOUT_SECONDS`；secret 为 `SecretField("apiKey","mineru:api_key")`；`probe` 委托现有 `MineruClient(...).probe()` 并返回 `serverAuthMode/serverTiers/serverVersion/reachable`。

- [x] **Step 4: 运行通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/external_services backend/tests/services/external_services
git commit -m "feat(service): add declarative external service spec registry"
```

#### Task C2: SecretBox 通用字段加密并保持幂等

**Files:**
- Modify: `backend/services/secret_box.py`（新增通用 wrap/unwrap；`wrap_mineru_service_json` 改为委托）
- Test: `backend/tests/services/test_secret_box_external.py`

- [ ] **Step 1: 写失败测试（幂等 + 只加密 secret 字段）**

```python
from backend.services.external_services.registry import get_service
from backend.services.secret_box import wrap_service_json, unwrap_service_json


def test_wrap_is_idempotent_and_preserves_non_secret():
    spec = get_service("mineru")
    raw = '{"baseUrl":"http://x","apiKey":"k1","tier":"pro"}'
    once = wrap_service_json(spec, raw)
    twice = wrap_service_json(spec, once)
    assert once == twice
    assert "k1" not in once
    out = unwrap_service_json(spec, once)
    assert '"apiKey": "k1"' in out or '"apiKey":"k1"' in out
    assert '"baseUrl": "http://x"' in out or '"baseUrl":"http://x"' in out
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现**（遍历 `spec.secret_fields`，复用 `encrypt_secret/decrypt_secret/is_wrapped`；解密失败置空串，与现状一致）

- [ ] **Step 4: 运行通过 + 既有 secret_box 测试全绿**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/services/test_secret_box_external.py backend/tests -k secret_box -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/secret_box.py backend/tests/services/test_secret_box_external.py
git commit -m "refactor(secret): drive field encryption from service specs"
```

#### Task C3: settings_repo 去硬编码 + 通用配置加载

**Files:**
- Modify: `backend/data/settings_repo.py:150-230`（两处 `if key ==`）
- Modify: `backend/services/document_parse/config.py`（`load_service_settings` + 薄包装）
- Test: `backend/tests/data/test_settings_repo_external.py`

- [x] **Step 1: 写失败测试（get/set 走 spec，仍能还原明文）**

```python
def test_settings_repo_roundtrips_mineru_secret(tmp_repo):
    tmp_repo.set("mineru_service", '{"baseUrl":"http://x","apiKey":"secret"}')
    stored = tmp_repo.get_raw("mineru_service")  # 测试辅助：未经解密
    assert "secret" not in stored
    got = tmp_repo.get("mineru_service")
    assert '"apiKey": "secret"' in got or '"apiKey":"secret"' in got
```

（若 `get_raw` 不存在，用底层 store 读取；不得为测试新增生产 API。）

- [x] **Step 2: 运行确认失败** → FAIL

- [x] **Step 3: 实现**

```python
from backend.services.external_services.registry import get_by_preference_key

# get() 内：
spec = get_by_preference_key(key)
if spec is not None and spec.secret_fields:
    return unwrap_service_json(spec, raw_value)
# set() 内：
spec = get_by_preference_key(key)
if spec is not None and spec.secret_fields:
    raw_value = wrap_service_json(spec, raw_value)
```

`load_service_settings(spec)`：defaults ← `settings_repo.get(spec.preference_key)`（已解密）← env；`load_mineru_settings()` 转为对结果做类型转换（字段与现有 `MineruSettings` 完全一致）。

- [x] **Step 4: 运行通过 + MinerU 配置测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/data/test_settings_repo_external.py backend/tests -k "mineru or settings_repo" -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/settings_repo.py backend/services/document_parse/config.py backend/services/external_services/settings.py backend/tests/data/test_settings_repo_external.py
git commit -m "refactor(settings): replace mineru hardcoding with service spec dispatch"
```

#### Task C4: 通用状态路由（MinerU 形状不变）

**Files:**
- Create: `backend/api/external_service_routes.py`
- Modify: `backend/api/mineru_routes.py`（改为委托构建器）
- Modify: `backend/main.py`（注册通用路由或沿用 mineru 路由）
- Test: `backend/tests/api/test_external_service_status.py`

- [x] **Step 1: 写失败测试（无 key 泄露 + 形状）**

```python
def test_status_never_leaks_key(client):
    r = client.get("/api/v1/mineru/status")
    body = r.json()
    assert "apiKey" not in body
    for k in ("configured", "enabled", "hasApiKey", "reachable"):
        assert k in body
```

- [x] **Step 2: 运行确认失败** → FAIL（若已通过，说明现状形状正确，转为回归保护）

- [x] **Step 3: 实现 `build_external_service_router(spec)` 并让 `mineru_routes` 委托**

响应 = `{configured, enabled, hasApiKey, reachable, error}` ∪ probe 结果（probe 返回 `serverAuthMode/serverTiers/serverVersion/reason`）。secrets 只用于 `hasApiKey=bool(value)`。

- [x] **Step 4: 运行通过 + 既有 mineru 路由测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -k "mineru or external_service" -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/external_service_routes.py backend/api/mineru_routes.py backend/main.py backend/tests/api/test_external_service_status.py
git commit -m "refactor(api): build service status routes from specs"
```

#### Task C5: 前端声明式服务卡片

**Files:**
- Create: `src/features/settings/externalServices/registry.ts`
- Create: `src/features/settings/externalServices/ExternalServiceCard.tsx`
- Modify: `src/pages/settings/MineruServiceCard.tsx`（薄包装，保留自定义状态区）
- Test: `src/features/settings/externalServices/__tests__/ExternalServiceCard.test.tsx`

**Interfaces:**
- Produces: `ExternalServiceUiSpec { key; title; description; fields; statusEndpoint; renderStatus? }`；`ExternalServiceCard({ spec })`

- [x] **Step 1: 写失败测试（按 spec 渲染字段 + 调状态端点）**

```tsx
it('renders fields from spec', () => {
  render(<ExternalServiceCard spec={{ key: 'demo', title: 'Demo', description: '', fields: [{ jsonKey: 'baseUrl', label: 'Base URL', type: 'text' }], statusEndpoint: '/api/v1/demo/status' }} />);
  expect(screen.getByLabelText('Base URL')).toBeTruthy();
});
```

- [x] **Step 2: 运行确认失败** → FAIL

- [x] **Step 3: 实现通用卡片 + MinerU UI spec；`MineruServiceCard` 委托**

保持：密码字段脱敏显示、状态徽标、`hasApiKey` 提示、自定义 `renderStatus`（展示 authMode/version）——与现状视觉一致。

- [x] **Step 4: 运行通过 + 既有 settings 测试**

Run: `npx vitest run src/features/settings src/pages/settings` → PASS

- [x] **Step 5: 提交**

```bash
git add src/features/settings/externalServices src/pages/settings/MineruServiceCard.tsx
git commit -m "refactor(settings): render external services from declarative specs"
```

#### Task C6: 技术文档 + 全量验证

**Files:**
- Create: `docs/technical/<next>-selfhosted-service-framework.md`
- Update: `docs/technical/README.md`（章节目录）
- Update: `docs/user-manual/<next>-selfhosted-services.md`（可选：用户如何配置 DrawIO/MinerU）
- Delete plan doc after merge（按项目规范）

- [x] **Step 1: 写技术文档**：三层通道（内置工具 / MCP / 插件）、RichMedia 契约、ExternalServiceSpec 声明示例、DrawIO 部署、双分支注意。
  - 实际：`docs/technical/174-selfhosted-service-framework.md`（原 P0 阶段以 172 创建；rebase 到 #3301 后 172 被规则抽取占用、#3308 又占用 173，顺延为 174）。用户手册为 `60-selfhosted-services.md`（原 59，同样顺延）。
- [x] **Step 2: 注册到 README 目录**（编号取合并时实际最大号 +1；并发 PR 可能抢占，需顺延）。
  - 实际：技术目录登记 173（简介 P0–P2）；用户手册登记 60。
- [x] **Step 3: 全量验证**

```bash
npx tsc --noEmit
npx vitest run
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q
```

> 结果：tsc 0 错；ruff 通过（UP045 为既有设置警告）；vitest 7770 通过 / 1 失败（`ArenaAccounts` 负载时序 flake，单跑 8/8 通过）；pytest 18259 通过 / 8 失败（3 个单跑通过 = 负载 flake；`test_git_tool` 3 个为已知 locale 假红；`test_retry_resilience`/`test_wiki_generate_falls_back_without_llm` 已在 merge-base 基线 worktree 复现同样失败 = 既有环境性）。

- [x] **Step 4: 提交**

```bash
git add docs
git commit -m "docs(service): document self-hosted service framework and rich media"
```

---

## 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| Puppeteer 安装需下载 Chromium，CI/离线环境可能失败 | A1/A2 构建红 | CI 设 `PUPPETEER_SKIP_DOWNLOAD=1` + 系统 Chrome；或把 drawio dist 构建移到发行流水线而非测试流水线 |
| draw.io 实例不可用 | P0 无法真机验证 | 明确标注人工验证未完成；用 `embed.diagrams.net` 兜底；工具错误需可读 |
| MediaStore 落盘失败 | 图片丢失 | 回退旧 `imageData` base64 路径（有测试覆盖回退） |
| Electron 媒体 401 | 会话内图不显示 | 复用 `fetchMediaBlobUrl`（B4），禁止裸 `<img>` 打 `/api` |
| 历史回读丢图 | 用户体感回归 | B3 放宽 `normalizeToolCallEnvelope` + B7 显式回读验证 |
| `settings_repo` 去硬编码引入回归 | MinerU 配置读写错乱 | C3 先写「密文不落明文 / 解密可还原」测试；保留 `wrap_mineru_service_json` 薄委托；pytest `-k mineru` 全绿 |
| import-linter 层违规 | CI 架构红 | `domain/media.py` 纯数据；`external_services` 不 import data（settings_repo 单向依赖 registry） |
| py38 兼容 | win7 合并失败 | 全程 `from __future__ import annotations` + typing；避免 3.9+ 语法 |
| 文档编号并发冲突 | PR 冲突 | 合并前 fetch main 取实际最大号 +1（遵循既有经验） |
| 单 PR 过大 | 审阅困难 | 可拆 PR-1(A+B)/PR-2(C)，提交已按任务内聚 |

**依赖顺序：** A1 → A2 → A3（A 可独立完成）→ B1 → B2 → B3 → B4 → B5 → B6 → B7 → C1 → C2/C3（可并行）→ C4 → C5 → C6。

---

## 验证策略（Definition of Done）

- [ ] P0：桌面端真实生成一张 DrawIO 图并显示（或明确记录未验证原因）。
- [ ] P1：持久化 `tool_calls[].result` 不含 base64；刷新/切会话后图仍在；SVG 可交互（缩放/全屏/下载）。
- [ ] P2：新增一个「空壳 demo 服务」只需 spec + probe 即可出现在设置页并读写配置（用测试证明，不真正上线）。
- [ ] 全量：`tsc --noEmit`、`vitest run`、`ruff check backend`、`pytest backend/tests -q` 全绿。
- [ ] 双分支：main 合并后 cherry-pick 到 `release/win7` 并跑 py38 测试；文档编号顺延去重。
