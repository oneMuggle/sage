# R175：Python 运行时适配器纯函数单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime 适配器协议
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/adapters/python_adapter.py`（464 行，CPython 适配器——PATH 扫描
+ conda/venv 发现 + pyproject/requirements 清单识别 + 版本约束诊断）
的纯函数（build_command / discover_manifests / _parse_json_line /
_target_version_meet / diagnose）此前零测试。

## 覆盖矩阵（约 20 例）

1. build_command：argv=[python, -] + stdin_payload=code；
2. discover_manifests：pyproject.toml（requires_python 提取）/
   requirements.txt（注释过滤 + 排序）/ Pipfile / environment.yml；
3. _parse_json_line：正常 JSON / 非法 / 空行；
4. _target_version_meet：target_version 前缀匹配（>=3.10 / 3.8）；
5. diagnose：版本约束匹配 / 不匹配 / 缺运行时。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
