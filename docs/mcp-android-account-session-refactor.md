# Android：账户 / 会话重构方案

## 1. 目标（用户意图）

Arena.ai 对话必须登录。测试多种模型时：

- 每个账户有额度上限，也可能被风控，因此需要**多账户池**。
- 用户真正关心的是**目标会话**，账户只是载体。
- **自动化沿用现有流程**：会话页点「开始」后由 `RetryController` 自动跑（发 prompt、等回复、归档/保留）；点「停止」结束。不另做常驻开关。
- 自动跑期间账户遇到验证、风控、额度耗尽等阻碍时 **换号**（现有交接），从而积累账户和会话。
- **每一轮对话都跑探针**：中途模型可能切换，不能只在首轮认一次。
- 会话会很多：列表必须 **按模型名分类筛选**（并可扩展），版面方便扫读。
- 主入口先选会话；会话挂在账户上，并展示额度与风控。
- 现有「实例」就是账户：对外称**账户**，展示名 = **邮箱**。

本文件只定方案。实现按第 7 节分阶段。

## 2. 现状（android/）

当前产品轴是 **实例（instance）**，不是会话。

| 层 | 现状 |
| --- | --- |
| 启动页 | `InstancePickerActivity`：选实例 → `MainActivity` |
| 存储 | `filesDir/instances/<实例名>/`：vault、设置、归档、observed models |
| 登录隔离 | `ProfileManager`：实例名 → WebView Profile |
| 账户数据 | `AccountVault` 挂在实例目录 |
| 额度 / 风控 | `AccountBalanceClient`、`AccountRiskController` 已有，未进列表 UI |
| 会话 | `ConversationIdentity` 只规范化 URL；`GalleryActivity` 是归档，不是主入口 |
| 模型 | 探针读名 → `ObservedModelNames`；偏任务结束记一笔，没有每轮必探，没有按模型分组主列表 |
| 自动化 | `RetryController` + 换号交接已有，主路径仍是「开实例再点开始」 |
| 文案 | 大量「实例」 |

缺口：主路径是实例；显示名不是邮箱；额度风控不上屏；中途换模型会显示过期名；无跨账户会话索引；无「按需自动化 + 遇阻换号积累」闭环。

## 3. 领域模型

```
Account（原 Instance）
  id            稳定内部 id（目录名，不是邮箱）
  email         展示名与登录标识
  vault         密码、verified、排除邮箱
  profile       WebView 登录态
  risk          Available / Cooling / DepletedToday / NeedVerification / Rebinding / Invalid
  balance       creditsRemaining / totalCredits
  sessions[]    该账户下的 Arena 对话

Session（目标工作对象）
  url           ConversationIdentity.created() 规范化结果
  accountId     所属账户
  modelName     最近一轮探针结果（可变）
  modelHistory  每轮 {round, modelName, at}，供筛选与审计
  probeStatus   idle | probing | identified | failed
  lastActiveAt
  usable        由所属账户 risk + balance 推导
```

原则：

- 会话属于账户，一对多。同一规范化 URL 在同一账户内唯一。
- 账户健康度决定会话能否继续发。
- 展示用邮箱，存储用 id（邮箱含 `@`，不能当目录 / Profile 名）。
- 换号创建**新账户**；旧账户与其会话保留。新账户没有旧 URL（站点会话绑登录态）。
- 列表分组永远跟 **最新** `modelName`；历史名只做「曾用」。

## 4. UI 信息架构

### 4.1 启动页：会话优先 + 按模型筛选

会话数量会上去，不要平铺无结构长列表。

自上而下（单手可及）：

1. **顶栏**：标题「会话」；右侧账户入口（可用账户数 / 当前邮箱缩写）。
2. **筛选条：横向可滚动 Chip**
   - 第一枚固定「全部」
   - 每个 **模型名** 一枚 Chip，角标 = 该模型会话数
   - 「未探测 / 未识别」单独一枚，不混进真实模型
   - 「更多」预留扩展维度（账户、仅可用、最近）——第一期只做模型，数据用 `FilterDimension` 以便加维
   - 可多选模型（并集）；默认「全部」；选中高对比
3. **「全部」时按模型分组，组头 sticky**
   - 组头：模型名 + 条数；点组头 = 筛到该模型
   - 组内按 `lastActiveAt` 倒序
   - 已筛某一模型时不再重复组头，主行改会话短标题 / 短 id
4. **会话行：两行 + 右侧状态，信息密度优先**
   - 主行：最新模型名（或短标题）
   - 次行：邮箱 · 额度 · 相对时间；若换过模型，淡色「曾用 xxx」
   - 右侧小 chip：可用 / 冷却 / 验证 / 耗尽
   - 点击：该账户 Profile 打开该 URL
   - 不可用置灰；点开给换号 / 去验证 / 等待，不直接开跑
5. **FAB / 次操作**
   - 主 FAB：「新会话」（挑可用账户打开 `/agent`）
   - 账户管理不占主列表；换号发生在会话页点「开始」之后，列表上不另做开关

空态：无账户 → 添加账户；有账户无会话 → 开新会话，进去再点「开始」自动跑。

