// spec: docs/mcp-android-implementation-plan.md §4.1
// 把第八批的 ProxyGate 与第九批的 ActiveInstanceGate 接成唯一的启动入口。
package ai.arena.companion.app

import ai.arena.companion.data.AcquireResult
import ai.arena.companion.data.ActiveInstanceGate
import ai.arena.companion.net.ProxySettings

/** 启动结果。除了 [Ready]，**任何一种都不得让实例跑起来**。 */
sealed interface LaunchOutcome {
    /** 活动权 + 代理都就绪。`token` 交给 [SessionLauncher.release]。 */
    data class Ready(val instance: String, val token: Long, val proxy: String?) : LaunchOutcome
    /** 别的实例在跑，已排队。 */
    data class Queued(val holder: String, val position: Int) : LaunchOutcome
    /** 代理不可用。**已阻止启动，未回退直连**。 */
    data class Blocked(val reason: String) : LaunchOutcome
}

/**
 * 单一启动入口。顺序是有意的：
 *
 * 1. **先抢活动权**——代理是进程级的，没拿到活动权就去改 override 会把正在跑的实例
 *    的出口换掉。
 * 2. **再验代理**——失败则立刻交还活动权并返回 [LaunchOutcome.Blocked]，
 *    不留下一个"拿着活动权但没代理"的半吊子状态，更不回退直连。
 */
class SessionLauncher(
    private val instances: ActiveInstanceGate = ActiveInstanceGate(),
    private val proxy: ProxyGate = ProxyGate(),
) : AutoCloseable {

    /** 直接暴露闸门供排队可视化与诊断。 */
    val gate: ActiveInstanceGate get() = instances

    /** **必须在后台线程调用**：[ProxyGate.apply] 会阻塞等待 WebView 应用代理。 */
    fun launch(instance: String, settings: ProxySettings): LaunchOutcome {
        val granted = when (val r = instances.acquire(instance)) {
            is AcquireResult.Busy -> return LaunchOutcome.Queued(r.holder, r.position)
            is AcquireResult.Granted -> r
        }
        return try {
            proxy.apply(settings)
            LaunchOutcome.Ready(granted.instance, granted.token, proxy.active)
        } catch (e: ProxyUnavailableException) {
            instances.release(granted.token)
            LaunchOutcome.Blocked(e.message ?: "代理不可用，已阻止启动。")
        } catch (e: Exception) {
            instances.release(granted.token)
            LaunchOutcome.Blocked("启动前检查失败：${e.message}")
        }
    }

    /**
     * 交还活动权。**不自动提升队首**：下一个实例要跑必须重新走 [launch]，
     * 因为它得重新验一遍自己的代理，而不是继承上一个实例留下的 override。
     */
    fun release(token: Long): Boolean = instances.release(token)

    fun holder(): String? = instances.holder()?.instance

    fun queue(): List<String> = instances.queue()

    /** 强制接管，仅允许用户显式动作触发。 */
    fun forceTakeOver(instance: String) = instances.forceTakeOver(instance)

    override fun close() = proxy.close()
}
