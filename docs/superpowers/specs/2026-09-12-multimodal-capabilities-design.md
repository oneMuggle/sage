# 多模态 API 能力补全设计

> **日期**: 2026-09-12
> **状态**: 设计中
> **分支**: 将在 `feat/multimodal-capabilities` worktree 中实现

## 1. 背景与目标

Sage 当前仅支持 3 种 AI 能力槽位（model slot）：`chatModel`（文本对话）、`visionModel`（视觉理解）、`embeddingModel`（文本向量化）。图像生成、语音合成（TTS）、语音识别（ASR）等多模态能力缺少 API 接口封装和 UI 支持。

**目标**：以通用抽象层为基座，补全 TTS + ASR + 图像生成三项能力，通过 agent 工具（function calling）驱动，生成的多媒体内容在聊天中以本地文件引用方式渲染。

**不在本次范围内**：视频生成（无 OpenAI 标准 API，各家 provider 差异大，后续独立设计）。

## 2. 设计决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 实现范围 | TTS + ASR + 图像生成 | 视频生成无标准 API，复杂度远高于其他三项 |
| 交互形态 | Agent 工具驱动 | LLM 通过 function calling 调用，不需独立 UI 页面 |
| 存储策略 | 本地文件 + 引用路径 | 消息轻量、文件可复用，前端通过 `/api/v1/media/{id}` 加载 |
| ASR 输入 | 工作区文件 + 聊天附件 | 两者都支持，聊天附件通过拖拽/粘贴上传 |
| 架构方案 | 通用抽象层 | 引入 `AICapability` 基类 + 注册表，便于后续扩展 |

## 3. 架构概览

```
┌─────────────────────────────────────────────────────┐
│                     前端 (React)                      │
│                                                       │
│  Settings: ModelsTab (6 个 ModelSelector)             │
│  Chat: 多媒体消息渲染 (<img> / <audio>)               │
│  Chat: 附件拖拽上传 (ASR 音频输入)                     │
└─────────────────────────┬───────────────────────────┘
                          │ /api/v1/media/{id}
                          │ /api/v1/chat/attachments
                          │ /api/v1/llm/* (proxy)
┌─────────────────────────┴───────────────────────────┐
│                   后端 (FastAPI)                       │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │          backend/services/multimodal/            │ │
│  │                                                   │ │
│  │  capability.py   AICapability 抽象基类            │ │
│  │  registry.py     CapabilityRegistry 注册表        │ │
│  │  media_store.py  MediaStore 媒体文件管理          │ │
│  │  tts.py          TTSCapability                   │ │
│  │  asr.py          ASRCapability                   │ │
│  │  image_gen.py    ImageGenCapability              │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ backend/tools/    │  │ backend/api/             │  │
│  │ tts_tool.py       │  │ media_routes.py          │  │
│  │ asr_tool.py       │  │ chat_attachment_routes.py│  │
│  │ image_gen_tool.py │  │                          │  │
│  └──────────────────┘  └──────────────────────────┘  │
└───────────────────────────────────────────────────────┘
                          │
                          ▼ httpx (直连上游)
              ┌───────────────────────┐
              │  用户配置的 endpoint    │
              │  OpenAI / Azure / 本地  │
              └───────────────────────┘
```

## 4. 核心抽象层

### 4.1 AICapability 基类

