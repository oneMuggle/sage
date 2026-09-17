# Office 暂存引用核对（只读、人工操作）

在 Office 页查看暂存条目的 docType/documentId 后，在应用所用主机上、仓库根目录执行：

```powershell
python -m backend.office.staging_references --database "E:/actual/sage.db" --workspace "E:/actual/workspace" --doc-type word --document-id "实际导入 UUID"
```

必须指定**实际应用使用的数据库**；命令不会自动猜测数据库位置，也不会初始化、迁移或创建数据库。先核对应用配置，不要以空库/旧备份得出的负结果推断孤儿。此工具尚未接入 UI 自动调用。

- SQLite `mode=ro`、query_only、单次读事务；不使用会忽略实时 WAL 的 immutable 模式。
- 核对文档 ID（不排除归档）、derived_from 血缘引用、journal 输出路径（按路径分段匹配，避免前缀碰撞）。ID 跨工作区保守匹配，多保留优于漏保护。
- 缺失表/列、库损坏/繁忙、扫描超限、相对 journal 路径均视为核对不完整。有已知正向引用时保留正向证据。
- `referenced`：存在已知引用，保留。`unknown`：无法完成核对，保留。`no_reference_found`：仅在本次事务、列出的来源未查到引用，**不是孤儿证明，也不是删除许可**。
- `safe_to_delete` 永远为 false。退出码 2 表示核对不完整/参数无效；退出码 0 只表示核对已完成，不表示可删除。
- 不遍历/清理目录，不修改文档。SQLite 的只读 WAL 连接可能参与共享内存/锁管理；并不宣称数据库目录的所有元数据完全零变化。

仍需完成：全来源引用覆盖（包括文件快照、任意嵌入元数据等）、与进行中导入的原子协调、隔离恢复及保留策略。数据库读事务与文件系统不构成共同原子快照。不得将本工具直接用于自动删除。真实 Win7/安装包回滚验收仍需要对应环境。
