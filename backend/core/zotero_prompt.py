"""
Zotero 文献库 system prompt —— 让 LLM 知道文献库存在并主动检索。

注入条件：工具注册表里出现任意 ``mcp__zotero__*`` 工具时（与
``diagram_prompt.py`` 同模式）。注入点两处：legacy 编排路径
（``backend/api/legacy_routes.py``）与 ChatService 静态 prompt
（``backend/application/services/chat_service.py``）。

修复背景（2026-10-27 feat/zotero-llm-visible）：此前四层阻断中，
白名单过滤掉全部 MCP 工具 + 无任何 prompt 提及文献库，LLM 既看不见
工具也不知道有库可查。本模块解决第三层；M3 新增 ``zotero_sync`` /
``zotero_related`` 时需同步扩充下方工具清单。
"""

from typing import Any

#: Zotero MCP 工具命名空间前缀。闸门按前缀扫描而非固定工具名，
#: 服务器侧增删工具不会让 prompt 注入静默失效。
ZOTERO_TOOL_PREFIX = "mcp__zotero__"


def registry_has_zotero_tool(registry: Any) -> bool:
    """注册表内是否存在任意 ``mcp__zotero__*`` 工具。

    永不抛错：注册表异常不能让聊天启动失败。
    """
    try:
        return any(
            name.startswith(ZOTERO_TOOL_PREFIX) for name in registry.list_names()
        )
    except Exception:
        return False


ZOTERO_TOOL_PROMPT = """
## 本地文献库（Zotero）

你已接入用户的本地 Zotero 文献库。当用户询问论文、文献、参考文献、
研究方法出处、"我收藏的那篇…"、某位作者写过什么、某主题下有哪些
文献时，优先调用 mcp__zotero__zotero_search 检索文献库，而不是凭空回答。

### 工具

所有工具都以 ``mcp__zotero__`` 为命名空间前缀，调用时使用完整名：

- **mcp__zotero__zotero_search(query, collection_key?, tag?, limit?)** — 检索文献；
  query 匹配标题/作者/摘要，可用 collection_key 限定分类、tag 限定标签
- **mcp__zotero__zotero_get_item(item_key)** — 单篇完整元数据
  （作者、年份、DOI、摘要等）
- **mcp__zotero__zotero_get_annotations(item_key)** — 用户在该文献 PDF
  上的高亮与批注
- **mcp__zotero__zotero_read_pdf(item_key, chunk_offset?, chunk_size?)** —
  分段读取 PDF 全文
- **mcp__zotero__zotero_list_collections(parent_key?)** — 列出分类目录
- **mcp__zotero__zotero_get_bibtex(item_keys)** — 生成 BibTeX 引用条目
- **mcp__zotero__zotero_status()** — 文献库连接状态与规模
- **mcp__zotero__zotero_related(item_key)** — 与该文献相关的其他文献
  （Zotero related + wiki 图谱）
- **mcp__zotero__zotero_sync(force?)** — 手动触发库同步（一般无需主动调用）

### 使用原则

1. 引用文献时给出「标题 + 第一作者 + 年份」，便于用户核对。
2. 不要编造文献；检索无结果时明确说明「文献库中没有找到」，
   再考虑用 web_search 检索外部来源。
3. zotero_read_pdf 可能返回较长内容，先按 chunk 读、确认相关后再继续。
4. 用户提到某篇文献的「我的笔记 / 我标注的」时，用
   mcp__zotero__zotero_get_annotations 而不是猜内容。
5. 用户问"这篇论文跟什么相关 / 引用了谁 / 被谁引用"时，用
   mcp__zotero__zotero_related 探索关联文献。
"""
