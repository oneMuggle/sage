# R157：SkillLoader（SKILL.md 落盘器）单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；SKILL.md 生态（安全写盘 safe_writer）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`skills/loader.py`（122 行，SkillLoader：把批准的技能草稿写到
`<skills_dir>/<name>/SKILL.md`，skills_dir 三级解析：显式参数 →
SAGE_SKILLS_DIR → ~/.sage/skills；name 非法字符防御；read 审计回读）
此前零测试。

## 覆盖矩阵（约 14 例）

1. write：显式 skills_dir 下创建 `<name>/SKILL.md`、父目录自动建、
   内容往返一致；2. overwrite=True 覆盖旧内容；3. name 防御：空 /
   含 `/` / 含 `\\` / `.` / `..` → ValueError；4. read：存在返回全文、
   不存在 → None；5. read 同款 name 防御；6. skills_dir 解析三级优先：
   显式 > SAGE_SKILLS_DIR env > ~/.sage/skills（env 用 monkeypatch 验证
   前两级，第三级不触真实 home——用显式构造覆盖）；7. get_skill_loader
   单例与 reset_skill_loader 重置。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
