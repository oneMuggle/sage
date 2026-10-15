# Vision Model 智能降级方案设计

> 设计日期：2026-10-14  
> 状态：草案  
> 分支：feat/vision-model-fallback

## 1. 背景与目标

### 1.1 当前问题

Sage 项目当前将对话模型（chatModel）和识图模型（visionModel）分开设置，但存在严重的架构缺陷：

**问题 1：visionModel 是"幽灵配置"**
- 用户在设置页面可以配置 visionModel
- 但在实际聊天流程中，visionModel 从未被读取或调用
- 图片始终发送给 chatModel，与 visionModel 配置无关

**问题 2：多模态模型重复选择**
- GPT-4o、Claude 3 等多模态模型同时具备 chat + vision 能力
- `inferCapabilities()` 给这些模型打上两种能力标签
- 用户需要在"对话模型"和"视觉理解模型"两个下拉列表中各选择一次
- 选了不同模型也不会生效（visionModel 不工作）

**问题 3：用户预期与实际行为不符**
- 用户设置 Claude 3 为识图模型，期望图片用 Claude 3 分析
- 实际图片发给对话模型（如 GPT-4o）
- 用户被误导，配置无效

### 1.2 设计目标

实现**智能降级策略**，让 visionModel 设置真正生效：

1. **优先使用对话模型的原生多模态能力**
   - 如果 chatModel 支持 vision → 直接发给 chatModel（零延迟，原生体验）
   
2. **自动降级到 visionModel**
   - 如果 chatModel 不支持 vision → 检查 visionModel 是否配置
   - visionModel 已配置 → 后端调用 visionModel 生成图片描述，注入 chatModel 上下文
   - 对用户透明，体验接近原生多模态

3. **清晰的错误提示**
   - chatModel 不支持 vision + visionModel 未配置 → 提示用户配置或更换模型

### 1.3 核心设计原则

- **后端实现降级逻辑**：前端只负责发送图片和显示提示，后端负责路由决策
- **图片描述替换法**：visionModel 生成的描述替换原始图片，模拟原生多模态行为
- **向后兼容**：现有用户的 visionModel 配置不会丢失，激活后生效
- **最小改动**：不改变数据模型结构，只修改调用逻辑

## 2. 当前架构分析

### 2.1 数据模型

**前端类型定义**（`src/entities/setting/types.ts`）：
```typescript
interface ModelSelections {
  chatModel: ModelSelection;      // 对话模型（必填）
  visionModel: ModelSelection;    // 识图模型（选填，当前不工作）
  embeddingModel: ModelSelection;
  ttsModel: ModelSelection;
  asrModel: ModelSelection;
  imageGenModel: ModelSelection;
}

interface ModelSelection {
  endpointId: string | null;
  modelId: string | null;
}
```

**后端设置模型**（`backend/api/settings_models.py`）：
```python
class SettingsPayload(BaseModel):
    modelSelections: Optional[dict] = None  # 弱类型，实际校验在 canonicalizer
```

**能力推断逻辑**（`src/features/manage-endpoints/api.ts`）：
```typescript
function inferCapabilities(modelId: string): ModelCapability[] {
  const caps: ModelCapability[] = ['chat'];  // 所有模型默认有 chat 能力
  if (lower.includes('vision') || lower.includes('gpt-4o') || 
      lower.includes('gemini') || lower.includes('claude-3')) {
    caps.push('vision');  // 多模态模型同时获得 chat + vision
  }
  return caps;
}
```

### 2.2 当前图片处理流程

**前端**（`src/features/send-message/useChat.ts`）：
```typescript
const config: ChatConfig = {
  model: settings.modelSelections.chatModel.modelId,
  // ...
};

// 图片随消息一起发送
chatApi.sendMessage(message, images, config);
```

**后端**（`backend/api/legacy_routes.py`）：
```python
# 图片直接注入 user 消息，发给 chatModel
if data.images:
    messages[-1] = {
        "role": "user",
        "content": [
            {"type": "text", "text": data.message},
            *[{"type": "image_url", "image_url": {"url": img}} 
              for img in data.images],
        ],
    }
```

**问题**：后端没有检查 chatModel 是否支持 vision，直接把图片发给 chatModel。

### 2.3 visionModel 的当前使用

经过全代码搜索，visionModel 只在以下位置被读取：
1. 设置页面 UI（`ModelsTab.tsx`）—— 仅供用户配置
2. Demo 模式默认值填充（`types.ts` `withDemoSettingsDefaults()`）

**没有任何聊天/Agent 路径读取 visionModel 来决定图片识别使用哪个模型。**

## 3. 设计方案

### 3.1 智能降级策略

**核心逻辑**（后端实现）：

