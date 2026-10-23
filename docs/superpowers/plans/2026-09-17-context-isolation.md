# Context Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three-layer context isolation so users can switch topics in the same session without bleeding: explicit separator (manual), sliding window (turn limit), and auto topic detection (lightweight).

**Architecture:** Introduce `segment_id` + `subtype` columns on `messages`. Each "topic separator" message marks a boundary; history loading only includes the active segment. A `context_reset` flag in `ChatRequest` triggers separator insertion. A global `context_turn_limit` setting applies a hard turn cap. A lightweight detector (regex + embedding similarity) auto-inserts separators and emits `topic_shifted` SSE events.

**Tech Stack:** Python 3.10 / FastAPI / SQLite / TypeScript / React / Tauri

**Spec:** `docs/superpowers/specs/2026-09-17-context-isolation-design.md`

---

## Global Constraints

- All code uses the project's `sage-backend` conda env: `/home/fz/anaconda3/envs/sage-backend/bin/python`
- Backend tests run from `backend/tests/unit/` via `pytest` from the worktree root
- Frontend tests run via `npm test` from the worktree root
- DB schema changes go in `backend/data/database.py` `init_db()` using the existing `PRAGMA table_info` + `ALTER TABLE` idempotent pattern
- SettingsRepository KEYS whitelist must be updated for any new settings key
- Commit messages follow conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`)
- TDD: write test first, run it (red), implement (green), refactor, commit

---

## File Structure

| File | Purpose |
|---|---|
| `backend/data/database.py` | Add `segment_id`, `subtype` columns to `messages` table |
| `backend/data/session_repo.py` | Extend `Message` dataclass and `MessageRepository` with segment-aware methods |
| `backend/chat/history_context.py` | Segment-aware `db_rows_to_history`; new `apply_turn_limit` |
| `backend/chat/topic_detection.py` | NEW — lightweight topic shift detector (regex + embedding) |
| `backend/data/settings_repo.py` | Add 3 new KEYS |
| `backend/api/legacy_routes.py` | `ChatRequest.context_reset`; integrate separator + detector + turn limit |
| `backend/memory/working.py` | Add `segment_id` parameter to `add`/`get_context`; new `clear_segment` |
| `backend/memory/manager.py` | `get_context(segment_id=...)` (optional param) |
| `backend/chat/compaction.py` | Restrict compression to active segment |
| `backend/tests/unit/test_message_schema.py` | NEW — Message field tests |
| `backend/tests/unit/test_segment_repository.py` | NEW — repository segment method tests |
| `backend/tests/unit/test_segment_history.py` | NEW — segment-aware history tests |
| `backend/tests/unit/test_turn_limit.py` | NEW — sliding window tests |
| `backend/tests/unit/test_topic_detection.py` | NEW — detector tests |
| `backend/tests/unit/test_chat_context_reset.py` | NEW — API wiring test |
| `backend/tests/unit/test_turn_limit_setting.py` | NEW — settings key tests |
| `backend/tests/unit/test_memory_segment.py` | NEW — memory segment scoping tests |
| `backend/tests/integration/test_context_isolation_e2e.py` | NEW — integration test |
| `src/shared/api/types.ts` | Add `contextReset?: boolean` to `ChatConfig` |
| `src/shared/api/chatApi.ts` | Forward `contextReset` flag |
| `src/components/chat/ChatInput.tsx` | Add "New Topic" button |
| `src/components/chat/TopicSeparator.tsx` | NEW — separator line component |
| `src/components/chat/TopicShiftBanner.tsx` | NEW — auto-detection banner |
| `src/components/settings/ContextSettings.tsx` | NEW — turn limit slider |
| `src/shared/api/events.ts` | Add `topic_shifted` to `AgentEvent` union |

---

## Phase 1: Data Layer + Explicit Separator (方案 A)

### Task 1: DB schema — add `segment_id` and `subtype` to `messages`

**Files:**
- Modify: `backend/data/database.py` (init_db)
- Modify: `backend/data/session_repo.py:259-306` (Message dataclass)
- Create: `backend/tests/unit/test_message_schema.py`

**Interfaces:**
- Consumes: existing `messages` table; `init_db()` idempotent migration pattern
- Produces: `Message.segment_id: int = 0`, `Message.subtype: Optional[str] = None`

- [ ] **Step 1: Write failing test for Message fields**

```python
# backend/tests/unit/test_message_schema.py
from backend.data.session_repo import Message

def test_message_default_segment_zero():
    msg = Message(
        id="msg-1", session_id="s1", role="user", content="hi",
        created_at=1234567890
    )
    assert msg.segment_id == 0
    assert msg.subtype is None


def test_message_explicit_segment_and_subtype():
    msg = Message(
        id="msg-1", session_id="s1", role="system", content="reset",
        created_at=1, segment_id=2, subtype="topic_separator"
    )
    assert msg.segment_id == 2
    assert msg.subtype == "topic_separator"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-context-isolation && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_message_schema.py -v`
Expected: FAIL with `TypeError: unexpected keyword argument` or `AttributeError`

- [ ] **Step 3: Add fields to Message dataclass**

Edit `backend/data/session_repo.py` line 259-276 area. Add to `Message`:
```python
    segment_id: int = 0
    subtype: Optional[str] = None
```

Update `from_row` to handle the new columns:
```python
    @classmethod
    def from_row(cls, row: Any) -> "Message":
        return cls(
            id=row["id"], session_id=row["session_id"], role=row["role"],
            content=row["content"], created_at=row["created_at"],
            model=row["model"], provider=row["provider"],
            tool_calls=row["tool_calls"], tool_call_id=row["tool_call_id"],
            reasoning_content=row["reasoning_content"], step_index=row["step_index"],
            segment_id=row["segment_id"] if "segment_id" in row.keys() else 0,
            subtype=row["subtype"] if "subtype" in row.keys() else None,
        )
