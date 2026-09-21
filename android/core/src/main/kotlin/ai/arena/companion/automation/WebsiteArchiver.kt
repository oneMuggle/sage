// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.ModelArchive.cs
// spec: docs/mcp-android-implementation-plan.md §3.4 保留策略 / docs/mcp-android-prompt-confirm-timeout-20260921.md §6 B34
package ai.arena.companion.automation

import ai.arena.companion.identity.ConversationIdentity
import java.util.UUID

/** ModelArchive.js 每一步的返回：confirmed / pending / error 三选一（error 非空即失败）。 */
data class ArchiveStepResult(
    val confirmed: Boolean = false,
    val pending: Boolean = false,
    val error: String? = null,
    val evidence: String? = null,
    val stage: String? = null,
)

/** 归档被暂停（active() 变假）时抛出；阶段机此时已不在运行，不再重复报错。 */
class ArchivePausedException(message: String) : IllegalStateException(message)

/**
 * 「未保留模型仅移入网站归档」的轮询驱动，与 C# `WebPage.ArchiveModelConversation` 1:1：
 * 每 [intervalMillis] 调一次页面桥的 step()，最多 [attempts] 次；同一目标复用同一 token，
 * 页面侧据此把 open → menu → sent → confirmSent 的状态跨调用保存下来。
 *
 * 所有失败都以异常结束、绝不重试点击；调用方（RetryController.archiveExcludedModel）收到异常后暂停等人工。
 */
class WebsiteArchiver(
    private val step: suspend (target: String, token: String, prompt: String?, generationStamp: String?) -> ArchiveStepResult?,
    private val currentUrl: () -> String?,
    private val isAllowed: (String?) -> Boolean,
    private val delay: suspend (Long) -> Unit,
    private val attempts: Int = 120,
    private val intervalMillis: Long = 250,
) {
    private var archiveTarget: String? = null
    private var archiveToken: String? = null

    /** 当前目标使用的 token；仅供测试与诊断。 */
    val token: String? get() = archiveToken

    suspend fun archive(url: String?, prompt: String?, generationStamp: String?, active: () -> Boolean) {
        val target = ConversationIdentity.created(url)
            ?: throw IllegalStateException("仅支持真实 Arena 当前对话的归档")
        if (archiveTarget != target) {
            archiveTarget = target
            archiveToken = UUID.randomUUID().toString().replace("-", "")
        }
        val token = archiveToken!!
        repeat(attempts) {
            if (!active()) throw IllegalStateException("归档操作已取消；不会继续点击")
            val source = currentUrl()
            if (source == null || !isAllowed(source)) throw IllegalStateException("页面已改变，归档已停止")
            val result = step(target, token, prompt, generationStamp)
                ?: throw IllegalStateException("归档结果未确认")
            if (!result.error.isNullOrEmpty()) throw IllegalStateException(result.error)
            if (!active()) throw ArchivePausedException("归档已暂停；结果将在继续时确认")
            if (result.confirmed) return
            delay(intervalMillis)
        }
        throw IllegalStateException("归档尚未获得成功确认，已暂停。请检查网页；不会自动点击删除或继续下一条。")
    }
}
