// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ArchiveStore.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ArchiveEntry.cs
// spec: docs/mcp-android-implementation-plan.md §3.8
package ai.arena.companion.data

import ai.arena.companion.identity.ConversationIdentity
import java.io.File
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * 会话多轮模型记录，追踪多轮对话中可能发生的模型漂移。
 */
@Serializable
data class ModelRoundRecord(
    val round: Int,
    val model: String,
    val internal: String? = null,
    val reasoning: Long? = null,
    val timestamp: Long = 0L,
)

/**
 * 一条已归档的会话。不保存截图；归档动作在 arena 侧不可逆，因此不提供"恢复"。
 */
@Serializable
data class ArchiveEntry(
    val id: String,
    val title: String? = null,
    /** 本轮读到的模型名，原始写法，未净化。 */
    val model: String? = null,
    val url: String,
    /** 实例/账号数据目录，用于判断是否属于当前账号。 */
    var profile: String? = null,
    val email: String? = null,
    val prompt: String? = null,
    /** yyyy-MM-dd HH:mm:ss */
    val collectedAt: String? = null,
    /** 相对归档根的模型子目录名（已净化）。 */
    var modelFolder: String? = null,
    /** 相对归档根的入口文件名。 */
    var shortcut: String? = null,
    var renamed: Boolean = false,
    var renameError: String? = null,
    var exportedAt: String? = null,
    var exportedFolder: String? = null,
    /** 阶段 1 新增：所属账号唯一标识与额度快照 */
    val accountId: String? = null,
    val creditsRemaining: Long? = null,
    /** 阶段 1 新增：逐轮模型演进历史轨迹与漂移检测 */
    val modelHistory: List<ModelRoundRecord> = emptyList(),
    val modelDrifted: Boolean = false,
) {
    /** 记录新一轮对话的模型，并在模型变化时自动标明漂移。 */
    fun recordRound(roundNumber: Int, roundModel: String, roundInternal: String? = null, reasoning: Long? = null, ts: Long = 0L): ArchiveEntry {
        val record = ModelRoundRecord(
            round = roundNumber,
            model = roundModel,
            internal = roundInternal,
            reasoning = reasoning,
            timestamp = ts
        )
        val newHistory = modelHistory + record
        val initialModel = modelHistory.firstOrNull()?.model ?: model
        val drifted = modelDrifted || (initialModel != null && initialModel != roundModel)
        return copy(
            model = roundModel,
            modelHistory = newHistory,
            modelDrifted = drifted
        )
    }
}

/**
 * 按模型归档会话。落盘结构与桌面端一致：
 * ```
 * <归档根>/
 *   记录.json
 *   汇总.md
 *   <模型目录>/
 *     清单.md
 *     <标题>.url
 * ```
 * 安卓侧把 `.cmd` / `.lnk` 会话入口换成 deep link（方案 §4），语义保留：
 * 点击入口用本 App 打开该会话。
 */
class ArchiveStore(root: File, private val paths: PathPolicy = PathPolicy(root)) {

