"""
Diagram tool system prompt — guides LLM on when and how to use draw.io tools.

Injected into the system prompt when MCP diagram tools (drawio__render_diagram)
are registered in the tool registry.
"""

DIAGRAM_TOOL_PROMPT = """
## 图表生成能力

你可以使用 draw.io 图表工具生成可视化图表。当用户请求创建图表、流程图、时序图、思维导图、架构图或任何可视化表示时，使用 drawio__render_diagram 工具。

### 工具说明

**drawio__render_diagram(xml, format?)**
- xml: 完整的 mxGraphModel XML 字符串
- format: 可选，"svg"（默认）或 "png"

### XML 格式

```xml
<mxGraphModel>
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="2" value="文本" style="rounded=1;" vertex="1" parent="1">
      <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>
```

### 布局约束
- 所有元素保持在 x=0-800, y=0-600 范围内（单页视口）
- 从边距开始（x=40, y=40），保持元素紧密分组
- ID 从 "2" 开始（0 和 1 保留为根节点）
- 顶层形状设置 parent="1"
- 形状间距 150-200px，便于连线

### 常用样式
- 形状: rounded=1; fillColor=#dae8fc; strokeColor=#6c8ebf
- 连线: endArrow=classic; edgeStyle=orthogonalEdgeStyle
- 文字: fontSize=14; fontStyle=1（粗体）; align=center

### 使用场景
- 用户说"画一个…"、"帮我做个流程图"、"生成架构图"等
- 生成图表前先用 1-2 句话说明布局计划
- 然后调用工具生成 XML
- 图表会以预览图形式显示在聊天中
"""
