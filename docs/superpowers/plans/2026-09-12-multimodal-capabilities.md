# 多模态 API 能力补全实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以通用抽象层为基座，补全 TTS + ASR + 图像生成三项多模态能力，通过 agent 工具驱动，生成的多媒体内容在聊天中以本地文件引用方式渲染。

**Architecture:** 引入 `AICapability` 抽象基类 + `CapabilityRegistry` 注册表 + `MediaStore` 文件管理。三个具体能力（TTS/ASR/ImageGen）各自继承基类，通过 `build_request` / `parse_response` 模板方法与上游 OpenAI 兼容 API 交互。Agent 工具（`BaseTool` 子类）调用能力层执行，结果存为本地文件，前端通过 `/api/v1/media/{id}` 渲染。

**Tech Stack:** Python 3.10 / httpx / FastAPI / Pydantic v2 / React 18 / TypeScript / Vitest

**Spec:** `docs/superpowers/specs/2026-09-12-multimodal-capabilities-design.md`

## Global Constraints

- Python 运行环境：conda `sage-backend`（`/home/fz/anaconda3/envs/sage-backend/bin/python`）
- 后端工具调用上游直连 httpx，**不**经过 LLM proxy
- 前端端口 1420（Vite），后端端口 8765（FastAPI）
- 新增工具必须声明 `risk`（`RiskClass.WRITE` 或 `RiskClass.READ`）
- Settings snake_case → camelCase 映射必须在 `settings_canonicalizer.py` 同步
- `modelSelections` 新增 key 必须同步到 `LEGAL_MODEL_SELECTIONS_KEYS`
- `ModelCapability` 联合类型必须包含新能力
- 媒体文件存储在 `data/media/` 下，按日期分目录
- 聊天附件上传限制 25MB，白名单音频类型

---

## File Structure

### 新增文件

| 路径 | 职责 |
|------|------|
| `backend/services/multimodal/__init__.py` | 包初始化 |
| `backend/services/multimodal/capability.py` | AICapability 基类、枚举、数据类 |
| `backend/services/multimodal/media_store.py` | MediaStore 文件管理 |
| `backend/services/multimodal/registry.py` | CapabilityRegistry 注册表 |
| `backend/services/multimodal/tts.py` | TTSCapability |
| `backend/services/multimodal/asr.py` | ASRCapability |
| `backend/services/multimodal/image_gen.py` | ImageGenCapability |
| `backend/tools/tts_tool.py` | TextToSpeechTool |
| `backend/tools/asr_tool.py` | SpeechToTextTool |
| `backend/tools/image_gen_tool.py` | ImageGenerationTool |
| `backend/api/media_routes.py` | GET /api/v1/media/{id} |
| `backend/api/chat_attachment_routes.py` | POST /api/v1/chat/attachments |
| `backend/tests/unit/test_multimodal_capability.py` | 核心抽象 + 能力单元测试 |
| `backend/tests/unit/test_media_store.py` | MediaStore 单元测试 |
| `backend/tests/unit/test_multimodal_tools.py` | 工具单元测试 |
| `backend/tests/integration/test_media_routes.py` | Media 路由集成测试 |
| `backend/tests/integration/test_chat_attachments.py` | 附件上传集成测试 |
| `src/features/chat/MediaAttachment.tsx` | 多媒体消息渲染组件 |
| `src/features/send-message/AttachmentUpload.tsx` | 聊天附件上传组件 |

### 修改文件

| 路径 | 修改内容 |
|------|----------|
| `backend/tools/__init__.py` | 导入并注册 3 个新工具 |
| `backend/main.py` | mount media_router + chat_attachment_router |
| `backend/data/settings_canonicalizer.py` | ALIASES + LEGAL_MODEL_SELECTIONS_KEYS 扩展 |
| `src/entities/setting/types.ts` | ModelCapability 联合类型 + ModelSelections 扩展 |
| `src/pages/settings/ModelsTab.tsx` | 新增 3 个 ModelSelector |
| `src/features/manage-endpoints/api.ts` | inferCapabilities 扩展 |

---

## Milestone 1: 核心抽象层 + MediaStore

### Task 1.1: AICapability 基类 + 数据类

**Files:**
- Create: `backend/services/multimodal/__init__.py`
- Create: `backend/services/multimodal/capability.py`
- Test: `backend/tests/unit/test_multimodal_capability.py`

**Interfaces:**
- Produces: `AICapability`, `CapabilityKind`, `CapabilityConfig`, `AIHttpRequest`, `AIHttpResponse`
- Consumed by: Task 1.3 (TTS), Task 1.4 (ASR), Task 1.5 (ImageGen), Task 1.6 (Registry)

- [ ] **Step 1: 创建包初始化文件**

```python
# backend/services/multimodal/__init__.py
"""多模态 AI 能力抽象层"""
```

- [ ] **Step 2: 写失败测试 — 枚举和数据类**

```python
# backend/tests/unit/test_multimodal_capability.py
"""多模态能力抽象层单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def test_capability_kind_enum():
    from backend.services.multimodal.capability import CapabilityKind
    assert CapabilityKind.TTS.value == "tts"
    assert CapabilityKind.ASR.value == "asr"
    assert CapabilityKind.IMAGE_GEN.value == "image_gen"


def test_capability_config_frozen():
    from backend.services.multimodal.capability import CapabilityConfig
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="tts-1")
    assert config.base_url == "https://api.example.com"
    assert config.api_key == "sk-test"
    assert config.model == "tts-1"
    assert config.extra == {}
    with pytest.raises(AttributeError):
        config.base_url = "changed"


def test_http_request_defaults():
    from backend.services.multimodal.capability import AIHttpRequest
    req = AIHttpRequest(url="https://api.example.com/v1/audio/speech")
    assert req.method == "POST"
    assert req.timeout == 60.0
    assert req.body is None
    assert req.data is None


def test_http_response_fields():
    from backend.services.multimodal.capability import AIHttpResponse
    resp = AIHttpResponse(status_code=200, content=b"hello")
    assert resp.json is None
    assert resp.content_type == ""
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.multimodal'`

- [ ] **Step 4: 实现 capability.py**

```python
# backend/services/multimodal/capability.py
"""AICapability 抽象基类及数据类"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class CapabilityKind(Enum):
    """多模态能力类型"""
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
    """所有多模态能力的基类 — 模板方法模式"""

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
        """从 app_settings 读取本能力的端点配置"""
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

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/__init__.py backend/services/multimodal/capability.py backend/tests/unit/test_multimodal_capability.py
git commit -m "feat(multimodal): add AICapability base class, enums, and data classes"
```

