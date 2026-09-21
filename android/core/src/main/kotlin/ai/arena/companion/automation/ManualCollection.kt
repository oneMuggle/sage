// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ManualCollection.cs
// spec: docs/mcp-android-implementation-plan.md §3.3
package ai.arena.companion.automation

import ai.arena.companion.identity.ConversationIdentity
import kotlinx.coroutines.CancellationException

data class ManualCollectionResult(val state: PageState, val probe: ProbeSnapshot)

/**
 * 双读稳定性校验：read → validate → probe(before) → 500ms → probe(after) → read → validate → 全字段比对。
 * 每一步之间复查收集条件，条件改变立即取消。流程不可简化。
 */
object ManualCollection {

    private fun active(active: () -> Boolean) {
        if (!active()) throw CancellationException("收集条件已改变，未写入归档")
    }

    fun validate(state: PageState?) {
        if (state == null || !state.snapshotConsistent ||
            ConversationIdentity.created(state.url) == null || !state.main || !state.conversation
        ) throw IllegalStateException("当前不是已加载完成的具体会话，未收集")
        if (state.generating || state.activity || state.failed || state.termsPending ||
            !state.blocker.isNullOrEmpty() || !state.response ||
            state.generationStamp.isNullOrEmpty() || state.responseSignature.isNullOrEmpty()
        ) throw IllegalStateException("当前回答仍在生成、尚未就绪或存在错误，请等待回答完成后再收集")
    }

    suspend fun read(
        read: suspend () -> PageState?,
        probe: suspend () -> ProbeSnapshot?,
        isActive: () -> Boolean,
        delay: suspend (Int) -> Unit,
    ): ManualCollectionResult {
        active(isActive); val first = read(); active(isActive); validate(first)
        val before = probe() ?: ProbeSnapshot(); active(isActive)
        delay(500); active(isActive)
        val after = probe() ?: ProbeSnapshot(); active(isActive)
        val last = read(); active(isActive); validate(last)
        if (!ConversationIdentity.same(first!!.url, last!!.url) ||
            first.generationStamp != last.generationStamp ||
            first.responseSignature != last.responseSignature ||
            before.api != after.api || before.runId != after.runId || before.name != after.name
        ) throw IllegalStateException("读取期间会话、回答或模型发生变化，未写入；请稳定后再收集")
        return ManualCollectionResult(last, after)
    }
}