```python
# backend/services/multimodal/capability.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import httpx

class CapabilityKind(Enum):
    TTS = "tts"
    ASR = "asr"
    IMAGE_GEN = "image_gen"

@dataclass(frozen=True)
class CapabilityConfig:
    """从 settings 解析出的端点配置"""
    base_url: str
    api_key: str
    model: str
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AIHttpRequest:
    """标准化的 HTTP 请求构建结果"""
    url: str
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = None       # JSON body
    data: Any = None       # FormData (multipart uploads, e.g. ASR)
    timeout: float = 60.0

@dataclass(frozen=True)
class AIHttpResponse:
    """标准化的响应"""
    status_code: int
    content: bytes
    json: Optional[Dict] = None
    content_type: str = ""

class AICapability(ABC):
    """所有多模态能力的基类"""

    kind: CapabilityKind
    settings_slot: str  # e.g. "ttsModel", "asrModel", "imageGenModel"

    @abstractmethod
    def build_request(self, config: CapabilityConfig, **kwargs) -> AIHttpRequest:
        """构建上游 API 请求"""

    @abstractmethod
    def parse_response(self, response: AIHttpResponse, **kwargs) -> Any:
        """解析上游 API 响应"""

    async def execute(self, config: CapabilityConfig, **kwargs) -> Any:
        """模板方法：构建请求 → 发送 → 解析"""
        req = self.build_request(config, **kwargs)
        async with httpx.AsyncClient() as client:
            raw = await client.request(
                method=req.method,
                url=req.url,
                headers=req.headers,
                json=req.body,
                data=req.data,
                timeout=req.timeout,
            )
            is_json = raw.headers.get("content-type", "").startswith("application/json")
            resp = AIHttpResponse(
                status_code=raw.status_code,
                content=raw.content,
                json=raw.json() if is_json else None,
                content_type=raw.headers.get("content-type", ""),
            )
        return self.parse_response(resp, **kwargs)

    def load_config(self) -> Optional[CapabilityConfig]:
        """从 app_settings 读取本能力的端点配置。

        统一实现：读 modelSelections.{self.settings_slot} →
        查 endpoints 找到匹配 endpointId → 返回 CapabilityConfig。
        """
        from backend.data.settings_repo import SettingsRepository
        raw = SettingsRepository().get_json("app_settings")
        if not raw:
            return None
        selection = (raw.get("modelSelections") or {}).get(self.settings_slot)
        if not selection or not selection.get("endpointId"):
            return None
        for ep in raw.get("endpoints", []):
            if ep["id"] == selection["endpointId"]:
                return CapabilityConfig(
                    base_url=ep["baseUrl"].rstrip("/"),
                    api_key=ep.get("apiKey") or "",
                    model=selection.get("modelId") or ep.get("modelId") or "",
                )
        return None
```

### 4.2 能力注册表

```python
# backend/services/multimodal/registry.py

from typing import Dict, List, Optional
from .capability import AICapability, CapabilityKind

class CapabilityRegistry:
    """能力注册表 - 集中管理所有多模态能力"""

    _capabilities: Dict[CapabilityKind, AICapability] = {}

    @classmethod
    def register(cls, capability: AICapability) -> None:
        cls._capabilities[capability.kind] = capability

    @classmethod
    def get(cls, kind: CapabilityKind) -> Optional[AICapability]:
        return cls._capabilities.get(kind)

    @classmethod
    def available(cls) -> List[CapabilityKind]:
        """返回已配置可用的能力列表"""
        return [k for k, cap in cls._capabilities.items()
                if cap.load_config() is not None]

    @classmethod
    def all_kinds(cls) -> List[CapabilityKind]:
        return list(cls._capabilities.keys())

def register_all_capabilities() -> None:
    from .tts import TTSCapability
    from .asr import ASRCapability
    from .image_gen import ImageGenCapability

    CapabilityRegistry.register(TTSCapability())
    CapabilityRegistry.register(ASRCapability())
    CapabilityRegistry.register(ImageGenCapability())
```

### 4.3 MediaStore

