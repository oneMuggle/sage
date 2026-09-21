// spec: docs/mcp-android-implementation-plan.md §4.1
//       「代理为进程级 → 串行化单活动实例 + localhost 认证中继（必需）；
//         节点不可用时阻止启动、不回退直连」
package ai.arena.companion.app

import ai.arena.companion.net.ProxyRelay
import ai.arena.companion.net.ProxySettings
import android.os.Looper
import androidx.webkit.ProxyConfig
import androidx.webkit.ProxyController
import androidx.webkit.WebViewFeature
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** 代理无法就绪。**调用方必须阻止实例启动**，不得回退直连。 */
class ProxyUnavailableException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)

/**
 * 代理闸门。
 *
 * 关键平台事实：`ProxyController.setProxyOverride()` 是**进程级**的，一个进程里所有
 * WebView 共用一份设置。所以多实例并行跑不同代理在安卓上做不到——上层必须
 * **串行化到单个活动实例**，本类只负责「当前活动实例的代理要么正确生效、要么直接失败」。
 */
class ProxyGate(private val relay: ProxyRelay = ProxyRelay()) : AutoCloseable {

    /** 当前生效的代理描述，供 UI 显示；null 表示跟随系统。 */
    @Volatile var active: String? = null
        private set

    /** 本进程是否留下过 WebView 代理 override（override 是进程级的，得自己记账）。 */
    @Volatile private var overrideApplied = false

    /**
     * WebView 回调的投递执行器。**绝不能复用调用方的执行器**：[await] 会阻塞调用线程等回调，
     * 回调若又投递回同一个被阻塞的线程（典型：主线程），两者互相饿死，直到超时。
     */
    private val callbacks: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "proxy-gate-callback").apply { isDaemon = true }
    }

    /**
     * 为一个实例应用代理。失败一律抛 [ProxyUnavailableException]，
     * **绝不悄悄退回直连**——那会让请求带着真实 IP 出去。
     *
     * **必须在后台线程调用**：本方法会阻塞等待 WebView 应用结果（见 [await]）。
     */
    fun apply(settings: ProxySettings) {
        val upstream = try {
            settings.upstream()
        } catch (e: IllegalArgumentException) {
            throw ProxyUnavailableException(e.message ?: "代理配置无效。", e)
        }

        if (upstream == null) {
            clear()                               // system 模式：显式清除残留 override
            return
        }

        if (!WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE)) {
            throw ProxyUnavailableException(
                "当前 WebView 版本不支持代理设置，无法保证流量走节点，已阻止启动。请升级系统 WebView。")
        }

        // 先确认上游真的活着：中继本身只是转发，节点死了要在启动前就发现。
        probe(settings)

        val local = relay.localAddress(upstream)
        val config = ProxyConfig.Builder()
            .addProxyRule(local)
            // 不设 bypass：**任何 URL 都必须走代理**，漏出去一条就等于暴露真实 IP。
            .build()
        await { done -> ProxyController.getInstance().setProxyOverride(config, callbacks, done) }
        overrideApplied = true
        active = "${settings.mode}://${settings.host}:${settings.port} → $local"
    }

    /** 只在明确要回到"跟随系统"时调用。 */
    fun clear() {
        active = null
        if (!overrideApplied) return          // 本进程没设过：不必清，也不必等 WebView 回话
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE)) {
            overrideApplied = false
            return
        }
        await { done -> ProxyController.getInstance().clearProxyOverride(callbacks, done) }
        overrideApplied = false
    }

    /** TCP 连通性探测。连不上 → 抛，调用方阻止启动。 */
    private fun probe(settings: ProxySettings) {
        try {
            Socket().use { it.connect(InetSocketAddress(settings.host, settings.port), PROBE_TIMEOUT_MS) }
        } catch (e: IOException) {
            throw ProxyUnavailableException(
                "代理节点 ${settings.host}:${settings.port} 无法连接，已阻止启动（不会回退直连）。", e)
        }
    }

    /**
     * 阻塞等待 WebView 回话。回调投递到内部 [callbacks] 线程，与被阻塞的调用线程分离——
     * 历史 bug 就是「主线程阻塞 + 回调回主线程」自己等自己，必然 10 秒超时。
     */
    private fun await(action: (Runnable) -> Unit) {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "代理闸门会阻塞等待 WebView，不得在主线程调用；请在后台线程执行、再回主线程更新 UI。"
        }
        val latch = CountDownLatch(1)
        action(Runnable { latch.countDown() })
        if (!latch.await(APPLY_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            throw ProxyUnavailableException("代理设置未在 ${APPLY_TIMEOUT_SECONDS} 秒内生效，已阻止启动。")
        }
    }

    override fun close() {
        // 只发不等：close() 可能在任意线程被调用，等回调就有死锁风险；进程结束会带走 override。
        if (overrideApplied) {
            runCatching {
                if (WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE)) {
                    ProxyController.getInstance().clearProxyOverride(callbacks) {}
                }
            }
            overrideApplied = false
        }
        callbacks.shutdownNow()
        relay.close()
        active = null
    }

    private companion object {
        const val PROBE_TIMEOUT_MS = 8_000
        const val APPLY_TIMEOUT_SECONDS = 10L
    }
}
