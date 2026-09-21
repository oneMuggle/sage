// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AuthPages.cs
package ai.arena.companion.app

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AuthPages
import android.content.res.AssetManager
import android.net.Uri
import android.webkit.WebView
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.isActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/** Android WebView implementation of [AuthPages]. */
class WebViewAuthPages(
    private val arena: WebView,
    private val auth: WebView,
    assets: AssetManager,
    private val timeoutMillis: Long = 15000,
) : AuthPages {
    private val bridge: String = assets.open(AUTH_BRIDGE_ASSET)
        .bufferedReader(Charsets.UTF_8).use { it.readText() }

    override suspend fun read(target: String): Map<String, Any?> =
        execute(target, "window.__arenaAuth.read()")

    override suspend fun act(target: String, action: String, data: AccountData) {
        val payload = JSONObject()
            .put("email", data.email)
            .put("password", data.password)
            .put("name", data.name)
            .toString()
        execute(
            target,
            "(()=>{try{return window.__arenaAuth.act(${JSONObject.quote(action)},$payload);}" +
                "catch(e){return {bridgeError:(e&&e.message)||String(e)}}})()",
        )
    }

    override fun navigate(target: String, url: String) {
        if (!isAllowedNavigation(url)) throw IllegalStateException("登录流程地址不受支持")
        select(target).loadUrl(url)
    }

    private suspend fun execute(target: String, expression: String): Map<String, Any?> {
        val webView = select(target)
        if (!isSupportedPage(webView.url)) return mapOf("stage" to "loading")
        val script = "(function(){\n$bridge\nreturn ($expression);\n})()"
        val raw = evaluate(webView, "JSON.stringify($script)")
            ?: throw IllegalStateException("页面操作结果未确认")
        val data = parseObject(raw)
        data["bridgeError"]?.toString()?.takeIf { it.isNotEmpty() }?.let { throw IllegalStateException(it) }
        return data
    }

    private fun select(target: String): WebView = if (target == "auth") auth else arena

    private suspend fun evaluate(webView: WebView, script: String): String? = try {
        withTimeout(timeoutMillis) {
            withContext(Dispatchers.Main) {
                suspendCancellableCoroutine { cont ->
                    webView.evaluateJavascript(script) { value ->
                        if (cont.isActive) cont.resume(unwrap(value))
                    }
                }
            }
        }
    } catch (e: TimeoutCancellationException) {
        throw java.util.concurrent.TimeoutException("页面响应超时")
    }

    private fun parseObject(raw: String): MutableMap<String, Any?> {
        val obj = JSONObject(raw)
        val out = linkedMapOf<String, Any?>()
        val keys = obj.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val value = obj.opt(key)
            out[key] = if (value == JSONObject.NULL) null else value
        }
        return out
    }

    private fun isSupportedPage(url: String?): Boolean {
        val host = runCatching { Uri.parse(url).host }.getOrNull()
        return host == "arena.ai" || host == "10minutemail.one"
    }

    private fun isAllowedNavigation(url: String): Boolean {
        if (url == "about:blank") return true
        val parsed = runCatching { Uri.parse(url) }.getOrNull() ?: return false
        return parsed.scheme == "https" && (parsed.host == "arena.ai" || parsed.host == "10minutemail.one")
    }

    private companion object {
        const val AUTH_BRIDGE_ASSET = "AuthBridge.js"

        fun unwrap(value: String?): String? {
            if (value == null || value == "null") return null
            return try {
                JSONObject("{\"v\":$value}").optString("v")
            } catch (_: Exception) {
                value
            }
        }
    }
}
