// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.cs
// spec: docs/mcp-android-implementation-plan.md §4「必须保持单次快照语义」
package ai.arena.companion.app

import ai.arena.companion.automation.ArenaPage
import ai.arena.companion.automation.PageReadTimeoutException
import ai.arena.companion.automation.PageState
import ai.arena.companion.identity.ConversationIdentity
import android.webkit.WebView
import java.time.Instant
import kotlin.coroutines.resume
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.Dispatchers
import org.json.JSONArray
import org.json.JSONObject

/**
 * 用注入的 `PageBridge.js` 读取单次快照。
 *
 * **一次 evaluate 返回整个快照对象**，绝不拆成多次读取——那会撕裂 snapshotConsistent。
 * 读取超时抛 [PageReadTimeoutException]，由阶段机按指数退避处理
 * （流式渲染时主线程繁忙导致读超时是正常现象，安卓上只会更频繁）。
 */
class WebViewArenaPage(
    private val webView: WebView,
    private val readTimeoutMillis: Long = 8000,
) : ArenaPage {

    override val demo: Boolean = false

    override fun isAllowed(url: String?): Boolean =
        ConversationIdentity.route(url)?.startsWith("https://arena.ai") == true

    override suspend fun read(prompt: String?): PageState? {
        val raw = try {
            evaluate("(window.__ARENA_PAGE_BRIDGE__&&__ARENA_PAGE_BRIDGE__.snapshot(${quote(prompt)}))||null")
        } catch (e: TimeoutCancellationException) {
            throw PageReadTimeoutException("页面快照读取超时")
        }
        if (raw.isNullOrBlank() || raw == "null") return null
        return parse(raw)
    }

    override suspend fun act(name: String, prompt: String?) {
        evaluate("(window.__ARENA_PAGE_BRIDGE__&&__ARENA_PAGE_BRIDGE__.act(${quote(name)},${quote(prompt)}))||false")
    }

    private suspend fun evaluate(script: String): String? = withTimeout(readTimeoutMillis) {
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
                webView.evaluateJavascript("JSON.stringify($script)") { value ->
                    cont.resume(unwrap(value))
                }
            }
        }
    }

    private fun parse(raw: String): PageState {
        val o = JSONObject(raw)
        return PageState(
            url = o.optString("url").ifEmpty { null },
            browserSourceBefore = o.optString("browserSourceBefore").ifEmpty { null },
            browserSourceAfter = o.optString("browserSourceAfter").ifEmpty { null },
            main = o.optBoolean("main"),
            conversation = o.optBoolean("conversation"),
            promptConfirmed = o.optBoolean("promptConfirmed"),
            thinking = o.optBoolean("thinking"),
            generating = o.optBoolean("generating"),
            failed = o.optBoolean("failed"),
            response = o.optBoolean("response"),
            generationStamp = o.optString("generationStamp"),
            progressSignature = o.optString("progressSignature"),
            completionConfirmed = o.optBoolean("completionConfirmed"),
            activity = o.optBoolean("activity"),
            snapshotConsistent = o.optBoolean("snapshotConsistent", true),
            messageIdentity = o.optString("messageIdentity"),
            responseSignature = o.optString("responseSignature"),
            draft = if (o.isNull("draft")) null else o.optString("draft"),
            editor = o.optBoolean("editor"),
            blocker = o.optString("blocker"),
            termsPending = o.optBoolean("termsPending"),
            sendReady = o.optBoolean("sendReady"),
            newLinks = o.optInt("newLinks"),
            canExpand = o.optBoolean("canExpand"),
            // 附件（B35）：输入区已暂存的附件名 / 对话区已显示的附件名，供 RequestPreparation.check() 用。
            attachmentNames = strings(o.optJSONArray("attachmentNames")),
            conversationAttachments = strings(o.optJSONArray("conversationAttachments")),
            // rateLimitId / rateLimitRetryAt 由 RateLimitTracker.apply() 填，不从页面读。
            rateLimitRetryAt = Instant.MIN,
        )
    }

    private companion object {
        fun strings(array: JSONArray?): List<String> {
            if (array == null) return emptyList()
            return (0 until array.length()).mapNotNull { i -> array.optString(i).takeIf { it.isNotEmpty() } }
        }

        /** evaluateJavascript 返回的是 JSON 字面量，字符串结果带引号需要解包。 */
        fun unwrap(value: String?): String? {
            if (value == null || value == "null") return null
            return try {
                JSONObject("{\"v\":$value}").optString("v")
            } catch (_: Exception) {
                value
            }
        }

        fun quote(value: String?): String =
            if (value == null) "null" else JSONObject.quote(value)
    }
}