```python
# backend/core/legacy/agent.py
async def _prepare_messages_with_images(self, messages, images):
    """根据 chatModel 能力智能处理图片"""
    
    # 1. 获取 chatModel 的能力
    chat_model_caps = await self._get_model_capabilities(self.chat_model)
    
    # 2. 如果 chatModel 支持 vision，直接注入图片
    if 'vision' in chat_model_caps:
        return self._inject_images_as_content(messages, images)
    
    # 3. 降级：检查 visionModel 是否配置
    if self._is_vision_model_configured():
        # 调用 visionModel 生成图片描述
        descriptions = await self._generate_image_descriptions(images)
        # 替换图片为文本描述
        return self._replace_images_with_descriptions(messages, descriptions)
    
    # 4. 无 visionModel：抛出异常，前端提示用户
    raise VisionNotAvailableError(
        "对话模型不支持视觉识别，且未配置视觉理解模型"
    )
```

**降级流程**：
```
用户发送图片 + 文本
    ↓
后端检查 chatModel capabilities
    ↓
chatModel 支持 vision?
    ├─ 是 → 直接注入图片到消息（原生多模态）
    │       发给 chatModel
    │       返回响应
    │
    └─ 否 → 检查 visionModel 配置
             ├─ 已配置 → 调用 visionModel API
             │           生成每张图片的描述
             │           替换消息中的图片为描述文本
             │           发给 chatModel
             │           返回响应
             │
             └─ 未配置 → 返回错误
                         前端提示用户配置 visionModel
                         或更换支持 vision 的 chatModel
```

### 3.2 图片描述注入方式

**采用"替换图片为文本描述"方案**（业界通用）：

**原始消息**（用户发送）：
```python
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": "这张图片里有什么？"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]}
]
```

**降级后消息**（替换为描述）：
```python
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": "[图片内容：一张蓝天白云的照片，背景是蓝色天空和白色云朵]\n\n这张图片里有什么？"}
    ]}
]
```

**多图片场景**：
```python
# 用户发送 3 张图片
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": "[图片 1 内容：...]\n[图片 2 内容：...]\n[图片 3 内容：...]\n\n这些图片里有什么？"}
    ]}
]
```

### 3.3 能力检测机制

**后端需要获取模型的能力信息**：

**方案 A：前端传递能力信息**（推荐）
```typescript
// 前端发送消息时，附带 chatModel 的能力信息
chatApi.sendMessage(message, images, {
    model: chatModel.modelId,
    capabilities: chatModel.capabilities,  // ['chat', 'vision']
    // ...
});
```

**方案 B：后端推断能力**（备选）
```python
# 后端复用前端的 inferCapabilities 逻辑
def _infer_capabilities(self, model_id: str) -> List[str]:
    # 与前端 inferCapabilities 相同的规则
    caps = ['chat']
    if any(kw in model_id.lower() for kw in ['vision', 'gpt-4o', 'claude-3']):
        caps.append('vision')
    return caps
```

**推荐方案 A**：
- 前端已经有 `DiscoveredModel.capabilities` 信息
- 传递给后端避免重复推断逻辑
- 后端可以直接信任前端传递的能力信息

### 3.4 visionModel 调用实现

**后端调用 visionModel API**：

```python
# backend/core/legacy/agent.py
async def _generate_image_descriptions(self, images: List[str]) -> List[str]:
    """调用 visionModel 生成图片描述"""
    
    vision_config = self._build_vision_config()
    descriptions = []
    
    for image_data in images:
        try:
            # 调用 visionModel API
            description = await self._call_vision_model(
                vision_config,
                image_data
            )
            descriptions.append(description)
        except Exception as e:
            logger.error(f"visionModel 调用失败: {e}")
            descriptions.append("[图片识别失败]")
    
    return descriptions

def _build_vision_config(self) -> VisionConfig:
    """从设置中构建 visionModel 配置"""
    selections = self.settings.modelSelections
    vision_selection = selections.get('visionModel', {})
    
    endpoint = self._resolve_endpoint(vision_selection.get('endpointId'))
    
    return VisionConfig(
        provider=endpoint.provider,
        base_url=endpoint.baseUrl,
        api_key=endpoint.apiKey,
        model=vision_selection.get('modelId'),
    )

async def _call_vision_model(self, config: VisionConfig, image_data: str) -> str:
    """调用 visionModel API 生成图片描述"""
    # 复用 backend/wiki/vision.py 的 caption_image 逻辑
    from backend.wiki.vision import caption_image
    
    description = await caption_image(
        config=config,
        image_data=base64.b64decode(image_data.split(',')[1]),
        context="请详细描述这张图片的内容"
    )
    return description
```

