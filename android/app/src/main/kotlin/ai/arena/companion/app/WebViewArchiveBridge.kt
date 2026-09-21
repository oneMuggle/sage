// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.ModelArchive.cs（Execute(script + window.__arenaModelArchive(...)) 那一行）
// spec: docs/mcp-android-implementation-plan.md §3.4 保留策略 / §4「必须保持单次快照语义」
package ai.arena.companion.app

import ai.arena.companion.automation.ArchiveStepResult
import android.webkit.WebView
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/**
 * ModelArchive.js 的一步 = 一次 evaluateJavascript；轮询与超时由 core 的 [ai.arena.companion.automation.WebsiteArchiver] 负责。
 * 脚本随 ProbeBridge 在 document-start 注入，这里只调用 `window.__ARENA_ARCHIVE_BRIDGE__.step(...)`。
 */
class WebViewArchiveBridge(
    private val webView: WebView,
    private val timeoutMillis: Long = 8000,
) {

    suspend fun step(target: String, token: String, prompt: String?, generationStamp: String?): ArchiveStepResult? {
        val script = "JSON.stringify((window.__ARENA_ARCHIVE_BRIDGE__&&__ARENA_ARCHIVE_BRIDGE__.step(" +
            "${quote(target)},${quote(token)},${quote(prompt)},${quote(generationStamp)}))||{error:'archive bridge not loaded'})"
        val raw = evaluate(script) ?: return ArchiveStepResult(error = "页面归档脚本读取超时")
        return try {
            val unwrapped = JSONObject("{\"v\":$raw}").optString("v")
            if (unwrapped.isEmpty() || unwrapped == "null") return null
            val o = JSONObject(unwrapped)
            ArchiveStepResult(
                confirmed = o.optBoolean("confirmed", false),
                pending = o.optBoolean("pending", false),
                error = if (o.isNull("error")) null else o.optString("error").takeUnless { it == "null" || it.isEmpty() },
                evidence = if (o.isNull("evidence")) null else o.optString("evidence"),
                stage = if (o.isNull("stage")) null else o.optString("stage"),
            )
        } catch (e: Exception) {
            ArchiveStepResult(error = e.message ?: "parse failed: $raw")
        }
    }

    private suspend fun evaluate(script: String): String? = try {
        withTimeout(timeoutMillis) {
            withContext(Dispatchers.Main) {
                suspendCancellableCoroutine { cont ->
                    webView.evaluateJavascript(script) { value -> cont.resume(value) }
                }
            }
        }
    } catch (e: TimeoutCancellationException) {
        null
    }

    companion object {
        fun quote(v: String?): String = if (v == null) "null" else JSONObject.quote(v)
    }
}
