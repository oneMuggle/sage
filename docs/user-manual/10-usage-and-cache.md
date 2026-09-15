# 用量与缓存面板（cc switch 对标）

Sage 设置 → 通用 Tab 内的"用量"面板，汇总所有 chat 调用的 Token 消耗、估算成本与
缓存命中率，并支持时间维度筛选、请求明细分页、趋势图与 CSV 导出。

> 技术实现细节（DB 表结构 / REST 契约 / 单元测试）见
> [技术文档 37 §2](../technical/37-ecosystem-extensions.md#2-用量--成本面板cc-switch-对标三轮递进)。
> 本页只讲"怎么用"。

## 1. 顶部汇总卡片

打开设置 → 通用，向下找到用量卡片。三栏：

| 指标 | 含义 |
| --- | --- |
| 请求数 | 所选时间范围内的 chat 调用次数 |
| Tokens | prompt + completion 之和（不含 cache 命中部分） |
| 成本（USD） | 按内置定价表估算；未识别模型显示 `—` |

刷新按钮：手动重新拉取数据。默认每分钟自动刷新一次。

## 2. 缓存命中率

汇总卡片下方一条窄行，三列：

| 列 | 含义 |
| --- | --- |
| 缓存读 | 被 Anthropic prompt cache 直接命中的 tokens |
| 缓存写 | 写入 prompt cache 的 tokens（首次喂给 cache 的内容） |
| 命中率 | `缓存读 / (prompt + 缓存写)`，百分比显示 |

- ≥ 50% → 绿色（高命中）
- ≥ 20% → 中性灰
- < 20% → 浅灰

**调优建议**：命中率长期 < 20% 时，检查 system prompt 是否过大、是否每次都改写
cache 边界（缓存粒度按 4 段切分）。

## 3. 时间范围

四个 tab：

| Tab | 数据源 | 桶大小 |
| --- | --- | --- |
| 今日 | 内存态 bucket | 小时（24 桶） |
| 近 7 天 | `usage_events` 表 | 日 |
| 近 30 天 | `usage_events` 表 | 日 |
| 累计 | `usage_events` 表（截断 90 天） | 日 |

切 tab 后顶部数字、按模型表格、请求明细、趋势图同步刷新。

## 4. 按模型表格

每个模型一行，列出请求数、prompt / completion / cached_tokens、缓存读/写、
估算成本。表格按 prompt tokens 降序。

未知模型：成本列显示 `—`，不影响其他列。

## 5. 请求明细

分页表格，列：

- 时间（UTC ISO8601）
- 模型
- Tokens（prompt + completion 之和）
- 缓存读
- 缓存写
- 成本（USD）

下方翻页：上一页 / 下一页 + "第 N-M 条 / 共 K 条" 信息。默认每页 50 条，可达 500。

## 6. 趋势图

自绘 SVG 双线图：

- **蓝线**：请求数（左轴）
- **橙线**：成本 USD（右轴）
- **X 轴**：今日 24 个小时点；其他范围显示 "MM-DD" 格式

趋势图标题"用量趋势"。

- 无数据：图区显示"所选时间范围内暂无趋势数据"
- 加载中：显示"趋势数据加载中…"

## 7. 导出 CSV

趋势图右侧"导出 CSV"按钮：

- 文件名格式：`sage-usage-{range}-{timestamp}.csv`
- 编码：UTF-8 + BOM（Excel 双击直接打开中文不乱码）
- 列：`id, session_id, model, prompt_tokens, completion_tokens, total_tokens,
  cached_tokens, cache_read_tokens, cache_creation_tokens, estimated_cost_usd,
  first_token_ms, latency_ms, created_at_iso`

`first_token_ms` / `latency_ms` 是流式首 token 延迟与端到端延迟，未采集则为空。
导出按当前 range 过滤；选"累计"则拉所有 90 天内记录。

## 8. 单会话徽章

打开任意历史会话，标题下方会显示该会话的累计徽章：

- `1.2k tok · $0.0123`
- 命中率 ≥ 50% 时显示绿色 🎯 百分比

空会话（无任何 chat 调用）不显示徽章。

## 9. 常见问题

**Q: 为什么命中率一直是 0%？**
A: 当前 Sage 后端代理的所有 chat 调用都默认开启 Anthropic prompt cache。如仍为 0，
检查模型是否为支持 cache 的 Claude 系列（gpt-* / local-* 等不计入 cache）。

**Q: 累计 tab 显示"暂无"是不是数据丢了？**
A: 不是。L8 PR-B 之前的数据只在内存里，重启后丢失。PR-B 落地后才持久化。

**Q: 导出 CSV 在 Excel 打开乱码？**
A: 已带 UTF-8 BOM，正常情况双击即可。如仍乱码，用"数据 → 自文本"导入，编码选 UTF-8。

**Q: TTFT (first_token_ms) 字段为什么是空？**
A: 流式响应（chat_stream）才会记录首 token 时间，非流式响应该值为空。