```python
# backend/services/multimodal/media_store.py

import uuid
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, List

MEDIA_ROOT = Path("data/media")

class MediaKind(Enum):
    IMAGE = "image"
    AUDIO = "audio"

@dataclass(frozen=True)
class MediaRef:
    """媒体文件的引用"""
    id: str
    kind: MediaKind
    mime_type: str
    file_path: str       # 相对路径 e.g. "2026/09/12/abc123.mp3"
    file_size: int
    created_at: str      # ISO 8601
    source: str          # "tts" | "asr" | "image_gen" | "chat_upload"
    metadata: dict = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"/api/v1/media/{self.id}"

class MediaStore:
    """媒体文件生命周期管理"""

    def __init__(self, root: Path = MEDIA_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, kind: MediaKind, source: str,
             metadata: dict = None, ext: str = None) -> MediaRef:
        """存储媒体文件，返回 MediaRef"""
        media_id = uuid.uuid4().hex[:12]
        now = datetime.utcnow()
        date_dir = f"{now:%Y}/{now:%m}/{now:%d}"
        (self.root / date_dir).mkdir(parents=True, exist_ok=True)

        if not ext:
            mime = self._guess_mime(content, kind)
            ext = mimetypes.guess_extension(mime) or self._default_ext(kind)
        else:
            mime = mimetypes.guess_type(f"x.{ext}")[0] or self._default_mime(kind)

        filename = f"{media_id}.{ext.lstrip('.')}"
        rel_path = f"{date_dir}/{filename}"
        abs_path = self.root / rel_path
        abs_path.write_bytes(content)

        return MediaRef(
            id=media_id,
            kind=kind,
            mime_type=mime,
            file_path=rel_path,
            file_size=len(content),
            created_at=now.isoformat() + "Z",
            source=source,
            metadata=metadata or {},
        )

    def load(self, media_id: str) -> Optional[Tuple[MediaRef, bytes]]:
        """根据 ID 加载媒体文件"""
        for f in self.root.rglob(f"{media_id}.*"):
            content = f.read_bytes()
            rel = str(f.relative_to(self.root))
            kind = MediaKind.IMAGE if f.suffix in (".png", ".jpg", ".jpeg", ".webp") else MediaKind.AUDIO
            return MediaRef(
                id=media_id, kind=kind,
                mime_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream",
                file_path=rel, file_size=len(content),
                created_at=datetime.fromtimestamp(f.stat().st_mtime).isoformat() + "Z",
                source="unknown",
            ), content
        return None

    def delete(self, media_id: str) -> bool:
        for f in self.root.rglob(f"{media_id}.*"):
            f.unlink()
            return True
        return False

    def list_by_source(self, source: str, limit: int = 50) -> List[MediaRef]:
        # TODO: 实际实现需遍历文件，或引入 SQLite 索引
        return []

    @staticmethod
    def _guess_mime(content: bytes, kind: MediaKind) -> str:
        if content[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if content[:2] == b'\xff\xd8':
            return "image/jpeg"
        if content[:4] == b'RIFF' and content[8:12] == b'WAVE':
            return "audio/wav"
        if content[:3] == b'ID3' or content[:2] == b'\xff\xfb':
            return "audio/mpeg"
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"

    @staticmethod
    def _default_ext(kind: MediaKind) -> str:
        return "png" if kind == MediaKind.IMAGE else "mp3"

    @staticmethod
    def _default_mime(kind: MediaKind) -> str:
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"
```

## 5. 三个具体能力

### 5.1 TTS（文本转语音）

```python
# backend/services/multimodal/tts.py

from .capability import AICapability, AIHttpRequest, AIHttpResponse, CapabilityConfig, CapabilityKind
from .media_store import MediaStore, MediaKind, MediaRef

class TTSCapability(AICapability):
    kind = CapabilityKind.TTS
    settings_slot = "ttsModel"

    def build_request(self, config: CapabilityConfig, *,
                      text: str, voice: str = "alloy",
                      response_format: str = "mp3",
                      speed: float = 1.0) -> AIHttpRequest:
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return AIHttpRequest(
            url=f"{config.base_url}/audio/speech",
            headers=headers,
            body={
                "model": config.model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
                "speed": speed,
            },
            timeout=120.0,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> MediaRef:
        if response.status_code != 200:
            raise ValueError(f"TTS upstream returned {response.status_code}")
        store = MediaStore()
        return store.save(
            content=response.content,
            kind=MediaKind.AUDIO,
            source="tts",
            metadata={"text_preview": kwargs.get("text", "")[:100]},
            ext=kwargs.get("response_format", "mp3"),
        )
```

### 5.2 ASR（语音转写）

