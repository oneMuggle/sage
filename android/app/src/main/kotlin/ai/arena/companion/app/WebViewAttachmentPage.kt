// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AttachmentUpload.cs（Check / Stage 两段脚本 + DOM.setFileInputFiles）
// spec: docs/mcp-android-prompt-confirm-timeout-20260921.md §6 B35
package ai.arena.companion.app

import ai.arena.companion.automation.AttachmentEntry
import ai.arena.companion.automation.AttachmentPage
import ai.arena.companion.data.BoundAttachment
import ai.arena.companion.identity.ConversationIdentity
import android.net.Uri
import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.core.content.FileProvider
import java.io.File
import kotlin.coroutines.resume
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject

/**
 * 安卓版「把绑定附件交给页面」。
 *
 * 桌面端用 CDP `DOM.setFileInputFiles` 直接往 `<input type=file>` 塞文件；安卓 WebView 没有这条路，
 * 唯一的交付口是 [WebChromeClient.onShowFileChooser]：页面自己打开文件选择时，原生侧把 `content://` URI
 * 通过回调交回去，效果等同用户在系统选择器里选中了这些文件。而 Blink 只允许**用户激活**触发文件选择，
 * `input.click()` 在脚本里无效，所以 [deliver] 由原生侧向 WebView 派发一次真实的触摸 down/up，
 * 落点是 `PageBridge.attachmentEntry()` 给出的入口坐标。
 *
 * 安全边界：
 * - 只在 [deliver] 期间「武装」回调；其余时间 `onShowFileChooser` 返回 false（与之前没有 WebChromeClient 时一致）。
 * - 武装窗口只有 [armMillis]；窗口内没有回调即视为失败，绝不留着一个悬而未决的回调等下次页面动作来消费。
 * - 回调到来时再核一次 URL 仍在 arena.ai/agent、input 与文件数量兼容（单选 input 不接受多文件），不符就交空值。
 * - 文件通过 [FileProvider] 以只读 `content://` 暴露；这是 `TaskSettingsStore.import` 复制到应用私有目录的副本。
 */