---

### Task 1.2: MediaStore 媒体文件管理

**Files:**
- Create: `backend/services/multimodal/media_store.py`
- Test: `backend/tests/unit/test_media_store.py`

**Interfaces:**
- Produces: `MediaStore`, `MediaKind`, `MediaRef`, `MEDIA_ROOT`
- Consumed by: Task 1.3 (TTS), Task 1.5 (ImageGen), Task 6.1 (media routes), Task 6.2 (chat attachments)

- [ ] **Step 1: 写失败测试 — MediaStore 核心方法**

```python
# backend/tests/unit/test_media_store.py
"""MediaStore 单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def test_media_kind_enum():
    from backend.services.multimodal.media_store import MediaKind
    assert MediaKind.IMAGE.value == "image"
    assert MediaKind.AUDIO.value == "audio"


def test_media_ref_api_url():
    from backend.services.multimodal.media_store import MediaRef, MediaKind
    ref = MediaRef(
        id="abc123", kind=MediaKind.AUDIO, mime_type="audio/mpeg",
        file_path="2026/09/12/abc123.mp3", file_size=1024,
        created_at="2026-09-12T10:00:00Z", source="tts",
    )
    assert ref.api_url == "/api/v1/media/abc123"


def test_save_creates_file(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    # PNG magic bytes
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="image_gen")
    assert ref.kind == MediaKind.IMAGE
    assert ref.mime_type == "image/png"
    assert ref.file_size == len(content)
    assert ref.source == "image_gen"
    assert (tmp_path / ref.file_path).exists()
    assert (tmp_path / ref.file_path).read_bytes() == content


def test_save_audio_with_explicit_ext(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    content = b'\xff\xfb\x90\x00' + b'\x00' * 50
    ref = store.save(content=content, kind=MediaKind.AUDIO, source="tts", ext="mp3")
    assert ref.mime_type == "audio/mpeg"
    assert ref.file_path.endswith(".mp3")


def test_load_existing_media(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="image_gen")
    result = store.load(ref.id)
    assert result is not None
    loaded_ref, loaded_content = result
    assert loaded_ref.id == ref.id
    assert loaded_content == content


def test_load_nonexistent_returns_none(tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(root=tmp_path)
    assert store.load("nonexistent_id") is None


def test_delete_media(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    ref = store.save(content=b'\x89PNG\r\n\x1a\n' + b'\x00' * 5, kind=MediaKind.IMAGE, source="test")
    assert store.delete(ref.id) is True
    assert store.load(ref.id) is None


def test_delete_nonexistent_returns_false(tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(root=tmp_path)
    assert store.delete("nonexistent") is False


def test_guess_mime_magic_bytes():
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    assert MediaStore._guess_mime(b'\x89PNG\r\n\x1a\n' + b'\x00', MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b'\xff\xd8\xff' + b'\x00', MediaKind.IMAGE) == "image/jpeg"
    assert MediaStore._guess_mime(b'RIFF\x00\x00\x00\x00WAVE', MediaKind.AUDIO) == "audio/wav"
    assert MediaStore._guess_mime(b'ID3\x00' + b'\x00', MediaKind.AUDIO) == "audio/mpeg"
    # fallback
    assert MediaStore._guess_mime(b'\x00\x00\x00', MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b'\x00\x00\x00', MediaKind.AUDIO) == "audio/mpeg"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_media_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 media_store.py**

```python
# backend/services/multimodal/media_store.py
"""MediaStore — 媒体文件生命周期管理"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

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

    def save(
        self,
        content: bytes,
        kind: MediaKind,
        source: str,
        metadata: Optional[dict] = None,
        ext: Optional[str] = None,
    ) -> MediaRef:
        """存储媒体文件，返回 MediaRef"""
        media_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
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
            created_at=now.isoformat(),
            source=source,
            metadata=metadata or {},
        )

    def load(self, media_id: str) -> Optional[Tuple[MediaRef, bytes]]:
        """根据 ID 加载媒体文件"""
        for f in self.root.rglob(f"{media_id}.*"):
            content = f.read_bytes()
            rel = str(f.relative_to(self.root))
            kind = (
                MediaKind.IMAGE
                if f.suffix in (".png", ".jpg", ".jpeg", ".webp")
                else MediaKind.AUDIO
            )
            return MediaRef(
                id=media_id,
                kind=kind,
                mime_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream",
                file_path=rel,
                file_size=len(content),
                created_at=datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                source="unknown",
            ), content
        return None

    def delete(self, media_id: str) -> bool:
        """删除媒体文件"""
        for f in self.root.rglob(f"{media_id}.*"):
            f.unlink()
            return True
        return False

    @staticmethod
    def _guess_mime(content: bytes, kind: MediaKind) -> str:
        """通过 magic bytes 推断 MIME 类型"""
        if len(content) >= 8 and content[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if len(content) >= 2 and content[:2] == b'\xff\xd8':
            return "image/jpeg"
        if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WAVE':
            return "audio/wav"
        if len(content) >= 3 and (content[:3] == b'ID3' or content[:2] == b'\xff\xfb'):
            return "audio/mpeg"
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"

    @staticmethod
    def _default_ext(kind: MediaKind) -> str:
        return "png" if kind == MediaKind.IMAGE else "mp3"

    @staticmethod
    def _default_mime(kind: MediaKind) -> str:
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_media_store.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/media_store.py backend/tests/unit/test_media_store.py
git commit -m "feat(multimodal): add MediaStore with date-partitioned storage and MIME detection"
```

---

### Task 1.3: CapabilityRegistry

**Files:**
- Create: `backend/services/multimodal/registry.py`
- Test: `backend/tests/unit/test_multimodal_capability.py` (追加)

**Interfaces:**
- Produces: `CapabilityRegistry`, `register_all_capabilities()`
- Consumed by: Task 2.1-2.3 (tools use registry)

- [ ] **Step 1: 在测试文件末尾追加 registry 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_capability.py

def test_registry_register_and_get():
    from backend.services.multimodal.registry import CapabilityRegistry
    from backend.services.multimodal.capability import AICapability, CapabilityKind, CapabilityConfig, AIHttpRequest, AIHttpResponse

    class DummyCapability(AICapability):
        kind = CapabilityKind.TTS
        settings_slot = "ttsModel"
        def build_request(self, config, **kw): return AIHttpRequest(url="http://x")
        def parse_response(self, resp, **kw): return None

    CapabilityRegistry.register(DummyCapability())
    assert CapabilityRegistry.get(CapabilityKind.TTS) is not None
    assert CapabilityKind.TTS in CapabilityRegistry.all_kinds()
    # 清理
    CapabilityRegistry._capabilities.pop(CapabilityKind.TTS, None)


def test_registry_available_empty():
    from backend.services.multimodal.registry import CapabilityRegistry
    saved = CapabilityRegistry._capabilities.copy()
    CapabilityRegistry._capabilities.clear()
    assert CapabilityRegistry.available() == []
    CapabilityRegistry._capabilities = saved
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py::test_registry_register_and_get -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.multimodal.registry'`

- [ ] **Step 3: 实现 registry.py**

```python
# backend/services/multimodal/registry.py
"""能力注册表 — 集中管理所有多模态能力"""

from __future__ import annotations

from typing import Dict, List, Optional

from .capability import AICapability, CapabilityKind


class CapabilityRegistry:
    """能力注册表"""

    _capabilities: Dict[CapabilityKind, AICapability] = {}

    @classmethod
    def register(cls, capability: AICapability) -> None:
        cls._capabilities[capability.kind] = capability

    @classmethod
    def get(cls, kind: CapabilityKind) -> Optional[AICapability]:
        return cls._capabilities.get(kind)

    @classmethod
    def available(cls) -> List[CapabilityKind]:
        """返回已配置可用的能力列表（load_config 返回非 None）"""
        return [k for k, cap in cls._capabilities.items()
                if cap.load_config() is not None]

    @classmethod
    def all_kinds(cls) -> List[CapabilityKind]:
        return list(cls._capabilities.keys())


def register_all_capabilities() -> None:
    """注册所有多模态能力"""
    from .tts import TTSCapability
    from .asr import ASRCapability
    from .image_gen import ImageGenCapability

    CapabilityRegistry.register(TTSCapability())
    CapabilityRegistry.register(ASRCapability())
    CapabilityRegistry.register(ImageGenCapability())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -v`
Expected: PASS (6 tests total: 4 original + 2 new)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/registry.py backend/tests/unit/test_multimodal_capability.py
git commit -m "feat(multimodal): add CapabilityRegistry with register/get/available"
```

---

## Milestone 2: TTS 能力

### Task 2.1: TTSCapability

**Files:**
- Create: `backend/services/multimodal/tts.py`
- Test: `backend/tests/unit/test_multimodal_capability.py` (追加)

**Interfaces:**
- Produces: `TTSCapability`
- Consumed by: Task 2.2 (TextToSpeechTool)

- [ ] **Step 1: 在测试文件末尾追加 TTS 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_capability.py

def test_tts_build_request():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="tts-1")
    req = cap.build_request(config, text="Hello world", voice="alloy", speed=1.0)
    assert req.url == "https://api.example.com/audio/speech"
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.body["model"] == "tts-1"
    assert req.body["input"] == "Hello world"
    assert req.body["voice"] == "alloy"
    assert req.timeout == 120.0


def test_tts_build_request_no_api_key():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="tts-1")
    req = cap.build_request(config, text="Hello")
    assert "Authorization" not in req.headers


def test_tts_parse_response_saves_file(tmp_path, monkeypatch):
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    from backend.services.multimodal.tts import TTSCapability

    cap = TTSCapability()
    monkeypatch.setattr("backend.services.multimodal.tts.MediaStore",
                        lambda: MediaStore(root=tmp_path))
    resp = AIHttpResponse(status_code=200, content=b'\xff\xfb\x90\x00' + b'\x00' * 50)
    ref = cap.parse_response(resp, text="Hello world test")
    assert ref.kind == MediaKind.AUDIO
    assert ref.source == "tts"
    assert ref.file_size == 54


def test_tts_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    resp = AIHttpResponse(status_code=401, content=b'{"error": "invalid key"}')
    with pytest.raises(ValueError, match="401"):
        cap.parse_response(resp)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py::test_tts_build_request -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 tts.py**

```python
# backend/services/multimodal/tts.py
"""TTS（文本转语音）能力实现"""

from __future__ import annotations

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)
from .media_store import MediaKind, MediaRef, MediaStore


class TTSCapability(AICapability):
    """OpenAI 兼容 TTS API: POST {base_url}/audio/speech"""

    kind = CapabilityKind.TTS
    settings_slot = "ttsModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        text: str,
        voice: str = "alloy",
        response_format: str = "mp3",
        speed: float = 1.0,
    ) -> AIHttpRequest:
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
            raise ValueError(
                f"TTS upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        store = MediaStore()
        return store.save(
            content=response.content,
            kind=MediaKind.AUDIO,
            source="tts",
            metadata={"text_preview": kwargs.get("text", "")[:100]},
            ext=kwargs.get("response_format", "mp3"),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -k tts -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/tts.py backend/tests/unit/test_multimodal_capability.py
git commit -m "feat(multimodal): add TTSCapability with OpenAI-compatible /audio/speech"
```

---

### Task 2.2: TextToSpeechTool

**Files:**
- Create: `backend/tools/tts_tool.py`
- Test: `backend/tests/unit/test_multimodal_tools.py`

**Interfaces:**
- Produces: `TextToSpeechTool(BaseTool)`
- Consumed by: Task 4.3 (tool registration)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_multimodal_tools.py
"""多模态工具单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


