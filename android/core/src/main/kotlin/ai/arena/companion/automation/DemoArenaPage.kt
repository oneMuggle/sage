// spec: docs/mcp-android-implementation-plan.md §3.2 "arena-demo.local 分支保留"
// 离线演示/测试通道：不打真网即可跑通整条阶段机（阶段 C 验收项）。
package ai.arena.companion.automation

import java.time.Instant

/**
 * 纯内存的 arena-demo.local 页面模拟。
 * 只模拟页面对动作的反应，不做任何网络访问；阶段机的判断逻辑保持原样。
 */
class DemoArenaPage(private val clock: () -> Instant = { Instant.now() }) : ArenaPage {

    override val demo: Boolean = true

    private var conversationIndex = 0
    private var state = PageState(
        url = "https://arena-demo.local/agent",
        main = true,
        editor = true,
        newLinks = 1,
    )
    private var sendAt: Instant? = null

    /** 回答生成耗时（秒），测试可调。 */
    var generationSeconds: Long = 2

    val acts = mutableListOf<String>()

    override fun isAllowed(url: String?): Boolean =
        ai.arena.companion.identity.ConversationIdentity.route(url)?.startsWith("https://arena-demo.local") == true

    override suspend fun read(prompt: String?): PageState {
        val started = sendAt
        if (started != null) {
            val elapsed = (clock().toEpochMilli() - started.toEpochMilli()) / 1000
            if (elapsed >= generationSeconds) {
                state = state.copy(
                    generating = false,
                    activity = false,
                    response = true,
                    completionConfirmed = true,
                    responseSignature = "sig-$conversationIndex",
                    progressSignature = "sig-$conversationIndex",
                    generationStamp = "stamp-$conversationIndex",
                )
            }
        }
        return state.copy()
    }

    override suspend fun act(name: String, prompt: String?) {
        acts += name
        when (name) {
            "new" -> {
                conversationIndex++
                sendAt = null
                state = PageState(
                    url = "https://arena-demo.local/agent",
                    main = true,
                    editor = true,
                    newLinks = 1,
                )
            }
            "fill", "retryFill" -> state = state.copy(draft = prompt)
            "send", "retrySend" -> {
                sendAt = clock()
                state = state.copy(
                    url = "https://arena-demo.local/agent/demo-$conversationIndex",
                    conversation = true,
                    promptConfirmed = true,
                    generating = true,
                    activity = true,
                    draft = null,
                    editor = false,
                )
            }
            "expand" -> state = state.copy(newLinks = 1, canExpand = false)
            "terms" -> state = state.copy(termsPending = false)
        }
    }

    /** 测试钩子：直接注入页面状态变化。 */
    fun mutate(block: (PageState) -> PageState) { state = block(state) }

    fun sendReady(ready: Boolean) { state = state.copy(sendReady = ready) }
}