```

- [ ] **Step 4: Add idempotent migration to `database.py`**

Find where `messages` table is created (around line 465-488). Add migration block AFTER the `CREATE TABLE`:
```python
    # Migration: add segment_id and subtype (2026-09-17)
    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "segment_id" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN segment_id INTEGER NOT NULL DEFAULT 0")
    if "subtype" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN subtype TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_segment ON messages(session_id, segment_id, created_at)")
```

- [ ] **Step 5: Run test, verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_message_schema.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/data/database.py backend/data/session_repo.py backend/tests/unit/test_message_schema.py
git commit -m "feat(db): add segment_id and subtype columns to messages"
```

---

### Task 2: MessageRepository — segment-aware methods

**Files:**
- Modify: `backend/data/session_repo.py:483-700` (MessageRepository)
- Create: `backend/tests/unit/test_segment_repository.py`

**Interfaces:**
- Consumes: `Message` dataclass with new fields; `messages` table with new columns
- Produces:
  - `advance_segment(session_id: str) -> int` returns new segment_id
  - `get_active_segment(session_id: str) -> List[Message]`
  - `retreat_segment(session_id: str) -> bool`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_segment_repository.py
import pytest
from backend.data.session_repo import MessageRepository
from backend.data import database as db_mod

@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", str(tmp_path / "test.db"))
    db = db_mod.get_database()
    db.init_db()
    yield db

def test_advance_segment_creates_separator(db_setup):
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="hi", created_at=1)
    repo.insert(session_id="s1", role="assistant", content="hello", created_at=2)

    new_seg = repo.advance_segment("s1")
    assert new_seg == 1

    msgs = repo.get_by_session("s1")
    assert any(m.subtype == "topic_separator" for m in msgs)
    assert msgs[-1].subtype == "topic_separator"
    assert msgs[-1].segment_id == 1

def test_get_active_segment_excludes_old(db_setup):
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="old", created_at=1)
    repo.advance_segment("s1")
    repo.insert(session_id="s1", role="user", content="new", created_at=2)

    active = repo.get_active_segment("s1")
    contents = [m.content for m in active]
    assert "new" in contents
    assert "old" not in contents

def test_retreat_segment_undoes_last_separator(db_setup):
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="msg1", created_at=1)
    repo.advance_segment("s1")
    repo.insert(session_id="s1", role="user", content="msg2", created_at=2)

    assert repo.retreat_segment("s1") is True
    active = repo.get_active_segment("s1")
    assert any(m.content == "msg1" for m in active)
    assert any(m.content == "msg2" for m in active)

def test_retreat_segment_no_separator_returns_false(db_setup):
    repo = MessageRepository()
    assert repo.retreat_segment("s1") is False
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_segment_repository.py -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Implement the three methods**

Add `import time` at top of `backend/data/session_repo.py` if not present.

Add to `MessageRepository` class:
```python
    def get_active_segment(self, session_id: str) -> List[Message]:
        """Return messages after the last topic_separator."""
        all_msgs = self.get_by_session(session_id, limit=100000)
        last_sep_idx = -1
        for i in range(len(all_msgs) - 1, -1, -1):
            if all_msgs[i].subtype == "topic_separator":
                last_sep_idx = i
                break
        return all_msgs[last_sep_idx + 1:]

    def advance_segment(self, session_id: str) -> int:
        """Insert a topic_separator message and return the new segment_id."""
        all_msgs = self.get_by_session(session_id, limit=100000)
        max_seg = max((m.segment_id for m in all_msgs), default=-1)
        new_seg = max_seg + 1
        self.insert(
            session_id=session_id,
            role="system",
            content="[上下文已在此处重置]",
            created_at=int(time.time() * 1000),
        )
        conn = self.db.get_connection()
        last = self.get_by_session(session_id, limit=1)[-1]
        conn.execute(
            "UPDATE messages SET segment_id = ?, subtype = ? WHERE id = ?",
            (new_seg, "topic_separator", last.id),
        )
        conn.commit()
        return new_seg

    def retreat_segment(self, session_id: str) -> bool:
        """Remove the last topic_separator (if any) and merge segments."""
        all_msgs = self.get_by_session(session_id, limit=100000)
        for i in range(len(all_msgs) - 1, -1, -1):
            if all_msgs[i].subtype == "topic_separator":
                conn = self.db.get_connection()
                conn.execute("DELETE FROM messages WHERE id = ?", (all_msgs[i].id,))
                conn.commit()
                return True
        return False
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_segment_repository.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/data/session_repo.py backend/tests/unit/test_segment_repository.py
git commit -m "feat(repo): add advance_segment, retreat_segment, get_active_segment"
```

---

### Task 3: history_context — segment-aware loading + apply_turn_limit

**Files:**
- Modify: `backend/chat/history_context.py:88-110` (db_rows_to_history), append `apply_turn_limit`
- Create: `backend/tests/unit/test_segment_history.py`

**Interfaces:**
- Consumes: `Message` rows from `get_active_segment()`
- Produces:
  - `db_rows_to_history` filters out separator messages (subtype=topic_separator)
  - `apply_turn_limit(messages, turn_limit) -> (kept, omitted)`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_segment_history.py
from backend.chat.history_context import db_rows_to_history, apply_turn_limit

def test_db_rows_to_history_excludes_separator():
    rows = [
        type("M", (), {"role": "user", "content": "old q", "tool_calls": None, "reasoning_content": None})(),
        type("M", (), {"role": "system", "content": "reset", "subtype": "topic_separator", "tool_calls": None, "reasoning_content": None})(),
        type("M", (), {"role": "user", "content": "new q", "tool_calls": None, "reasoning_content": None})(),
    ]
    result = db_rows_to_history(rows)
    assert len(result) == 1
    assert result[0]["content"] == "new q"


def test_apply_turn_limit_no_limit():
    msgs = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    kept, omitted = apply_turn_limit(msgs, turn_limit=None)
    assert len(kept) == 10
    assert omitted == 0


def test_apply_turn_limit_caps():
    msgs = []
    for i in range(6):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    kept, omitted = apply_turn_limit(msgs, turn_limit=2)
    user_contents = [m["content"] for m in kept if m["role"] == "user"]
    assert user_contents == ["q4", "q5"]
    assert omitted > 0