# ── TextToSpeechTool ────────────────────────────────────────────

def test_tts_tool_schema():
    from backend.tools.tts_tool import TextToSpeechTool
    tool = TextToSpeechTool()
    assert tool.schema.name == "text_to_speech"
    assert "text" in tool.schema.parameters["required"]


def test_tts_tool_risk():
    from backend.tools.tts_tool import TextToSpeechTool
    from backend.domain.risk import RiskClass
    tool = TextToSpeechTool()
    assert tool.risk == RiskClass.WRITE
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 tts_tool.py**

```python
# backend/tools/tts_tool.py
"""TextToSpeechTool — 将文本转为语音音频"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class TextToSpeechTool(BaseTool):
    """将文本转为语音音频。返回可播放的音频文件引用。"""

    risk = RiskClass.WRITE
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="text_to_speech",
            description="将文本转为语音音频。返回可播放的音频文件引用路径。"
                        "需要先在设置中配置 TTS 模型。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要转为语音的文本内容",
                    },
                    "voice": {
                        "type": "string",
                        "default": "alloy",
                        "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                        "description": "语音角色",
                    },
                    "speed": {
                        "type": "number",
                        "default": 1.0,
                        "minimum": 0.25,
                        "maximum": 4.0,
                        "description": "语速倍率 (0.25-4.0)",
                    },
                },
                "required": ["text"],
            },
        )

    def execute(self, *, text: str, voice: str = "alloy", speed: float = 1.0,
                **kwargs) -> ToolResult:
        from backend.services.multimodal.tts import TTSCapability

        cap = TTSCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="TTS 模型未配置，请先在 设置 → 模型 中配置语音合成(TTS)模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    media_ref = pool.submit(
                        asyncio.run,
                        cap.execute(config, text=text, voice=voice, speed=speed),
                    ).result()
            else:
                media_ref = asyncio.run(
                    cap.execute(config, text=text, voice=voice, speed=speed)
                )

            return ToolResult(
                success=True,
                content=f"已生成音频: {media_ref.api_url}",
                output={"media_ref": media_ref, "api_url": media_ref.api_url},
            )
        except Exception as e:
            logger.exception("TTS execution failed")
            return ToolResult(success=False, error=f"TTS 生成失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -k tts -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/tts_tool.py backend/tests/unit/test_multimodal_tools.py
git commit -m "feat(tools): add TextToSpeechTool with async execution"
```

