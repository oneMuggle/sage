// ref: reference/Arena\u6a21\u578b\u52a9\u624b-\u6e90\u7801-fyb-0.1.0/src/RenamePage.cs
// spec: docs/mcp-android-implementation-plan.md \u00a73.1 rename \u9636\u6bb5
package ai.arena.companion.app

import ai.arena.companion.automation.RenameExecutor
import ai.arena.companion.automation.RenameState
import android.webkit.WebView
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/**
 * \u7528 ModelRename.js \u5b9e\u73b0 RenameExecutor\u3002
 * \u6bcf\u6b21 act \u90fd\u662f\u4e00\u6b21 evaluateJavascript\uff0c\u4e0e WebViewArenaPage \u540c\u6837\u7684\u5355\u6b21\u5feb\u7167\u8bed\u4e49\u3002
 */
class WebViewRenameExecutor(
    private val webView: WebView,
    private val timeoutMillis: Long = 8000,
) : RenameExecutor {

    override suspend fun execute(action: String, value: String, target: String?): RenameState {
        val script = "JSON.stringify((window.__ARENA_RENAME_BRIDGE__&&__ARENA_RENAME_BRIDGE__.act(${quote(action)},${quote(value)},${quote(target)}))||{error:'rename bridge not loaded'})"
        val raw = evaluate(script) ?: return RenameState(error = "rename bridge not loaded")
        return try {
            val unwrapped = JSONObject("{\"v\":$raw}").optString("v")
            val o = JSONObject(unwrapped)
            RenameState(
                linkCount = o.optInt("linkCount", 0),
                title = if (o.isNull("title")) null else o.optString("title"),
                renameMenu = o.optBoolean("renameMenu", false),
                renameDialog = o.optBoolean("renameDialog", false),
                pending = o.optBoolean("pending", false),
                error = if (o.isNull("error")) null else o.optString("error").takeUnless { it == "null" || it.isEmpty() },
            )
        } catch (e: Exception) {
            RenameState(error = e.message ?: "parse failed: $raw")
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
