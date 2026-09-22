"""Job store for arena background jobs (plan §5.8).

User-initiated registration/draw jobs run in daemon threads and report
through an append-only per-job event log. The API streams those events as
NDJSON with ``?after_seq=`` resume (same contract as
backend/api/orch_run_control.py:91), so the store must be:

* thread-safe (workers append from a thread pool),
* bounded (deque maxlen; a runaway job cannot eat memory),
* snapshot-able (status/progress for polling endpoints).

Deliberately *not* EventHub: EventHub is bound to RunEvent/run_id domain
models (plan appendix C #2).
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

#: Per-job event cap. Reference jobs emit ~2 events per account; 5000 covers
#: a 500-round draw job with gate noise without unbounded growth.
MAX_EVENTS = 5000

JOB_KINDS = ("registration", "draw")
JOB_STATUSES = ("running", "stopping", "done", "failed", "stopped")


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


@dataclass
class JobEvent:
    seq: int
    ts: str
    level: str  # info | warn | error
    kind: str   # log | progress | register_result | draw_result | gate | switch_ip | token | error | done
    message: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_ndjson(self) -> str:
        import json

        return json.dumps(
            {
                "seq": self.seq,
                "ts": self.ts,
                "level": self.level,
                "kind": self.kind,
                "message": self.message,
                "data": self.data,
            },
            ensure_ascii=False,
        )


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"
    created_at: str = field(default_factory=_utcnow)
    total: int = 0
    done: int = 0
    ok: int = 0
    failed: int = 0
    params: Dict[str, Any] = field(default_factory=dict)
    results: List[Dict[str, Any]] = field(default_factory=list)
    events: Deque[JobEvent] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    error: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    _seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "total": self.total,
            "done": self.done,
            "ok": self.ok,
            "failed": self.failed,
            "params": self.params,
            "result_count": len(self.results),
            "error": self.error,
            "last_seq": self._seq,
        }


class JobStore:
    """Thread-safe registry of jobs (module-level singleton per feature)."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, total: int, params: Optional[Dict[str, Any]] = None) -> Job:
        if kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind {kind!r}; expected one of {JOB_KINDS}")
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, total=max(0, int(total)), params=params or {})
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [job.snapshot() for job in sorted(jobs, key=lambda j: j.created_at)]

    def append_event(
        self,
        job_id: str,
        level: str,
        kind: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[JobEvent]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            with job._lock:
                job._seq += 1
                event = JobEvent(
                    seq=job._seq,
                    ts=_utcnow(),
                    level=level,
                    kind=kind,
                    message=str(message)[:2000],
                    data=data or {},
                )
                job.events.append(event)
            return event

    def events_after(self, job_id: str, after_seq: int = 0) -> List[JobEvent]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return []
            with job._lock:
                return [e for e in job.events if e.seq > after_seq]

    def mark_done(self, job_id: str, ok_count: int, failed_count: int) -> None:
        self._set_status(job_id, "done")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.ok = ok_count
                job.failed = failed_count
                job.done = ok_count + failed_count

    def _set_status(self, job_id: str, status: str) -> None:
        if status not in JOB_STATUSES:
            raise ValueError(f"unknown job status {status!r}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = status

    def request_stop(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.stop_event.set()
            if job.status == "running":
                job.status = "stopping"
            return True

    def is_stop_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.stop_event.is_set())

    def finish(
        self,
        job_id: str,
        status: str,
        ok_count: int = 0,
        failed_count: int = 0,
        error: str = "",
    ) -> None:
        if status not in ("done", "failed", "stopped"):
            raise ValueError(f"invalid final status {status!r}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.ok = ok_count
            job.failed = failed_count
            job.done = ok_count + failed_count
            job.error = error[:500]

    def clear(self) -> None:
        """Test hook: drop all job history."""
        with self._lock:
            self._jobs.clear()
