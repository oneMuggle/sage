# Vision Model 智能降级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 vision model 智能降级策略，让 visionModel 设置真正生效，优先使用 chatModel 的原生多模态能力，不足时自动降级到 visionModel。

**Architecture:** 后端实现智能降级逻辑：检查 chatModel 的 capabilities，如果支持 vision 则直接注入图片，否则调用 visionModel 生成图片描述并替换为文本。前端传递 chatModel.capabilities 并在 UI 层显示提示/禁用按钮。

**Tech Stack:** Python 3.10 (FastAPI), TypeScript (React), pytest, vitest

**Spec:** `docs/superpowers/specs/2026-10-14-vision-model-fallback-design.md`

## Global Constraints

- Python 环境：必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`
- 前端环境：Node.js v25.9.0（通过 nvm）
- 端口约定：后端 8765（worktree 8771），前端 1420（worktree 1426）
- 代码风格：Python 使用 ruff 格式化，TypeScript 使用 ESLint + Prettier
- 测试覆盖率：新增代码至少 80% 覆盖

---

## Task 1: 后端单元测试 - chatModel 支持 vision 时直接注入图片

**Files:**
- Create: `backend/tests/unit/test_agent_vision.py`
- Modify: `backend/core/legacy/agent.py` (后续任务)

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `test_chat_model_supports_vision()` 测试函数

- [ ] **Step 1: Write the failing test**

创建测试文件：

```python
# backend/tests/unit/test_agent_vision.py
"""Vision model fallback unit tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestVisionFallback:
    """Test intelligent vision fallback strategy."""

    @pytest.mark.asyncio
    async def test_chat_model_supports_vision(self):
        """chatModel 支持 vision 时，直接注入图片，不调用 visionModel。"""
        from backend.core.legacy.agent import SageAgent

        # Arrange
        agent = MagicMock(spec=SageAgent)
        agent._get_model_capabilities = AsyncMock(return_value=['chat', 'vision'])
        agent._inject_images_as_content = MagicMock(return_value=[
            {"role": "user", "content": [
                {"type": "text", "text": "描述这张图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
            ]}
        ])

        messages = [{"role": "user", "content": "描述这张图片"}]
        images = ["data:image/png;base64,..."]

        # Act
        # 调用实际方法（需要后续实现）
        result = await SageAgent._prepare_messages_with_images(
            agent, messages, images
        )

        # Assert
        assert len(result) == 1
        assert result[0]["content"][1]["type"] == "image_url"
        agent._inject_images_as_content.assert_called_once_with(messages, images)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/fz/project/sage/.worktrees/feat-vision-model-fallback
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py::TestVisionFallback::test_chat_model_supports_vision -v
```

Expected: FAIL with "AttributeError: type object 'SageAgent' has no attribute '_prepare_messages_with_images'"

- [ ] **Step 3: Commit failing test**

```bash
git add backend/tests/unit/test_agent_vision.py
git commit -m "test: add failing test for vision fallback - chatModel supports vision"
```

---

## Task 2: 后端实现 - chatModel 支持 vision 时直接注入图片

**Files:**
- Modify: `backend/core/legacy/agent.py` (添加方法)
- Test: `backend/tests/unit/test_agent_vision.py`

**Interfaces:**
- Consumes: `test_chat_model_supports_vision()` 测试
- Produces: `_prepare_messages_with_images()`, `_inject_images_as_content()` 方法

- [ ] **Step 1: Implement _prepare_messages_with_images method**

在 `backend/core/legacy/agent.py` 中添加方法（在类定义内）：

```python
async def _prepare_messages_with_images(
    self,
    messages: List[Dict[str, Any]],
    images: List[str]
) -> List[Dict[str, Any]]:
    """根据 chatModel 能力智能处理图片。

    如果 chatModel 支持 vision，直接注入图片到消息。
    否则降级到 visionModel（后续任务实现）。

    Args:
        messages: 对话消息列表
        images: base64 编码的图片列表

    Returns:
        处理后的消息列表
    """
    if not images:
        return messages

    # 获取 chatModel 的能力
    chat_model_caps = await self._get_model_capabilities(self.chat_model)

    # 如果 chatModel 支持 vision，直接注入图片
    if 'vision' in chat_model_caps:
        return self._inject_images_as_content(messages, images)

    # TODO: 降级到 visionModel（后续任务实现）
    raise NotImplementedError("visionModel fallback not yet implemented")

def _inject_images_as_content(
    self,
    messages: List[Dict[str, Any]],
    images: List[str]
) -> List[Dict[str, Any]]:
    """将图片注入到最后的 user 消息中。

    Args:
        messages: 对话消息列表
        images: base64 编码的图片列表

    Returns:
        注入图片后的消息列表
    """
    if not messages:
        return messages

    # 复制消息避免修改原列表
    result = messages.copy()

    # 注入图片到最后的 user 消息
    last_msg = result[-1]
    if last_msg.get("role") == "user":
        result[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": last_msg.get("content", "")},
                *[
                    {"type": "image_url", "image_url": {"url": img}}
                    for img in images
                ],
            ],
        }

    return result

async def _get_model_capabilities(self, model_id: str) -> List[str]:
    """获取模型的能力列表。

    当前实现：从前端传递的 capabilities 属性读取。
    如果未传递，使用推断逻辑。

    Args:
        model_id: 模型 ID

    Returns:
        能力列表，如 ['chat', 'vision']
    """
    # 优先从 settings 中读取（后续任务实现前端传递）
    # 当前使用推断逻辑
    caps = ['chat']
    model_lower = model_id.lower() if model_id else ""

    if any(kw in model_lower for kw in [
        'vision', 'gpt-4o', 'gemini', 'claude-3'
    ]):
        caps.append('vision')

    return caps
```

- [ ] **Step 2: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py::TestVisionFallback::test_chat_model_supports_vision -v
```

Expected: PASS

- [ ] **Step 3: Commit implementation**

```bash
git add backend/core/legacy/agent.py
git commit -m "feat: implement vision fallback - direct injection when chatModel supports vision"
```

---

## Task 3: 后端单元测试 - visionModel 降级逻辑

**Files:**
- Modify: `backend/tests/unit/test_agent_vision.py`
- Modify: `backend/core/legacy/agent.py` (后续任务)

**Interfaces:**
- Consumes: Task 1-2 的实现
- Produces: `test_fallback_to_vision_model()` 测试函数

- [ ] **Step 1: Write the failing test**

在 `backend/tests/unit/test_agent_vision.py` 中添加测试：

```python
@pytest.mark.asyncio
async def test_fallback_to_vision_model(self):
    """chatModel 不支持 vision 时，降级到 visionModel 生成图片描述。"""
    from backend.core.legacy.agent import SageAgent

    # Arrange
    agent = MagicMock(spec=SageAgent)
    agent._get_model_capabilities = AsyncMock(return_value=['chat'])  # 不支持 vision
    agent._is_vision_model_configured = MagicMock(return_value=True)
    agent._generate_image_descriptions = AsyncMock(return_value=["一张蓝天白云的照片"])
    agent._replace_images_with_descriptions = MagicMock(return_value=[
        {"role": "user", "content": [
            {"type": "text", "text": "[图片内容：一张蓝天白云的照片]\n\n描述这张图片"}
        ]}
    ])

    messages = [{"role": "user", "content": "描述这张图片"}]
    images = ["data:image/png;base64,..."]

    # Act
    result = await SageAgent._prepare_messages_with_images(agent, messages, images)

    # Assert
    assert len(result) == 1
    assert "图片内容" in result[0]["content"][0]["text"]
    agent._generate_image_descriptions.assert_called_once_with(images)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py::TestVisionFallback::test_fallback_to_vision_model -v
```

Expected: FAIL with "NotImplementedError: visionModel fallback not yet implemented"

- [ ] **Step 3: Commit failing test**

```bash
git add backend/tests/unit/test_agent_vision.py
git commit -m "test: add failing test for visionModel fallback"
```

---

## Task 4: 后端实现 - visionModel 降级逻辑

**Files:**
- Modify: `backend/core/legacy/agent.py`
- Test: `backend/tests/unit/test_agent_vision.py`

**Interfaces:**
- Consumes: Task 1-3 的实现
- Produces: `_is_vision_model_configured()`, `_generate_image_descriptions()`, `_replace_images_with_descriptions()` 方法

- [ ] **Step 1: Implement visionModel fallback methods**

在 `backend/core/legacy/agent.py` 中完善 `_prepare_messages_with_images` 方法：

```python
async def _prepare_messages_with_images(
    self,
    messages: List[Dict[str, Any]],
    images: List[str]
) -> List[Dict[str, Any]]:
    """根据 chatModel 能力智能处理图片。"""
    if not images:
        return messages

    # 获取 chatModel 的能力
    chat_model_caps = await self._get_model_capabilities(self.chat_model)

    # 如果 chatModel 支持 vision，直接注入图片
    if 'vision' in chat_model_caps:
        return self._inject_images_as_content(messages, images)

    # 降级：检查 visionModel 是否配置
    if self._is_vision_model_configured():
        # 调用 visionModel 生成图片描述
        descriptions = await self._generate_image_descriptions(images)
        # 替换图片为文本描述
        return self._replace_images_with_descriptions(messages, descriptions)

    # 无 visionModel：抛出异常
    from backend.core.exceptions import VisionNotAvailableError
    raise VisionNotAvailableError(
        "对话模型不支持视觉识别，且未配置视觉理解模型"
    )
```

添加辅助方法：

```python
def _is_vision_model_configured(self) -> bool:
    """检查是否配置了 visionModel。"""
    selections = getattr(self.settings, 'modelSelections', {})
    vision_selection = selections.get('visionModel', {})
    return bool(vision_selection.get('modelId'))

async def _generate_image_descriptions(self, images: List[str]) -> List[str]:
    """调用 visionModel 生成图片描述。

    Args:
        images: base64 编码的图片列表

    Returns:
        每张图片的描述文本列表
    """
    vision_config = self._build_vision_config()
    descriptions = []

    for image_data in images:
        try:
            description = await self._call_vision_model(vision_config, image_data)
            descriptions.append(description)
        except Exception as e:
            logger.error(f"visionModel 调用失败: {e}")
            descriptions.append("[图片识别失败]")

    return descriptions

def _build_vision_config(self):
    """从设置中构建 visionModel 配置。"""
    from backend.wiki.vision import VisionConfig

    selections = getattr(self.settings, 'modelSelections', {})
    vision_selection = selections.get('visionModel', {})

    # TODO: 解析 endpoint（需要实现 _resolve_endpoint）
    # 当前简化：直接从 vision_selection 读取
    return VisionConfig(
        provider=vision_selection.get('provider', 'openai'),
        base_url=vision_selection.get('baseUrl', ''),
        api_key=vision_selection.get('apiKey', ''),
        model=vision_selection.get('modelId', 'gpt-4-vision-preview'),
    )

async def _call_vision_model(self, config, image_data: str) -> str:
    """调用 visionModel API 生成图片描述。"""
    import base64
    from backend.wiki.vision import caption_image

    # 解析 base64 数据
    if ',' in image_data:
        image_bytes = base64.b64decode(image_data.split(',')[1])
    else:
        image_bytes = base64.b64decode(image_data)

    description = await caption_image(
        config=config,
        image_data=image_bytes,
        context="请详细描述这张图片的内容"
    )
    return description

def _replace_images_with_descriptions(
    self,
    messages: List[Dict[str, Any]],
    descriptions: List[str]
) -> List[Dict[str, Any]]:
    """将图片替换为文本描述。

    Args:
        messages: 对话消息列表
        descriptions: 图片描述列表

    Returns:
        替换后的消息列表
    """
    if not messages:
        return messages

    result = messages.copy()
    last_msg = result[-1]

    if last_msg.get("role") == "user":
        # 构建图片描述文本
        desc_parts = []
        for i, desc in enumerate(descriptions, 1):
            if len(descriptions) == 1:
                desc_parts.append(f"[图片内容：{desc}]")
            else:
                desc_parts.append(f"[图片 {i} 内容：{desc}]")

        desc_text = "\n".join(desc_parts)
        original_text = last_msg.get("content", "")
        combined_text = f"{desc_text}\n\n{original_text}"

        result[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": combined_text}
            ],
        }

    return result
```

- [ ] **Step 2: Add VisionNotAvailableError exception**

在 `backend/core/exceptions.py` 中添加：

```python
class VisionNotAvailableError(Exception):
    """视觉识别不可用异常。"""
    pass
```

- [ ] **Step 3: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py::TestVisionFallback::test_fallback_to_vision_model -v
```

Expected: PASS

- [ ] **Step 4: Commit implementation**

```bash
git add backend/core/legacy/agent.py backend/core/exceptions.py
git commit -m "feat: implement visionModel fallback - generate descriptions and replace images"
```

---

## Task 5: 后端单元测试 - visionModel 未配置时抛出异常

**Files:**
- Modify: `backend/tests/unit/test_agent_vision.py`

**Interfaces:**
- Consumes: Task 1-4 的实现
- Produces: `test_no_vision_model_configured()` 测试函数

- [ ] **Step 1: Write the failing test**

在 `backend/tests/unit/test_agent_vision.py` 中添加测试：

```python
@pytest.mark.asyncio
async def test_no_vision_model_configured(self):
    """chatModel 不支持 vision + visionModel 未配置时，抛出异常。"""
    from backend.core.legacy.agent import SageAgent
    from backend.core.exceptions import VisionNotAvailableError

    # Arrange
    agent = MagicMock(spec=SageAgent)
    agent._get_model_capabilities = AsyncMock(return_value=['chat'])
    agent._is_vision_model_configured = MagicMock(return_value=False)

    messages = [{"role": "user", "content": "描述这张图片"}]
    images = ["data:image/png;base64,..."]

    # Act & Assert
    with pytest.raises(VisionNotAvailableError, match="视觉识别"):
        await SageAgent._prepare_messages_with_images(agent, messages, images)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py::TestVisionFallback::test_no_vision_model_configured -v
```

Expected: PASS（因为 Task 4 已实现异常抛出）

- [ ] **Step 3: Commit test**

```bash
git add backend/tests/unit/test_agent_vision.py
git commit -m "test: add test for visionModel not configured error"
```

---

## Task 6: 集成 vision fallback 到 legacy_routes.py

**Files:**
- Modify: `backend/api/legacy_routes.py:1635-1645`

**Interfaces:**
- Consumes: Task 1-5 的实现
- Produces: 修改后的图片处理逻辑

- [ ] **Step 1: Replace image handling code in legacy_routes.py**

将第 1635-1645 行的图片处理代码替换为：

```python
# G6 (2026-09-06): 图片附件处理。
# 智能降级：优先使用 chatModel 的原生 vision 能力，不足时降级到 visionModel。
if data.images:
    messages = await agent._prepare_messages_with_images(messages, data.images)
```

- [ ] **Step 2: Run backend tests to verify integration**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit integration**

```bash
git add backend/api/legacy_routes.py
git commit -m "feat: integrate vision fallback into legacy_routes.py"
```

---

## Task 7: 前端传递 chatModel.capabilities

**Files:**
- Modify: `src/features/send-message/useChat.ts`

**Interfaces:**
- Consumes: 前端的 `chatModel.capabilities` 信息
- Produces: 修改后的 API 调用

- [ ] **Step 1: Add capabilities to chat API request**

在 `src/features/send-message/useChat.ts` 中修改 sendMessage 调用：

```typescript
// 找到 sendMessage 调用处，添加 capabilities 参数
const chatModel = settings.modelSelections.chatModel;
const chatModelCapabilities = chatModel.capabilities ?? ['chat'];

const response = await chatApi.sendMessage({
  message,
  images: opts?.images,
  model: chatModel.modelId,
  capabilities: chatModelCapabilities,  // 新增
  // ... 其他参数
});
```

- [ ] **Step 2: Update chatApi type definition**

在 `src/shared/api/chatApi.ts` 中更新请求类型：

```typescript
interface SendMessageRequest {
  message: string;
  images?: string[];
  model?: string;
  capabilities?: string[];  // 新增
  // ... 其他字段
}
```

- [ ] **Step 3: Run frontend build to verify**

```bash
npm run build
```

Expected: Build succeeds

- [ ] **Step 4: Commit frontend changes**

```bash
git add src/features/send-message/useChat.ts src/shared/api/chatApi.ts
git commit -m "feat: pass chatModel.capabilities to backend API"
```

---

## Task 8: 后端接收 capabilities 参数

**Files:**
- Modify: `backend/api/legacy_routes.py`

**Interfaces:**
- Consumes: 前端传递的 capabilities 参数
- Produces: 修改后的请求处理

- [ ] **Step 1: Add capabilities field to request model**

在 `backend/api/legacy_routes.py` 中找到请求模型定义，添加：

```python
class ChatRequest(BaseModel):
    # ... 现有字段
    capabilities: Optional[List[str]] = None  # 新增
```

- [ ] **Step 2: Pass capabilities to agent**

在创建 agent 时传递 capabilities：

```python
agent = SageAgent(
    # ... 现有参数
    chat_model_capabilities=data.capabilities,  # 新增
)
```

- [ ] **Step 3: Update _get_model_capabilities to use passed value**

修改 `agent.py` 中的 `_get_model_capabilities` 方法：

```python
async def _get_model_capabilities(self, model_id: str) -> List[str]:
    """获取模型的能力列表。"""
    # 优先使用前端传递的 capabilities
    if hasattr(self, 'chat_model_capabilities') and self.chat_model_capabilities:
        return self.chat_model_capabilities

    # 降级：使用推断逻辑
    caps = ['chat']
    model_lower = model_id.lower() if model_id else ""

    if any(kw in model_lower for kw in [
        'vision', 'gpt-4o', 'gemini', 'claude-3'
    ]):
        caps.append('vision')

    return caps
```

- [ ] **Step 4: Run backend tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_vision.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit changes**

```bash
git add backend/api/legacy_routes.py backend/core/legacy/agent.py
git commit -m "feat: receive and use chatModel.capabilities from frontend"
```

---

## Task 9: 前端 UI - 显示 vision 提示和禁用按钮

**Files:**
- Modify: `src/features/send-message/ChatInput.tsx`

**Interfaces:**
- Consumes: `chatModel.capabilities` 和 `visionModel.modelId`
- Produces: UI 提示和禁用逻辑

- [ ] **Step 1: Add vision detection logic**

在 `src/features/send-message/ChatInput.tsx` 中添加：

```typescript
const chatModelCaps = settings.modelSelections.chatModel.capabilities ?? [];
const supportsVision = chatModelCaps.includes('vision');
const visionModelConfigured = Boolean(
  settings.modelSelections.visionModel?.modelId
);

const showVisionWarning = !supportsVision && !visionModelConfigured;
const showVisionInfo = !supportsVision && visionModelConfigured;
```

- [ ] **Step 2: Add UI alerts**

在图片上传按钮附近添加提示：

```tsx
{showVisionWarning && (
  <Alert type="warning">
    当前对话模型不支持视觉识别，请配置视觉理解模型或更换支持视觉的对话模型
  </Alert>
)}

{showVisionInfo && (
  <Alert type="info">
    图片将通过 {settings.modelSelections.visionModel.modelId} 识别后转为文本描述
  </Alert>
)}

<input
  type="file"
  accept="image/*"
  disabled={showVisionWarning}
  onChange={handleImageUpload}
/>
```

- [ ] **Step 3: Run frontend tests**

```bash
npm test -- ChatInput
```

Expected: Tests PASS

- [ ] **Step 4: Commit UI changes**

```bash
git add src/features/send-message/ChatInput.tsx
git commit -m "feat: show vision warnings and disable upload when not supported"
```

---

## Task 10: 更新 ModelsTab UI - 说明 visionModel 的作用

**Files:**
- Modify: `src/pages/settings/ModelsTab.tsx`

**Interfaces:**
- Consumes: 无
- Produces: 改进的 UI 文案

- [ ] **Step 1: Update visionModel description**

在 `src/pages/settings/ModelsTab.tsx` 中修改 visionModel 选择器的描述：

```tsx
<ModelSelector
  label="视觉理解模型"
  desc="选填。当对话模型不支持视觉识别时，自动使用此模型生成图片描述"
  groupedModels={visionModels}
  value={visionModel}
  onChange={(v) => updateSettings({
    modelSelections: { ...settings.modelSelections, visionModel: v }
  })}
/>
```

- [ ] **Step 2: Run frontend build**

```bash
npm run build
```

Expected: Build succeeds

- [ ] **Step 3: Commit UI text update**

```bash
git add src/pages/settings/ModelsTab.tsx
git commit -m "docs: clarify visionModel purpose in settings UI"
```

---

## Task 11: 端到端手动测试

**Files:**
- None（手动测试）

**Interfaces:**
- Consumes: Task 1-10 的实现
- Produces: 测试报告

- [ ] **Step 1: Start backend and frontend**

```bash
# Terminal 1: Start backend
cd /home/fz/project/sage/.worktrees/feat-vision-model-fallback
conda activate sage-backend && python -m backend.main

# Terminal 2: Start frontend
npm run dev
```

- [ ] **Step 2: Test scenario 1 - chatModel supports vision**

1. 设置 chatModel = GPT-4o（支持 vision）
2. 上传图片并发送
3. 验证：图片直接发给 GPT-4o，响应正常

- [ ] **Step 3: Test scenario 2 - fallback to visionModel**

1. 设置 chatModel = GPT-3.5（不支持 vision）
2. 设置 visionModel = GPT-4V
3. 上传图片并发送
4. 验证：图片被替换为描述文本，GPT-3.5 正常响应

- [ ] **Step 4: Test scenario 3 - no visionModel configured**

1. 设置 chatModel = GPT-3.5（不支持 vision）
2. 不设置 visionModel
3. 验证：图片上传按钮被禁用，显示警告提示

- [ ] **Step 5: Document test results**

创建测试报告文件 `docs/superpowers/plans/2026-10-14-vision-fallback-test-report.md`：

```markdown
# Vision Fallback 测试报告

## 测试环境
- 日期：2026-10-14
- 分支：feat/vision-model-fallback
- 环境：worktree

## 测试场景

### 场景 1: chatModel 支持 vision
- 结果：✅ PASS
- 备注：图片直接发送，响应正常

### 场景 2: 降级到 visionModel
- 结果：✅ PASS
- 备注：图片被替换为描述，响应正常

### 场景 3: visionModel 未配置
- 结果：✅ PASS
- 备注：按钮禁用，提示显示正确
```

- [ ] **Step 6: Commit test report**

```bash
git add docs/superpowers/plans/2026-10-14-vision-fallback-test-report.md
git commit -m "docs: add vision fallback end-to-end test report"
```

---

## Summary

**Total tasks:** 11  
**Estimated time:** 7-10 days  
**Dependencies:** None（任务按顺序执行）

**Key deliverables:**
1. 后端智能降级逻辑（Task 1-6）
2. 前端能力传递（Task 7-8）
3. 前端 UI 提示（Task 9-10）
4. 端到端测试（Task 11）

**Success criteria:**
- 所有单元测试通过
- 三个测试场景全部 PASS
- 代码覆盖率 ≥ 80%
