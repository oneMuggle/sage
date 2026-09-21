// spec: docs/mcp-android-implementation-plan.md §3.6（附件 SHA256 内容寻址）
package ai.arena.companion.data

import java.io.File

/**
 * 附件目录回收。
 *
 * 附件按 `Attachments/<sha256>/<name>` 内容寻址，**同一内容被多处引用时共享同一目录**。
 * 所以删除一条引用不能顺手删目录——那会把另一处仍在用的附件删掉。
 * 正确做法是引用计数：只回收当前**没有任何设置引用**的哈希目录。
 */
object AttachmentGarbage {

    /** 统计每个哈希目录被引用的次数。 */
    fun referenceCounts(settings: Iterable<TaskSettings>): Map<String, Int> {
        val counts = mutableMapOf<String, Int>()
        for (s in settings) for (a in s.attachments) {
            counts[a.sha256] = (counts[a.sha256] ?: 0) + 1
        }
        return counts
    }

    /** 列出无人引用的哈希目录。 */
    fun unreferenced(instanceDir: File, settings: Iterable<TaskSettings>): List<File> {
        val live = referenceCounts(settings).keys
        val root = File(instanceDir, "Attachments")
        if (!root.isDirectory) return emptyList()
        return root.listFiles().orEmpty()
            .filter { it.isDirectory && it.name !in live }
            .sortedBy { it.name }
    }

    /**
     * 回收无人引用的目录，返回删掉的目录数与释放的字节数。
     *
     * `dryRun=true` 时只统计不删——UI 要能先告诉用户"将清理 N 项、释放 X"，
     * 再由用户确认。删除操作必须是用户明确同意的。
     */
    fun collect(instanceDir: File, settings: Iterable<TaskSettings>, dryRun: Boolean = false):
        Pair<Int, Long> {
        var count = 0
        var bytes = 0L
        for (dir in unreferenced(instanceDir, settings)) {
            val size = dir.walkBottomUp().filter { it.isFile }.sumOf { it.length() }
            if (dryRun || dir.deleteRecursively()) { count++; bytes += size }
        }
        return count to bytes
    }
}
