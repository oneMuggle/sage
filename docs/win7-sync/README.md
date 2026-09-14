# Win7/Main 最大化对齐 — 工作区文档

> 分支：`chore/win7-main-sync` 基于 `origin/release/win7`  
> 端口：`PYTHON_BACKEND_PORT=8776` / `VITE_DEV_PORT=1431`  
> 方案：`docs/technical/99-win7-main-sync.md`

## 快速开始

```powershell
python scripts/win7/classify_diff.py
python scripts/win7/parity_report.py
```

平台层：`backend/platform/win7/pydantic_compat.py` + `win_compat.py`
