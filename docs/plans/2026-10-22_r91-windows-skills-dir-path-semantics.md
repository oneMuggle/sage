# R91 Windows `skills_dir` preference 路径语义修复规格

- 日期：2026-10-22
- 基线：`main` `20ac6129217a030b006b430a87d817121ec1e83d`
- 状态：已实施，待 PR CI 终验
- 触发：R90 合并后的 main CI 终验

## 1. 问题与证据

main CI run `39752585633` 的 workflow 结论为 `success`，但非阻塞 job
`Backend unit (Windows, non-blocking)` 仍有一条失败：

```text
tests/unit/test_skills_dir_policy.py::test_absolute_path_is_returned
assert None == WindowsPath('/opt/skills')
1 failed, 11023 passed, 519 skipped
```

同一 Windows job 在 R90 合并前的 main 提交 `d12f0b180` 与 `cdcebc54` 上也已失败，
因此这是 skill-settings 引入后被 non-blocking 结论掩盖的既有问题，不是 R90 回归。

## 2. 根因

`read_skills_dir_preference()` 的合同是只接受宿主文件系统上的绝对路径，并拒绝含
`..` 段的路径；实现使用宿主原生 `Path(...).is_absolute()`。测试却把 POSIX 的
`/opt/skills` 当成了所有平台的绝对路径：

| 输入 | POSIX | Windows `Path` 语义 | preference 应有结果 |
|---|---|---|---|
| `/opt/skills` | 绝对路径 | 无盘符 root-relative，`is_absolute()` 为 `False` | Windows 拒绝 |
| `\opt\skills` | 普通相对名称 | 无盘符 root-relative | Windows 拒绝 |
| `C:skills` | 普通相对名称 | drive-relative，依赖该盘当前目录 | Windows 拒绝 |
| `C:/skills` | 普通相对名称 | 带盘符与根目录的绝对路径 | Windows 接受 |
| `//server/share/skills` | 实现定义的双斜杠路径 | UNC 绝对路径 | Windows 接受 |

Windows 上把 `/opt/skills` 强行解释成 POSIX 绝对路径会让结果依赖当前盘，
违背现有“不按当前工作目录或当前盘猜目录”的保守口径。因此本轮不放宽生产策略，
而是把真实文件系统夹具改成宿主原生绝对路径，并显式锁定上述拒绝语义。

现有 `test_parent_traversal_is_rejected` 同样使用 `/opt/../etc/skills`；它在
Windows 上会先因非绝对路径被拒绝，未真正覆盖 `..` 分支。本轮一并改为基于
`tmp_path` 的原生绝对路径。

审计还发现一个与函数“不抛异常”合同不符的小缺口：损坏或鸭子类型的 repo 若返回
`int`、`list`、`dict` 等非字符串/非 `PathLike` 值，`Path(value)` 会抛 `TypeError`，
而当前仅捕获 `OSError`、`RuntimeError`、`ValueError`。真实
`SettingsRepository.get()` 的类型合同是 `str | None`，但 importer 调用
`read_skills_dir_preference()` 时没有再包一层异常兜底；为兑现“设置损坏不升级成
启动失败”，本轮把 `TypeError` 纳入同一 warning + `None` 回退。

测试文件顶部的优先级注释还写成了“显式参数 > preference > env”，与 importer、
loader 及 `test_env_wins_over_preference` 的实际口径相反。本轮只校正注释为：

```text
显式参数 > SAGE_SKILLS_DIR env > preference "skills_dir" > ~/.sage/skills
```

## 3. 实施范围

1. `backend/skills/skill_md/skills_dir_policy.py`
   - 仅在路径构造异常元组中加入 `TypeError`；
   - 不改变有效原生绝对路径、`~` 展开、相对路径或 `..` 的既有结论。
2. `backend/tests/unit/test_skills_dir_policy.py`
   - 绝对路径用 `tmp_path` 构造，并证明 policy 不会替调用方 `mkdir`；
   - 绝对路径的正斜杠表示用 `Path.as_posix()` 构造，避免把逻辑字符串与真实
     文件系统路径混为一谈；
   - `..` 用 `tmp_path / "skills" / ".." / "escape"` 构造原生绝对路径；
   - 增加非字符串 preference 的无抛回退用例；
   - 增加 Windows-only 的 root-relative 与 drive-relative 拒绝用例；
   - 校正文件顶部的优先级注释。
3. 本规格文档。

## 4. 非目标

- 不让 Windows 接受 `/opt/skills`、`\opt\skills` 或 `C:skills`；
- 不改变显式构造参数与 `SAGE_SKILLS_DIR` 的可信调用模型；
- 不把 preference 的校验扩展到符号链接解析、目录存在性或权限探测；这些仍由
  importer/loader 按各自职责处理；
- 不修改 SkillsTab 的输入与保存行为；
- 不处理 Win7 分支同步，也不弱化任何 CI gate。

## 5. 验证口径

1. MCP diagnostics：生产与测试 Python 文件均无新增诊断；
2. 远端 Windows Python 3.12 定向运行 `test_skills_dir_policy.py`，并运行相关
   importer 测试确认优先级链无回归；
3. 对改动 Python 文件运行 Ruff 与 `py38_hazard_scan.py`（逐文件）；
4. `git diff --check` 与最终 diff 人工复核；
5. PR CI 终验时单独核对 `Backend unit (Windows, non-blocking)` job 的真实结论，
   不只看 workflow 的汇总 `success`。

## 6. 风险与回滚

- 生产改动仅把一类原本会抛出的损坏输入收敛为既有 `None` 回退，不改变任何有效
  路径的返回值；
- 测试改动把平台相关语义显式化，POSIX 的既有正向覆盖仍由 `tmp_path` 保留；
- 若 CI 出现与本轮无关的新失败，应按 job 日志拆分归因，不以放宽路径策略换取绿灯；
- 回滚只需撤销本轮单个提交，不涉及数据迁移、设置格式或 API 合同。

## 7. 实施记录

- 生产与测试文件 diagnostics 均为 0；
- 远端 Windows Python 3.12：`test_skills_dir_policy.py` 19 passed；
- 远端 Windows Python 3.12：`test_skill_md_importer.py` 51 passed、3 skipped
  （跳过原因为当前环境无 symlink 特权）；
- Ruff、两份改动 Python 文件的 py38 hazard scan 与 `git diff --check` 均通过。