```python
# backend/services/multimodal/asr.py

from pathlib import Path
from .capability import AICapability, AIHttpRequest, AIHttpResponse, CapabilityConfig, CapabilityKind

class ASRCapability(AICapability):
    kind = CapabilityKind.ASR
    settings_slot = "asrModel"

    def build_request(self, config: CapabilityConfig, *,
                      file_path: str = None,
                      file_content: bytes = None,
                      language: str = None) -> AIHttpRequest:
        if file_path and not file_content:
            file_content = Path(file_path).read_bytes()
            filename = Path(file_path).name
        elif file_content:
            filename = "upload.ogg"
        else:
            raise ValueError("必须提供 file_path 或 file_content")

        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        body = {"model": config.model}
        if language:
            body["language"] = language

        return AIHttpRequest(
            url=f"{config.base_url}/audio/transcriptions",
            headers=headers,
            data={"file": (filename, file_content), **{k: (None, v) for k, v in body.items()}},
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> dict:
        if response.status_code != 200:
            raise ValueError(f"ASR upstream returned {response.status_code}")
        data = response.json or {}
        return {
            "text": data.get("text", ""),
            "language": data.get("language", ""),
        }
```

### 5.3 图像生成

```python
# backend/services/multimodal/image_gen.py

import base64
from typing import List
from .capability import AICapability, AIHttpRequest, AIHttpResponse, CapabilityConfig, CapabilityKind
from .media_store import MediaStore, MediaKind, MediaRef

class ImageGenCapability(AICapability):
    kind = CapabilityKind.IMAGE_GEN
    settings_slot = "imageGenModel"

    def build_request(self, config: CapabilityConfig, *,
                      prompt: str, size: str = "1024x1024",
                      quality: str = "standard", n: int = 1) -> AIHttpRequest:
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return AIHttpRequest(
            url=f"{config.base_url}/images/generations",
            headers=headers,
            body={
                "model": config.model,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "n": n,
                "response_format": "b64_json",
            },
            timeout=120.0,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> List[MediaRef]:
        if response.status_code != 200:
            raise ValueError(f"ImageGen upstream returned {response.status_code}")
        data = response.json or {}
        items = data.get("data", [])
        store = MediaStore()
        refs = []
        for item in items:
            b64 = item.get("b64_json") or item.get("url", "")
            if b64 and not item.get("url"):
                content = base64.b64decode(b64)
                ref = store.save(
                    content=content,
                    kind=MediaKind.IMAGE,
                    source="image_gen",
                    metadata={
                        "prompt": kwargs.get("prompt", ""),
                        "revised_prompt": item.get("revised_prompt", ""),
                    },
                    ext="png",
                )
                refs.append(ref)
        return refs
```

## 6. Agent 工具

### 6.1 TextToSpeechTool

```python
# backend/tools/tts_tool.py

from backend.tools.base import BaseTool, ToolResult, RiskClass

class TextToSpeechTool(BaseTool):
    risk = RiskClass.WRITE
    name = "text_to_speech"
    description = "将文本转为语音音频。返回可播放的音频文件引用。"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要转为语音的文本"},
            "voice": {"type": "string", "default": "alloy",
                      "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]},
            "speed": {"type": "number", "default": 1.0, "minimum": 0.25, "maximum": 4.0},
        },
        "required": ["text"],
    }

    def execute(self, text: str, voice: str = "alloy", speed: float = 1.0,
                **ctx) -> ToolResult:
        from backend.services.multimodal.tts import TTSCapability
        cap = TTSCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="TTS 模型未配置，请先在 设置 → 模型 中配置语音合成(TTS)模型",
            )
        try:
            media_ref = cap.execute(config, text=text, voice=voice, speed=speed)
            return ToolResult(
                success=True,
                content=f"已生成音频: {media_ref.api_url}",
                output={"media_ref": media_ref, "api_url": media_ref.api_url},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"TTS 生成失败: {e}")
```

### 6.2 SpeechToTextTool

```python
# backend/tools/asr_tool.py

from backend.tools.base import BaseTool, ToolResult, RiskClass

class SpeechToTextTool(BaseTool):
    risk = RiskClass.READ
    name = "speech_to_text"
    description = "将音频文件转为文字。支持工作区内的音频文件路径。"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "工作区内音频文件的绝对或相对路径"},
            "language": {"type": "string", "description": "音频语言 (ISO 639-1 代码，如 zh/en/ja)，可选"},
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, language: str = None, **ctx) -> ToolResult:
        from backend.services.multimodal.asr import ASRCapability
        cap = ASRCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="ASR 模型未配置，请先在 设置 → 模型 中配置语音识别(ASR)模型",
            )
        try:
            result = cap.execute(config, file_path=file_path, language=language)
            return ToolResult(
                success=True,
                content=result["text"],
                output=result,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"ASR 转写失败: {e}")
```

