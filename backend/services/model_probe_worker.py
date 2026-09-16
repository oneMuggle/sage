"""Python-side wrapper around the model probe.

Two backends:
  - "python" (default, used on Win7 and as fallback): calls the ported
    classification logic directly in-process.
  - "node" (main branch only): spawns a Node.js worker subprocess and
    forwards evidence via stdin/stdout JSON lines.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Dict, List, Optional

from .model_probe_py.classify import (
    SOURCE_WEIGHTS, resolveEvidence, vendorFromUrl,
)
from .model_probe_py.idmap import resolveModelId

logger = logging.getLogger(__name__)


def _source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(source, 0.5)


class ModelProbeWorker:
    """Unified entry point for evidence → verdict.

    backend="python" runs the ported classify.js logic in-process.
    backend="node" spawns a Node.js subprocess that runs the original
    arena-model-probe code (main branch only).
    """

    def __init__(
        self,
        backend: str = "python",
        node_command: Optional[List[str]] = None,
    ):
        if backend not in ("python", "node"):
            raise ValueError(f"backend must be 'python' or 'node', got {backend!r}")
        if backend == "node" and shutil.which("node") is None and node_command is None:
            logger.warning("node not found, falling back to python backend")
            backend = "python"
        self._backend = backend
        self._node_command = node_command or ["node"]
        self._proc: Optional[subprocess.Popen] = None

    def classify(self, evidence: Dict) -> Dict:
        if self._backend == "node":
            return self._classify_via_node(evidence)
        return self._classify_in_process(evidence)

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            self._proc = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # -- internal ----------------------------------------------------------

    def _classify_in_process(self, evidence: Dict) -> Dict:
        if not evidence:
            return {
                "modelId": None, "family": None, "confidence": 0.0,
                "source": None, "evidence_count": 0,
            }
        # Resolve UUID to model name via idmap
        if evidence.get("modelId"):
            evidence = dict(evidence)
            evidence["modelId"] = resolveModelId(evidence["modelId"])
        # If we have a modelId, wrap in single-item list for resolveEvidence
        if evidence.get("modelId") or evidence.get("family"):
            return resolveEvidence([evidence])
        # Try to extract family from URL if no modelId given
        if evidence.get("raw"):
            vendor = vendorFromUrl(evidence["raw"])
            if vendor:
                return resolveEvidence([{
                    "source": evidence.get("source", "url.host.vendor"),
                    "family": vendor,
                    "weight": _source_weight("url.host.vendor"),
                }])
        return {
            "modelId": None, "family": None, "confidence": 0.0,
            "source": evidence.get("source"), "evidence_count": 0,
        }

    def _classify_via_node(self, evidence: Dict) -> Dict:
        if self._proc is None or self._proc.poll() is not None:
            self._start_node_proc()
        assert self._proc is not None
        try:
            line = json.dumps({"cmd": "evidence", "data": evidence}) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
            response_line = self._proc.stdout.readline()
            if not response_line:
                raise RuntimeError("node worker closed unexpectedly")
            return json.loads(response_line)
        except Exception as e:  # noqa: BLE001
            logger.warning("node classify failed (%s); falling back to python", e)
            return self._classify_in_process(evidence)

    def _start_node_proc(self) -> None:
        from pathlib import Path
        worker_path = Path(__file__).parent / "model_probe_worker" / "worker.mjs"
        if not worker_path.exists():
            raise FileNotFoundError(f"Node worker not found at {worker_path}")
        self._proc = subprocess.Popen(
            self._node_command + [str(worker_path)],
            cwd=str(worker_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
