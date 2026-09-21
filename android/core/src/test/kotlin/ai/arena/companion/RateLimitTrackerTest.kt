package ai.arena.companion

import ai.arena.companion.automation.PageState
import ai.arena.companion.automation.RateLimitRecord
import ai.arena.companion.automation.RateLimitStore
import ai.arena.companion.automation.RateLimitTracker
import java.time.Instant
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RateLimitTrackerTest {

    private class MemoryStore(var record: RateLimitRecord? = null) : RateLimitStore {
        override fun load() = record
        override fun save(record: RateLimitRecord) { this.record = record }
    }

    private val now: Instant = Instant.parse("2026-09-20T00:00:00Z")

    @BeforeTest
    fun reset() = RateLimitTracker.resetSharedDeadlines()

    @Test
    fun `only create-chat 429 counts`() {
        assertTrue(RateLimitTracker.matches("https://arena.ai/nextjs-api/stream/create-chat"))
        assertFalse(RateLimitTracker.matches("https://arena.ai/nextjs-api/stream/other"))
        assertFalse(RateLimitTracker.matches("https://other.ai/nextjs-api/stream/create-chat"))
    }

    @Test
    fun `numeric retry-after clamps to at least one second`() {
        assertEquals(now.plusSeconds(1), RateLimitTracker.parse("0", null, now))
        assertEquals(now.plusSeconds(30), RateLimitTracker.parse("30", null, now))
        assertNull(RateLimitTracker.parse("-1", null, now))
        assertNull(RateLimitTracker.parse("99999999999", null, now))
    }

    @Test
    fun `http-date uses server date delta when present`() {
        val target = "Sun, 20 Sep 2026 00:10:00 GMT"
        val server = "Sun, 20 Sep 2026 00:09:00 GMT"
        assertEquals(now.plusSeconds(60), RateLimitTracker.parse(target, server, now))
        // 无 server Date 时用绝对时间
        assertEquals(Instant.parse("2026-09-20T00:10:00Z"), RateLimitTracker.parse(target, null, now))
        // 绝对时间已过期则不早于 now+1s
        assertEquals(now.plusSeconds(1), RateLimitTracker.parse("Sun, 20 Sep 2020 00:00:00 GMT", null, now))
    }

    @Test
    fun `non-429 and non-matching urls do not bump the sequence`() {
        val store = MemoryStore()
        val t = RateLimitTracker("slot-a", store)
        t.observe("https://arena.ai/nextjs-api/stream/create-chat", 200, "30", null, now)
        t.observe("https://arena.ai/other", 429, "30", null, now)
        assertNull(store.record)
    }

    @Test
    fun `deadline is shared across slots of the same scope but id is not`() {
        val a = RateLimitTracker("scope", MemoryStore())
        val b = RateLimitTracker("scope", MemoryStore())
        a.observe("https://arena.ai/nextjs-api/stream/create-chat", 429, "60", null, now)

        val sa = PageState(); a.apply(sa)
        val sb = PageState(); b.apply(sb)
        assertEquals(1, sa.rateLimitId)
        // 另一个槽不继承 response id，只继承 deadline
        assertEquals(0, sb.rateLimitId)
        assertEquals(sa.rateLimitRetryAt, sb.rateLimitRetryAt)
    }
}
