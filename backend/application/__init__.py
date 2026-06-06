"""Sage application 层（用例编排 / 业务服务）。

本层是六边形架构的应用核心，依赖关系：

- 仅可依赖 ``backend.domain``（纯领域模型）与 ``backend.ports``（端口协议）
- **禁止** 依赖 ``backend.adapters.*``（具体实现由 API 路由层注入）
- **禁止** 依赖 ``fastapi`` / ``httpx`` / ``sqlite3`` 等 I/O 框架

设计原则：

- **用例驱动**（Use Case）：每个 Service 对应一个高阶业务用例（聊天、记忆维护等）。
- **端口编排**：Service 通过 ports 抽象调用外部能力（LLM / Storage / Tools / Metrics / Events）。
- **依赖倒置**：API 路由层在装配时把具体 adapter 注入到 Service 构造器。

子模块布局：

| 子模块        | Service              | 说明                                |
|---------------|----------------------|-------------------------------------|
| ``services``  | ``ChatService``      | 一次对话轮次编排（PG2.9）           |
"""
