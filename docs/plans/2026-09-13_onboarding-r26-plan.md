# 首启配置向导（第二十六轮批次 A）实施计划

> 日期: 2026-09-13 · 分支: `feat/onboarding-r26` · 基于 main @ 0f128682
> 来源: 第二十一轮差距分析 D6 前端报告——"完全没有首次启动引导，
> 端点未配置时只有一条警告条 + 无 provider 预设"。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景

主流桌面 AI 应用（Cherry Studio 按 provider 列表一键填 baseUrl、
ChatGPT/Claude 的引导流）都把"首次接入"做成显式引导；Sage 此前只有
聊天页一条警告条 + 跳设置首页，首次体验是最大留损点。

## 实施（前端 only，零后端变更）

`src/features/onboarding/OnboardingWizard.tsx`（新）：

- **Step 1 协议**: openai-compatible / anthropic / gemini / ollama
  四卡单选（provider 预设语义），openai-compatible 附常见服务商提示。
- **Step 2 地址与密钥**: baseUrl（按协议给 placeholder）+ apiKey
  （ollama 免密钥隐藏输入框）。非 openai 协议按钮文案变"直接保存"
  ——跳过测试（各协议 /models 发现语义不同，诚实引导到设置页测）。
- **Step 3 测试并选模型**: openai 协议复用 EndpointsTab 同款
  `testEndpointConnection`（/models 发现 + chat completions 连通），
  成功后从发现列表选对话模型；失败展示原因仍可保存。
- **保存**: 一次 `updateSettings` 写入 `endpoints += 新端点` 与
  `modelSelections.chatModel`；完成态给"开始使用 Sage"收尾按钮。
- **跳过**: 右上角 X —— 不写任何设置。

**Welcome 接线**: 无可用端点（全部端点缺 baseUrl 或必填 apiKey）
且未手动关闭时，在推荐卡片上方渲染向导；`settings.isLoading` 期间
不闪现。

**i18n**: wizard.* 23 组键（zh/en）。

## 测试

- `OnboardingWizard.test.tsx` 5 例: 默认协议步 / openai 全流程
  （测试→选模型→保存断言 endpoints+chatModel 写入形态）/ ollama
  免密钥直接保存 / 测试失败仍可保存 / 跳过零写入。
- Welcome 回归 3 例通过；tsc/eslint 全绿。

## 本批不做（后续候选）

- prompt 模板库（M）
- anthropic/gemini/ollama 的协议级连接测试（各家 /models 语义不同，M）
- 向导内嵌计费/余额查询（L）
