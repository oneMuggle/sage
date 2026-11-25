# 内建站点 profile

此目录存放**随产品分发**的文献站点 profile（YAML）。当前为空——不内置任何具体第三方站点，以保证产品中立。

- 需要某站点时，把 `docs/templates/literature-sites/` 下的示例复制到 `~/.sage/literature_sites/`（用户级）或 `<项目>/.sage/literature_sites/`（项目级）启用。
- profile 字段规范见 `backend/literature/README.md` 与 `backend/literature/models.py`。
- 加载优先级：builtin(本目录) < 用户级 < 项目级。
