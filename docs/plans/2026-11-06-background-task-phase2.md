# BashSessionRegistry 跨重启持久化 · Phase 2

> 日期：2026-11-06
> 分支：`feat/background-task-phase2`
> 状态：实施中

## 背景

Phase 0/1 已交付完整的后台任务一等公民能力：退出观察器 + 完成唤醒 +
OS 通知 + 两个 LLM 工具。但 `BashSessionRegistry` 仍是纯内存表 ——
后端重启时所有后台 shell 成为孤儿进程（`tools/bash_session.py` 模块注释
明确标注），用户也无法再查输出或清理。

Phase 2 目标：把注册表元数据持久化到 SQLite，重启后尝试恢复存活 shell
到 registry；无法恢复的按"未知退出码结束"处理（触发完成通知）。
Windows 暂不实施（pgid 验证语义不同，单测 skip on nt）。

## 涉及的文件与模块

### 后端
- `backend/tools/bash_session_persistence.py`（新模块）：SQLite 表
  `bash_sessions` + `BashSessionStore` 仓储。
- `backend/tools/subprocess_util.py`：新增 `ResurrectedProcess` 数据类，
  通过 `os.getpgid(pid)` 校验 pgid 防 PID 复用；提供 `poll()` 接口。
- `backend/tools/bash_session.py`：
  - `BashSession` 新增 `resurrected: bool`；
  - `register()` 同步写入持久化；
  - `terminate()` / `clear()` / 退出观察器触发时删除记录；
  - `read_increment()` 回写偏移；
  - `get_registry()` 首次调用时执行 `restore()`：加载所有行 → 构造
    `ResurrectedProcess` → 仍存活的加入注册表并登记退出观察器；已死的
    推一条"未知退出码"通知到后台队列。

### 数据库
- 新建表 `bash_sessions`（由 `BashSessionStore.__init__` 幂等创建）：
  ```sql
  CREATE TABLE IF NOT EXISTS bash_sessions (
    shell_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    pgid INTEGER NOT NULL,
    command TEXT NOT NULL,
    stdout_path TEXT NOT NULL,
    stderr_path TEXT NOT NULL,
    stdout_identity TEXT,    -- JSON: [dev, inode]
    stderr_identity TEXT,
    stdout_offset INTEGER NOT NULL DEFAULT 0,
    stderr_offset INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL
  );
  ```

### 测试
- `backend/tests/unit/test_bash_session_persistence.py`（新）
- `backend/tests/unit/test_bash_session_restore.py`（新，POSIX only）
- `backend/tests/unit/test_subprocess_util_resurrect.py`（新，POSIX only）

## 技术方案

### T1: BashSessionStore 仓储

```python
# backend/tools/bash_session_persistence.py
class BashSessionStore:
    def persist(self, session: BashSession) -> None: ...
    def remove(self, shell_id: str) -> None: ...
    def update_offsets(self, shell_id: str, stdout: int, stderr: int) -> None: ...
    def list_all(self) -> List[StoredRecord]: ...
```

全局单例通过 `get_bash_session_store()` 延迟创建（依赖 `get_database()`）。

### T2: ResurrectedProcess

```python
@dataclass
class ResurrectedProcess:
    pid: int
    pgid: int
    returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode
        try:
            current_pgid = os.getpgid(self.pid)
        except (ProcessLookupError, OSError):
            self.returncode = None
            return self.returncode
        if current_pgid != self.pgid:
            # PID 被复用为其它进程组 —— 我们的进程已结束
            self.returncode = None
            return self.returncode
        return None  # 仍存活
```

`BashSession.status()` 的既有分支经 `observe_process_exit` → `poll()` 接入。

### T3: get_registry 启动恢复

`restore()` 流程：
1. `store.list_all()` → 所有行。
2. 对每行构造 `ResurrectedProcess(pid, pgid)`。
3. 校验输出文件身份与存储一致（identity 比对），避免文件被替换后读到错误输出。
4. `poll()` 检测存活：
   - 存活 → 注入 registry（绕过 `max_sessions` 检查，硬恢复）；
   - 已死 → 推到后台通知队列（`exit_code=None`），并从 store 删除。
5. 对恢复的 shell 自动登记默认退出观察器（完成通知）。

### T4: 偏移量回写

`read_increment()` 末尾回写 `stdout_offset` / `stderr_offset`（SQLite 写放大
可接受：调用间隔 ≥0.5s）。

### T5: 终止与清理

`terminate()` 成功后 `store.remove(shell_id)`；退出观察器检测到退出后同样
删除记录，避免僵尸行。

## 实施步骤

- [x] M1: 本 plan 文档
- [x] M2: BashSessionStore 仓储（T1）+ 单元测试
- [x] M3: ResurrectedProcess shim（T2）+ 单元测试（POSIX only）
- [x] M4: BashSessionRegistry 集成（T3 + T4 + T5）+ 单元测试
- [x] M5: 集成测试：spawn shell → 重启后端 → 恢复/通知
- [x] M6: ruff / py38 / typecheck / 架构检查
- [ ] M7: PR → CI → 合并；同步 win7

## 风险评估

| 风险 | 缓解 |
|---|---|
| PID 复用误判 | `ResurrectedProcess.poll()` 用 pgid 校验；不匹配视为结束 |
| SQLite 写放大 | 偏移回写仅在 `read_increment` 时 |
| 重启期间 shell 数超限 | `restore()` 绕过 `max_sessions` 预检查，硬恢复 |
| 输出文件被删或身份变化 | `file_identity` 校验；不一致按结束处理 |
| Windows 不支持 | Phase 2 POSIX-only；Windows 保持内存表行为 |

## 不在范围内

- Windows 持久化（pgid 语义不同，需 `CREATE_NEW_PROCESS_GROUP` + `tasklist` 校验）
- 跨机器 shell 迁移
- shell 内部状态（cwd、环境变量）恢复 —— 只恢复进程句柄与输出