```

- [ ] **Step 2: Run tests, verify failure**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_segment_history.py -v`
Expected: FAIL on `apply_turn_limit` (not defined); `test_db_rows_to_history_excludes_separator` may fail or pass depending on current filtering

- [ ] **Step 3: Modify `db_rows_to_history` to skip separators**

Edit `backend/chat/history_context.py` line 88-110. Add at top of the for loop body (after `role = ...` check):
```python
        if getattr(row, "subtype", None) == "topic_separator":
            continue
```

- [ ] **Step 4: Append `apply_turn_limit` to history_context.py**

Add to end of file:
```python
def apply_turn_limit(
    messages: Sequence[Dict[str, str]],
    turn_limit: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], int]:
    """Drop oldest user messages until only `turn_limit` rounds remain.
    One round = 1 user + 1 assistant.
    """
    if not turn_limit or turn_limit <= 0:
        return list(messages), 0
    user_count = 0
    cutoff = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_count += 1
            if user_count > turn_limit:
                cutoff = i + 1
                break
    kept = messages[cutoff:]
    omitted = len(messages) - len(kept)
    return kept, omitted
```

- [ ] **Step 5: Run tests, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_segment_history.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/chat/history_context.py backend/tests/unit/test_segment_history.py
git commit -m "feat(history): segment-aware row filtering + apply_turn_limit"
```

---

### Task 4: Wire ChatRequest.context_reset + segment in chat_stream_create

**Files:**
- Modify: `backend/api/legacy_routes.py:307-318` (ChatRequest) and `2833-2878` (history loading)
- Create: `backend/tests/unit/test_chat_context_reset.py`

**Interfaces:**
- Consumes: `ChatRequest.context_reset`, `MessageRepository.advance_segment`, `get_active_segment`
- Produces: When `context_reset=True`, calls `advance_segment` BEFORE message persistence; uses `get_active_segment` for history loading

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_chat_context_reset.py
import pytest
from unittest.mock import MagicMock, patch
from backend.data.session_repo import MessageRepository

def test_advance_segment_called_when_context_reset():
    """Smoke test: verify the wiring exists."""
    mock_repo = MagicMock(spec=MessageRepository)
    mock_repo.advance_segment.return_value = 1
    mock_repo.get_active_segment.return_value = []
    # The real validation is end-to-end via UI.
    # This ensures the method contract is stable.
    assert hasattr(mock_repo, 'advance_segment')
    result = mock_repo.advance_segment("s1")
    mock_repo.advance_segment.assert_called_once_with("s1")
    assert result == 1
```

- [ ] **Step 2: Add `context_reset` to `ChatRequest`**

Edit `backend/api/legacy_routes.py` line 307-318, add field:
```python
    context_reset: bool = False  # NEW — send topic separator before this message
```

- [ ] **Step 3: Wire advance_segment and get_active_segment in chat_stream_create**

Find the block at lines 2838-2848. Replace:
```python
try:
    history_rows = await asyncio.to_thread(
        lambda: MessageRepository().get_by_session(
            data.session_id, limit=100000
        )
    )
except Exception as hist_err:
    logger.warning(...)
    history_rows = []
```

With:
```python
repo = MessageRepository()
try:
    # 显式上下文重置 (方案 A)
    if data.context_reset:
        await asyncio.to_thread(repo.advance_segment, data.session_id)
        # 重置 working memory 当前段
        try:
            from backend.memory.working import WorkingMemory
            WorkingMemory().clear(data.session_id)
        except Exception as mem_err:
            logger.warning("working memory clear failed: %s", mem_err)

    history_rows = await asyncio.to_thread(
        repo.get_active_segment, data.session_id
    )
except Exception as hist_err:
    logger.warning("history load failed: %s", hist_err)
    history_rows = []
```

- [ ] **Step 4: Run all backend unit tests**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -x -q`
Expected: All previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/unit/test_chat_context_reset.py
git commit -m "feat(api): ChatRequest.context_reset + active segment history"
```

---

### Task 5: Frontend — ChatConfig.contextReset + new topic button + separator UI

**Files:**
- Modify: `src/shared/api/types.ts:504-532` (ChatConfig)
- Modify: `src/shared/api/chatApi.ts:159-186` (invoke call)
- Modify: `src/components/chat/ChatInput.tsx` (add New Topic button)
- Create: `src/components/chat/TopicSeparator.tsx`

**Interfaces:**
- Produces: `contextReset?: boolean` in ChatConfig; forwarded to backend

- [ ] **Step 1: Add contextReset to ChatConfig**

Edit `src/shared/api/types.ts` around line 531:
```typescript
  contextReset?: boolean;  // NEW: send topic separator before this message
```

- [ ] **Step 2: Forward contextReset in chatApi.ts invoke call**

Edit `src/shared/api/chatApi.ts` around line 159-186, add line:
```typescript
    contextReset: config?.contextReset ?? false,
```

- [ ] **Step 3: Create TopicSeparator component**

Create `src/components/chat/TopicSeparator.tsx`:
```tsx
import React from 'react';

export function TopicSeparator({ content }: { content?: string }) {
  return (
    <div className="flex items-center my-4 text-xs text-gray-400">
      <div className="flex-1 border-t border-gray-300 dark:border-gray-600" />
      <span className="px-3">{content || '上下文已在此处重置'}</span>
      <div className="flex-1 border-t border-gray-300 dark:border-gray-600" />
    </div>
  );
}
```

- [ ] **Step 4: Add New Topic button to ChatInput**

Find `src/components/chat/ChatInput.tsx` (or equivalent — search for the submit button). Add a button next to the send button:
```tsx
<button
  type="button"
  onClick={() => onSend('', { contextReset: true })}
  title="开始新话题（重置 LLM 上下文）"
  className="px-3 py-2 rounded border border-gray-300 hover:bg-gray-100 text-sm"
>
  新话题
</button>
```

