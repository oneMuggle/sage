# R128：slash command 注册表单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；skill_md M10（slash 命令索引）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`skills/skill_md/slash_registry.py`（98 行，command_name → SkillMdSkill
不可变索引：user_invocable 过滤、命令名规范化 `/foo|foo|//foo → /foo`、
execute_command 委托 execute_v2）此前零测试。

## 覆盖矩阵（12 例）

1. from_registry 索引规则：builtin（非 SkillMdSkill 实例）永不索引；
   user_invocable=False 跳过；True 才索引；
2. 命名：显式 user_invocable_name 优先、否则 fallback `/{doc.name}`；
3. resolve："/foo" / "foo" / "//foo" 变体全解析；未注册 → None；
   空串 / 纯斜杠 → None（规范化为空串 miss）；
4. list_commands 返回规范化带斜杠键；
5. execute_command：委托 execute_v2（params.args 列表化透传、context
   空字典）、返回 execute_v2 结果；未注册 → LookupError；
6. 不可变索引：构建后修改源映射不影响 registry；
7. registry.get 返回 None 时安全跳过。

SkillMdSkill 用最小子类替身（覆写 __init__ 只设 _doc、execute_v2 记录
调用），通过 isinstance 门禁且不依赖 SKILL.md 解析。

## 验证

- pytest 新文件 + skills 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 SKILL.md 解析与 execute_v2 的 body fallback 细节（skill_md
  解析域另有用例）。