### 3.5 UI 提示策略

**前端根据 chatModel 能力显示不同提示**：

**场景 1：chatModel 支持 vision**
```tsx
// 静默，不显示任何提示
<ModelSelector label="视觉理解模型" desc="选填，当对话模型不支持视觉时使用" />
```

**场景 2：chatModel 不支持 vision + visionModel 已配置**
```tsx
// 显示提示
<Alert type="info">
  图片将通过 {visionModel.modelId} 识别后转为文本描述
</Alert>
<ModelSelector label="视觉理解模型" value={visionModel} />
```

**场景 3：chatModel 不支持 vision + visionModel 未配置**
```tsx
// 显示警告 + 禁用图片上传
<Alert type="warning">
  当前对话模型不支持视觉识别，请配置视觉理解模型或更换支持视觉的对话模型
</Alert>
<Button disabled>上传图片</Button>
```

**前端检测逻辑**：
```typescript
// src/features/send-message/ChatInput.tsx
const chatModelCaps = chatModel.capabilities ?? [];
const supportsVision = chatModelCaps.includes('vision');
const visionModelConfigured = Boolean(settings.modelSelections.visionModel.modelId);

const showVisionWarning = !supportsVision && !visionModelConfigured;
const showVisionInfo = !supportsVision && visionModelConfigured;

// 禁用图片上传
<input type="file" disabled={showVisionWarning} />
```

## 4. 架构设计

### 4.1 组件职责

| 组件 | 职责 |
|------|------|
| **前端 ChatInput** | 检测 chatModel 能力，显示提示，禁用/启用图片上传 |
| **前端 useChat** | 发送消息时附带 chatModel.capabilities |
| **后端 legacy_routes** | 接收能力信息，传递给 agent |
| **后端 agent.py** | 智能降级逻辑，路由决策 |
| **后端 wiki/vision.py** | 复用 caption_image 调用 visionModel |

### 4.2 数据流

```
┌─────────────┐
│  用户上传图片 │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────┐
│ 前端 ChatInput               │
│ - 检测 chatModel.capabilities│
│ - 显示提示/禁用按钮          │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 前端 useChat                 │
│ - 发送 message + images      │
│ - 附带 capabilities          │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 后端 legacy_routes           │
│ - 接收 capabilities          │
│ - 传递给 agent               │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 后端 agent.py                │
│ - 检查 capabilities          │
│ - 路由决策                   │
│   ├─ vision → 直接注入图片   │
│   └─ 无 vision → 调用 visionModel │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 后端 wiki/vision.py          │
│ - caption_image() 调用 API   │
│ - 返回图片描述               │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 后端 agent.py                │
│ - 替换图片为描述             │
│ - 发给 chatModel             │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 返回响应给前端               │
└──────────────────────────────┘
```

### 4.3 错误处理

**错误场景 1：visionModel API 调用失败**
```python
try:
    description = await self._call_vision_model(config, image_data)
except Exception as e:
    logger.error(f"visionModel 调用失败: {e}")
    description = "[图片识别失败]"
```

**错误场景 2：chatModel 不支持 vision + visionModel 未配置**
```python
if not supports_vision and not vision_model_configured:
    raise HTTPException(
        status_code=400,
        detail="对话模型不支持视觉识别，且未配置视觉理解模型"
    )
```

**前端处理**：
```typescript
catch (error) {
    if (error.message.includes("视觉识别")) {
        toast.error("请配置视觉理解模型或更换支持视觉的对话模型");
    }
}
```

## 5. 测试策略

### 5.1 单元测试

**后端测试**（`backend/tests/unit/test_agent_vision.py`）：
```python
def test_chat_model_supports_vision():
    """chatModel 支持 vision 时，直接注入图片"""
    agent = Agent(capabilities=['chat', 'vision'])
    messages = [{"role": "user", "content": "描述这张图片"}]
    images = ["data:image/png;base64,..."]
    
    result = agent._prepare_messages_with_images(messages, images)
    # 验证图片直接注入，未调用 visionModel
    assert result[0]["content"][1]["type"] == "image_url"

def test_fallback_to_vision_model():
    """chatModel 不支持 vision 时，降级到 visionModel"""
    agent = Agent(capabilities=['chat'])
    agent._is_vision_model_configured = lambda: True
    agent._generate_image_desions = AsyncMock(return_value=["图片描述"])
    
    messages = [{"role": "user", "content": "描述这张图片"}]
    images = ["data:image/png;base64,..."]
    
    result = agent._prepare_messages_with_images(messages, images)
    # 验证图片被替换为描述
    assert "图片描述" in result[0]["content"][0]["text"]

def test_no_vision_model_configured():
    """chatModel 不支持 vision + visionModel 未配置时，抛出异常"""
    agent = Agent(capabilities=['chat'])
    agent._is_vision_model_configured = lambda: False
    
    with pytest.raises(VisionNotAvailableError):
        agent._prepare_messages_with_images([], ["..."])
```

