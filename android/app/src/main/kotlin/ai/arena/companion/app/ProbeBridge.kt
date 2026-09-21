// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ProbeInjection.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ProbeReader.cs
// spec: docs/mcp-android-implementation-plan.md §3.9 / §4
package ai.arena.companion.app

import android.webkit.WebView
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

/**
 * document-start 注入 + 主动 push 读取。
 *
 * `addDocumentStartJavaScript` 与 WebView2 的 `AddScriptToExecuteOnDocumentCreatedAsync`
 * 语义严格对等（都在页面脚本之前运行、覆盖 iframe）。必须在页面脚本之前接管 fetch/XHR，
 * 否则漏掉首个对话请求。
 *
 * 相比 C# 版的 CDP evaluate 轮询，这里用 WebMessageListener 让探针主动 push，
 * 消掉 `ProbeReader.cs` 注释里记录的三个坑（IIFE 包装、runId 残留、引号转义）。
 */
class ProbeBridge(private val assets: android.content.res.AssetManager) {

    /** 注入是否成功。失败时**静默降级**，只在状态栏提示，不影响任何其他功能。 */
    var injected: Boolean = false
        private set

    var lastError: String? = null
        private set

    /** 只在 arena.ai 上运行。 */
    private val origins = setOf("https://arena.ai")

    fun install(webView: WebView) {
        try {
            if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
                lastError = "当前 WebView 不支持 document-start 注入，模型名将显示为「未识别（探针未加载）」"
                injected = false
                return
            }
            val script = buildString {
                // 页面内悬浮面板会挡住自动点击，必须关掉。
                append("window.__MODEL_PROBE_OPTIONS__={showHUD:false};\n")
                append(readAsset(PROBE_ASSET))
                append('\n')
                append(readAsset(BRIDGE_ASSET))
                append('\n')
                append(readAsset(RENAME_ASSET))
                append('\n')
                append(readAsset(ARCHIVE_ASSET))
            }
            WebViewCompat.addDocumentStartJavaScript(webView, script, origins)
            injected = true
            lastError = null
        } catch (e: Exception) {
            // 注入失败静默降级：不抛、不阻塞，阶段机会在 20 秒后以"未识别（探针未加载）"收尾。
            injected = false
            lastError = e.message ?: e.toString()
        }
    }

    /** 探针脚本从资源读取而非内嵌，便于单独更新（§3.9）。 */
    private fun readAsset(name: String): String =
        assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }

    companion object {
        const val PROBE_ASSET = "arena-model-probe.inject.js"
        const val BRIDGE_ASSET = "PageBridge.js"
        const val RENAME_ASSET = "ModelRename.js"
        const val ARCHIVE_ASSET = "ModelArchive.js"
    }
}