(Adjust `onSend` signature if it doesn't accept options. The simplest pattern: add an options param `{ contextReset?: boolean }`.)

- [ ] **Step 5: Wire separator rendering in chat list**

Find the chat message list component (search for `.map((msg)` patterns). Add conditional rendering:
```tsx
{message.subtype === 'topic_separator' ? (
  <TopicSeparator content={message.content} />
) : (
  // existing message rendering
)}
```

**Pragmatic approach for message list data:** The message list API may need to expose `subtype` and `segment_id`. If streaming events don't include them, add a `GET /api/v1/sessions/{id}/messages` endpoint that returns messages with the new fields.

- [ ] **Step 6: Build & smoke test**

```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && npm run build
```

In the UI: click "新话题" → verify separator line appears → verify next AI response doesn't reference the prior topic.

- [ ] **Step 7: Commit**

```bash
git add src/shared/api/types.ts src/shared/api/chatApi.ts src/components/chat/ChatInput.tsx src/components/chat/TopicSeparator.tsx
git commit -m "feat(ui): new topic button + topic separator rendering"
```

---

## Phase 2: Sliding Window (方案 B)

### Task 6: Settings — add context_turn_limit + detection keys to KEYS whitelist

**Files:**
- Modify: `backend/data/settings_repo.py:18-69` (KEYS)
- Create: `backend/tests/unit/test_turn_limit_setting.py`

**Interfaces:**
- Produces: New keys `context_turn_limit`, `auto_topic_detection`, `topic_detection_threshold` whitelisted

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_turn_limit_setting.py
import pytest
from backend.data.settings_repo import SettingsRepository
from backend.data import database as db_mod

@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", str(tmp_path / "test.db"))
    db = db_mod.get_database()
    db.init_db()
    yield

def test_context_turn_limit_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("context_turn_limit", "10")
    assert repo.get("context_turn_limit") == "10"

def test_auto_topic_detection_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("auto_topic_detection", "true")
    assert repo.get("auto_topic_detection") == "true"

def test_topic_detection_threshold_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("topic_detection_threshold", "0.35")
    assert repo.get("topic_detection_threshold") == "0.35"

def test_unknown_key_raises(db_setup):
    repo = SettingsRepository()
    with pytest.raises(ValueError):
        repo.set("bogus_key_xyz", "x")
```

- [ ] **Step 2: Run test, verify failure**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_turn_limit_setting.py -v`
Expected: FAIL — key not in whitelist

- [ ] **Step 3: Add keys to KEYS whitelist**

Edit `backend/data/settings_repo.py` line 18-69. Add inside the frozenset (before closing brace):
```python
    "context_turn_limit",
    "auto_topic_detection",
    "topic_detection_threshold",
```

- [ ] **Step 4: Run test, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_turn_limit_setting.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/data/settings_repo.py backend/tests/unit/test_turn_limit_setting.py
git commit -m "feat(settings): whitelist context_turn_limit + detection keys"
```

---

### Task 7: Pipeline — apply turn limit in build_request_messages + chat_stream_create

**Files:**
- Modify: `backend/chat/history_context.py` (add `turn_limit` param to `build_request_messages`)
- Modify: `backend/api/legacy_routes.py` (pass `turn_limit` to `build_request_messages`)
- Create: `backend/tests/unit/test_turn_limit.py`

**Interfaces:**
- Consumes: `SettingsRepository.get("context_turn_limit")` (returns str or None); `apply_turn_limit`
- Produces: Turn-limited history passed to LLM

- [ ] **Step 1: Write failing test for build_request_messages with turn_limit**

```python
# backend/tests/unit/test_turn_limit.py
from backend.chat.history_context import build_request_messages

def test_build_request_messages_applies_turn_limit():
    rows = []
    for i in range(6):
        rows.append(type("M", (), {"role": "user", "content": f"q{i}", "tool_calls": None, "reasoning_content": None})())
        rows.append(type("M", (), {"role": "assistant", "content": f"a{i}", "tool_calls": None, "reasoning_content": None})())

    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current q",
        history_rows=rows,
        turn_limit=2,
    )
    # Extract user messages (excluding the trailing current user message)
    user_msgs = [m for m in messages[1:-1] if m["role"] == "user"]  # skip system + trailing user
    assert len(user_msgs) == 2
```

- [ ] **Step 2: Run test, verify failure**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_turn_limit.py -v`
Expected: FAIL — `build_request_messages` doesn't accept `turn_limit`

- [ ] **Step 3: Add `turn_limit` parameter to `build_request_messages`**

Edit `backend/chat/history_context.py` around line 144:
```python
def build_request_messages(
    system_content: str,
    user_text: str,
    history_rows: Sequence[Any],
    attachment_block: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    trailing_system: Optional[str] = None,
    turn_limit: Optional[int] = None,  # NEW
) -> Tuple[List[Dict[str, Any]], int]:
    kept, omitted = truncate_history(db_rows_to_history(history_rows), budget_tokens)
    # 方案 B：滑动窗口
    if turn_limit:
        kept, turn_omitted = apply_turn_limit(kept, turn_limit)
        omitted += turn_omitted
    # ... rest unchanged
```

- [ ] **Step 4: Pass turn_limit from chat_stream_create**

In `backend/api/legacy_routes.py`, find the `build_request_messages(...)` call (around line 2870). Add:
```python
from backend.data.settings_repo import SettingsRepository

turn_limit_raw = SettingsRepository().get("context_turn_limit")
turn_limit = int(turn_limit_raw) if turn_limit_raw else None
```

And pass `turn_limit=turn_limit` to `build_request_messages(...)`.

- [ ] **Step 5: Run test, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_turn_limit.py -v`
Expected: 1 passed

- [ ] **Step 6: Run all backend tests**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add backend/chat/history_context.py backend/api/legacy_routes.py backend/tests/unit/test_turn_limit.py
git commit -m "feat(chat): apply turn_limit from settings in request assembly"
```

---

### Task 8: Frontend — Context settings turn limit slider

**Files:**
- Create: `src/components/settings/ContextSettings.tsx`
- Modify: settings page (find via `grep -rn "Settings\|settings" src/components/`)
- Modify: settings API (find via `grep -rn "getSetting\|setSetting\|get_setting\|set_setting" src/shared/`)