### 6.3 ImageGenerationTool

```python
# backend/tools/image_gen_tool.py

from backend.tools.base import BaseTool, ToolResult, RiskClass

class ImageGenerationTool(BaseTool):
    risk = RiskClass.WRITE
    name = "generate_image"
    description = "根据文本描述生成图像。返回图片文件引用。"
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "图像描述（英文效果更佳）"},
            "size": {"type": "string", "default": "1024x1024",
                     "enum": ["256x256", "512x512", "1024x1024", "1792x1024"]},
            "quality": {"type": "string", "default": "standard",
                        "enum": ["standard", "hd"]},
        },
        "required": ["prompt"],
    }

    def execute(self, prompt: str, size: str = "1024x1024",
                quality: str = "standard", **ctx) -> ToolResult:
        from backend.services.multimodal.image_gen import ImageGenCapability
        cap = ImageGenCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="图像生成模型未配置，请先在 设置 → 模型 中配置图像生成模型",
            )
        try:
            media_refs = cap.execute(config, prompt=prompt, size=size, quality=quality)
            urls = [ref.api_url for ref in media_refs]
            return ToolResult(
                success=True,
                content=f"已生成 {len(media_refs)} 张图片: {urls[0] if urls else 'none'}",
                output={"media_refs": media_refs, "api_urls": urls},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"图像生成失败: {e}")
```

### 6.4 工具注册

在 `backend/tools/__init__.py:register_all_tools()` 中新增：

```python
from backend.tools.tts_tool import TextToSpeechTool
from backend.tools.asr_tool import SpeechToTextTool
from backend.tools.image_gen_tool import ImageGenerationTool

registry.register(TextToSpeechTool())
registry.register(SpeechToTextTool())
registry.register(ImageGenerationTool())
```

## 7. 后端 API 路由

### 7.1 Media Serve 路由

```python
# backend/api/media_routes.py

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services.multimodal.media_store import MediaStore, MEDIA_ROOT

router = APIRouter(prefix="/api/v1", tags=["media"])

@router.get("/media/{media_id}")
async def serve_media(media_id: str) -> FileResponse:
    """提供媒体文件的 HTTP 访问"""
    store = MediaStore()
    result = store.load(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media not found")
    ref, content = result
    abs_path = MEDIA_ROOT / ref.file_path
    return FileResponse(
        path=str(abs_path),
        media_type=ref.mime_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

### 7.2 Chat Attachment Upload 路由

```python
# backend/api/chat_attachment_routes.py

from fastapi import APIRouter, UploadFile, File
from backend.services.multimodal.media_store import MediaStore, MediaKind

router = APIRouter(prefix="/api/v1", tags=["chat"])

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4"}
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB

@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """上传聊天附件（音频文件等），存储到 data/media/ 并返回 MediaRef"""
    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
        if ext not in ("mp3", "wav", "ogg", "webm", "m4a", "flac"):
            return {"error": f"不支持的文件类型: {file.content_type}"}

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return {"error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB"}

    store = MediaStore()
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else None
    ref = store.save(
        content=content,
        kind=MediaKind.AUDIO,
        source="chat_upload",
        metadata={"original_filename": file.filename or "unknown"},
        ext=ext,
    )
    return {"media_ref": ref, "api_url": ref.api_url}
```

## 8. 前端变更

### 8.1 Settings 类型扩展

```typescript
// src/entities/setting/types.ts 变更

type ModelCapability = 'chat' | 'vision' | 'embedding' | 'tts' | 'asr' | 'image_gen';

interface ModelSelections {
  chatModel: ModelSelection;
  visionModel: ModelSelection;
  embeddingModel: ModelSelection;
  ttsModel: ModelSelection;        // 新增
  asrModel: ModelSelection;        // 新增
  imageGenModel: ModelSelection;   // 新增
}

// DEFAULT_MODEL_SELECTIONS 增加三个 null slot
```

### 8.2 Backend Canonicalizer 扩展

```python
# backend/data/settings_canonicalizer.py 变更

