# MCP 会话交付物：Office 暂存隔离式清理（quarantine）

日期：2026-09-17 ｜ 授权：CI 绿后合并 #1035 / #904，随后继续未完成项；清理方式选定「隔离 + 恢复」，不做真实删除。

## 本轮已完成的前置动作

- `main` #1035 以 squash 合并，合并提交 `c120bfde71eaa2823ccaacbba820bcd1260af1e3`。
- `release/win7` #904 以 merge commit 合并，合并提交 `f26020807df09f8bbce772def50641569bd6337c`。
- 合并前复核：两个 PR `mergeable=true`、head 与已验证 SHA 一致、对应 Actions run 全绿、全部 check runs 无失败项。
- 合并后复核：`origin/main` 与 `origin/release/win7` 的 `src/widgets/chat/ChatInput.tsx` 均含 `disposed` 卸载守卫。

## 本次新增

- `backend/office/staging_quarantine.py`：隔离式清理器（plan / quarantine / report / restore / purge）。
- `backend/tests/unit/office/test_staging_quarantine.py`：20 项安全契约测试。
- `docs/verification/2026-09-17-office-quarantine.md`：操作手册与判定口径。

## 设计要点

1. **只读计划**：`plan` 不改任何字节。证据来源在既有只读工具之上扩展为
   `office_documents.id / derived_from / workspace_path / metadata`、`office_self_checks.doc_id`、
   `office_journal_generations.output_path / workspace_path`、`office_journal_specs.spec_json /
   template_filename / workspace_path`、四张 office 表的全字段 token 扫描，以及工作区文件扫描
   （含 .docx/.pptx/.xlsx 等 zip 容器内部关系部件）。
2. **已注册工作区一律保留**：候选目录若位于数据库仍登记的 `workspace_path` 之下，直接判为
   `referenced`。清理目标只剩「数据库已不认识的工作区遗留暂存」，这是本工具最主要的真实场景。
3. **保守分类**：`referenced` / `unknown`（缺表缺列、扫描超预算、超时、路径歧义、空目录、符号链接、
   读取失败）/ `fresh`（静默期 24h 内被修改）/ `no_reference_found`。只有最后一类可进入隔离。
4. **可恢复搬运**：先写 `intent` 记录并 fsync → 复制到
   `<workspace>/office/.quarantine/<id>.tmp-quarantine`（逐文件 SHA-256 校验、独占创建）→
   复制后再次摘要比对源目录 → `os.replace` 定版为 `<id>` 并写 `done` → 仅在内容仍与副本逐文件一致时
   删除源目录并写 `source_removed`。任何漂移写 `needs_review` 且保留源文件。
5. **崩溃续跑**：下次运行先 `_resume_incomplete`：副本完整则补完搬运；副本残缺则丢弃副本、保留源；
   源与副本都不在则写 `needs_review` 交人工。清单为 append-only JSONL，逐条 fsync。
6. **并发协调**：`quarantine.lock` 单写者锁（忙则全部保留并返回 `quarantine_busy`）；Windows 下对候选
   目录取 FILE_SHARE_NONE 句柄，令进行中的导入/编辑器写入与本操作互斥。这不是跨进程 exactly-once
   承诺，只是把竞态窗口压到「失败即保留」。
7. **永久删除三重门禁**：`purge` 需 `--allow-permanent-deletion` + 逐字重打 quarantine id + 已过保留期
   （默认 7 天），且目标必须位于隔离根内。默认全流程零删除，保留期到期也只标记为可人工处理。

## 明确边界（未宣称）

- 数据库读事务与文件系统不构成共同原子快照；本工具用「复制后校验 + 漂移即保留」代替原子性宣称。
- 不覆盖任意嵌入元数据的全部形态（例如二进制内非 ASCII 编码的 id）、外部备份、快照卷。
- `no_reference_found` 不是孤儿证明，也不是删除许可；`plan` 输出的 `safe_to_delete` 恒为 false。
- 未接入 UI 自动调用，未接入定时任务；仅 CLI 与显式人工触发。
- 真实 Windows 7 系统与安装包回滚验收仍未完成，属发布门禁。
