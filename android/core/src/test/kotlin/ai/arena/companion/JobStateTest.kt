package ai.arena.companion

import ai.arena.companion.data.JobState
import ai.arena.companion.data.JobStateStore
import ai.arena.companion.data.RecoveryDecision
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class JobStateTest {

    private fun tempDir(): File = Files.createTempDirectory("job").toFile()

    private fun state(phase: String, clean: Boolean = false) = JobState(
        instance = "inst-1",
        prompt = "1+1=",
        limit = 10,
        rounds = 3,
        attempt = 1,
        phase = phase,
        savedAtUtc = "2026-09-20T00:00:00Z",
        cleanShutdown = clean,
    )

    @Test
    fun `no state means fresh start`() {
        assertTrue(JobStateStore(tempDir()).decide() is RecoveryDecision.Fresh)
    }

    @Test
    fun `clean shutdown needs no recovery prompt`() {
        val store = JobStateStore(tempDir())
        store.save(state("observe", clean = true))
        assertTrue(store.decide() is RecoveryDecision.CleanExit)
    }

    @Test
    fun `killed mid round recovers as paused and never auto replays`() {
        val store = JobStateStore(tempDir())
        store.save(state("observe"))
        val d = store.decide() as RecoveryDecision.Interrupted
        assertTrue(d.canContinue)
        assertEquals(3, d.state.rounds)
        assertTrue(d.reason.contains("不会自动重发"))
    }

    @Test
    fun `unknown phase is not resumable`() {
        val store = JobStateStore(tempDir())
        store.save(state("someFuturePhase"))
        val d = store.decide() as RecoveryDecision.Interrupted
        assertFalse(d.canContinue)
        assertTrue(d.reason.contains("重新开始"))
    }

    @Test
    fun `corrupted state file never guesses`() {
        val dir = tempDir()
        File(dir, "job-state.json").writeText("{not json")
        val d = JobStateStore(dir).decide()
        assertTrue(d is RecoveryDecision.Unusable)
    }

    @Test
    fun `unknown schema version is rejected`() {
        val dir = tempDir()
        File(dir, "job-state.json").writeText("""{"schemaVersion":99,"instance":"i","prompt":"p","limit":0,"rounds":0,"attempt":0,"phase":"observe","savedAtUtc":"x"}""")
        val d = JobStateStore(dir).decide() as RecoveryDecision.Unusable
        assertTrue(d.reason.contains("99"))
    }

    @Test
    fun `rate limit deadline survives a restart`() {
        val store = JobStateStore(tempDir())
        store.save(state("cooldown").copy(rateLimitRetries = 2, retryUntilUtc = "2026-09-20T00:05:00Z"))
        val loaded = store.load()!!
        assertEquals(2, loaded.rateLimitRetries)
        assertEquals("2026-09-20T00:05:00Z", loaded.retryUntilUtc)
    }

    @Test
    fun `clear removes the state file`() {
        val dir = tempDir()
        val store = JobStateStore(dir)
        store.save(state("observe"))
        store.clear()
        assertTrue(store.decide() is RecoveryDecision.Fresh)
    }
}