账户页（次级）：行标题 = 邮箱；额度、风控、注册 / 导入 / 更换邮箱。

### 4.2 会话页（MainActivity）

- Toolbar 标题 = 最新探针模型名（探测中… / 未识别）；副标题 = 邮箱。
- **每轮回复稳定后立刻改标题**，不等整段任务结束。
- 自动化入口仍是现有 **开始 / 停止**（`toggleRun` → `RetryController`）。未点开始 = 手动聊天；点了开始 = 按任务设置自动发、等回复、遇阻换号。
- 无论是否在跑自动，**每一轮回复都探针**。
- 仍受 `ActiveInstanceGate`：同时只跑一个账户 WebView。

### 4.3 文案

用户可见「实例」→「账户」；主入口叫「会话」。Intent 可暂留 `EXTRA_INSTANCE`，新代码用 `accountId`。

## 5. 自动化与每轮探针

自动化**不另起交互**，对齐现在的会话页：

- 点「开始」：`toggleRun` → 启动检查 / 登录 → `RetryController` 按 `TaskSettings` 循环发消息。
- 点「停止」或关页面：暂停，已提交的不重发（现语义）。
- 换号交接带 `EXTRA_RUN_AFTER_LOGIN` 的新页，仍是打开后自动 `toggleRun`。

两层仍要拆开，只是自动层的开关就是「开始」：

1. **每轮探针（始终）**
   每一轮回复稳定后 `probeReader.read()`。名字变了：更新 `modelName`、Chip、分组、toolbar；旧名写入 `modelHistory`。
2. **自动推进（点了开始才跑）**
   自动发 prompt；遇阻走现有换号。点停止即停。

### 5.1 遇阻换号 → 积累账户和会话

仅在自动跑（已点开始）期间：

1. 当前账户上继续会话；每轮发送后探针，登记/更新会话。
2. 阻碍自动化（人机验证、Cloudflare、连续 429、额度低于阈值、登录失效）时：
   - 当前账户写入对应 `AccountState`，会话标不可用原因；
   - **不丢**已有会话；
   - 池内下一可用账户，或 `AccountReplacement` 建新账户；
   - 新账户上开 **新会话**（不继承旧 URL），并按现有交接自动再点开始；
   - 直到用户停止或达到 `MAX_AUTO_REPLACEMENTS`。
3. 「验证是否等人」仍由 `pauseOnCaptcha` 决定。

这样点一次开始就能边测模型边攒账户/会话，不必在列表上再做一个积累开关。

### 5.2 保留策略

探针不归档、不删除。自动发出的短探测默认保留。正式测试轮仍用 `ModelRetentionPolicy`。

## 6. 逻辑与存储

### 6.1 账户目录

- 根目录可暂仍 `filesDir/instances/`，语义改为账户。
- 旧自定义目录名保留；新账户 `acct_<hex>`，email 只在 vault。
- 显示名：`AccountData.email.ifBlank { id }`。
- `InstanceManager` 逐步变成列出账户对象（id + email + risk + balance 缓存）。

### 6.2 会话索引

`<accountDir>/sessions.json`（或全局 index + accountId）：

- key：规范化 URL
- fields：modelName（最新）、modelHistory、probeStatus、updatedAt、title

启动页 = 索引 ∪ 归档 URL；Chip / 分组用最新 modelName。

筛选扩展：`FilterDimension`（先 `model`，后 `account` / `usable`），避免把 Chip 写死在 Activity。

### 6.3 Profile / Gate / 换号

- Profile 仍按 **accountId**。
- Gate holder 用 accountId，文案显示邮箱。
- 换号：新 id，注册完成再写 email；旧账户原样保留。

### 6.4 额度与风控上屏

列表读缓存；打开或自动换号前刷新 balance。Chip 短、可扫。

## 7. 实施顺序

1. 展示改邮箱（目录先不动）。
2. 会话索引 + 启动页主列表 + **模型 Chip / 分组**。
3. **每轮探针**（含中途改名）。
4. **开始后的遇阻换号**接到会话索引（沿用 `toggleRun` / 交接，不新增开关）。
5. 新账户 id 化。
6. 清理用户可见「实例」文案；类名可后改。

## 8. 测试要点

- 旧实例目录仍能打开，显示 email。
- 跨账户会话聚合；同账户同 URL 不重复。
- 不可用账户下的会话不能开自动化。
- 连续两轮探针名不同：分组跟新名，history 有旧名。
- Chip 只出现真实出现过的模型；未识别独立。
- 未点开始：不自动发、不换号；手动回复仍每轮探针。
- 点开始后验证/风控/耗尽：留下旧会话，交接新账户新会话并自动再开始（受换号上限约束）。
- 点停止后不再发消息、不再换号。
- MULTI_PROFILE 不支持时禁止第二账户。
- 邮箱不得当目录名。

## 9. 非目标

- 不把多账户 Cookie 混进一个 WebView。
- 不在站点侧把会话迁到新邮箱。
- 探测不是多轮评测集；自动积累只是换号续跑。
- 不改桌面 C# 参考实现。
