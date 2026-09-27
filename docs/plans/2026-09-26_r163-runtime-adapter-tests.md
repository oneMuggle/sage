# R163：RuntimeAdapter 注册表 + 运行时来源分类单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime_probe/exec/diagnose 与语言实现
  的解耦层
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/runtime_adapter.py`（153 行，RuntimeAdapter 协议 +
AdapterRegistry 注册中心 + classify_python_source 运行时来源推断）
此前零测试。注册表（重复注册拒绝/大小写归一/排序）与分类函数（conda/
venv/project/system 路径特征）是 runtime 工具族的接线核心。

## 覆盖矩阵（约 14 例）

AdapterRegistry：
1. register 后 get 命中（大小写不敏感）；2. 重复注册 → ValueError；
3. get 未注册 → None；4. languages() 排序返回；5. all() 返回列表；
6. 模块级 registry 单例可独立使用。

classify_python_source：
7. /anaconda、/miniconda、/conda → CONDA；8. /.venv/、结尾
/venv/bin/python、/venv/ → VENV；9. 前缀匹配 → PROJECT；10. 其他 →
SYSTEM；11. 大小写不敏感。

数据类：12. CommandRequest/SafeRunResult 缺省字段。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