ALIASES = {
    ...,
    "tts_model": "ttsModel",
    "asr_model": "asrModel",
    "image_gen_model": "imageGenModel",
}

LEGAL_MODEL_SELECTIONS_KEYS = frozenset({
    "chatModel", "visionModel", "embeddingModel",
    "ttsModel", "asrModel", "imageGenModel",
})
```

### 8.3 ModelsTab UI

在 `src/pages/settings/ModelsTab.tsx` 中新增三个 `<ModelSelector>` 组件：

```
聊天模型       → chatModel
视觉理解模型    → visionModel
嵌入模型        → embeddingModel
语音合成 (TTS)  → ttsModel        ← 新增
语音识别 (ASR)  → asrModel        ← 新增
图像生成        → imageGenModel    ← 新增
```

### 8.4 Endpoint 能力推断扩展

```typescript
// src/features/manage-endpoints/api.ts - inferCapabilities() 扩展

function inferCapabilities(modelId: string): ModelCapability[] {
  const caps: ModelCapability[] = ['chat'];
  const lower = modelId.toLowerCase();

  if (/gpt-4o|gpt-4-vision|claude-3|gemini-pro-vision/.test(lower)) {
    caps.push('vision');
  }
  if (/embed|text-embedding|bge|e5/.test(lower)) {
    caps.push('embedding');
  }
  // 新增
  if (/tts|speech-|voice-/.test(lower)) {
    caps.push('tts');
  }
  if (/whisper|asr|transcri/.test(lower)) {
    caps.push('asr');
  }
  if (/dall|image|stable-diffusion|sdxl|flux/.test(lower)) {
    caps.push('image_gen');
  }
  return caps;
}
```

### 8.5 聊天附件上传组件

```tsx
// src/features/send-message/AttachmentUpload.tsx

// 聊天输入框旁的附件按钮 + 拖拽区域
// 上传后返回 MediaRef 给聊天消息作为附件
```

### 8.6 聊天多媒体渲染组件

```tsx
// src/features/chat/MediaAttachment.tsx

