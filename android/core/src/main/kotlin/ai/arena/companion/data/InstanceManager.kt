// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/InstanceManager.cs
// spec: docs/mcp-android-implementation-plan.md §3.7 / §4「Mutex → 单进程注册表」
package ai.arena.companion.data

import java.io.File

/**
 * 实例名校验 + 重命名（移动目录 + 重写全部引用，任一步失败全部回滚）。
 *
 * 与桌面端的唯一结构性差异：判断"实例正在运行"不用跨进程 Mutex。
 * 安卓是单进程，进程内注册表即可（方案 §4）。注册表由外部注入，核心层不假设其实现。
 */
class InstanceManager(
    root: File,
    /** 返回该实例目录当前是否正在运行。 */
    private val isRunning: (File) -> Boolean = { false },
) {

    val root: File = root.absoluteFile.normalize().also { it.mkdirs() }

    fun directoryFor(name: String): File = File(root, name)

    fun list(): List<String> =
        root.listFiles()?.filter { it.isDirectory && !it.name.startsWith(".") }?.map { it.name }?.sorted()
            ?: emptyList()

    fun create(name: String): File {
        validateName(name)
        val dir = directoryFor(name)
        if (dir.exists()) throw IllegalStateException("已经存在同名实例，请换一个名称")
        if (!dir.mkdirs()) throw java.io.IOException("无法创建实例目录：${dir.path}")
        return dir
    }

    /**
     * 重命名。顺序严格照抄参考：
     * 校验名称 → 确认自身未运行 → 确认没有其它运行中实例引用该路径 → 移动目录 → 重写引用。
     * 重写引用失败则把目录移回原位并抛出。
     */
    fun rename(currentName: String, newName: String): String {
        validateName(newName)
        val source = directoryFor(currentName)
        val target = directoryFor(newName)
        if (!source.isDirectory) throw java.io.FileNotFoundException("选中的实例已经不存在，请刷新后重试")
        if (source.path == target.path) throw IllegalStateException("新名称与当前名称相同")
        ensureStopped(source)
        ensureReferenceOwnersStopped(source)
        if (!source.path.equals(target.path, ignoreCase = true) && target.exists())
            throw java.io.IOException("已经存在同名实例，请换一个名称")

        moveDirectory(source, target)
        try {
            rewriteStoredPaths(target, source.path, target.path)
            return newName
        } catch (e: Exception) {
            try { moveDirectory(target, source) } catch (_: Exception) { }
            throw e
        }
    }

    /** 删除实例。安卓无系统回收站，`recycle` 时移入 App 内 `.trash/` 暂存目录（方案 §4）。 */
    fun delete(name: String, recycle: Boolean = true) {
        val dir = directoryFor(name)
        if (!dir.isDirectory) throw java.io.FileNotFoundException("选中的实例已经不存在，请刷新后重试")
        ensureStopped(dir)
        if (recycle) {
            val trash = File(root, ".trash").also { it.mkdirs() }
            val stamp = System.currentTimeMillis()
            if (!dir.renameTo(File(trash, "$name-$stamp")))
                throw java.io.IOException("无法把实例移入回收目录")
        } else {
            if (!dir.deleteRecursively()) throw java.io.IOException("删除实例目录失败")
        }
    }

    // ---- 内部 -------------------------------------------------------------

    private fun ensureStopped(dir: File) {
        if (isRunning(dir)) throw IllegalStateException("这个实例正在运行，请先关闭该实例后再操作")
    }

    /** 其它运行中实例的归档若引用了该路径，禁止重命名。 */
    private fun ensureReferenceOwnersStopped(source: File) {
        val absolute = jsonToken(source.path)
        val relative = jsonToken(source.name)
        for (dir in root.listFiles()?.filter { it.isDirectory } ?: emptyList()) {
            if (dir.path.equals(source.path, ignoreCase = true)) continue
            if (!isRunning(dir)) continue
            for (file in referenceFiles(dir)) {
                val content = try { file.readText(Charsets.UTF_8) } catch (_: Exception) { continue }
                if (content.contains(absolute, ignoreCase = true) ||
                    content.contains(relative, ignoreCase = true)
                ) throw IllegalStateException("实例「${dir.name}」正在使用引用该账号的归档，请先关闭它后再重命名")
            }
        }
    }

    private fun referenceFiles(instanceDir: File): List<File> {
        val files = mutableListOf<File>()
        File(instanceDir, "task-settings.json").takeIf { it.isFile }?.let { files += it }
        val destination = File(instanceDir, "archive-destination.txt")
            .takeIf { it.isFile }?.readText()?.trim()?.takeUnless { it.isBlank() } ?: DEFAULT_ARCHIVE
        val archiveRoot = File(destination).let { if (it.isAbsolute) it else File(instanceDir, destination) }
        File(archiveRoot, ArchiveStore.RECORDS).takeIf { it.isFile }?.let { files += it }
        return files
    }

    /** 仅大小写变更走中间临时目录两步移动。 */
    private fun moveDirectory(source: File, target: File) {
        if (source.path.equals(target.path, ignoreCase = true) && source.path != target.path) {
            val middle = File(source.parentFile, ".__arena_rename_" + java.util.UUID.randomUUID().toString().replace("-", ""))
            if (!source.renameTo(middle)) throw java.io.IOException("重命名实例目录失败")
            if (!middle.renameTo(target)) {
                if (middle.exists() && !source.exists()) middle.renameTo(source)
                throw java.io.IOException("重命名实例目录失败")
            }
            return
        }
        if (!source.renameTo(target)) throw java.io.IOException("重命名实例目录失败")
    }

    /**
     * 重写所有引用旧路径的 JSON 文件。任一步失败，已改动的文件全部还原。
     */
    private fun rewriteStoredPaths(instanceDir: File, oldPath: String, newPath: String) {
        val targets = mutableListOf<File>()
        File(instanceDir, "task-settings.json").takeIf { it.isFile }?.let { targets += it }
        for (dir in root.listFiles()?.filter { it.isDirectory } ?: emptyList()) {
            for (file in referenceFiles(dir)) if (targets.none { it.path == file.path }) targets += file
        }

        val oldValue = jsonToken(oldPath)
        val newValue = jsonToken(newPath)
        val oldRelative = jsonToken(File(oldPath).name)
        val newRelative = jsonToken(File(newPath).name)
        val backup = LinkedHashMap<File, String>()
        try {
            for (file in targets) {
                val original = file.readText(Charsets.UTF_8)
                var updated = original
                // 只替换"路径 + 分隔符/引号"的形态，避免误伤同名前缀。
                for ((from, to) in listOf(oldValue to newValue, oldRelative to newRelative)) {
                    updated = updated.replace("$from\"", "$to\"", ignoreCase = true)
                    updated = updated.replace("$from\\\\", "$to\\\\", ignoreCase = true)
                    updated = updated.replace("$from/", "$to/", ignoreCase = true)
                }
                if (updated != original) {
                    backup[file] = original
                    AtomicFiles.write(file, updated)
                }
            }
        } catch (e: Exception) {
            for ((file, original) in backup) {
                try { file.writeText(original, Charsets.UTF_8) } catch (_: Exception) { }
            }
            throw e
        }
    }

    companion object {
        const val DEFAULT_ARCHIVE = "模型归档"

        private val NAME = Regex("^[\\p{L}\\p{N}_ -]{1,40}$")

        /** `^[\p{L}\p{N}_ -]{1,40}$` 且不含首尾空格。 */
        fun validateName(name: String?) {
            if (name.isNullOrEmpty()) throw IllegalArgumentException("实例名称不能为空")
            if (name != name.trim()) throw IllegalArgumentException("实例名称不能以空格开头或结尾")
            if (!NAME.matches(name))
                throw IllegalArgumentException("实例名称只能包含字母、数字、下划线、空格和连字符，且不超过 40 个字符")
        }

        /** JSON 字符串字面量内的转义形态（不含外层引号）。 */
        fun jsonToken(value: String): String =
            value.replace("\\", "\\\\").replace("\"", "\\\"")
    }
}
