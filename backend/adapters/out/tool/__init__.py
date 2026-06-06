"""Tool 出站适配器。

- ``InprocToolAdapter`` ：将进程内 ``backend.tools.registry.ToolRegistry``
  桥接为 ``ToolPort``，供上层 ``ChatService`` 通过端口注入。
"""
