// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.cs:L11-L47 (PageState / IArenaPage)
// spec: docs/mcp-android-implementation-plan.md §4 "必须保持单次快照语义"
package ai.arena.companion.automation

import java.time.Instant

/**
 * 页面单次快照。必须由 PageBridge.js 一次 evaluate 返回整个对象——
 * 拆成多次读取会撕裂 snapshotConsistent 的语义。
 */
data class PageState(
    var url: String? = null,
    // 原生浏览器地址仅用于诊断，永不用于授权动作。
    var browserSourceBefore: String? = null,
    var browserSourceAfter: String? = null,
    var main: Boolean = false,
    var conversation: Boolean = false,
    var promptConfirmed: Boolean = false,
    var thinking: Boolean = false,
    var generating: Boolean = false,
    var failed: Boolean = false,
    var response: Boolean = false,
    var generationStamp: String? = null,
    var progressSignature: String? = null,
    var completionConfirmed: Boolean = false,
    var activity: Boolean = false,
    var snapshotConsistent: Boolean = true,
    var messageIdentity: String? = null,
    var responseSignature: String? = null,
    var draft: String? = null,
    var editor: Boolean = false,
    var blocker: String? = null,
    var termsPending: Boolean = false,
    var rateLimitId: Int = 0,
    var rateLimitRetryAt: Instant = Instant.MIN,
    var sendReady: Boolean = false,
    var newLinks: Int = 0,
    var canExpand: Boolean = false,
    var attachmentNames: List<String> = emptyList(),
    var conversationAttachments: List<String> = emptyList(),
)

/** 探针快照，对 ProbeSnapshot。 */
data class ProbeSnapshot(
    val api: Boolean = false,
    val runId: String? = null,
    val name: String? = null,
    val lastError: String? = null,
)

/** 读取超时。对 C# TimeoutException 分支（流式渲染时主线程繁忙属正常现象）。 */
class PageReadTimeoutException(message: String) : Exception(message)

interface ArenaPage {
    suspend fun read(prompt: String?): PageState?
    suspend fun act(name: String, prompt: String?)
    fun isAllowed(url: String?): Boolean
    val demo: Boolean
}

interface ProbeReader {
    suspend fun read(): ProbeSnapshot?
}

interface RenamePage {
    suspend fun rename(title: String, active: () -> Boolean, say: (String) -> Unit)
}

/** 对 IRequestPreparation（附件上传准备）。 */
interface RequestPreparation {
    val required: Boolean
    fun beginRound()
    suspend fun prepare(): Boolean
    suspend fun check(): Boolean
}