    private val json = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }
    private val sync = Any()

    var root: File = root.absoluteFile.normalize()
        private set

    /** 由外部提供：为某个会话地址生成 deep link。 */
    var deepLink: ((String) -> String)? = null

    private val entriesFile: File get() = File(root, RECORDS)

    fun setRoot(path: File) {
        val full = path.absoluteFile.normalize()
        full.mkdirs()
        root = full
    }

    fun all(): MutableList<ArchiveEntry> = synchronized(sync) {
        try {
            if (!entriesFile.exists()) return mutableListOf()
            val list = json.decodeFromString(
                ListSerializer(ArchiveEntry.serializer()),
                entriesFile.readText(Charsets.UTF_8),
            )
            list.forEach { it.profile = paths.resolve(it.profile) }
            list.toMutableList()
        } catch (_: Exception) {
            // 记录读不出按空处理，与桌面端一致：不能因为一条坏记录挡住整个图集。
            mutableListOf()
        }
    }

    fun find(url: String?): ArchiveEntry? {
        if (url.isNullOrEmpty()) return null
        return all().firstOrNull { ConversationIdentity.same(it.url, url) }
    }

    /**
     * 写一条归档：建模型目录 → 建会话入口 → 落盘清单与汇总。
     * 同一会话重复归档幂等：补写缺失的入口文件，不重复记录。
     */
    fun save(entry: ArchiveEntry): ArchiveEntry = synchronized(sync) {
        if (ConversationIdentity.created(entry.url) == null)
            throw IllegalStateException("会话地址无效，未归档")
        root.mkdirs()
        val folder = sanitizeSegment(entry.model?.takeUnless { it.isBlank() } ?: UNIDENTIFIED)
        val modelDir = File(root, folder)
        modelDir.mkdirs()

        // 文件名里把时间冒号换成连字符（00:12 → 00-12），截断 100 字符，为空用 id。
        var fileName = sanitizeSegment((entry.title ?: "").replace(':', '-'))
        if (fileName.isEmpty()) fileName = entry.id
        if (fileName.length > 100) fileName = fileName.substring(0, 100)

        val shortcut = File(modelDir, "$fileName.url")
        if (!shortcut.exists()) {
            val link = deepLink?.invoke(entry.url) ?: entry.url
            try {
                AtomicFiles.write(shortcut, "[InternetShortcut]\nURL=$link\n")
            } catch (_: Exception) {
                // 入口文件写不出不阻塞归档记录。
            }
        }
        entry.modelFolder = folder
        entry.shortcut = "$folder/${shortcut.name}"

        val all = all()
        val index = all.indexOfFirst { ConversationIdentity.same(it.url, entry.url) }
        if (index >= 0) all[index] = entry else all.add(entry)
        writeRecords(all)
        writeModelList(folder, all.filter { it.modelFolder == folder })
        writeSummary(all)
        return entry
    }

    /**
     * 删除一条本地归档记录及它独占的入口文件。
     * **不删除 Arena 网站上的对话**，也不碰导出副本。
     */
    fun delete(id: String): ArchiveEntry? = synchronized(sync) {
        if (id.isBlank()) throw IllegalArgumentException("归档记录标识为空")
        val all = all()
        val index = all.indexOfFirst { it.id == id }
        if (index < 0) return null
        val removed = all.removeAt(index)
        root.mkdirs()
        writeRecords(all)
        cleanupAfterRemoval(listOf(removed), all)
        writeSummary(all)
        return removed
    }

    fun deleteMany(ids: Collection<String>): List<ArchiveEntry> = synchronized(sync) {
        val requested = ids.toSet()
        if (requested.isEmpty() || requested.any { it.isBlank() })
            throw IllegalArgumentException("请先选择有效记录")
        val all = all()
        val removed = all.filter { requested.contains(it.id) }
        if (removed.size != requested.size)
            throw IllegalStateException("部分选中记录已变化，请刷新后重新选择；未删除任何记录")
        val remaining = all.filter { !requested.contains(it.id) }
        writeRecords(remaining)
        cleanupAfterRemoval(removed, remaining)
        writeSummary(remaining)
        return removed
    }

    /** 只改记录里的导出字段，不重建入口、不改清单。记录已不存在时返回 null。 */
    fun markExported(id: String, folder: String, at: String?): ArchiveEntry? = synchronized(sync) {
        if (id.isBlank()) throw IllegalArgumentException("归档记录标识为空")
        if (folder.isBlank()) throw IllegalArgumentException("导出文件夹为空")
        val all = all()
        val entry = all.firstOrNull { it.id == id } ?: return null
        entry.exportedAt = at?.takeUnless { it.isBlank() } ?: nowStamp()
        entry.exportedFolder = folder
        root.mkdirs()
        writeRecords(all)
        return entry
    }

    // ---- 内部 -------------------------------------------------------------

    private fun cleanupAfterRemoval(removed: List<ArchiveEntry>, remaining: List<ArchiveEntry>) {
        // 旧版本中同名标题可能共用一个入口文件；仍有记录引用时不能删它。
        for (item in removed) {
            val stillUsed = !item.shortcut.isNullOrBlank() &&
                remaining.any { it.shortcut.equals(item.shortcut, ignoreCase = true) }
            if (!stillUsed) tryDeleteArchiveFile(item.shortcut)
        }
        for (folder in removed.map { it.modelFolder ?: UNIDENTIFIED }.distinct()) {
            val entries = remaining.filter { (it.modelFolder ?: UNIDENTIFIED) == folder }
            if (entries.isNotEmpty()) writeModelList(folder, entries)
            else {
                tryDeleteArchiveFile("$folder/$MANIFEST")
                tryDeleteEmptyModelDirectory(folder)
            }
        }
    }

    private fun writeRecords(entries: List<ArchiveEntry>) {
        val copy = entries.map { it.copy(profile = paths.store(it.profile)) }
        AtomicFiles.write(entriesFile, json.encodeToString(ListSerializer(ArchiveEntry.serializer()), copy))
    }

    private fun tryDeleteArchiveFile(relativePath: String?) {
        if (relativePath.isNullOrBlank() || File(relativePath).isAbsolute) return
        try {
            val target = File(root, relativePath).absoluteFile.normalize()
            if (!target.path.startsWith(root.path + File.separator)) return
            if (target.isFile) target.delete()
        } catch (_: Exception) {
            // 删除入口失败不应阻止记录与汇总更新。
        }
    }

    private fun tryDeleteEmptyModelDirectory(folder: String?) {
        if (folder.isNullOrBlank() || File(folder).isAbsolute) return
        try {
            val target = File(root, folder).absoluteFile.normalize()
            if (!target.path.startsWith(root.path + File.separator)) return
            if (target.isDirectory && target.list()?.isEmpty() == true) target.delete()
        } catch (_: Exception) {
            // 目录非空或被占用时保留，不扩大删除范围。
        }
    }

    private fun writeModelList(folder: String, entries: List<ArchiveEntry>) {
        val sb = StringBuilder()
        sb.append("# ").append(folder).append('\n').append('\n')
        sb.append("共 ").append(entries.size).append(" 条会话。点击本目录下的入口可用本应用打开对应会话。\n\n")
        sb.append("| 会话标题 | 时间 | 会话链接 |\n| --- | --- | --- |\n")
        for (e in entries.sortedBy { it.collectedAt ?: "" }) {
            sb.append("| ").append(md(e.title)).append(" | ").append(md(e.collectedAt))
                .append(" | ").append(e.url).append(" |\n")
        }
        AtomicFiles.write(File(File(root, folder), MANIFEST), sb.toString())
    }

    private fun writeSummary(all: List<ArchiveEntry>) {
        val byModel = all.groupBy { it.modelFolder ?: UNIDENTIFIED }
            .map { (model, group) ->
                Triple(
                    model,
                    group.size,
                    (group.minOfOrNull { it.collectedAt ?: "" } ?: "") to
                        (group.maxOfOrNull { it.collectedAt ?: "" } ?: ""),
                )
            }
            .sortedWith(compareByDescending<Triple<String, Int, Pair<String, String>>> { it.second }.thenBy { it.first })
        val sb = StringBuilder()
        sb.append("# 模型归档汇总\n\n")
        sb.append("共 ").append(all.size).append(" 条会话，分布在 ").append(byModel.size).append(" 个模型目录下。\n\n")
        sb.append("| 模型 | 会话数 | 首次 | 末次 |\n| --- | --- | --- | --- |\n")
        for ((model, count, span) in byModel) {
            sb.append("| ").append(md(model)).append(" | ").append(count)
                .append(" | ").append(md(span.first)).append(" | ").append(md(span.second)).append(" |\n")
        }
        AtomicFiles.write(File(root, SUMMARY), sb.toString())
    }

    companion object {
        const val RECORDS = "记录.json"
        const val SUMMARY = "汇总.md"
        const val MANIFEST = "清单.md"
        const val UNIDENTIFIED = "未识别"

        private val INVALID = charArrayOf('/', '\\', ':', '*', '?', '"', '<', '>', '|', '\u0000')

        private fun md(value: String?): String = (value ?: "").replace("|", "\\|")

        fun nowStamp(): String = java.time.LocalDateTime.now()
            .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))

        /** 模型名可能含 `/`（如 zai-org/GLM-5.3-Flash），统一净化成合法目录/文件名。 */
        fun sanitizeSegment(value: String?): String {
            if (value.isNullOrEmpty()) return ""
            var text = value.trim()
            for (bad in INVALID) text = text.replace(bad, '_')
            text = text.trimEnd('.', ' ')
            return text
        }
    }
}
