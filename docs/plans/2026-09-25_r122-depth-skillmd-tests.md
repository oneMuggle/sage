# R122：子代理深度防护 + SKILL.md 安全校验单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；O5 嵌套深度防护（2026-09-08）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`orchestration/depth.py`（76 行，ContextVar 子代理嵌套深度防护——防自定义
profile 白名单穿透派生孙代理）与 `skills/skill_md/validation.py`
（88 行，`{baseDir}` 路径遍历防御 + 日志注入脱敏）均为安全边界纯逻辑
模块，此前零测试。

## 覆盖矩阵

### `backend/tests/unit/orchestration/test_depth.py`（11 例）

1. 默认深度 0（conductor）；2. enter/exit 配对置位与恢复；
3. 嵌套 enter 多层 + token 配对恢复前值；4. max 默认 1；
5. env 覆盖：合法值 / 带空白值；6. env 非法值 / 0 / 负数 → 回退 1；
7. is_nesting_allowed：深度 0 → True、深度达上限 → False、env 放宽后
   深度 1 → True；8. 用例 finally 保证 ContextVar 复位不泄漏到其他用例。

### `backend/tests/unit/skills/test_skill_md_validation.py`（14 例）

1. validate_base_dir：合法根内 → 返回 resolve 后绝对路径；
2. 根外目录 → SkillMdSecurityError（消息含允许根列表）；
3. 空 allowed_roots → 错误；4. 不存在的目录/根（resolve strict=False）
   正常工作；5. **前缀兄弟目录**（/root vs /root2）不得误判为包含；
6. `allowed/..` 遍历解析后落在根外 → 拒绝；7. 多根任一命中即可；
8. sanitize_for_logging：控制字符（\x00-\x08/\x0b-\x1f/\x7f）替换为
   `?`，tab/LF 保留；9. 超长截断且标注原始总长；10. 非 str 输入强转；
11. 自定义 max_len。

## 验证

- pytest 新文件 + 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 depth 的 run_in_executor 线程通路（文档已声明不设防的已知限制）；
- 不测 loader 层对 SkillMdSecurityError 的调用链（属 loader 用例域）。