---

## Milestone 3: ASR 能力

### Task 3.1: ASRCapability

**Files:**
- Create: `backend/services/multimodal/asr.py`
- Test: `backend/tests/unit/test_multimodal_capability.py` (追加)

**Interfaces:**
- Produces: `ASRCapability`
- Consumed by: Task 3.2 (SpeechToTextTool)

- [ ] **Step 1: 在测试文件末尾追加 ASR 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_capability.py

def test_asr_build_request_from_file_content():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="whisper-1")
    req = cap.build_request(config, file_content=b"fake audio data", language="zh")
    assert req.url == "https://api.example.com/audio/transcriptions"
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.data is not None


def test_asr_build_request_from_file_path(tmp_path):
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake audio data")
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="whisper-1")
    req = cap.build_request(config, file_path=str(audio_file))
    assert req.url == "https://api.example.com/audio/transcriptions"


def test_asr_build_request_no_input_raises():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="whisper-1")
    with pytest.raises(ValueError, match="必须提供"):
        cap.build_request(config)


def test_asr_parse_response_success():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    resp = AIHttpResponse(
        status_code=200,
        content=b'{"text": "你好世界", "language": "zh"}',
        json={"text": "你好世界", "language": "zh"},
        content_type="application/json",
    )
    result = cap.parse_response(resp)
    assert result["text"] == "你好世界"
    assert result["language"] == "zh"


def test_asr_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    resp = AIHttpResponse(status_code=500, content=b'error')
    with pytest.raises(ValueError, match="500"):
        cap.parse_response(resp)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -k asr -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 asr.py**

```python
# backend/services/multimodal/asr.py
"""ASR（语音识别 / 语音转写）能力实现"""

from __future__ import annotations

from pathlib import Path

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)


class ASRCapability(AICapability):
    """OpenAI 兼容 ASR API: POST {base_url}/audio/transcriptions (multipart)"""

    kind = CapabilityKind.ASR
    settings_slot = "asrModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        file_path: str = None,
        file_content: bytes = None,
        language: str = None,
    ) -> AIHttpRequest:
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

        fields = {"model": config.model}
        if language:
            fields["language"] = language

        data = {
            "file": (filename, file_content),
            **{k: (None, v) for k, v in fields.items()},
        }

        return AIHttpRequest(
            url=f"{config.base_url}/audio/transcriptions",
            headers=headers,
            data=data,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> dict:
        if response.status_code != 200:
            raise ValueError(
                f"ASR upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        data = response.json or {}
        return {
            "text": data.get("text", ""),
            "language": data.get("language", ""),
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -k asr -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/asr.py backend/tests/unit/test_multimodal_capability.py
git commit -m "feat(multimodal): add ASRCapability with multipart upload support"
```

---

### Task 3.2: SpeechToTextTool

**Files:**
- Create: `backend/tools/asr_tool.py`
- Test: `backend/tests/unit/test_multimodal_tools.py` (追加)

- [ ] **Step 1: 在测试文件末尾追加 ASR tool 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_tools.py

# ── SpeechToTextTool ────────────────────────────────────────────

def test_asr_tool_schema():
    from backend.tools.asr_tool import SpeechToTextTool
    tool = SpeechToTextTool()
    assert tool.schema.name == "speech_to_text"
    assert "file_path" in tool.schema.parameters["required"]