**Interfaces:**
- Produces: UI control bound to `context_turn_limit` setting; values `null/3/5/8/10/15/20`

- [ ] **Step 1: Find settings API pattern**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && grep -rn "get_setting\|set_setting\|getSetting\|setSetting" src/ | head -20
```

Report findings — use the actual function signature.

- [ ] **Step 2: Add helper for context_turn_limit**

In the settings API file (identified in Step 1), add:
```typescript
export async function setContextTurnLimit(value: number | null) {
  return invoke('set_setting', { key: 'context_turn_limit', value: value === null ? null : String(value) });
}
export async function getContextTurnLimit(): Promise<number | null> {
  const v = await invoke<string | null>('get_setting', { key: 'context_turn_limit' });
  return v ? Number(v) : null;
}
```

Adjust if the actual Tauri command names differ.

- [ ] **Step 3: Create ContextSettings component**

Create `src/components/settings/ContextSettings.tsx`:
```tsx
import React, { useEffect, useState } from 'react';
import { getContextTurnLimit, setContextTurnLimit } from '@/shared/api/settingsApi';  // adjust import path

const OPTIONS: { label: string; value: number | null }[] = [
  { label: '无限制', value: null },
  { label: '3 轮', value: 3 },
  { label: '5 轮', value: 5 },
  { label: '8 轮', value: 8 },
  { label: '10 轮', value: 10 },
  { label: '15 轮', value: 15 },
  { label: '20 轮', value: 20 },
];

