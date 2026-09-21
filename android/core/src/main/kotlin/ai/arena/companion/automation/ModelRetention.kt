// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ModelRetention.cs
// spec: docs/mcp-android-implementation-plan.md §3.4
package ai.arena.companion.automation

import java.text.Normalizer

/**
 * Per-run 不可变策略。exclusions 是精确模型名，永不做 family/prefix 匹配。
 * 未知模型默认保留。
 */
class ModelRetentionPolicy(catalog: Iterable<String>?, exclusions: Iterable<String>?) {

    private val known: Set<String> =
        (catalog ?: emptyList()).map(::key).filter { it.isNotEmpty() }.map { it.lowercase() }.toSet()
    private val excluded: Set<String> =
        (exclusions ?: emptyList()).map(::key).filter { it.isNotEmpty() }.map { it.lowercase() }.toSet()

    /** 四个条件缺一不可。 */
    fun excludes(model: String?): Boolean {
        val k = key(model)
        if (k.isEmpty()) return false
        if (k.startsWith(UNIDENTIFIED)) return false
        val lower = k.lowercase()
        return known.contains(lower) && excluded.contains(lower)
    }

    companion object {
        const val UNIDENTIFIED = "未识别"
        const val DEMO_MODEL_PREFIX = "演示模型"

        val KEEP_ALL = ModelRetentionPolicy(emptyList(), emptyList())

        /** Trim + NFC；异常返回空串。 */
        fun key(name: String?): String {
            if (name.isNullOrBlank()) return ""
            return try {
                Normalizer.normalize(name.trim(), Normalizer.Form.NFC)
            } catch (_: Exception) {
                ""
            }
        }
    }
}

data class ModelRetentionGroup(val name: String, val names: List<String>)

/** 对 ModelRetentionCatalog。schemaVersion 必须为 2。 */
class ModelRetentionCatalog(val schemaVersion: Int, models: List<ModelRetentionGroup>) {

    val models: List<ModelRetentionGroup> = models.sortedBy { it.name.lowercase() }

    val names: List<String> get() = models.map { it.name }
    val allNames: List<String> get() = models.flatMap { it.names }

    private fun set(values: Iterable<String>?): Set<String> =
        (values ?: emptyList()).map { ModelRetentionPolicy.key(it).lowercase() }.toSet()

    /** 旧的混合选择向"保留"迁移，绝不向"归档"迁移。 */
    fun collapse(saved: Iterable<String>?): List<String> {
        val ex = set(saved)
        return models.filter { g -> g.names.all { ex.contains(ModelRetentionPolicy.key(it).lowercase()) } }
            .map { it.name }
    }

    fun expand(choices: Iterable<String>?): List<String> {
        val ex = set(choices)
        return models.filter { ex.contains(ModelRetentionPolicy.key(it.name).lowercase()) }.flatMap { it.names }
    }

    fun policy(saved: Iterable<String>?): ModelRetentionPolicy =
        ModelRetentionPolicy(allNames, expand(collapse(saved)))

    fun withObserved(values: Iterable<String>?): ModelRetentionCatalog {
        val known = allNames.map { ModelRetentionPolicy.key(it).lowercase() }.toMutableSet()
        val added = mutableListOf<ModelRetentionGroup>()
        for (raw in values ?: emptyList()) {
            val name = ModelRetentionPolicy.key(raw)
            if (name.isEmpty() || name.length > 200) continue
            if (name.any { it.isISOControl() }) continue
            if (name.startsWith(ModelRetentionPolicy.UNIDENTIFIED)) continue
            if (name.startsWith(ModelRetentionPolicy.DEMO_MODEL_PREFIX)) continue
            if (!known.add(name.lowercase())) continue
            added += ModelRetentionGroup(name, listOf(name))
        }
        return if (added.isEmpty()) this
        else ModelRetentionCatalog(2, models + added)
    }

    companion object {
        /** 校验规则与 C# Load() 一致；无效直接抛。 */
        fun validated(schemaVersion: Int, models: List<ModelRetentionGroup>?): ModelRetentionCatalog {
            if (schemaVersion != 2 || models.isNullOrEmpty()) error("模型目录版本无效")
            val seen = mutableSetOf<String>()
            for (g in models) {
                if (g.names.isEmpty() || g.names.none { it.equals(g.name, ignoreCase = true) })
                    error("模型选择组无效")
                for (n in g.names) {
                    if (ModelRetentionPolicy.key(n) != n || n.isBlank() || n.length > 200 ||
                        n.any { it.isISOControl() } || !seen.add(n.lowercase())
                    ) error("模型名称重复或无效")
                }
            }
            return ModelRetentionCatalog(schemaVersion, models)
        }
    }
}
