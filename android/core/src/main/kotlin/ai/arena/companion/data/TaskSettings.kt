// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/TaskSettings.cs
// spec: docs/mcp-android-implementation-plan.md §3.6
package ai.arena.companion.data

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class BoundAttachment(
    val name: String,
    var path: String,
    val sha256: String,
    val bytes: Long,
)

@Serializable
data class TaskSettings(
    /** 每轮发送的消息。默认最短的一句，只为触发一次真实模型调用。 */
    var prompt: String = DEFAULT_PROMPT,
    var excludedModels: MutableList<String> = mutableListOf(),
    var pauseOnCaptcha: Boolean = true,
    /** 轮次间隔与抖动（秒）。间隔从本轮全部处理完成后起算，首轮不等待。 */
    var stepPauseSeconds: Double = 3.0,
    var stepPauseJitterSeconds: Double = 2.0,
    var attachments: MutableList<BoundAttachment> = mutableListOf(),
    /** 本次运行的轮次上限；0 表示不限（对应桌面端「收集后继续」勾选）。 */
    var roundLimit: Int = 0,
    /** 一轮内回答长时间无实质变化的上限（秒）；阶段机内部再取 max(60, 值)。 */
    var maximumNoProgressSeconds: Int = DEFAULT_MAXIMUM_NO_PROGRESS_SECONDS,
    /** 等探针给出本轮模型名的上限（秒）；超时按「未识别」收尾。 */
    var modelWaitSeconds: Int = DEFAULT_MODEL_WAIT_SECONDS,
) {
    /** 把越界值收回到阶段机能接受的范围；不改语义，只防手误。 */
    fun normalized(): TaskSettings = apply {
        if (roundLimit < 0) roundLimit = 0
        if (maximumNoProgressSeconds < MIN_NO_PROGRESS_SECONDS) maximumNoProgressSeconds = MIN_NO_PROGRESS_SECONDS
        if (modelWaitSeconds < MIN_MODEL_WAIT_SECONDS) modelWaitSeconds = MIN_MODEL_WAIT_SECONDS
    }

    companion object {
        const val DEFAULT_PROMPT = "1+1="
        /** 旧版本默认值：读配置时仍是它说明用户没改过，跟随新默认值。 */
        const val LEGACY_DEFAULT_PROMPT = "hi"
        /** 与 RetryController / C# 默认值一致（300 / 150 秒）。 */
        const val DEFAULT_MAXIMUM_NO_PROGRESS_SECONDS = 300
        const val DEFAULT_MODEL_WAIT_SECONDS = 150
        const val MIN_NO_PROGRESS_SECONDS = 60
        const val MIN_MODEL_WAIT_SECONDS = 30
    }
}

/**
 * 每实例的任务设置存储。所有写入走原子替换。
 * 附件使用 SHA256 内容寻址目录 `Attachments/<hash>/<name>`，复制后重新哈希校验。
 */
class TaskSettingsStore(directory: File) {

    val directory: File = directory.absoluteFile.normalize().also { it.mkdirs() }
    private val paths = PathPolicy(this.directory)
    private val config = File(this.directory, "task-settings.json")
    private val json = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }

    fun load(): TaskSettings {
        if (!config.exists()) return TaskSettings()
        val settings = try {
            json.decodeFromString(TaskSettings.serializer(), config.readText(Charsets.UTF_8))
        } catch (e: Exception) {
            throw IllegalStateException("任务设置无法读取", e)
        }
        // 空值或仍是旧默认值时跟随新默认值；用户手改过则原样保留。
        if (settings.prompt.isBlank() || settings.prompt == TaskSettings.LEGACY_DEFAULT_PROMPT)
            settings.prompt = TaskSettings.DEFAULT_PROMPT
        settings.attachments.forEach { it.path = paths.resolve(it.path)!! }
        return settings.normalized()
    }

    fun save(settings: TaskSettings) {
        val copy = settings.normalized().copy(
            excludedModels = settings.excludedModels.toMutableList(),
            attachments = settings.attachments
                .map { it.copy(path = paths.store(it.path)!!) }
                .toMutableList(),
        )
        AtomicFiles.write(config, json.encodeToString(TaskSettings.serializer(), copy))
    }

    /** 导入附件到内容寻址目录，复制后重新哈希校验。 */
    fun import(source: File): BoundAttachment {
        val full = source.absoluteFile.normalize()
        if (!full.isFile || full.length() == 0L)
            throw IllegalArgumentException("附件不存在或为空：${full.name}")
        val hash = hash(full)
        val folder = File(File(directory, "Attachments"), hash)
        folder.mkdirs()
        val destination = File(folder, full.name)
        if (!destination.exists()) full.copyTo(destination)
        if (hash(destination) != hash) throw IllegalStateException("附件副本校验失败")
        return BoundAttachment(full.name, destination.path, hash, full.length())
    }

    companion object {
        fun hash(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { stream ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val read = stream.read(buffer)
                    if (read <= 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        /** 存在性 + 字节数 + 哈希三项全查；附件名不得重复。 */
        fun verify(files: Iterable<BoundAttachment>) {
            val names = mutableSetOf<String>()
            for (file in files) {
                if (!names.add(file.name.lowercase()))
                    throw IllegalStateException("附件名称重复，请使用不同名称")
                val f = File(file.path)
                if (!f.isFile || f.length() != file.bytes || hash(f) != file.sha256)
                    throw IllegalStateException("绑定附件已丢失或改变：${file.name}")
            }
        }
    }
}