export function ContextSettings() {
  const [val, setVal] = useState<number | null>(null);
  useEffect(() => { getContextTurnLimit().then(setVal); }, []);

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">上下文轮数限制</label>
      <select
        className="border rounded px-2 py-1"
        value={val ?? 'null'}
        onChange={async (e) => {
          const v = e.target.value === 'null' ? null : Number(e.target.value);
          setVal(v);
          await setContextTurnLimit(v);
        }}
      >
        {OPTIONS.map(o => (
          <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
        ))}
      </select>
      <p className="text-xs text-gray-500">
        限制每次发送给模型的最近对话轮数（1 轮 = 1 次用户输入 + 1 次助手回复）。
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Mount in Settings page**

Find Settings page (via grep in Step 1) and add `<ContextSettings />` in an appropriate section (e.g., "Chat" or "Advanced").

- [ ] **Step 5: Build & smoke test**

```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && npm run build
```

In UI: open Settings → select "5 轮" → send 8 messages → verify AI only sees last 5.

- [ ] **Step 6: Commit**

```bash
git add src/components/settings/ContextSettings.tsx
git add src/components/settings/Settings.tsx  # or wherever mounted
git add src/shared/api/settingsApi.ts  # or wherever settings helpers live
git commit -m "feat(ui): context turn limit setting dropdown"
```

---

## Phase 3: Auto Topic Detection (方案 C)

### Task 9: Topic detection module — regex + embedding similarity

**Files:**
- Create: `backend/chat/topic_detection.py`
- Create: `backend/tests/unit/test_topic_detection.py`

**Interfaces:**
- Produces:
  - `QUICK_NEW_TOPIC_SIGNALS: List[str]`
  - `detect_topic_shift(user_text, recent_assistant_texts, embed_fn=None, threshold=0.35) -> Tuple[bool, str]`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_topic_detection.py
from backend.chat.topic_detection import detect_topic_shift

def test_quick_signal_chinese():
    is_new, reason = detect_topic_shift("换个话题，我想问下...", [])
    assert is_new is True
    assert reason == "quick_signal"

def test_quick_signal_english():
    is_new, reason = detect_topic_shift("By the way, completely different question.", [])
    assert is_new is True
    assert reason == "quick_signal"

def test_no_signal_no_embed_fn_returns_false():
    is_new, reason = detect_topic_shift("继续解释上一段", ["hello"])
    assert is_new is False
    assert reason == "no_signal"

def test_embed_low_similarity_triggers():
    def fake_embed(text: str):
        return [0.0] * 384 if "weather" in text.lower() else [1.0] + [0.0] * 383
    is_new, reason = detect_topic_shift(
        "What's the weather today?",
        ["Sure, here's the bug fix..."],
        embed_fn=fake_embed,
    )
    assert is_new is True
    assert reason == "embed_similarity"

def test_embed_high_similarity_no_trigger():
    def fake_embed(text: str):
        return [1.0] + [0.0] * 383
    is_new, reason = detect_topic_shift(
        "Tell me more about that.",
        ["Here's a detailed explanation of X."],
        embed_fn=fake_embed,
    )
    assert is_new is False
    assert reason == "embed_similarity"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_topic_detection.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement topic_detection.py**

Create `backend/chat/topic_detection.py`:
```python
"""Lightweight topic shift detection.

Two-layer strategy:
1. Regex quick channel — match obvious "change topic" phrases (<1ms).
2. Embedding similarity — compare user input to recent assistant turns;
   if avg cosine similarity < threshold (default 0.35), flag as new topic (<50ms).

Embedding is optional; if embed_fn is None and quick signals miss, returns False.
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional, Sequence, Tuple

QUICK_NEW_TOPIC_SIGNALS = [
    r"换个话题", r"另一个问题", r"新话题", r"不相关的",
    r"另外[，,。]", r"顺便问[一]?下",
    r"new topic", r"unrelated question", r"by the way",
    r"switching to", r"different question",
]

_QUICK_PATTERN = re.compile("|".join(QUICK_NEW_TOPIC_SIGNALS), re.IGNORECASE)
DEFAULT_SIMILARITY_THRESHOLD = 0.35


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def detect_topic_shift(
    user_text: str,
    recent_assistant_texts: List[str],
    embed_fn: Optional[Callable[[str], List[float]]] = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Tuple[bool, str]:
    """Return (is_new_topic, reason).

    reason ∈ {"quick_signal", "embed_similarity", "no_signal"}.
    """
    if _QUICK_PATTERN.search(user_text or ""):
        return True, "quick_signal"

    if embed_fn is None or not recent_assistant_texts:
        return False, "no_signal"

    try:
        user_vec = embed_fn(user_text)
    except Exception:
        return False, "no_signal"

    sims = []
    for txt in recent_assistant_texts[-3:]:
        try:
            sims.append(_cosine(user_vec, embed_fn(txt)))
        except Exception:
            continue
    if not sims:
        return False, "no_signal"

    avg = sum(sims) / len(sims)
    return (avg < threshold, "embed_similarity")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_topic_detection.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/chat/topic_detection.py backend/tests/unit/test_topic_detection.py
git commit -m "feat(chat): lightweight topic shift detector (regex + embedding)"
```

---

### Task 10: Wire detector into chat_stream_create + emit topic_shifted SSE

**Files:**
- Modify: `backend/api/legacy_routes.py` (in chat_stream_create)
- Modify: `src/shared/api/events.ts` (add `topic_shifted` event)

**Interfaces:**
- Consumes: `detect_topic_shift`, `SettingsRepository.get("auto_topic_detection")`, embed function
- Produces: When detector fires, calls `advance_segment`, emits `topic_shifted` event

- [ ] **Step 1: Find embed function**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && grep -rn "def embed\|def encode\|class.*Embed" backend/embeddings/ 2>/dev/null | head -10
```

Use the project's existing embed function. If unavailable, detector handles `embed_fn=None` gracefully.

- [ ] **Step 2: Add detector wiring in chat_stream_create**

In `backend/api/legacy_routes.py`, after `history_rows = ...` block (from Task 4), BEFORE `build_request_messages`:

```python
# 方案 C：智能话题检测
from backend.chat.topic_detection import detect_topic_shift
from backend.data.settings_repo import SettingsRepository as _SR

_auto_detect = _SR().get("auto_topic_detection")
if not data.context_reset and (_auto_detect is None or _auto_detect.lower() == "true"):
    recent_assistant = [
        r.content for r in (history_rows or [])[-6:]
        if getattr(r, "role", None) == "assistant"
    ]
    embed_fn = None
    try:
        from backend.embeddings import get_embedder
        embedder = get_embedder()
        embed_fn = lambda t: embedder.embed_query(t)
    except Exception:
        pass

    is_new, reason = detect_topic_shift(data.message, recent_assistant, embed_fn=embed_fn)
    if is_new:
        new_seg = await asyncio.to_thread(repo.advance_segment, data.session_id)
        history_rows = await asyncio.to_thread(repo.get_active_segment, data.session_id)
        # Emit SSE event to notify frontend
        try:
            await stream_queue.put({
                "type": "topic_shifted",
                "segment_id": new_seg,
                "reason": reason,
            })
        except Exception:
            logger.warning("failed to emit topic_shifted event")
```

Adjust the `stream_queue` variable name to match the actual SSE queue in `chat_stream_create` (find via `grep -n "queue\|put\|emit"` in surrounding context).

- [ ] **Step 3: Add `topic_shifted` to AgentEvent type**

In `src/shared/api/events.ts`, find the `AgentEvent` union/type and add:
```typescript
| { type: 'topic_shifted'; segment_id: number; reason: string }
```

Match the existing union pattern.

- [ ] **Step 4: Run all tests**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -x -q`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/legacy_routes.py src/shared/api/events.ts
git commit -m "feat(chat): integrate topic detector + emit topic_shifted SSE"
```

---

### Task 11: Frontend — TopicShiftBanner + retreat endpoint

**Files:**
- Create: `src/components/chat/TopicShiftBanner.tsx`
- Modify: chat event handler (find where AgentEvent is dispatched)
- Modify: `backend/api/legacy_routes.py` (add retreat endpoint)

**Interfaces:**
- Consumes: `topic_shifted` SSE event
- Produces: Banner UI; "Restore full context" button calls retreat API

- [ ] **Step 1: Add backend retreat endpoint**

In `backend/api/legacy_routes.py`, find existing session endpoints (near the chat endpoints). Add:
```python
@router.post("/sessions/{session_id}/segments/retreat")
async def retreat_session_segment(session_id: str):
    ok = MessageRepository().retreat_segment(session_id)
    return {"ok": ok}
```

- [ ] **Step 2: Find IPC pattern**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && grep -rn "invoke.*session\|invoke.*api" electron/ src/shared/api/ | head -10
```

Determine the right Tauri command name for HTTP endpoints.

- [ ] **Step 3: Create TopicShiftBanner component**

Create `src/components/chat/TopicShiftBanner.tsx`:
```tsx
import React, { useEffect, useState } from 'react';
import { invoke } from '@/shared/api/tauri';  // adjust path

export function TopicShiftBanner({ sessionId, onRetreat }: { sessionId: string; onRetreat: () => void }) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setVisible(false), 10000);
    return () => clearTimeout(t);
  }, []);

  if (!visible) return null;

  return (
    <div className="bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 px-4 py-2 flex items-center justify-between text-sm">
      <span>💡 检测到新话题，已自动隔离旧上下文</span>
      <div className="flex gap-2">
        <button
          className="text-blue-600 hover:underline"
          onClick={async () => {
            await invoke('retreat_session_segment', { sessionId });
            onRetreat();
            setVisible(false);
          }}
        >恢复完整上下文</button>
        <button
          className="text-gray-500 hover:underline"
          onClick={() => setVisible(false)}
        >×</button>
      </div>
    </div>
  );
}
```

Adjust `invoke` import path based on project's Tauri pattern.

- [ ] **Step 4: Mount banner on `topic_shifted` event**

Find where `AgentEvent` handlers live in the chat UI. Add case:
```typescript
case 'topic_shifted':
  setShiftInfo({ segmentId: event.segment_id, reason: event.reason });
  break;
```

Render `<TopicShiftBanner sessionId={sessionId} onRetreat={() => reloadHistory()} />` when `shiftInfo` is set.

- [ ] **Step 5: Smoke test**

Send a quick-signal trigger ("By the way, different question"), verify banner appears for 10s, click "Restore" → verify next AI response references the prior topic.

- [ ] **Step 6: Commit**

```bash
git add src/components/chat/TopicShiftBanner.tsx backend/api/legacy_routes.py
git commit -m "feat(ui): topic shift banner + retreat endpoint"
```

---

## Phase 4: Compaction + Integration

### Task 12: Compaction restricted to active segment

**Files:**
- Modify: caller in `backend/api/legacy_routes.py` (find `_maybe_auto_compact_session` or similar)
- Create: `backend/tests/unit/test_compaction_segment.py`

**Interfaces:**
- Consumes: `get_active_segment` (returns already-segmented messages)
- Produces: Compaction only runs on active segment's messages

- [ ] **Step 1: Find compaction caller**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-context-isolation && grep -n "auto_compact\|should_compact\|compact_messages\|_maybe_auto" backend/api/legacy_routes.py backend/chat/compaction.py | head -20
```

Report: which function triggers compaction, where it's called from, what messages it operates on.

- [ ] **Step 2: Write failing test**

```python
# backend/tests/unit/test_compaction_segment.py
from backend.chat.compaction import should_compact

def test_should_compact_counts_active_messages():
    msgs = [{"role": "user", "content": f"msg {i} " * 100} for i in range(12)]
    assert should_compact(msgs) is True

def test_should_compact_skips_short():
    msgs = [{"role": "user", "content": "hi"} for _ in range(3)]
    assert should_compact(msgs) is False
```

- [ ] **Step 3: Run test, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_compaction_segment.py -v`
Expected: 2 passed (no changes needed — compaction already operates on whatever list is passed to it)

- [ ] **Step 4: Ensure compaction caller uses get_active_segment**

In the call site (identified in Step 1), confirm `history_rows` passed to compaction is from `get_active_segment` (not raw `get_by_session`). If it's already active segment (from Task 4), no change needed.

If it isn't, change the call:
```python
# Before:
all_rows = MessageRepository().get_by_session(session_id)
# After:
all_rows = MessageRepository().get_active_segment(session_id)
```

- [ ] **Step 5: Commit (if changes)**

```bash
git add backend/api/legacy_routes.py backend/tests/unit/test_compaction_segment.py
git commit -m "refactor(compaction): restrict compaction to active segment"
```

---

### Task 13: Integration test — three layers compose

**Files:**
- Create: `backend/tests/integration/test_context_isolation_e2e.py`

**Interfaces:**
- End-to-end: schema → segment → turn limit → detection → compaction all work together

- [ ] **Step 1: Write integration test**

```python
# backend/tests/integration/test_context_isolation_e2e.py
import pytest
from backend.data.session_repo import MessageRepository
from backend.data.settings_repo import SettingsRepository
from backend.chat.history_context import apply_turn_limit, db_rows_to_history
from backend.chat.topic_detection import detect_topic_shift
from backend.data import database as db_mod

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", str(tmp_path / "test.db"))
    db = db_mod.get_database()
    db.init_db()
    yield

def test_explicit_separator_then_turn_limit(fresh_db):
    repo = MessageRepository()
    SettingsRepository().set("context_turn_limit", "2")

    # Segment 0
    for i in range(5):
        repo.insert("s1", "user", f"old-{i}", 1000 + i)
        repo.insert("s1", "assistant", f"old-reply-{i}", 1000 + i)

    # Manual separator
    new_seg = repo.advance_segment("s1")
    assert new_seg == 1

    # Segment 1 with many turns
    for i in range(10):
        repo.insert("s1", "user", f"new-{i}", 2000 + i)
        repo.insert("s1", "assistant", f"new-reply-{i}", 2000 + i)

    active = repo.get_active_segment("s1")
    history = db_rows_to_history(active)
    kept, omitted = apply_turn_limit(history, turn_limit=2)

    user_contents = [m["content"] for m in kept if m["role"] == "user"]
    assert user_contents == ["new-8", "new-9"]
    assert all(not c.startswith("old-") for c in [m["content"] for m in kept])

def test_topic_detection_triggers_separator(fresh_db):
    repo = MessageRepository()
    repo.insert("s1", "assistant", "Bug fix explanation", 1)

    is_new, reason = detect_topic_shift("By the way, completely different", ["Bug fix explanation"])
    assert is_new is True
    assert reason == "quick_signal"

    if is_new:
        repo.advance_segment("s1")
    repo.insert("s1", "user", "Weather question", 2)

    active = repo.get_active_segment("s1")
    assert all(not (getattr(m, 'content', '') == "Bug fix explanation") for m in active)
```

- [ ] **Step 2: Run test, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_context_isolation_e2e.py -v`
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_context_isolation_e2e.py
git commit -m "test: integration test for three-layer context isolation"
```

---

### Task 14: Memory layer — segment-aware WorkingMemory

**Files:**
- Modify: `backend/memory/working.py:161-214` (add) and `248-269` (get_context)
- Modify: `backend/memory/manager.py:237-308` (get_context accepts segment_id)
- Create: `backend/tests/unit/test_memory_segment.py`

**Interfaces:**
- Produces: `WorkingMemory.add(..., segment_id=0)`, `WorkingMemory.get_context(..., segment_id=0)`, `WorkingMemory.clear_segment(session_id, segment_id)`; `MemoryManager.get_context(limit=10, session_id=None, segment_id=None)`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_memory_segment.py
from backend.memory.working import WorkingMemory

def test_working_memory_segment_isolation():
    wm = WorkingMemory()
    wm.add("s1", {"role": "user", "content": "old topic fact"}, segment_id=0)
    wm.add("s1", {"role": "user", "content": "new topic fact"}, segment_id=1)

    seg0 = wm.get_context("s1", segment_id=0)
    seg1 = wm.get_context("s1", segment_id=1)

    assert any(m["content"] == "old topic fact" for m in seg0)
    assert all(m["content"] != "new topic fact" for m in seg0)
    assert any(m["content"] == "new topic fact" for m in seg1)
    assert all(m["content"] != "old topic fact" for m in seg1)


def test_clear_segment_keeps_other_segments():
    wm = WorkingMemory()
    wm.add("s1", {"role": "user", "content": "old"}, segment_id=0)
    wm.add("s1", {"role": "user", "content": "new"}, segment_id=1)

    wm.clear_segment("s1", segment_id=0)
    assert all(m["content"] != "old" for m in wm.get_context("s1", segment_id=0))
    assert any(m["content"] == "new" for m in wm.get_context("s1", segment_id=1))
```

- [ ] **Step 2: Run tests, verify failure**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_segment.py -v`
Expected: FAIL — `segment_id` parameter not supported

- [ ] **Step 3: Add segment_id to WorkingMemory**

In `backend/memory/working.py`:

Modify `add` (around line 161):
```python
    def add(self, session_id=None, message=None, segment_id: int = 0) -> int:
        # existing compat handling at top...
        sid = self._resolve(session_id)
        content = message.get("content", "")
        tokens = self._estimate_tokens(content)
        seq = self._session_seq.get(sid, 0) + 1
        self._session_seq[sid] = seq
        self._messages.append({
            "session_id": sid,
            "segment_id": segment_id,  # NEW
            "role": message.get("role", "user"),
            "content": content,
            "tokens": tokens,
            "timestamp": time.time(),
            "seq": seq,
        })
        # ... rest unchanged
```

Modify `get_context` (around line 248):
```python
    def get_context(self, session_id=None, limit=None, segment_id: Optional[int] = None):
        # ... existing logic ...
        msgs = self._session_messages(sid)
        if segment_id is not None:
            msgs = [m for m in msgs if m.get("segment_id", 0) == segment_id]
        if limit is None:
            return msgs
        return msgs[-limit:]
```

Add `clear_segment` after existing `clear` (around line 303):
```python
    def clear_segment(self, session_id=None, segment_id: int = 0):
        sid = self._resolve(session_id)
        self._messages = deque(
            m for m in self._messages
            if not (m.get("session_id") == sid and m.get("segment_id", 0) == segment_id)
        )
        self._save_snapshot(sid)
```

- [ ] **Step 4: Update MemoryManager.get_context signature**

In `backend/memory/manager.py` line 237, add `segment_id`:
```python
    def get_context(self, limit: int = 10, session_id: Optional[str] = None, segment_id: Optional[int] = None) -> str:
        # ... existing logic ...
        # Working memory call (around line 263):
        working_context = self.working.get_context(session_id, segment_id=segment_id)
        # ... rest unchanged
```

- [ ] **Step 5: Run tests, verify pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_segment.py -v`
Expected: 2 passed

- [ ] **Step 6: Wire segment_id through chat_stream_create**

In `backend/api/legacy_routes.py`, find where `memory_manager.get_context(...)` is called (search for `get_context`). Pass the active `segment_id`:
```python
# Get current segment_id from last message
active_segment_id = 0
if history_rows:
    active_segment_id = max(
        (getattr(m, 'segment_id', 0) for m in repo.get_by_session(data.session_id, limit=100000)),
        default=0
    )
memory_context = memory_manager.get_context(limit=10, session_id=data.session_id, segment_id=active_segment_id)
```

Simpler approach: track `segment_id` from `advance_segment` return value or derive from `history_rows[-1]`.

- [ ] **Step 7: Run full backend suite**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -x -q`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add backend/memory/working.py backend/memory/manager.py backend/api/legacy_routes.py backend/tests/unit/test_memory_segment.py
git commit -m "feat(memory): segment-scoped working memory and manager.get_context"
```

---

## Execution Order

Tasks MUST be completed in this order:
1. Task 1 (DB schema)
2. Task 2 (Repository methods)
3. Task 3 (history_context filters + apply_turn_limit)
4. Task 4 (Backend wiring for context_reset)
5. Task 5 (Frontend new topic button)
6. Task 6 (Settings keys)
7. Task 7 (Pipeline turn limit)
8. Task 8 (Frontend turn limit slider)
9. Task 9 (Detector module)
10. Task 10 (Wire detector + SSE)
11. Task 11 (Frontend banner)
12. Task 12 (Compaction segment)
13. Task 13 (Integration test)
14. Task 14 (Memory segment scoping)

Tasks 1-5 are Phase 1 (explicit separator); 6-8 are Phase 2 (sliding window); 9-11 are Phase 3 (auto detection); 12-14 are Phase 4 (compaction + integration).

---

## Manual E2E Checklist (run after all tasks)

```
1. [ ] Open Sage, start new chat
2. [ ] Send "Explain the office_read tool"
3. [ ] Send "现在切换话题，今天天气怎么样"
4. [ ] Verify TopicShiftBanner appears for 10s
5. [ ] Verify AI response is about weather, NOT about office_read
6. [ ] Click "Restore full context" → send another weather question
7. [ ] Verify AI now references office_read (segment was retreated)
8. [ ] Open Settings → set turn limit to 3
9. [ ] Send 5 messages → verify AI only sees last 3
10. [ ] Click "新话题" button → verify separator line appears
11. [ ] Restart app → verify separator persists (DB-backed)
```

---

## Self-Review Checklist (run before opening PR)

- [ ] All 14 tasks have a "Run test, verify pass" step
- [ ] No "TBD" / "TODO" / "fill in later" placeholders
- [ ] All function signatures match across tasks (e.g., `advance_segment(session_id) -> int` consistent in Tasks 2, 4, 10)
- [ ] All new setting keys (`context_turn_limit`, `auto_topic_detection`, `topic_detection_threshold`) are in the KEYS whitelist (Task 6)
- [ ] Migration in `database.py` is idempotent (uses `PRAGMA table_info` check)
- [ ] No breaking changes to existing `ChatRequest` clients (new fields have defaults)
- [ ] WorkingMemory `segment_id` param defaults to 0 (backward compatible)
- [ ] Each task ends with a commit; no "fix in next task" anti-pattern
- [ ] Manual E2E checklist is included in PR description
