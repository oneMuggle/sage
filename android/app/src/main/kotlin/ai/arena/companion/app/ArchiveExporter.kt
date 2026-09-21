// spec: docs/mcp-android-implementation-plan.md §4「PortablePaths 便携树 → App 私有目录为根；导出走 SAF」
package ai.arena.companion.app

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File

/** 导出结果。`failures` 非空时**不要声称导出成功**。 */
data class ExportReport(
    val files: Int,
    val bytes: Long,
    val failures: List<String>,
) {
    val ok: Boolean get() = failures.isEmpty()

    fun describe(): String = buildString {
        append("已导出 ").append(files).append(" 个文件（").append(bytes / 1024).append(" KB）")
        if (failures.isNotEmpty()) {
            append("\n以下 ").append(failures.size).append(" 项失败：\n")
            append(failures.take(10).joinToString("\n"))
            if (failures.size > 10) append("\n…")
        }
    }
}

/**
 * 把归档目录树导出到用户通过 SAF 选定的位置。
 *
 * 安卓没有"随便往某个路径写文件"这回事，所以桌面端的「导出到文件夹」对应
 * `ACTION_OPEN_DOCUMENT_TREE` + `DocumentFile`。
 *
 * **逐个文件记录失败而不是中途抛出**：导出一半就崩，用户拿到的是一份看起来完整
 * 实则残缺的目录。宁可全部尝试完，再如实报告哪些没成功。
 */
object ArchiveExporter {

    fun export(context: Context, source: File, treeUri: Uri): ExportReport {
        val target = DocumentFile.fromTreeUri(context, treeUri)
            ?: return ExportReport(0, 0, listOf("无法访问选定的目录"))
        if (!target.canWrite()) return ExportReport(0, 0, listOf("对选定的目录没有写入权限"))
        if (!source.isDirectory) return ExportReport(0, 0, listOf("归档目录不存在：${source.name}"))

        val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.ROOT)
            .format(java.util.Date())
        // 建一个带时间戳的子目录，绝不覆盖用户选定目录里已有的同名内容。
        val root = target.createDirectory("arena-归档-$stamp")
            ?: return ExportReport(0, 0, listOf("无法在选定目录下创建导出文件夹"))

        val failures = mutableListOf<String>()
        var files = 0
        var bytes = 0L
        copyInto(context, source, root, source, failures) { size -> files++; bytes += size }
        return ExportReport(files, bytes, failures)
    }

    private fun copyInto(
        context: Context,
        dir: File,
        target: DocumentFile,
        base: File,
        failures: MutableList<String>,
        onFile: (Long) -> Unit,
    ) {
        for (child in dir.listFiles().orEmpty().sortedBy { it.name }) {
            val label = child.relativeToOrSelf(base).path
            if (child.isDirectory) {
                val sub = target.createDirectory(child.name)
                if (sub == null) { failures += "$label（无法创建目录）"; continue }
                copyInto(context, child, sub, base, failures, onFile)
                continue
            }
            val mime = if (child.extension.equals("json", true)) "application/json" else "text/plain"
            val doc = target.createFile(mime, child.name)
            if (doc == null) { failures += "$label（无法创建文件）"; continue }
            try {
                val out = context.contentResolver.openOutputStream(doc.uri)
                if (out == null) {
                    failures += "$label（无法打开输出流）"
                } else {
                    out.use { sink -> child.inputStream().use { it.copyTo(sink) } }
                    onFile(child.length())
                }
            } catch (e: Exception) {
                failures += "$label（${e.message ?: "写入失败"}）"
            }
        }
    }
}
