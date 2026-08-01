"""权限出站适配器（A1，来自 OpenWorker）。

- ``PermissionEngine``：对每次工具调用裁决 allow / deny / ask-user，
  消费工具注册时声明的 ``RiskClass``（数据驱动，取代按名硬编码）。
"""
