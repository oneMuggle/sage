// spec: docs/mcp-android-implementation-plan.md §7 第 3/4 条（新增，参考是纯内存态）
// 桌面端 RetryController 是纯内存态，桌面进程不会被随机杀所以能忍；
// 安卓上 Doze / 后台回收 / 厂商 ROM 杀后台让它不成立，必须持久化。
// 同时修掉 docs/mcp-reference-inventory-20260919.md R2 记录的问题
// （arena_jobs.py 无 paused 状态、重启不恢复）。
package ai.arena.companion.data

import ai.arena.companion.automation.RetryController
import java.io.File
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 一次自动化任务的可恢复状态。
 *
 * 刻意**不**持久化任何"正在进行中的动作"：没有 pendingAct、没有 inFlightRequest。
 * 恢复后一律进入 paused 等人工确认，禁止自动重放任何有副作用的操作（§7 第 4 条）。
 */
@Serializable
data class JobState(
    val schemaVersion: Int = SCHEMA_VERSION,
    val instance: String,
    val prompt: String,
    val limit: Int,
    val rounds: Int,
    val attempt: Int,
    val phase: String,
    /** 本轮追踪的会话地址，用于恢复后向用户说明"停在哪条对话上"。 */
    val trackedUrl: String? = null,
    val lastModel: String? = null,
    val rateLimitRetries: Int = 0,
    /** ISO-8601，服务端要求的等待截止时间；跨重启必须保留，不能清零重来。 */
    val retryUntilUtc: String? = null,
    val websiteArchivedRounds: Int = 0,
    /** 写入这条状态的时刻，用于诊断"被杀了多久"。 */
    val savedAtUtc: String,
    /** 上一次运行是否是干净收尾。false 表示进程被杀。 */
    val cleanShutdown: Boolean = false,
    val message: String? = null,
) {
    companion object {
        const val SCHEMA_VERSION = 1

        /** 恢复后允许续跑的阶段；其余一律视为不可续，只能重新开始。 */
        val RESUMABLE_PHASES = setOf(
            "inspect", "new", "waitNew", "fill", "send", "confirm",
            "observe", "model", "rename", "collect", "roundPause", "cooldown", "websiteArchive",
        )
    }
}

/** 恢复决定。一律不自动继续——差别只在于给用户什么选项。 */
sealed class RecoveryDecision {
    /** 没有留下状态，全新开始。 */
    object Fresh : RecoveryDecision()

    /** 上次干净收尾，无需恢复提示。 */
    data class CleanExit(val state: JobState) : RecoveryDecision()

    /**
     * 上次被杀。**进入 paused 等人工确认**，附可读诊断。
     * `canContinue` 只决定 UI 是否提供"继续"按钮，不代表会自动继续。
     */
    data class Interrupted(
        val state: JobState,
        val canContinue: Boolean,
        val reason: String,
    ) : RecoveryDecision()

    /** 状态文件存在但读不出或版本不认识。不猜，要求重新开始。 */
    data class Unusable(val reason: String) : RecoveryDecision()
}

class JobStateStore(directory: File) {

    private val file = File(directory.absoluteFile.normalize().also { it.mkdirs() }, "job-state.json")
    private val json = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }

    fun clear() { if (file.exists()) file.delete() }

    fun save(state: JobState) =
        AtomicFiles.write(file, json.encodeToString(JobState.serializer(), state))

    fun load(): JobState? {
        if (!file.exists()) return null
        return try {
            json.decodeFromString(JobState.serializer(), file.readText(Charsets.UTF_8))
        } catch (_: Exception) {
            null
        }
    }

    /** 从控制器快照出当前状态。仅记录可安全恢复的字段。 */
    fun capture(
        instance: String,
        controller: RetryController,
        cleanShutdown: Boolean,
        nowUtc: String,
    ): JobState = JobState(
        instance = instance,
        prompt = controller.prompt ?: "",
        limit = controller.limit,
        rounds = controller.rounds,
        attempt = controller.attempt,
        phase = controller.phase,
        trackedUrl = controller.trackedUrl,
        lastModel = controller.lastModel,
        rateLimitRetries = controller.rateLimitRetries,
        retryUntilUtc = controller.retryAt?.toString(),
        websiteArchivedRounds = controller.websiteArchivedRounds,
        savedAtUtc = nowUtc,
        cleanShutdown = cleanShutdown,
        message = controller.message,
    )

    fun decide(): RecoveryDecision {
        if (!file.exists()) return RecoveryDecision.Fresh
        val state = load()
            ?: return RecoveryDecision.Unusable("任务状态文件已损坏，无法恢复；请重新开始（不会自动重放任何操作）")
        if (state.schemaVersion != JobState.SCHEMA_VERSION)
            return RecoveryDecision.Unusable("任务状态版本不认识（${state.schemaVersion}），请重新开始")
        if (state.cleanShutdown) return RecoveryDecision.CleanExit(state)
        if (state.phase == "idle")
            return RecoveryDecision.Interrupted(state, false, "上次运行被中断，但当时没有进行中的任务")
        val resumable = JobState.RESUMABLE_PHASES.contains(state.phase)
        val reason = if (resumable)
            "上次运行在「${state.phase}」阶段被系统中断（已完成 ${state.rounds} 轮）。" +
                "已保留进度并暂停，不会自动重发已提交的问题；请检查页面后决定是否继续。"
        else
            "上次运行在未知阶段「${state.phase}」被中断，无法安全续跑；请重新开始。"
        return RecoveryDecision.Interrupted(state, resumable, reason)
    }
}
