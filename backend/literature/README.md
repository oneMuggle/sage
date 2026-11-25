# 文献站点 profile（SiteProfile）

新增站点 = 新增一份 YAML，不改流水线代码。

## 三级目录（后者覆盖前者）

| 层 | 目录 |
|---|---|
| 内置 | `backend/literature/sites/*.yaml` |
| 用户 | `~/.sage/literature_sites/*.yaml`（可用 `SAGE_LITERATURE_SITES_DIR` 覆盖） |
| 项目 | `<workspace>/.sage/literature_sites/*.yaml` |

同 `id` 的 profile 以更高层为准，便于用户或项目覆盖随包配置。

## 必填字段

`id` / `display_name` / `home_url` / `domains` / `search.url_template`（含 `{query}`）。

## 可选字段

`access`（登录方式与登录态判定）、`search.wait_for`、`search.pagination`、
`search.result_fields`、`detail`、`pdf`、`rate_limit`、`compliance`、
`status`（`ready` / `draft`）、`last_verified_at`（`YYYY-MM-DD`）。

## 交互式检索（`search.mode: interactive`）

适合"入口页 → 点击/跳转 → 输入关键词 → Enter 提交"的站点：

```yaml
search:
  mode: interactive
  url_template: "https://example.org/entry"   # 入口页（无需 {query}）
  entry_url: "https://example.org/entry"
  entry_click: "检索入口"                     # 可选，点击入口按钮
  input_selectors:
    - "input[placeholder*='检索词']"
  submit_key: Enter
  wait_after_s: 5
  result_hint: 结果条目结构说明
```

`SageToolDriver`（`backend/literature/sage_driver.py`）把 driver 调用映射到
`sage.call("browser_*")`，可在 `execute_code` 中使用。

对 `search.mode: url` 的 profile，`search_with_profile` 会先走快路径
`sage.call("web_fetch")`（自动带该域登录态，比开浏览器快一个数量级）；
登录墙 / 反爬 / 空正文时自动回落浏览器通道。`search.mode: interactive`
必须走浏览器（需在真实页面输入检索词），不启用快路径。

## Claims 账本与核验（M2a）

每次核验生成 `claims.jsonl`，每行一条 claim：

```json
{
  "claim_id": "c0001",
  "section": "body",
  "text": "带 [cite:p1] 的段落原文",
  "citation_keys": ["p1"],
  "verdict": "supported",
  "notes": "",
  "metadata_schema_ok": true
}
```

- `extract-claims`：从 `draft.md` 按段落抽取带 `[cite:KEY]` 的主张。
- `verify-claims`：跑 Layer 1+2a 核验：
  - `unresolved`：引用 key 不在文献池；
  - `unsupported`：claim 无引用；
  - `supported`：引用 key 都在文献池；
  - `flagged`：引用存在，但引用论文没有任何 evidence 记录（Layer 3a）。
  - 退出码 1 表示存在 unresolved/unsupported。
- 外部 DOI/元数据 2-of-3 共识（Layer 2b）：
  - `verify-metadata` 对每篇有 DOI/arXiv 的文献查询 Crossref / OpenAlex / Semantic Scholar；
  - 至少 2 家标题/年份/作者匹配 → `verified`；1 家 → `partial`；0 → `unverified`；
    无 DOI/arXiv → `skipped`；
  - 报告写入 `metadata_verification.json`。
- 语义 claim support（Layer 3b：被引段落是否真的支持该句，含 PDF 页定位）留 M2c。

```bash
python -m backend.literature.cli extract-claims --run runs/<id>
python -m backend.literature.cli verify-claims --run runs/<id>
python -m backend.literature.cli verify-metadata --run runs/<id>
```

## 语义 claim support（M2c）

LLM 阅读 `claims.jsonl` 与 `evidence.jsonl` 后输出 `claim_support.json`：

```json
[
  {
    "claim_id": "c0001",
    "support": "supported",
    "rationale": "证据 e1 的发现直接支持该句",
    "evidence_refs": ["e1"]
  }
]
```

`support` 取值：`supported` / `flagged` / `unsupported` / `unclear`。
`apply-claim-support` 做确定性校验并合并；`unresolved` / `unsupported` 的 claim
不会被覆盖。

## EvidenceLedger 与核验报告

- `build-ledger`：把 papers / evidence / claims（以及 `--external` JSON entries）
  收敛为 `ledger.json`；外部来源通过 `source_type/source_id/locator/quote`
  接入。
- `report`：生成 `export/verification_report.md` / `.json`，按
  supported / flagged / unsupported / unclear 分组，并带元数据与 ledger 统计。

```bash
python -m backend.literature.cli apply-claim-support --run runs/<id> --json claim_support.json
python -m backend.literature.cli build-ledger --run runs/<id> [--external citations.json]
python -m backend.literature.cli report --run runs/<id>
```

## Rubric 评审与引用样式（M2c 收尾）

- `rubric`：确定性四维评分（方法 / 覆盖 / 逻辑 / 写作，各 0–5 分，总分 20），
  读取 query_log / papers / evidence / claims / outline / draft / gate / metadata，
  不调用 LLM，输出 `export/rubric_review.md` / `.json`。
  评分是**模拟评审/写作自检**，不是同行评审；`band` 为 优/良/及格/待改进，
  每个维度带可读的 `issues` 清单。
- 引用样式：`build_references(..., style="gbt7714" | "ieee")`；
  `export --style ieee` 时 `references.json.style = "ieee"`。
  IEEE 行格式：`[1] A. Author, "Title," Venue, Year.`（英文名缩写首字母，
  超过 3 位作者用 `et al.`；中文名保持原样）。APA/CSL 未实现。

```bash
python -m backend.literature.cli rubric --run runs/<id>
python -m backend.literature.cli export --run runs/<id> --style ieee
```

## 设计规则

- 站点差异只写在这里或 skill 的 `references/`，禁止写进 pipeline 代码。
- 选择器未实测前用空字符串 + `status: draft`，由"录制模式"补齐。
- 第三方站点默认 `compliance.default_enabled: false`，用户显式启用。
- 不代填密码、不导出 cookie、不绕过付费墙；验证码交还用户。
- `home_url` 与渲染出的检索 URL 必须落在 `domains` 内（含子域名），防止
  profile 把请求指向任意主机。

## 站点 profile 示例

内建站点目录 `backend/literature/sites/` 保持中立（不携带具体站点）。示例 profile
见 `docs/templates/literature-sites/`，复制到 `~/.sage/literature_sites/` 或
`<项目>/.sage/literature_sites/` 后生效；加载优先级 builtin < 用户级 < 项目级。
具体站点的选择器与实测要点写在该站点 profile 注释与模板 README 中。