def test_asr_tool_risk():
    from backend.tools.asr_tool import SpeechToTextTool
    from backend.domain.risk import RiskClass
    tool = SpeechToTextTool()
    assert tool.risk == RiskClass.READ
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -k asr -v`
Expected: FAIL

- [ ] **Step 3: 实现 asr_tool.py**

```python
# backend/tools/asr_tool.py
"""SpeechToTextTool — 将音频文件转为文字"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class SpeechToTextTool(BaseTool):
    """将音频文件转为文字。支持工作区内的音频文件路径或聊天附件上传的音频。"""

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="speech_to_text",
            description="将音频文件转为文字。支持工作区内的音频文件路径或聊天附件上传的音频。"
                        "需要先在设置中配置 ASR 模型。",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "音频文件的绝对或相对路径（支持 mp3/wav/ogg/webm/m4a/flac）",
                    },
                    "language": {
                        "type": "string",
                        "description": "音频语言（ISO 639-1 代码，如 zh/en/ja），可选",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(self, *, file_path: str, language: str = None, **kwargs) -> ToolResult:
        from backend.services.multimodal.asr import ASRCapability

        cap = ASRCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="ASR 模型未配置，请先在 设置 → 模型 中配置语音识别(ASR)模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        cap.execute(config, file_path=file_path, language=language),
                    ).result()
            else:
                result = asyncio.run(
                    cap.execute(config, file_path=file_path, language=language)
                )

            return ToolResult(
                success=True,
                content=result["text"],
                output=result,
            )
        except FileNotFoundError:
            return ToolResult(success=False, error=f"音频文件不存在: {file_path}")
        except Exception as e:
            logger.exception("ASR execution failed")
            return ToolResult(success=False, error=f"ASR 转写失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -k asr -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/asr_tool.py backend/tests/unit/test_multimodal_tools.py
git commit -m "feat(tools): add SpeechToTextTool for audio transcription"
```

---

## Milestone 4: 图像生成能力

### Task 4.1: ImageGenCapability

**Files:**
- Create: `backend/services/multimodal/image_gen.py`
- Test: `backend/tests/unit/test_multimodal_capability.py` (追加)

- [ ] **Step 1: 在测试文件末尾追加 ImageGen 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_capability.py

import base64

def test_image_gen_build_request():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.image_gen import ImageGenCapability
    cap = ImageGenCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="dall-e-3")
    req = cap.build_request(config, prompt="a cute cat", size="1024x1024", quality="standard")
    assert req.url == "https://api.example.com/images/generations"
    assert req.body["model"] == "dall-e-3"
    assert req.body["prompt"] == "a cute cat"
    assert req.body["response_format"] == "b64_json"
    assert req.timeout == 120.0


def test_image_gen_parse_response_b64(tmp_path, monkeypatch):
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.image_gen import ImageGenCapability
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    cap = ImageGenCapability()
    monkeypatch.setattr("backend.services.multimodal.image_gen.MediaStore",
                        lambda: MediaStore(root=tmp_path))
    png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    b64_data = base64.b64encode(png_bytes).decode()
    resp = AIHttpResponse(
        status_code=200,
        content=b'{}',
        json={"data": [{"b64_json": b64_data, "revised_prompt": "a cute cat photo"}]},
        content_type="application/json",
    )
    refs = cap.parse_response(resp, prompt="a cute cat")
    assert len(refs) == 1
    assert refs[0].kind == MediaKind.IMAGE
    assert refs[0].source == "image_gen"
    assert refs[0].metadata["prompt"] == "a cute cat"


def test_image_gen_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.image_gen import ImageGenCapability
    cap = ImageGenCapability()
    resp = AIHttpResponse(status_code=400, content=b'bad request')
    with pytest.raises(ValueError, match="400"):
        cap.parse_response(resp)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -k image_gen -v`
Expected: FAIL

- [ ] **Step 3: 实现 image_gen.py**

```python
# backend/services/multimodal/image_gen.py
"""图像生成能力实现"""

from __future__ import annotations

import base64
import logging
from typing import List

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)
from .media_store import MediaKind, MediaRef, MediaStore

logger = logging.getLogger(__name__)


class ImageGenCapability(AICapability):
    """OpenAI 兼容图像生成 API: POST {base_url}/images/generations"""

    kind = CapabilityKind.IMAGE_GEN
    settings_slot = "imageGenModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> AIHttpRequest:
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
            raise ValueError(
                f"ImageGen upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        data = response.json or {}
        items = data.get("data", [])
        store = MediaStore()
        refs: List[MediaRef] = []
        for item in items:
            b64_data = item.get("b64_json")
            if not b64_data:
                continue
            content = base64.b64decode(b64_data)
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

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_capability.py -k image_gen -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/services/multimodal/image_gen.py backend/tests/unit/test_multimodal_capability.py
git commit -m "feat(multimodal): add ImageGenCapability with b64_json response parsing"
```

---

### Task 4.2: ImageGenerationTool

**Files:**
- Create: `backend/tools/image_gen_tool.py`
- Test: `backend/tests/unit/test_multimodal_tools.py` (追加)

- [ ] **Step 1: 在测试文件末尾追加 ImageGen tool 测试**

```python
# 追加到 backend/tests/unit/test_multimodal_tools.py

# ── ImageGenerationTool ──────────────────────────────────────────

def test_image_gen_tool_schema():
    from backend.tools.image_gen_tool import ImageGenerationTool
    tool = ImageGenerationTool()
    assert tool.schema.name == "generate_image"
    assert "prompt" in tool.schema.parameters["required"]


def test_image_gen_tool_risk():
    from backend.tools.image_gen_tool import ImageGenerationTool
    from backend.domain.risk import RiskClass
    tool = ImageGenerationTool()
    assert tool.risk == RiskClass.WRITE
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -k image_gen -v`
Expected: FAIL

- [ ] **Step 3: 实现 image_gen_tool.py**

```python
# backend/tools/image_gen_tool.py
"""ImageGenerationTool — 根据文本描述生成图像"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class ImageGenerationTool(BaseTool):
    """根据文本描述生成图像。返回图片文件引用。"""

    risk = RiskClass.WRITE
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="generate_image",
            description="根据文本描述生成图像。返回图片文件引用路径。"
                        "需要先在设置中配置图像生成模型。",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图像描述（英文效果更佳）",
                    },
                    "size": {
                        "type": "string",
                        "default": "1024x1024",
                        "enum": ["256x256", "512x512", "1024x1024", "1792x1024"],
                        "description": "图片尺寸",
                    },
                    "quality": {
                        "type": "string",
                        "default": "standard",
                        "enum": ["standard", "hd"],
                        "description": "图片质量",
                    },
                },
                "required": ["prompt"],
            },
        )

    def execute(self, *, prompt: str, size: str = "1024x1024",
                quality: str = "standard", **kwargs) -> ToolResult:
        from backend.services.multimodal.image_gen import ImageGenCapability

        cap = ImageGenCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="图像生成模型未配置，请先在 设置 → 模型 中配置图像生成模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    media_refs = pool.submit(
                        asyncio.run,
                        cap.execute(config, prompt=prompt, size=size, quality=quality),
                    ).result()
            else:
                media_refs = asyncio.run(
                    cap.execute(config, prompt=prompt, size=size, quality=quality)
                )

            urls = [ref.api_url for ref in media_refs]
            return ToolResult(
                success=True,
                content=f"已生成 {len(media_refs)} 张图片: {urls[0] if urls else 'none'}",
                output={"media_refs": media_refs, "api_urls": urls},
            )
        except Exception as e:
            logger.exception("ImageGen execution failed")
            return ToolResult(success=False, error=f"图像生成失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py -k image_gen -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/image_gen_tool.py backend/tests/unit/test_multimodal_tools.py
git commit -m "feat(tools): add ImageGenerationTool for text-to-image"
```

---

### Task 4.3: 工具注册

**Files:**
- Modify: `backend/tools/__init__.py` (imports 区域 + register_all_tools 函数)

- [ ] **Step 1: 在 imports 区域末尾添加新工具导入**

在 `backend/tools/__init__.py` 的 imports 区域末尾，添加：

```python
from .tts_tool import TextToSpeechTool
from .asr_tool import SpeechToTextTool
from .image_gen_tool import ImageGenerationTool
```

- [ ] **Step 2: 在 register_all_tools 中注册新工具**

在 `register_all_tools` 函数中（在 `register_mcp_tools` 之前），添加：

```python
    # Multimodal tools: TTS / ASR / Image Generation
    registry.register(TextToSpeechTool(policy=policy))
    registry.register(SpeechToTextTool(policy=policy))
    registry.register(ImageGenerationTool(policy=policy))
```

- [ ] **Step 3: 运行全部多模态相关测试确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_multimodal_tools.py backend/tests/unit/test_multimodal_capability.py backend/tests/unit/test_media_store.py -v`
Expected: ALL PASS

- [ ] **Step 4: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/__init__.py
git commit -m "feat(tools): register TTS/ASR/ImageGen tools in register_all_tools"
```

---

## Milestone 5: Settings 集成

### Task 5.1: Backend settings_canonicalizer 扩展

**Files:**
- Modify: `backend/data/settings_canonicalizer.py` (ALIASES 字典 + LEGAL_MODEL_SELECTIONS_KEYS frozenset)

- [ ] **Step 1: 在 ALIASES 中添加新映射**

在 `backend/data/settings_canonicalizer.py` 的 `ALIASES` 字典中，在 `"embedding_model": "embeddingModel"` 之后添加：

```python
    "tts_model": "ttsModel",
    "asr_model": "asrModel",
    "image_gen_model": "imageGenModel",
```

- [ ] **Step 2: 在 LEGAL_MODEL_SELECTIONS_KEYS 中添加新 key**

将 `LEGAL_MODEL_SELECTIONS_KEYS` 修改为：

```python
LEGAL_MODEL_SELECTIONS_KEYS: FrozenSet[str] = frozenset(
    {
        "chatModel",
        "visionModel",
        "embeddingModel",
        "ttsModel",
        "asrModel",
        "imageGenModel",
    }
)
```

- [ ] **Step 3: 运行现有 settings 测试确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -k "settings" -v --timeout=30`
Expected: PASS (existing tests still pass with new keys)

- [ ] **Step 4: 提交**

```bash
cd /home/fz/project/sage
git add backend/data/settings_canonicalizer.py
git commit -m "feat(settings): add ttsModel/asrModel/imageGenModel to canonicalizer"
```

---

### Task 5.2: Frontend types 扩展

**Files:**
- Modify: `src/entities/setting/types.ts` (ModelCapability 联合类型 + ModelSelections 接口 + DEFAULT_MODEL_SELECTIONS)

- [ ] **Step 1: 扩展 ModelCapability 联合类型**

将 `ModelCapability` 修改为：

```typescript
export type ModelCapability = 'chat' | 'vision' | 'embedding' | 'tts' | 'asr' | 'image_gen';
```

- [ ] **Step 2: 扩展 ModelSelections 接口**

在 `ModelSelections` 接口中添加：

```typescript
export interface ModelSelections {
  chatModel: ModelSelection;
  visionModel: ModelSelection;
  embeddingModel: ModelSelection;
  ttsModel: ModelSelection;
  asrModel: ModelSelection;
  imageGenModel: ModelSelection;
}
```

- [ ] **Step 3: 扩展 DEFAULT_MODEL_SELECTIONS**

```typescript
const DEFAULT_MODEL_SELECTIONS: ModelSelections = {
  chatModel: { ...DEFAULT_MODEL_SELECTION },
  visionModel: { ...DEFAULT_MODEL_SELECTION },
  embeddingModel: { ...DEFAULT_MODEL_SELECTION },
  ttsModel: { ...DEFAULT_MODEL_SELECTION },
  asrModel: { ...DEFAULT_MODEL_SELECTION },
  imageGenModel: { ...DEFAULT_MODEL_SELECTION },
};
```

- [ ] **Step 4: 运行前端类型检查**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -30`
Expected: 无新增类型错误

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add src/entities/setting/types.ts
git commit -m "feat(types): extend ModelCapability and ModelSelections for TTS/ASR/ImageGen"
```

---

### Task 5.3: inferCapabilities 扩展

**Files:**
- Modify: `src/features/manage-endpoints/api.ts` (inferCapabilities 函数)

- [ ] **Step 1: 扩展 inferCapabilities 函数**

将 `inferCapabilities` 函数替换为：

```typescript
function inferCapabilities(modelId: string): ModelCapability[] {
  const lower = modelId.toLowerCase();
  const caps: ModelCapability[] = ['chat'];

  if (
    lower.includes('vision') ||
    lower.includes('gpt-4o') ||
    lower.includes('gemini') ||
    lower.includes('claude-3') ||
    lower.includes('image')
  ) {
    caps.push('vision');
  }
  if (lower.includes('embed') || lower.includes('text-embedding') || lower.includes('vector')) {
    caps.push('embedding');
  }
  // TTS
  if (/tts|speech-|voice-/.test(lower)) {
    caps.push('tts');
  }
  // ASR
  if (/whisper|asr|transcri/.test(lower)) {
    caps.push('asr');
  }
  // Image generation
  if (/dall|image-gen|stable-diffusion|sdxl|flux/.test(lower)) {
    caps.push('image_gen');
  }

  return caps;
}
```

- [ ] **Step 2: 提交**

```bash
cd /home/fz/project/sage
git add src/features/manage-endpoints/api.ts
git commit -m "feat(endpoints): extend inferCapabilities for TTS/ASR/ImageGen model detection"
```

---

### Task 5.4: ModelsTab UI 新增 3 个 ModelSelector

**Files:**
- Modify: `src/pages/settings/ModelsTab.tsx` (model selector 变量 + group 变量 + JSX)

- [ ] **Step 1: 在组件顶部添加新 model selector 变量**

在已有的 `chatModel` / `visionModel` / `embeddingModel` 变量声明附近，添加：

```typescript
  const ttsModel = settings.modelSelections?.ttsModel || { endpointId: null, modelId: null };
  const asrModel = settings.modelSelections?.asrModel || { endpointId: null, modelId: null };
  const imageGenModel = settings.modelSelections?.imageGenModel || { endpointId: null, modelId: null };
```

- [ ] **Step 2: 添加新 model group 变量**

在 `chatModels` / `visionModels` / `embeddingModels` 变量声明附近，添加：

```typescript
  const ttsModels = groupModels('tts' as any);
  const asrModels = groupModels('asr' as any);
  const imageGenModels = groupModels('image_gen' as any);
```

- [ ] **Step 3: 在现有 3 个 ModelSelector 后添加 3 个新组件**

在向量/嵌入模型的 `<ModelSelector>` 之后，添加：

```tsx
      <ModelSelector
        label="语音合成 (TTS)"
        desc="用于文本转语音（选填）"
        groupedModels={ttsModels}
        value={ttsModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, ttsModel: v } })
        }
      />
      <ModelSelector
        label="语音识别 (ASR)"
        desc="用于语音转文字（选填）"
        groupedModels={asrModels}
        value={asrModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, asrModel: v } })
        }
      />
      <ModelSelector
        label="图像生成"
        desc="用于文本生成图像（选填）"
        groupedModels={imageGenModels}
        value={imageGenModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, imageGenModel: v } })
        }
      />
```

- [ ] **Step 4: 运行前端类型检查**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -30`
Expected: 无新增错误

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add src/pages/settings/ModelsTab.tsx
git commit -m "feat(settings): add TTS/ASR/ImageGen model selectors in ModelsTab"
```

---

## Milestone 6: 后端 API 路由

### Task 6.1: Media Serve 路由

**Files:**
- Create: `backend/api/media_routes.py`
- Test: `backend/tests/integration/test_media_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_media_routes.py
"""Media serve 路由集成测试"""

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_serve_media_found(tmp_path, monkeypatch):
    """GET /api/v1/media/{id} 应返回文件"""
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    monkeypatch.setattr("backend.api.media_routes.MEDIA_ROOT", tmp_path)
    store = MediaStore(root=tmp_path)
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="test")

    from backend.api.media_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/media/{ref.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_serve_media_not_found():
    """GET /api/v1/media/{id} 不存在应 404"""
    from backend.api.media_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/media/nonexistent_id")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_media_routes.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 media_routes.py**

```python
# backend/api/media_routes.py
"""媒体文件 serve 路由"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services.multimodal.media_store import MEDIA_ROOT, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

# 使用模块级引用，便于测试 monkeypatch
MEDIA_ROOT_REF = MEDIA_ROOT


@router.get("/media/{media_id}")
async def serve_media(media_id: str) -> FileResponse:
    """提供媒体文件的 HTTP 访问"""
    store = MediaStore()
    result = store.load(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media not found")
    ref, _content = result
    abs_path = MEDIA_ROOT / ref.file_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Media file missing on disk")
    return FileResponse(
        path=str(abs_path),
        media_type=ref.mime_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_media_routes.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/api/media_routes.py backend/tests/integration/test_media_routes.py
git commit -m "feat(api): add GET /api/v1/media/{id} for serving media files"
```

---

### Task 6.2: Chat Attachment Upload 路由

**Files:**
- Create: `backend/api/chat_attachment_routes.py`
- Test: `backend/tests/integration/test_chat_attachments.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_chat_attachments.py
"""Chat attachment upload 集成测试"""

import io

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_upload_audio_attachment(tmp_path, monkeypatch):
    """POST /api/v1/chat/attachments 上传音频文件"""
    from backend.services.multimodal.media_store import MediaStore
    monkeypatch.setattr("backend.services.multimodal.media_store.MEDIA_ROOT", tmp_path)

    from backend.api.chat_attachment_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("test.mp3", io.BytesIO(b'\xff\xfb\x90\x00' + b'\x00' * 50), "audio/mpeg")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "media_ref" in data


@pytest.mark.asyncio
async def test_upload_too_large(tmp_path, monkeypatch):
    """超过 25MB 上限应返回错误"""
    from backend.api.chat_attachment_routes import router, MAX_ATTACHMENT_SIZE
    monkeypatch.setattr("backend.services.multimodal.media_store.MEDIA_ROOT", tmp_path)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        huge = b'\x00' * (MAX_ATTACHMENT_SIZE + 1)
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("huge.mp3", io.BytesIO(huge), "audio/mpeg")},
        )
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_upload_unsupported_type(tmp_path, monkeypatch):
    """不支持的文件类型应返回错误"""
    monkeypatch.setattr("backend.services.multimodal.media_store.MEDIA_ROOT", tmp_path)

    from backend.api.chat_attachment_routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("test.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")},
        )
    data = resp.json()
    assert "error" in data
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_attachments.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 chat_attachment_routes.py**

```python
# backend/api/chat_attachment_routes.py
"""聊天附件上传路由"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, UploadFile

from backend.services.multimodal.media_store import MediaKind, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4", "audio/x-m4a"}
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "webm", "m4a", "flac"}
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB


@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """上传聊天附件（音频文件等），存储到 data/media/ 并返回 MediaRef"""
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return {"error": f"不支持的文件类型: {file.content_type}"}

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return {
            "error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB"
        }

    store = MediaStore()
    ref = store.save(
        content=content,
        kind=MediaKind.AUDIO,
        source="chat_upload",
        metadata={"original_filename": file.filename or "unknown"},
        ext=ext if ext else None,
    )
    return {"media_ref": ref, "api_url": ref.api_url}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_attachments.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage
git add backend/api/chat_attachment_routes.py backend/tests/integration/test_chat_attachments.py
git commit -m "feat(api): add POST /api/v1/chat/attachments for audio upload"
```

---

### Task 6.3: 在 main.py 中挂载新路由

**Files:**
- Modify: `backend/main.py` (路由挂载区域)

- [ ] **Step 1: 在 main.py 中添加新路由导入和挂载**

在 `backend/main.py` 的路由挂载区域（在已有 `app.include_router(...)` 调用附近），添加：

```python
# Multimodal: media file serving + chat attachment upload
from backend.api.media_routes import router as media_router
from backend.api.chat_attachment_routes import router as chat_attachment_router

app.include_router(media_router, prefix="/api/v1")
app.include_router(chat_attachment_router, prefix="/api/v1")
```

- [ ] **Step 2: 运行 smoke test 确认启动无异常**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.main import app; print('OK:', len(app.routes), 'routes')"`
Expected: `OK: <N> routes` — 无异常

