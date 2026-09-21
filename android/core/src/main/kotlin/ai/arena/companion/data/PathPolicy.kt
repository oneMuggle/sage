// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/PortablePaths.cs
// spec: docs/mcp-android-implementation-plan.md §4「PortablePaths 便携树 → App 私有目录为根」
package ai.arena.companion.data

import java.io.File

/**
 * 便携路径策略：树内存相对路径，树外存绝对路径。
 * Android 侧 base 是 App 私有目录；导出走 SAF，不在本层处理。
 */
class PathPolicy(base: File) {

    val base: File = base.absoluteFile.normalize()

    /** 相对路径按 base 解析；绝对路径原样规范化。 */
    fun resolve(path: String?): String? {
        if (path.isNullOrBlank()) return path
        val f = File(path)
        return if (f.isAbsolute) f.absoluteFile.normalize().path
        else File(base, path).absoluteFile.normalize().path
    }

    /** 树内 → 相对；树外 → 绝对；等于根 → "."。 */
    fun store(path: String?): String? {
        if (path.isNullOrBlank()) return path
        val full = File(resolve(path)!!)
        if (full.path.equals(base.path, ignoreCase = false)) return "."
        val prefix = base.path + File.separator
        return if (full.path.startsWith(prefix)) full.path.substring(prefix.length) else full.path
    }

    /** 目标是否落在 base 之内（防目录穿越）。 */
    fun contains(path: String?): Boolean {
        if (path.isNullOrBlank()) return false
        val full = File(resolve(path)!!)
        return full.path.startsWith(base.path + File.separator)
    }
}

/** 原子写入：tmp + rename。对 C# 的 tmp + File.Replace。 */
object AtomicFiles {
    fun write(target: File, content: String) {
        target.parentFile?.mkdirs()
        val tmp = File(target.parentFile, target.name + ".tmp")
        tmp.writeText(content, Charsets.UTF_8)
        if (!tmp.renameTo(target)) {
            // 某些文件系统上目标存在时 rename 失败；删除后重试，仍失败则抛出。
            if (target.exists() && target.delete() && tmp.renameTo(target)) return
            tmp.delete()
            throw java.io.IOException("原子替换失败：${target.path}")
        }
    }
}
