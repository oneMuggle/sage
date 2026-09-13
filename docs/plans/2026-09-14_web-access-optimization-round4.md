# 网页访问能力优化 Round 4：设置 UI 落地——代理 + 搜索引擎（main）（2026-09-14）

- **状态**：方案完成，实施中
- **上游文档**：Round 1（#742/#748）§3.4 明确推迟的"设置 UI"；Round 2（#756/#759）、Round 3（#763/#765）已交付
- **范围**：**仅 main**（win7 前端按 Round 1 §3.4 继续缓行——后端默认链 `["bing","ddg"]` 无 UI 可用；本轮无 win7 cherry）
- **编号约定**：F = 前端设置
- **方法**：基于 NetworkTab.tsx（291 行）既有模式勘察（preferences KV + settingsClient + i18n + vitest）

## 0. 结论速览

Round 1-3 交付的搜索引擎链、代理、key 加密全部可用但**只能手写 preferences KV**——设置界面缺位使这些能力对普通用户不可发现。本轮把 NetworkTab 扩到完整"网络访问"设置页：

| # | 内容 | 后端 KV |
| --- | --- | --- |
| F1 | 代理设置卡片：http/https 两个输入，空 = 不启用 | `web_proxy`（Round 2 批次2） |
| F2 | 搜索引擎卡片：首选引擎下拉（bing/ddg/tavily/zhipu）+ Tavily/智谱 key 输入（password 遮盖） | `search_config`（Round 1 批次1 + Round 3 K1 自动加密） |

## 1. 设计

- **完全复用既有模式**：`settingsClient.getPreference/setPreference` 读写 KV；改动即持久化（无"保存"按钮，与现有 network_policy 交互一致）。
- **key 输入**：`type=password` 遮盖；落库明文由后端 SettingsRepository.set 钩子自动 SecretBox 包裹（Round 3 K1），读侧透明解密回显。
- **首选引擎下拉**：写 `search_config.order = [首选, ...其余默认]`（保持 Round 1 引擎链语义）；tavily/zhipu 未填 key 时照常可选——后端 resolve_engine_chain 自动跳过未配置的 API 引擎并回退默认链。
- **校验**：代理 URL 前缀校验（http://、https://、socks5://）；其余交后端 fail-safe。
- **i18n**：zh/en 两份 `settings.network.proxy.*` 与 `settings.network.search.*` 键。

## 2. 测试与验收

- `NetworkTab.test.tsx` 扩展：代理输入保存写 KV（JSON 内容断言）、首选引擎变更写 order、key 输入写 search_config；坏代理 URL 显示错误不保存。
- 验收：设置 → 网络 → 填 http 代理即生效（后端逐调用现读）；选 tavily + 填 key 后 `web_search` 走 API 引擎。

## 3. 双分支

main only。win7 侧无对应改动（后端无需变），无 cherry(win7) 项。
