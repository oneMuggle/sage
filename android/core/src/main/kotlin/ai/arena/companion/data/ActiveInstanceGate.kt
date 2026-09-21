// spec: docs/mcp-android-implementation-plan.md §4.1
//       「代理为进程级 → 串行化单活动实例（必需）」
package ai.arena.companion.data

/** 请求活动权的结果。 */
sealed interface AcquireResult {
    /** 拿到活动权。 */
    data class Granted(val instance: String, val token: Long) : AcquireResult
    /** 已被别的实例占用——**排队等待，绝不并行**。 */
    data class Busy(val holder: String, val queued: Boolean, val position: Int) : AcquireResult
}

/**
 * 活动实例闸门。
 *
 * 为什么必须存在：安卓的 `setProxyOverride` 是进程级的，一个进程里所有 WebView 共用
 * 一份代理设置。桌面端每个实例一个浏览器进程、各带各的 `--proxy-server`，安卓做不到。
 * 如果放任多实例并行，**第二个实例会悄悄用着第一个实例的出口 IP**——这正是
 * `proxy_relay.py` 注释里记录过的那类隔离失效事故。所以这里把并行变成排队。
 *
 * 语义要点：
 * - 同一时刻**至多一个**实例持有活动权。
 * - `token` 是单调递增的持有凭据；`release` 必须带对 token，**过期 token 无效**，
 *   防止一个已被强制接管的旧持有者在超时后把新持有者释放掉。
 * - 本类只管互斥与排队，不启动任何东西；调用方拿到 `Granted` 后才去 `ProxyGate.apply`。
 */
class ActiveInstanceGate(private val clock: () -> Long = System::currentTimeMillis) {

    data class Holder(val instance: String, val token: Long, val since: Long)

    private val lock = Any()
    private var holder: Holder? = null
    private val waiting = ArrayDeque<String>()
    private var nextToken = 1L

    fun holder(): Holder? = synchronized(lock) { holder }

    fun queue(): List<String> = synchronized(lock) { waiting.toList() }

    /** 申请活动权；占用中则入队（同一实例重复申请不会重复入队）。 */
    fun acquire(instance: String): AcquireResult = synchronized(lock) {
        val name = instance.trim()
        require(name.isNotEmpty()) { "实例名不能为空" }
        val current = holder
        if (current == null) {
            waiting.remove(name)
            val token = nextToken++
            holder = Holder(name, token, clock())
            return AcquireResult.Granted(name, token)
        }
        // 重入：同名实例再次申请，沿用原 token，不排队也不换令牌。
        if (current.instance == name) return AcquireResult.Granted(name, current.token)
        if (!waiting.contains(name)) waiting.addLast(name)
        return AcquireResult.Busy(current.instance, queued = true, position = waiting.indexOf(name) + 1)
    }

    /**
     * 释放活动权。token 不匹配返回 false 且**不做任何事**——
     * 旧持有者被接管后迟到的 release 不能误伤新持有者。
     */
    fun release(token: Long): Boolean = synchronized(lock) {
        val current = holder ?: return false
        if (current.token != token) return false
        holder = null
        return true
    }

    /** 队首实例出队并接手；无人排队返回 null。 */
    fun promoteNext(): AcquireResult.Granted? = synchronized(lock) {
        if (holder != null) return null
        val next = waiting.removeFirstOrNull() ?: return null
        val token = nextToken++
        holder = Holder(next, token, clock())
        return AcquireResult.Granted(next, token)
    }

    /** 放弃排队。 */
    fun cancel(instance: String): Boolean = synchronized(lock) { waiting.remove(instance.trim()) }

    /**
     * 强制接管。**只允许由明确的用户动作触发**（例如"停止当前实例并切换"）：
     * 自动接管会让一个正在等页面的任务被无声打断，而方案要求一切异常都停下等人工。
     */
    fun forceTakeOver(instance: String): AcquireResult.Granted = synchronized(lock) {
        val name = instance.trim()
        require(name.isNotEmpty()) { "实例名不能为空" }
        waiting.remove(name)
        val token = nextToken++
        holder = Holder(name, token, clock())
        return AcquireResult.Granted(name, token)
    }

    /** 持有时长（毫秒）；无人持有返回 0。供 UI 提示"已运行 xx"，**不做自动超时抢占**。 */
    fun heldForMillis(): Long = synchronized(lock) {
        holder?.let { clock() - it.since } ?: 0L
    }
}
