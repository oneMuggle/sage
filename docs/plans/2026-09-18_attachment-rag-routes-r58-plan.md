# r58 批次计划：附件 RAG 路由接线（索引 / 检索 / 删除 + 配置决策）

日期：2026-09-16（分支创建于 main@0b808e91，含 r57 库层 #960）
文件面：backend/api/chat_attachment_routes.py、backend/services/attachment_rag.py
（+1 小辅助）、单测；零前端改动（IPC/设置面板为切片 3）。

## 配置来源决策（本批次的"产品决策"）

采用**请求级嵌入配置**，与 wiki ingest 完全同口径（wiki_routes 也是请求带
embed_base_url/api_key/model/dim）：
- 一致性：Sage 现有两条嵌入链路（wiki ingest、wiki chat）都是请求级配置，
  不引入第三种机制；
- 无新设置面：不需要 ModelsTab/环境变量新增"嵌入 provider"概念；
- 失败面干净：未传嵌入配置 → 索引端点返回 400 说明性错误（不是静默降级），
  上传主流程不受影响（索引是独立端点，不挂在上传钩子上）。

挂载时机也改为显式：前端/调用方在上传拿到 media_id 后**按需调用**
POST /chat/attachments/{id}/index。不自动索引的原因：嵌入调用花钱且慢，
自动触发（25MB docx）在聊天场景是惊吓；由 UI 显式发起（切片 3）才可控。

## 交付

1. `POST /chat/attachments/{media_id}/index`：
   - body: `{embed: {base_url, api_key, model, dim?}, target_chunk_size?}`
   - 读附件全文（复用既有 _extract / text 读取路径；非文档 → 400）；
   - 调 index_attachment（r57 库层），返回 {chunks, dim, page_path}；
   - 空文本（扫描版 pdf）→ {chunks: 0}；嵌入失败 → AttachmentRagError → 502。
2. `POST /chat/attachments/search`：
   - body: `{query_vector: float[], media_ids?: string[], limit?, dim}` —— 
     直接收向量（嵌入由调用方完成，保持路由无网络依赖，单测友好）；
   - 返回 hits（page_path/chunk_index/content/score）。
3. `DELETE /chat/attachments/{media_id}/index`：删除索引，返回 {removed}。
4. attachment_rag.py 增 `attachment_vector_store_path(data_root)` 小辅助：
   统一 `<data_root>/rag/attachments.json` 路径约定（路由与测试共用）。
5. 单测：TestClient + fake http_post…——注意 index 路由内部不走 http_post 注入，
   而是 requests/httpx？——不：保持库层注入口径，路由层用 `httpx.AsyncClient.post`
   直发（wiki 同款）。单测用 respx 拦截 embeddings 端点（r54 同款）。

## 测试
- 上传 docx/txt → index（respx 假嵌入）→ search 命中 → delete 清空；
- 非文档附件 index → 400；不存在 → 404；空文本 → chunks=0；
- 缺 embed 配置 → 422（pydantic）；嵌入端点 500 → 502。

## 不做
- 前端 UI / IPC（切片 3）；聊天 producer 检索注入（切片 4）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