**前端测试**（`src/features/send-message/__tests__/ChatInput.test.tsx`）：
```typescript
test('禁用图片上传当 chatModel 不支持 vision 且 visionModel 未配置', () => {
    const chatModel = { capabilities: ['chat'] };
    const settings = { modelSelections: { chatModel, visionModel: { modelId: null } } };
    
    render(<ChatInput settings={settings} />);
    
    expect(screen.getByLabelText('上传图片')).toBeDisabled();
    expect(screen.getByText(/请配置视觉理解模型/)).toBeInTheDocument();
});
```

### 5.2 集成测试

**端到端测试**：
1. 设置 chatModel = GPT-4o（支持 vision），验证图片直接发送
2. 设置 chatModel = GPT-3.5（不支持 vision）+ visionModel = GPT-4V，验证降级逻辑
3. 设置 chatModel = GPT-3.5 + visionModel 未配置，验证错误提示

### 5.3 手动测试清单

- [ ] chatModel = GPT-4o，上传图片，验证原生多模态体验
- [ ] chatModel = GPT-3.5 + visionModel = GPT-4V，上传图片，验证降级逻辑
- [ ] chatModel = GPT-3.5 + visionModel 未配置，验证错误提示
- [ ] 上传多张图片，验证描述正确注入
- [ ] visionModel API 调用失败，验证错误处理

## 6. 实施步骤

### 阶段 1：后端智能降级（3-5 天）

1. **修改 agent.py**
   - 添加 `_prepare_messages_with_images()` 方法
   - 添加 `_get_model_capabilities()` 方法
   - 添加 `_is_vision_model_configured()` 方法
   - 添加 `_generate_image_descriptions()` 方法
   - 修改消息处理逻辑，调用智能降级

2. **修改 legacy_routes.py**
   - 接收前端传递的 capabilities
   - 传递给 agent

3. **添加单元测试**
   - 测试三种场景（支持 vision / 降级 / 未配置）

### 阶段 2：前端能力传递（2 天）

1. **修改 useChat.ts**
   - 发送消息时附带 chatModel.capabilities

2. **修改 ChatInput.tsx**
   - 检测 chatModel 能力
   - 显示提示/禁用按钮

3. **添加前端测试**
   - 测试 UI 提示逻辑

### 阶段 3：UI 优化（1-2 天）

1. **修改 ModelsTab.tsx**
   - visionModel 选择器显示为"降级方案"
   - 根据 chatModel 能力动态显示提示

2. **添加用户引导**
   - 首次配置时提示 visionModel 的作用

### 阶段 4：端到端测试（1 天）

1. 手动测试三种场景
2. 修复发现的问题
3. 更新文档

## 7. 风险与依赖

### 7.1 技术风险

**风险 1：visionModel 调用延迟**
- 降级逻辑需要额外调用 visionModel API，增加延迟
- 缓解：异步调用，显示加载状态

**风险 2：visionModel 描述质量**
- 不同 visionModel 的描述质量差异大
- 缓解：提示用户使用高质量 visionModel（如 GPT-4V）

**风险 3：模型能力推断不准确**
- `inferCapabilities()` 基于模型名称匹配，可能遗漏
- 缓解：允许用户手动设置模型能力（未来优化）

### 7.2 依赖

- 依赖 `backend/wiki/vision.py` 的 `caption_image()` 函数
- 依赖前端 `DiscoveredModel.capabilities` 信息

## 8. 未来优化

1. **模型能力手动设置**
   - 允许用户在端点配置中手动勾选模型能力
   - 避免自动推断不准确

2. **visionModel 描述缓存**
   - 对相同图片的描述进行缓存
   - 减少重复调用

3. **流式描述生成**
   - visionModel 生成描述时流式返回
   - 提升用户体验

4. **多语言描述**
   - 根据用户语言偏好生成对应语言的描述

## 9. 总结

本方案通过**智能降级策略**解决了 visionModel 的"幽灵配置"问题：

- **优先使用 chatModel 的原生多模态能力**（零延迟，原生体验）
- **自动降级到 visionModel**（两阶段调用，体验接近原生）
- **清晰的错误提示**（引导用户配置）

实施后，visionModel 设置将真正生效，用户可以：
- 使用同一个多模态模型处理对话和图片（推荐）
- 使用文本模型对话 + 视觉模型识图（成本优化）

设计符合用户预期，实现简单，向后兼容。