- [ ] **Step 3: 提交**

```bash
cd /home/fz/project/sage
git add backend/main.py
git commit -m "feat(api): mount media and chat attachment routers in main.py"
```

---

## Milestone 7: 前端多媒体渲染 + 附件上传

### Task 7.1: MediaAttachment 组件

**Files:**
- Create: `src/features/chat/MediaAttachment.tsx`

- [ ] **Step 1: 实现 MediaAttachment 组件**

```tsx
// src/features/chat/MediaAttachment.tsx
import React, { useState } from 'react';

interface MediaAttachmentProps {
  /** API URL like /api/v1/media/{id} */
  url: string;
  /** MIME type e.g. "image/png", "audio/mpeg" */
  mimeType: string;
  /** Optional alt text / caption */
  caption?: string;
}

/**
 * Renders a media attachment in chat messages.
 * - image/* → <img> with click-to-zoom
 * - audio/* → <audio controls>
 * - fallback → download link
 */
export const MediaAttachment: React.FC<MediaAttachmentProps> = ({ url, mimeType, caption }) => {
  const [zoomed, setZoomed] = useState(false);

  if (mimeType.startsWith('image/')) {
    return (
      <>
        <div className="my-2">
          <img
            src={url}
            alt={caption || 'Generated image'}
            className="max-w-sm rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
            onClick={() => setZoomed(true)}
          />
          {caption && <p className="text-xs text-muted mt-1">{caption}</p>}
        </div>
        {zoomed && (
          <div
            className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
            onClick={() => setZoomed(false)}
          >
            <img
              src={url}
              alt={caption || 'Generated image'}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        )}
      </>
    );
  }

  if (mimeType.startsWith('audio/')) {
    return (
      <div className="my-2">
        <audio controls src={url} className="max-w-sm w-full">
          Your browser does not support audio playback.
        </audio>
        {caption && <p className="text-xs text-muted mt-1">{caption}</p>}
      </div>
    );
  }

  // Fallback: download link
  return (
    <div className="my-2">
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm text-accent hover:underline"
      >
        📎 {caption || 'Download media'}
      </a>
    </div>
  );
};
```

