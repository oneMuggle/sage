package ai.arena.companion

import ai.arena.companion.automation.ModelRetentionCatalog
import ai.arena.companion.automation.ModelRetentionGroup
import ai.arena.companion.automation.ModelRetentionPolicy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ModelRetentionTest {

    private val policy = ModelRetentionPolicy(listOf("gpt-5", "claude-4"), listOf("gpt-5"))

    @Test
    fun `exact name only never prefix or family`() {
        assertTrue(policy.excludes(" gpt-5 "))
        assertFalse(policy.excludes("gpt-5-mini"))
        assertFalse(policy.excludes("claude-4"))
    }

    @Test
    fun `unknown models are kept by default`() {
        assertFalse(ModelRetentionPolicy(emptyList(), listOf("gpt-5")).excludes("gpt-5"))
    }

    @Test
    fun `unidentified is never excluded`() {
        val p = ModelRetentionPolicy(listOf("未识别（探针未加载）"), listOf("未识别（探针未加载）"))
        assertFalse(p.excludes("未识别（探针未加载）"))
    }

    @Test
    fun `blank key yields no exclusion`() {
        assertFalse(policy.excludes(null))
        assertFalse(policy.excludes("   "))
        assertEquals("", ModelRetentionPolicy.key(" "))
    }

    @Test
    fun `legacy mixed selection collapses towards retention`() {
        val catalog = ModelRetentionCatalog.validated(
            2,
            listOf(
                ModelRetentionGroup("gpt-5", listOf("gpt-5", "gpt-5-high")),
                ModelRetentionGroup("claude-4", listOf("claude-4")),
            )
        )
        // 只勾了组内一个成员 → 不折叠成整组排除（向保留迁移）
        assertEquals(emptyList(), catalog.collapse(listOf("gpt-5")))
        assertEquals(listOf("gpt-5"), catalog.collapse(listOf("gpt-5", "gpt-5-high")))
        val p = catalog.policy(listOf("gpt-5", "gpt-5-high"))
        assertTrue(p.excludes("gpt-5-high"))
        assertFalse(p.excludes("claude-4"))
    }

    @Test
    fun `observed models never add unidentified or demo entries`() {
        val catalog = ModelRetentionCatalog.validated(2, listOf(ModelRetentionGroup("a", listOf("a"))))
        val grown = catalog.withObserved(listOf("未识别（x）", "演示模型（模拟）", "b", "b"))
        assertEquals(listOf("a", "b"), grown.names)
    }
}
