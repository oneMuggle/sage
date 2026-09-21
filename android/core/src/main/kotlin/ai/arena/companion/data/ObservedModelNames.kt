// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.ModelRetention.cs（ObservedModelsPath / ObserveRetentionModels）
// spec: docs/mcp-android-implementation-plan.md §3.4 保留策略
package ai.arena.companion.data

import ai.arena.companion.automation.ModelRetentionCatalog
import ai.arena.companion.automation.ModelRetentionGroup
import java.io.File
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * 每实例「见过的模型名」缓存：`<实例目录>/model-observed-names.json`。
 *
 * 保留策略只对目录里已知的模型生效（`ModelRetentionPolicy.excludes` 四条件之一），
 * 而安卓端没有内置 model-catalog.json，目录 = 本地归档里出现过的模型 ∪ 这份缓存。
 * 没有缓存时，被勾选归档的模型一旦本地归档被清空就会悄悄变回「保留」——所以每轮完成都记一笔。
 * 过滤规则与 `ModelRetentionCatalog.withObserved` 单一来源：空名、超长、控制字符、「未识别…」「演示模型…」一律不记。
 * 读失败视为空（无效缓存绝不扩大归档范围）；写入走原子替换。
 */
class ObservedModelNames(directory: File) {

    private val file = File(directory, FILE_NAME)
    private val json = Json { ignoreUnknownKeys = true }

    fun load(): List<String> {
        if (!file.isFile) return emptyList()
        val raw = try {
            json.decodeFromString(ListSerializer(String.serializer()), file.readText(Charsets.UTF_8))
        } catch (_: Exception) {
            return emptyList()
        }
        return filter(emptyList(), raw)
    }

    /** 记录新观察到的名字；返回是否有新增。 */
    fun record(values: Iterable<String?>): Boolean {
        val before = load()
        val after = filter(before, values.filterNotNull())
        if (after.size == before.size) return false
        AtomicFiles.write(file, json.encodeToString(ListSerializer(String.serializer()), after))
        return true
    }

    fun record(value: String?): Boolean = record(listOf(value))

    companion object {
        const val FILE_NAME = "model-observed-names.json"

        /** 与 withObserved 相同的过滤 + 大小写不敏感去重，输出按名称排序。 */
        fun filter(existing: Iterable<String>, values: Iterable<String>): List<String> {
            val base = ModelRetentionCatalog(2, emptyList()).withObserved(existing)
            return base.withObserved(values).allNames.sortedBy { it.lowercase() }
        }
    }
}