- [ ] **Step 2: 提交**

```bash
cd /home/fz/project/sage
git add src/features/chat/MediaAttachment.tsx
git commit -m "feat(chat): add MediaAttachment component for image/audio rendering"
```

---

### Task 7.2: AttachmentUpload 组件

**Files:**
- Create: `src/features/send-message/AttachmentUpload.tsx`

- [ ] **Step 1: 实现 AttachmentUpload 组件**

```tsx
// src/features/send-message/AttachmentUpload.tsx
import React, { useCallback, useRef, useState } from 'react';

interface AttachmentUploadProps {
  onAttachmentUploaded: (attachment: { mediaRef: any; apiUrl: string }) => void;
  onError?: (error: string) => void;
}

const ACCEPTED_TYPES = 'audio/mpeg,audio/wav,audio/ogg,audio/webm,audio/mp4,audio/x-m4a';
const MAX_SIZE = 25 * 1024 * 1024;

/**
 * Chat attachment upload button with drag-and-drop support.
 * Uploads audio files to /api/v1/chat/attachments and returns MediaRef.
 */
export const AttachmentUpload: React.FC<AttachmentUploadProps> = ({
  onAttachmentUploaded,
  onError,
}) => {
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(
    async (file: File) => {
      if (file.size > MAX_SIZE) {
        onError?.(`文件过大 (${(file.size / 1024 / 1024).toFixed(1)}MB)，上限 25MB`);
        return;
      }

      setUploading(true);
      try {
        const formData = new FormData();
        formData.append('file', file);

        const resp = await fetch('/api/v1/chat/attachments', {
          method: 'POST',
          body: formData,
        });

        const data = await resp.json();
        if (data.error) {
          onError?.(data.error);
          return;
        }

        onAttachmentUploaded({
          mediaRef: data.media_ref,
          apiUrl: data.api_url,
        });
      } catch (err) {
        onError?.(`上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
      } finally {
        setUploading(false);
      }
    },
    [onAttachmentUploaded, onError],
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <div className="relative">
      <button
        type="button"
        className="p-1.5 rounded-md text-muted hover:text-text hover:bg-surface-hover transition-colors disabled:opacity-50"
        title="上传音频文件"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
      >
        {uploading ? (
          <span className="animate-pulse">⏳</span>
        ) : (
          <span>📎</span>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="hidden"
        onChange={handleFileChange}
      />
    </div>
  );
};
```

- [ ] **Step 2: 提交**

```bash
cd /home/fz/project/sage
git add src/features/send-message/AttachmentUpload.tsx
git commit -m "feat(chat): add AttachmentUpload component for audio file upload"
```

---

## Milestone 8: 集成测试 + 回归验证

### Task 8.1: 全量后端测试

- [ ] **Step 1: 运行所有多模态相关测试**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_multimodal_capability.py \
  backend/tests/unit/test_media_store.py \
  backend/tests/unit/test_multimodal_tools.py \
  backend/tests/integration/test_media_routes.py \
  backend/tests/integration/test_chat_attachments.py \
  -v --tb=short
```
Expected: ALL PASS

- [ ] **Step 2: 运行 settings canonicalizer 测试确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -k "settings" -v --timeout=30`
Expected: PASS

- [ ] **Step 3: 运行全量单元测试确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ --timeout=60 -q`
Expected: 无新增失败

---

## Milestone 9: Profile 白名单 + 构建验证

### Task 9.1: Agent Profile 白名单更新

- [ ] **Step 1: 查找默认 profile 定义**

Run: `cd /home/fz/project/sage && grep -rn "allowed_tools" backend/data/ --include="*.py" -l`

- [ ] **Step 2: 将新工具加入默认 profile 的 allowed_tools**

根据 Step 1 找到的文件，在 `allowed_tools` 列表中添加：

```python
"text_to_speech", "speech_to_text", "generate_image",
```

- [ ] **Step 3: 运行 profile 相关测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -k "profile" -v --timeout=30`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
cd /home/fz/project/sage
git add -A
git commit -m "feat(profile): add TTS/ASR/ImageGen tools to default profile whitelist"
```

---

### Task 9.2: 前端构建验证

- [ ] **Step 1: 运行前端类型检查**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -20`
Expected: 无新增类型错误

- [ ] **Step 2: 运行前端构建**

Run: `cd /home/fz/project/sage && npm run build 2>&1 | tail -20`
Expected: BUILD SUCCESS

- [ ] **Step 3: 提交（如有类型修复）**

```bash
cd /home/fz/project/sage
git add -A
git commit -m "fix(frontend): resolve TypeScript errors for multimodal types"
```

---

## 实施顺序总结

```
M1 (核心抽象 + MediaStore + Registry)
  ↓
M2 (TTS: capability + tool)  ──┐
M3 (ASR: capability + tool)  ──┼── 可并行
M4 (ImageGen: capability + tool) ─┘
  ↓
M5 (Settings: canonicalizer + types + UI)
  ↓
M6 (API routes: media + attachments + main.py mount)
  ↓
M7 (Frontend: MediaAttachment + AttachmentUpload)
  ↓
M8 (Integration tests)
  ↓
M9 (Profile whitelist + build verification)
```
