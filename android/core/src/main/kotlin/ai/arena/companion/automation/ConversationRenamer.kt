// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RenamePage.cs
// spec: docs/mcp-android-implementation-plan.md §3.1（rename 阶段）/ §5
package ai.arena.companion.automation

import ai.arena.companion.identity.ConversationIdentity
import java.time.Instant
import kotlinx.coroutines.CancellationException

/** 重命名页面脚本返回的状态。对 C# 的 Dictionary<string,object>。 */
data class RenameState(
    val linkCount: Int = 0,
    val title: String? = null,
    val renameMenu: Boolean = false,
    val renameDialog: Boolean = false,
    val pending: Boolean = false,
    val error: String? = null,
)

/** 页面动作执行器：(action, value, target) → 状态。由宿主用注入脚本实现。 */
fun interface RenameExecutor {
    suspend fun execute(action: String, value: String, target: String?): RenameState
}

/** 超时。与 C# 的 TimeoutException 对应，消息原样保留。 */
class RenameTimeoutException(message: String) : Exception(message)

/**
 * 会话重命名。对 `RenamePage.cs`，实现 [RenamePage] 接口供阶段机的 rename 阶段调用。
 *
 * 最关键的一条不变量：**`saveSubmitted` 在 dispatch 之前置位**。
 * 保存响应不确定时，点"继续"绝不能导致重复保存——宁可只去确认结果。
 */
class ConversationRenamer(
    private val currentUrl: () -> String?,
    private val executor: RenameExecutor,
    private val clock: () -> Instant = { Instant.now() },
    private val delay: suspend (Long) -> Unit,
) : RenamePage {

    private var pendingTarget: String? = null
    private var pendingTitle: String? = null
    private var saveSubmitted = false

    suspend fun state(): RenameState = executor.execute("state", "", null)

    suspend fun close() {
        try { executor.execute("cleanup", "", null) } catch (_: Exception) { }
    }

    override suspend fun rename(title: String, active: () -> Boolean, say: (String) -> Unit) {
        checkActive(active)
        val target = ConversationIdentity.created(currentUrl())
            ?: throw IllegalStateException("当前不是可重命名的 Arena 对话")
        if (target != pendingTarget || title != pendingTitle) {
            pendingTarget = target; pendingTitle = title; saveSubmitted = false
        }

        var current = act("state", "", target, active)
        if (hasTitle(current, title) || saveSubmitted) {
            confirm(target, title, current, active, say); return
        }

        if (!current.renameDialog) {
            if (!current.renameMenu) openMenu(target, active, say)
            waitFor("renameMenu", target, active)
            act("menuRename", "", target, active)
            waitFor("renameDialog", target, active)
        }
        act("fill", title, target, active)
        delay(150); checkActive(active)
        // 置位必须在 dispatch 之前：响应不确定时，"继续"绝不能重放保存。
        saveSubmitted = true
        act("save", "", target, active)
        current = act("state", "", target, active)
        confirm(target, title, current, active, say)
    }

    private suspend fun confirm(
        target: String,
        title: String,
        initial: RenameState,
        active: () -> Boolean,
        say: (String) -> Unit,
    ) {
        var state = initial
        val deadline = clock().plusSeconds(30)
        var previous: String? = null
        while (true) {
            checkActive(active)
            val matched = hasTitle(state, title)
            if (matched && !state.renameDialog) { saveSubmitted = false; return }
            val message = if (matched) "名称已更新，等待重命名窗口关闭…" else "已提交重命名，等待网页确认…"
            if (message != previous) { say(message); previous = message }
            if (!clock().isBefore(deadline)) {
                throw RenameTimeoutException(
                    if (matched) "名称已更新，但重命名窗口在30秒内尚未关闭；请检查后点“继续”，不会重复保存"
                    else "重命名提交后30秒仍未确认，已保留本轮；点“继续”只检查结果，不会重复保存"
                )
            }
            delay(200); checkActive(active)
            state = act("state", "", target, active)
        }
    }

    private suspend fun openMenu(target: String, active: () -> Boolean, say: (String) -> Unit) {
        val deadline = clock().plusSeconds(10)
        var retry = false
        while (true) {
            val result = act("openMenu", if (retry) "retry" else "", target, active)
            if (!result.pending) return
            if (!retry) say("正在展开侧栏并等待当前对话入口…")
            if (!clock().isBefore(deadline))
                throw RenameTimeoutException("等待侧栏中的当前对话入口超时；本轮已保留，请检查后点“继续”")
            retry = true
            delay(200); checkActive(active)
        }
    }

    private suspend fun waitFor(key: String, target: String, active: () -> Boolean) {
        repeat(25) {
            val state = act("state", "", target, active)
            val ready = when (key) {
                "renameMenu" -> state.renameMenu
                "renameDialog" -> state.renameDialog
                else -> false
            }
            if (ready) return
            delay(200); checkActive(active)
        }
        throw RenameTimeoutException("等待重命名控件超时")
    }

    private suspend fun act(action: String, value: String, target: String?, active: () -> Boolean): RenameState {
        checkActive(active)
        val result = executor.execute(action, value, target)
        if (result.error != null) throw IllegalStateException(result.error)
        checkActive(active)
        return result
    }

    private fun checkActive(active: () -> Boolean) {
        if (!active()) throw CancellationException("重命名等待已暂停")
    }

    companion object {
        private val WHITESPACE = Regex("\\s+")

        /** 侧栏里必须恰好一个入口，且标题规范化后完全相等。 */
        fun hasTitle(state: RenameState, title: String): Boolean {
            if (state.linkCount != 1) return false
            val normalized = WHITESPACE.replace(
                java.text.Normalizer.normalize(title, java.text.Normalizer.Form.NFC), " "
            ).trim()
            return state.title == normalized
        }
    }
}
