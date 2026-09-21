package ai.arena.companion

import ai.arena.companion.automation.ManualCollection
import ai.arena.companion.automation.PageState
import ai.arena.companion.automation.ProbeSnapshot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ManualCollectionTest {

    private fun ready() = PageState(
        url = "https://arena.ai/agent/11111111-2222-3333-4444-555555555555",
        main = true,
        conversation = true,
        response = true,
        generationStamp = "stamp",
        responseSignature = "sig",
    )

    @Test
    fun `stable double read succeeds`() = runTest {
        val probe = ProbeSnapshot(api = true, runId = "r1", name = "gpt-5")
        val result = ManualCollection.read({ ready() }, { probe }, { true }, { })
        assertEquals("gpt-5", result.probe.name)
    }

    @Test
    fun `answer changing between reads is rejected`() = runTest {
        var n = 0
        assertFailsWith<IllegalStateException> {
            ManualCollection.read(
                { ready().also { it.responseSignature = "sig-${n++}" } },
                { ProbeSnapshot(api = true, runId = "r1", name = "gpt-5") },
                { true },
                { },
            )
        }
    }

    @Test
    fun `probe model changing between reads is rejected`() = runTest {
        var n = 0
        assertFailsWith<IllegalStateException> {
            ManualCollection.read(
                { ready() },
                { ProbeSnapshot(api = true, runId = "r${n++}", name = "gpt-5") },
                { true },
                { },
            )
        }
    }

    @Test
    fun `generating state never collects`() = runTest {
        assertFailsWith<IllegalStateException> {
            ManualCollection.read({ ready().also { it.generating = true } }, { null }, { true }, { })
        }
    }

    @Test
    fun `non concrete conversation url never collects`() = runTest {
        assertFailsWith<IllegalStateException> {
            ManualCollection.read({ ready().also { it.url = "https://arena.ai/agent" } }, { null }, { true }, { })
        }
    }
}
