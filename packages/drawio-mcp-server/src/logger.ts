/**
 * Logger for MCP server
 * All logs go to stderr since MCP uses stdin/stdout for JSON-RPC
 */

export const log = {
    info: (...args: unknown[]) => console.error(`[sage-drawio-mcp] [INFO]`, ...args),
    error: (...args: unknown[]) => console.error(`[sage-drawio-mcp] [ERROR]`, ...args),
    warn: (...args: unknown[]) => console.error(`[sage-drawio-mcp] [WARN]`, ...args),
    debug: (...args: unknown[]) =>
        process.env.DEBUG === "true" &&
        console.error(`[sage-drawio-mcp] [DEBUG]`, ...args),
}