// 识别消息中的 media_ref / api_urls
// image/* → <img> + 点击放大
// audio/* → <audio controls>
```

### 8.7 消息数据结构扩展

```typescript
// 在 assistant message 中增加附件字段
interface AssistantMessage {
  // ...existing fields...
  toolOutputs?: Array<{
    toolName: string;
    output?: {
      media_refs?: MediaRef[];
      api_urls?: string[];
      [key: string]: any;
    };
  }>;
}
```

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| 模型未配置 | Tool 返回 `ToolResult(success=False, error="xxx 模型未配置，请先在设置中配置")` |
| 上游 API 401/403 | 透传错误信息，提示 "API 密钥无效或权限不足" |
| 上游 API 超时 | httpx.TimeoutException → "上游服务响应超时" |
| 上游返回非预期格式 | ValueError → "上游返回格式异常" + 记录 trace |
| MediaStore 磁盘满 | OSError → ToolResult error "磁盘空间不足" |
| 聊天附件上传超限 | 返回 error "文件过大" |
| 不支持的文件类型 | 返回 error "不支持的文件类型" |

## 10. 测试策略

| 测试层 | 覆盖 |
|--------|------|
| **单元测试** | 每个 capability 的 `build_request` / `parse_response`（mock httpx） |
| **单元测试** | `MediaStore.save` / `load` / `delete`（tmp_path fixture） |
| **单元测试** | `CapabilityRegistry` 注册/查询/available |
| **单元测试** | 每个 tool 的 `execute`（mock capability） |
| **单元测试** | `load_config` 各种情况（未配置/endpoint 不存在/正常） |
| **集成测试** | Settings canonicalizer 接受新 slot keys |
| **集成测试** | `/api/v1/media/{id}` serve 路由（正常 + 404） |
| **集成测试** | `/api/v1/chat/attachments` upload（正常 + 超限 + 不支持类型） |
| **前端测试** | ModelsTab 渲染 6 个 ModelSelector |
| **前端测试** | `inferCapabilities` 识别新模型类型 |
| **前端测试** | MediaAttachment 渲染 `<img>` / `<audio>` |
| **E2E** | 配置 TTS → agent 调用 → 聊天中出现音频播放器 |

## 11. 新增/修改文件清单

| 类型 | 路径 | 操作 |
|------|------|------|
| 核心抽象 | `backend/services/multimodal/__init__.py` | 新增 |
| 核心抽象 | `backend/services/multimodal/capability.py` | 新增 |
| 媒体存储 | `backend/services/multimodal/media_store.py` | 新增 |
| 注册表 | `backend/services/multimodal/registry.py` | 新增 |
| TTS | `backend/services/multimodal/tts.py` | 新增 |
| ASR | `backend/services/multimodal/asr.py` | 新增 |
| 图像生成 | `backend/services/multimodal/image_gen.py` | 新增 |
| TTS Tool | `backend/tools/tts_tool.py` | 新增 |
| ASR Tool | `backend/tools/asr_tool.py` | 新增 |
| ImageGen Tool | `backend/tools/image_gen_tool.py` | 新增 |
| Media 路由 | `backend/api/media_routes.py` | 新增 |
| 附件路由 | `backend/api/chat_attachment_routes.py` | 新增 |
| 注册工具 | `backend/tools/__init__.py` | 修改 |
| 注册路由 | `backend/main.py` | 修改（mount 新 router） |
| Settings 类型 | `src/entities/setting/types.ts` | 修改 |
| Settings UI | `src/pages/settings/ModelsTab.tsx` | 修改 |
| 端点测试 | `src/features/manage-endpoints/api.ts` | 修改 |
| 聊天附件上传 | `src/features/send-message/AttachmentUpload.tsx` | 新增 |
| 聊天多媒体渲染 | `src/features/chat/MediaAttachment.tsx` | 新增 |
| 单元测试 | `backend/tests/unit/test_multimodal_capability.py` | 新增 |
| 单元测试 | `backend/tests/unit/test_media_store.py` | 新增 |
| 单元测试 | `backend/tests/unit/test_multimodal_tools.py` | 新增 |
| 集成测试 | `backend/tests/integration/test_media_routes.py` | 新增 |
| 集成测试 | `backend/tests/integration/test_chat_attachments.py` | 新增 |
| 前端测试 | `src/features/chat/__tests__/MediaAttachment.test.tsx` | 新增 |
| 前端测试 | `src/pages/settings/__tests__/ModelsTab-multimodal.test.tsx` | 新增 |

## 12. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 上游 API 响应格式不统一（非 OpenAI 兼容） | 中 | 高 | `parse_response` 加宽容解析 + 明确错误提示 |
| 大文件上传导致内存压力 | 低 | 中 | 25MB 上限 + 流式写入（后续优化） |
| `wiki/` 目录下 `embeddings.py` 与新模块概念重叠 | 低 | 低 | 新模块独立在 `services/multimodal/`，不碰 `wiki/` |
| Agent profile 白名单未包含新工具 | 中 | 高 | 更新默认 profile 的 `allowed_tools` |
| 聊天消息渲染器不识别新 tool output 格式 | 中 | 中 | 前端测试覆盖 + 降级为纯文本链接 |

## 13. 里程碑

- **M1**: 核心抽象层 + MediaStore + 单元测试
- **M2**: TTS 能力 + Tool + 测试
- **M3**: ASR 能力 + Tool + 测试
- **M4**: 图像生成能力 + Tool + 测试
- **M5**: Settings 集成（前端类型 + canonicalizer + ModelsTab UI）
- **M6**: 后端 API 路由（media serve + chat attachments）
- **M7**: 前端聊天多媒体渲染 + 附件上传
- **M8**: 集成测试 + E2E
- **M9**: Agent profile 白名单更新 + 文档

## 14. 与现有代码的关系

- **不修改** `backend/wiki/embeddings.py` 和 `backend/wiki/vision.py` — 它们继续服务 wiki 子系统
- **不修改** `backend/api/llm_proxy_routes.py` — 新能力直连上游，不经 proxy
- **不修改** `backend/tools/workspace_index.py` — 保持独立的 embedding 工具
- **新增** `backend/services/multimodal/` 作为独立的多模态服务层
- **未来可选**：将 `wiki/embeddings.py` 迁移为 `AICapability` 子类，统一调用约定（不在本次范围内）
