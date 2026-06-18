/**
 * Puppeteer-based headless renderer for draw.io diagrams
 *
 * Core flow:
 * 1. Launch headless Chromium via Puppeteer
 * 2. Navigate to self-hosted draw.io embed page
 * 3. Use postMessage to load XML and export as SVG/PNG
 * 4. Return the rendered image as data URL
 */

import puppeteer, { type Browser, type Page } from "puppeteer"
import { log } from "./logger.js"

// Extract origin from URL for postMessage security check
function getOrigin(url: string): string {
    try {
        const parsed = new URL(url)
        return `${parsed.protocol}//${parsed.host}`
    } catch {
        return url
    }
}

export class DrawioRenderer {
    private browser: Browser | null = null
    private page: Page | null = null
    private drawioBaseUrl: string = ""
    private drawioOrigin: string = ""
    private isReady = false
    private initPromise: Promise<void> | null = null

    /**
     * Initialize the headless browser and load draw.io embed page
     */
    async init(drawioBaseUrl: string, executablePath?: string): Promise<void> {
        if (this.isReady) return
        if (this.initPromise) return this.initPromise

        this.initPromise = this._doInit(drawioBaseUrl, executablePath)
        return this.initPromise
    }

    private async _doInit(drawioBaseUrl: string, executablePath?: string): Promise<void> {
        this.drawioBaseUrl = drawioBaseUrl.replace(/\/$/, "")
        this.drawioOrigin = getOrigin(this.drawioBaseUrl)

        log.info(`Launching headless browser...`)
        this.browser = await puppeteer.launch({
            headless: true,
            executablePath: executablePath || undefined,
            args: [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        })

        this.page = await this.browser.newPage()
        await this.page.setViewport({ width: 1200, height: 800 })

        // Create a container page with an iframe for draw.io embed mode
        // draw.io's embed+proto=json requires being inside an iframe to work properly
        const iframeUrl = `${this.drawioBaseUrl}/?embed=1&proto=json&spin=0&libraries=0&noSaveBtn=1&noExitBtn=1`
        const containerHtml = `<!DOCTYPE html><html><head><style>
            html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}
            iframe{width:100%;height:100%;border:none;}
        </style></head><body>
            <iframe id="drawio" src="${iframeUrl}"></iframe>
        </body></html>`

        await this.page.setContent(containerHtml)
        log.info(`Loaded container page with draw.io iframe: ${iframeUrl}`)

        // Wait for draw.io to initialize via postMessage from iframe
        await this.waitForDrawioInit()
        this.isReady = true
        log.info("draw.io renderer ready")
    }

    /**
     * Wait for draw.io to send the 'init' event via postMessage
     */
    private async waitForDrawioInit(): Promise<void> {
        if (!this.page) throw new Error("Page not initialized")

        return new Promise<void>((resolve, reject) => {
            const timeout = setTimeout(() => {
                reject(new Error("draw.io init timeout (30s)"))
            }, 30000)

            // Listen for postMessage from draw.io iframe
            this.page!.exposeFunction("onDrawioMessage", (data: string) => {
                try {
                    const msg = JSON.parse(data)
                    if (msg.event === "init") {
                        clearTimeout(timeout)
                        resolve()
                    }
                } catch {
                    // ignore parse errors
                }
            })

            // Inject script to forward postMessage to exposed function
            this.page!.evaluate((origin: string) => {
                window.addEventListener("message", (e) => {
                    if (typeof e.data === "string") {
                        try {
                            const msg = JSON.parse(e.data)
                            if (msg.event === "init") {
                                ;(window as any).onDrawioMessage(e.data)
                            }
                        } catch {
                            // ignore
                        }
                    }
                })
            }, this.drawioOrigin)
        })
    }

    /**
     * Render a draw.io diagram XML to SVG or PNG
     * @returns data URL string (e.g., "data:image/svg+xml;base64,...")
     */
    async renderDiagram(
        xml: string,
        format: "svg" | "png" = "svg",
    ): Promise<string> {
        if (!this.isReady || !this.page) {
            throw new Error("Renderer not initialized. Call init() first.")
        }

        log.info(`Rendering diagram (${xml.length} chars, format=${format})`)

        // Step 1: Load the XML into draw.io
        await this.loadDiagram(xml)

        // Step 2: Export as SVG or PNG
        const dataUrl = await this.exportDiagram(format)

        log.info(`Diagram rendered successfully (${dataUrl.length} chars)`)
        return dataUrl
    }

    /**
     * Send load command to draw.io iframe and wait for it to be ready
     */
    private async loadDiagram(xml: string): Promise<void> {
        if (!this.page) throw new Error("Page not initialized")

        // Set up listener for autosave event (indicates load is complete)
        await this.page.evaluate(() => {
            return new Promise<void>((resolve) => {
                const handler = (e: MessageEvent) => {
                    try {
                        const msg = JSON.parse(e.data)
                        if (msg.event === "autosave" || msg.event === "save") {
                            window.removeEventListener("message", handler)
                            // Give draw.io a moment to finish rendering
                            setTimeout(resolve, 300)
                        }
                    } catch {
                        // ignore
                    }
                }
                window.addEventListener("message", handler)
                // Timeout fallback
                setTimeout(() => {
                    window.removeEventListener("message", handler)
                    resolve()
                }, 8000)
            })
        })

        // Send load command
        const loadMsg = JSON.stringify({
            action: "load",
            xml,
            autosave: 0,
        })

        await this.page.evaluate((msg: string) => {
            const iframe = document.getElementById("drawio") as HTMLIFrameElement
            if (iframe?.contentWindow) {
                iframe.contentWindow.postMessage(msg, "*")
            }
        }, loadMsg)
    }

    /**
     * Request export from draw.io and wait for the result
     */
    private async exportDiagram(format: "svg" | "png"): Promise<string> {
        if (!this.page) throw new Error("Page not initialized")

        const exportMsg = JSON.stringify({
            action: "export",
            format: format === "png" ? "png" : "svg",
            ...(format === "png" ? { scale: 2 } : {}),
        })

        // Set up listener for export result
        const resultPromise = new Promise<string>((resolve, reject) => {
            const timeout = setTimeout(() => {
                reject(new Error(`Export timeout (15s) for format=${format}`))
            }, 15000)

            this.page!.evaluate((origin: string) => {
                return new Promise<void>((resolveEval) => {
                    const handler = (e: MessageEvent) => {
                        try {
                            const msg = JSON.parse(e.data)
                            if (msg.event === "export" && msg.data) {
                                window.removeEventListener("message", handler)
                                ;(window as any).__exportResult = msg.data
                                resolveEval()
                            }
                        } catch {
                            // ignore
                        }
                    }
                    window.addEventListener("message", handler)
                    // Auto-resolve after timeout (will be caught by outer timeout)
                    setTimeout(() => {
                        window.removeEventListener("message", handler)
                        resolveEval()
                    }, 14000)
                })
            }, this.drawioOrigin)

            // Poll for result
            const pollInterval = setInterval(async () => {
                const result = await this.page!.evaluate(() => {
                    const r = (window as any).__exportResult
                    if (r) {
                        delete (window as any).__exportResult
                        return r
                    }
                    return null
                })
                if (result) {
                    clearTimeout(timeout)
                    clearInterval(pollInterval)
                    resolve(result)
                }
            }, 200)
        })

        // Send export request to iframe
        await this.page.evaluate((msg: string) => {
            const iframe = document.getElementById("drawio") as HTMLIFrameElement
            if (iframe?.contentWindow) {
                iframe.contentWindow.postMessage(msg, "*")
            }
        }, exportMsg)

        const data = await resultPromise

        // Normalize to data URL
        if (format === "svg") {
            if (data.startsWith("data:")) return data
            // Raw SVG text → encode as data URL
            return `data:image/svg+xml;base64,${Buffer.from(data, "utf-8").toString("base64")}`
        } else {
            // PNG should already be a data URL from draw.io
            if (data.startsWith("data:image/png")) return data
            throw new Error(`Unexpected PNG export format: ${data.slice(0, 50)}`)
        }
    }

    /**
     * Wait for a specific draw.io event
     */
    private async waitForEvent(event: string, timeoutMs: number): Promise<void> {
        if (!this.page) throw new Error("Page not initialized")

        return new Promise<void>((resolve, reject) => {
            const timeout = setTimeout(() => {
                reject(new Error(`Timeout waiting for '${event}' event (${timeoutMs}ms)`))
            }, timeoutMs)

            // For 'load' event, draw.io sends a 'save' or 'autosave' event after loading
            // We give it a short delay to ensure rendering is complete
            const checkInterval = setInterval(async () => {
                clearInterval(checkInterval)
                clearTimeout(timeout)
                // Small delay to ensure rendering is done
                setTimeout(resolve, 500)
            }, 300)
        })
    }

    /**
     * Shutdown the headless browser
     */
    async shutdown(): Promise<void> {
        if (this.browser) {
            log.info("Shutting down headless browser")
            await this.browser.close()
            this.browser = null
            this.page = null
            this.isReady = false
            this.initPromise = null
        }
    }
}