class WebViewAttachmentPage(
    private val webView: WebView,
    private val authority: String,
    private val timeoutMillis: Long = 8000,
    private val armMillis: Long = 4000,
) : AttachmentPage {

    private class Armed(
        val uris: Array<Uri>,
        val result: CompletableDeferred<Boolean>,
    )

    private val lock = Any()
    private var armed: Armed? = null

    /** 最近一次交付的诊断说明（状态栏用）。 */
    @Volatile
    var lastNote: String? = null
        private set

    /** 装到 WebView 上；MainActivity 在 configureWebView 之后调用一次。 */
    fun install() {
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?,
            ): Boolean {
                val current = synchronized(lock) { armed.also { armed = null } }
                if (current == null || filePathCallback == null) return false
                val url = view?.url ?: webView.url
                val onAgent = ConversationIdentity.route(url)?.let {
                    it == "https://arena.ai/agent" || it.startsWith("https://arena.ai/agent/")
                } == true
                val multipleOk = current.uris.size <= 1 ||
                    fileChooserParams?.mode == FileChooserParams.MODE_OPEN_MULTIPLE
                if (!onAgent || !multipleOk) {
                    lastNote = if (!onAgent) "文件选择不在 Arena Agent 页面上发生，已拒绝交付"
                    else "页面附件入口只接受单个文件，绑定了 ${current.uris.size} 个，已拒绝交付"
                    filePathCallback.onReceiveValue(null)
                    current.result.complete(false)
                    return true
                }
                filePathCallback.onReceiveValue(current.uris)
                lastNote = "已通过文件选择回调交付 ${current.uris.size} 个附件"
                current.result.complete(true)
                return true
            }
        }
    }

    override suspend fun ready(names: List<String>): Boolean {
        val array = JSONArray().also { a -> names.forEach { a.put(it) } }
        val raw = evaluate("(window.__ARENA_PAGE_BRIDGE__&&__ARENA_PAGE_BRIDGE__.attachmentsReady($array))===true")
        return raw == "true"
    }

    override suspend fun entry(): AttachmentEntry? {
        val raw = evaluate("(window.__ARENA_PAGE_BRIDGE__&&__ARENA_PAGE_BRIDGE__.attachmentEntry())||null") ?: return null
        if (raw == "null" || raw.isBlank()) return null
        return try {
            val o = JSONObject(raw)
            AttachmentEntry(
                count = o.optInt("count", 0),
                reason = o.optString("reason").takeIf { it.isNotEmpty() },
                trigger = o.optBoolean("trigger", false),
                label = o.optString("label").takeIf { it.isNotEmpty() },
                x = o.optDouble("x", 0.0),
                y = o.optDouble("y", 0.0),
                width = o.optDouble("width", 0.0),
                height = o.optDouble("height", 0.0),
                offsetX = o.optDouble("offsetX", 0.0),
                offsetY = o.optDouble("offsetY", 0.0),
                scale = o.optDouble("scale", 1.0),
                dpr = o.optDouble("dpr", 1.0),
            )
        } catch (e: Exception) {
            null
        }
    }

    override suspend fun deliver(entry: AttachmentEntry, files: List<BoundAttachment>): Boolean {
        if (files.isEmpty()) return true
        val uris = files.map { f ->
            val file = File(f.path)
            if (!file.isFile) throw IllegalStateException("绑定附件已丢失或改变：${f.name}")
            FileProvider.getUriForFile(webView.context, authority, file)
        }.toTypedArray()
        val deferred = CompletableDeferred<Boolean>()
        synchronized(lock) {
            // 上一轮若还悬着（理论上不会：窗口到期即清），先按失败收掉，避免两个回调抢一个入口。
            armed?.result?.complete(false)
            armed = Armed(uris, deferred)
        }
        val touched = withContext(Dispatchers.Main) { tap(entry) }
        if (!touched) {
            synchronized(lock) { if (armed?.result === deferred) armed = null }
            lastNote = "附件入口坐标不在 WebView 可视范围内，未触摸"
            return false
        }
        val delivered = withTimeoutOrNull(armMillis) { deferred.await() } ?: false
        synchronized(lock) { if (armed?.result === deferred) armed = null }
        if (!delivered && lastNote?.startsWith("已通过") != false) lastNote = "触摸附件入口后页面没有打开文件选择"
        return delivered
    }

    /** CSS px（布局视口）→ WebView 视图像素：先减视觉视口偏移，再乘视觉缩放与 devicePixelRatio。 */
    private suspend fun tap(entry: AttachmentEntry): Boolean {
        val x = ((entry.x - entry.offsetX) * entry.scale * entry.dpr).toFloat()
        val y = ((entry.y - entry.offsetY) * entry.scale * entry.dpr).toFloat()
        if (entry.width <= 0 || entry.height <= 0) return false
        if (x < 0 || y < 0 || x > webView.width || y > webView.height) return false
        val down = SystemClock.uptimeMillis()
        fun event(action: Int, time: Long): MotionEvent = MotionEvent.obtain(down, time, action, x, y, 0).apply {
            source = InputDevice.SOURCE_TOUCHSCREEN
        }
        val d = event(MotionEvent.ACTION_DOWN, down)
        try { webView.dispatchTouchEvent(d) } finally { d.recycle() }
        delay(TAP_HOLD_MILLIS)
        val u = event(MotionEvent.ACTION_UP, SystemClock.uptimeMillis())
        try { webView.dispatchTouchEvent(u) } finally { u.recycle() }
        return true
    }

    private suspend fun evaluate(script: String): String? = try {
        withTimeout(timeoutMillis) {
            withContext(Dispatchers.Main) {
                suspendCancellableCoroutine { cont ->
                    webView.evaluateJavascript("JSON.stringify($script)") { value -> cont.resume(unwrap(value)) }
                }
            }
        }
    } catch (e: TimeoutCancellationException) {
        null
    }

    companion object {
        /** 触摸按住时长；太短会被当成误触，太长会触发长按菜单。 */
        const val TAP_HOLD_MILLIS = 60L

        fun unwrap(value: String?): String? {
            if (value == null || value == "null") return null
            return try { JSONObject("{\"v\":$value}").optString("v") } catch (_: Exception) { value }
        }
    }
}
