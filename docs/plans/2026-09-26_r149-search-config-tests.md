# R149：搜索配置加载器 search_config 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；搜索引擎链配置（preferences KV + enc:
  密钥静态加密）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/search_config.py`（119 行，从 preferences KV 加载搜索引擎链与
API key：任何读取/解析/校验失败都回退默认链 (bing, ddg)，未知引擎
过滤、enc: 包裹密钥解包失败按空处理）此前零测试。

## 覆盖矩阵（约 16 例）

1. 空配置 / None → 默认链；2. repo.get 抛异常 → 默认（fail-safe）；
3. 非法 JSON → 默认；4. 非 dict JSON → 默认；5. 合法配置：order
保留、tavily/zhipu key 透传、parallel 与 parallel_first_n 解析；
6. order 含未知引擎 → 过滤；全未知 → 回退默认链；7. parallel 非
真值 → False、parallel_first_n 非法（0/-1/字符串）→ 2；
8. `_unwrap_secret`：普通字符串透传、enc: 包裹解密（patch
decrypt_secret）、解密失败 → 空串、非字符串 → 空串。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
