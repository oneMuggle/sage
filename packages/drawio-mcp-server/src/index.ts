#!/usr/bin/env node
/* eslint-disable */
/**
 * MCP Server for Sage - draw.io diagram renderer
 *
 * Uses Puppeteer headless browser to render draw.io XML to SVG/PNG.
 * The rendered image data is returned to the caller for inline display in chat.
 */

// Setup DOM polyfill for Node.js (required for XML operations)
import { DOMParser } from "linkedom"
;(globalThis as any).DOMParser = DOMParser

// Create XMLSerializer polyfill using outerHTML
class XMLSerializerPolyfill {
    serializeToString(node: any): string {
        if (node.outerHTML !== undefined) {
            return node.outerHTML
        }
        if (node.documentElement) {
            return node.documentElement.outerHTML
        }
        return ""
    }
}
;(globalThis as any).XMLSerializer = XMLSerializerPolyfill

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js"
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js"
import { z } from "zod"
import { DrawioRenderer } from "./renderer.js"
import { validateAndFixXml, isMxCellXmlComplete } from "./xml-validation.js"
import { log } from "./logger.js"

// Configuration
const DRAWIO_BASE_URL = process.env.DRAWIO_BASE_URL || "http://localhost:8080"
const CHROME_PATH = process.env.CHROME_PATH || process.env.PUPPETEER_EXECUTABLE_PATH || ""

// Create MCP server
const server = new McpServer({
    name: "sage-drawio",
    version: "0.1.0",
})

// Create renderer instance
const renderer = new DrawioRenderer()

// Track current diagram state
let currentXml: string | null = null
let currentSvgDataUrl: string | null = null

// Initialize renderer on first tool call
let initPromise: Promise<void> | null = null
async function ensureInitialized(): Promise<void> {
    if (!initPromise) {
        log.info(`Initializing renderer with DRAWIO_BASE_URL=${DRAWIO_BASE_URL}${CHROME_PATH ? `, CHROME_PATH=${CHROME_PATH}` : ""}`)
        initPromise = renderer.init(DRAWIO_BASE_URL, CHROME_PATH || undefined)
    }
    return initPromise
}

// ============================================================================
// Tool: render_diagram
// ============================================================================
server.registerTool(
    "render_diagram",
    {
        description: `Render a draw.io diagram from XML and return a preview image.

Use this tool when the user asks to create, draw, or generate a diagram, flowchart, sequence diagram, mind map, or any visual representation.

The XML should be a complete mxGraphModel structure:
<mxGraphModel>
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="2" value="Hello" style="rounded=1;" vertex="1" parent="1">
      <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>

LAYOUT CONSTRAINTS:
- Keep all elements within x=0-800, y=0-600 (single page viewport)
- Use unique IDs starting from "2" (0 and 1 are reserved for root)
- Set parent="1" for top-level shapes
- Space shapes 150-200px apart for clear edge routing

COMMON STYLES:
- Shapes: rounded=1; fillColor=#hex; strokeColor=#hex
- Edges: endArrow=classic; edgeStyle=orthogonalEdgeStyle
- Text: fontSize=14; fontStyle=1 (bold); align=center

The tool returns an SVG preview image that will be displayed inline in the chat.`,
        inputSchema: {
            xml: z
                .string()
                .describe(
                    "The complete mxGraphModel XML string for the diagram to render.",
                ),
            format: z
                .enum(["svg", "png"])
                .optional()
                .describe(
                    "Output format. Default is 'svg'. Use 'png' for raster output.",
                ),
        },
    },
    async ({ xml: inputXml, format }) => {
        try {
            await ensureInitialized()

            // Validate and auto-fix XML
            let xml = inputXml
            const { valid, error, fixed, fixes } = validateAndFixXml(xml)
            if (fixed) {
                xml = fixed
                log.info(`XML auto-fixed: ${fixes.join(", ")}`)
            }
            if (!valid && error) {
                log.error(`XML validation failed: ${error}`)
                return {
                    content: [
                        {
                            type: "text",
                            text: `Error: XML validation failed - ${error}`,
                        },
                    ],
                    isError: true,
                }
            }

            // Check if XML is truncated
            if (!isMxCellXmlComplete(xml)) {
                return {
                    content: [
                        {
                            type: "text",
                            text: "Error: XML appears to be truncated. Please provide the complete mxGraphModel XML.",
                        },
                    ],
                    isError: true,
                }
            }

            // Render the diagram
            const outputFormat = format || "svg"
            const dataUrl = await renderer.renderDiagram(xml, outputFormat)

            // Update state
            currentXml = xml
            currentSvgDataUrl = outputFormat === "svg" ? dataUrl : currentSvgDataUrl

            log.info(`Diagram rendered: ${xml.length} chars XML → ${dataUrl.length} chars ${outputFormat.toUpperCase()}`)

            // Return image as MCP standard "image" content type
            // This ensures image data flows through the MCP protocol correctly
            const mimeType = outputFormat === "svg" ? "image/svg+xml" : "image/png"
            const base64Data = dataUrl.includes(",")
                ? dataUrl.split(",")[1]
                : dataUrl

            return {
                content: [
                    {
                        type: "text",
                        text: `Diagram rendered successfully!\n\nXML length: ${xml.length} characters\nFormat: ${outputFormat.toUpperCase()}`,
                    },
                    {
                        type: "image",
                        data: base64Data,
                        mimeType: mimeType,
                    },
                ],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            log.error("render_diagram failed:", message)
            return {
                content: [{ type: "text", text: `Error: ${message}` }],
                isError: true,
            }
        }
    },
)

// ============================================================================
// Tool: get_diagram_xml
// ============================================================================
server.registerTool(
    "get_diagram_xml",
    {
        description:
            "Get the current diagram XML. Call this before edit_diagram to see the current state.",
    },
    async () => {
        if (!currentXml) {
            return {
                content: [
                    {
                        type: "text",
                        text: "No diagram exists yet. Use render_diagram to create one.",
                    },
                ],
            }
        }
        return {
            content: [
                {
                    type: "text",
                    text: `Current diagram XML:\n\n${currentXml}`,
                },
            ],
        }
    },
)

// ============================================================================
// Graceful shutdown
// ============================================================================
let isShuttingDown = false
async function gracefulShutdown(reason: string) {
    if (isShuttingDown) return
    isShuttingDown = true
    log.info(`Shutting down: ${reason}`)
    await renderer.shutdown()
    process.exit(0)
}

process.stdin.on("close", () => gracefulShutdown("stdin closed"))
process.stdin.on("end", () => gracefulShutdown("stdin ended"))
process.on("SIGINT", () => gracefulShutdown("SIGINT"))
process.on("SIGTERM", () => gracefulShutdown("SIGTERM"))
process.stdout.on("error", (err) => {
    if (err.code === "EPIPE" || err.code === "ERR_STREAM_DESTROYED") {
        gracefulShutdown("stdout error")
    }
})

// ============================================================================
// Start the MCP server
// ============================================================================
async function main() {
    log.info("Starting sage draw.io MCP server (headless mode)...")
    log.info(`DRAWIO_BASE_URL=${DRAWIO_BASE_URL}`)

    const transport = new StdioServerTransport()
    await server.connect(transport)

    log.info("MCP server running on stdio")
}

main().catch((error) => {
    log.error("Fatal error:", error)
    process.exit(1)
})
