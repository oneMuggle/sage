package ai.arena.companion

import ai.arena.companion.data.AcquireResult
import ai.arena.companion.data.ActiveInstanceGate
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ActiveInstanceGateTest {

    @Test
    fun `first acquire wins and second one queues`() {
        val gate = ActiveInstanceGate()
        val a = gate.acquire("甲") as AcquireResult.Granted
        assertEquals("甲", a.instance)
        val b = gate.acquire("乙") as AcquireResult.Busy
        assertEquals("甲", b.holder)
        assertTrue(b.queued)
        assertEquals(1, b.position)
        assertEquals(listOf("乙"), gate.queue())
    }

    @Test
    fun `re-acquiring by the holder is reentrant and keeps the token`() {
        val gate = ActiveInstanceGate()
        val a = gate.acquire("甲") as AcquireResult.Granted
        val again = gate.acquire("甲") as AcquireResult.Granted
        assertEquals(a.token, again.token)
        assertTrue(gate.queue().isEmpty())
    }

    @Test
    fun `duplicate queue requests do not stack up`() {
        val gate = ActiveInstanceGate()
        gate.acquire("甲")
        gate.acquire("乙"); gate.acquire("乙"); gate.acquire("乙")
        assertEquals(listOf("乙"), gate.queue())
    }

    @Test
    fun `release requires the matching token`() {
        val gate = ActiveInstanceGate()
        val a = gate.acquire("甲") as AcquireResult.Granted
        assertFalse(gate.release(a.token + 999))
        assertEquals("甲", gate.holder()!!.instance)
        assertTrue(gate.release(a.token))
        assertNull(gate.holder())
        assertFalse(gate.release(a.token))       // 二次释放无效
    }

    @Test
    fun `a stale holder cannot release the new holder`() {
        val gate = ActiveInstanceGate()
        val old = gate.acquire("甲") as AcquireResult.Granted
        val new = gate.forceTakeOver("乙")
        assertFalse(gate.release(old.token))     // 迟到的释放必须无效
        assertEquals("乙", gate.holder()!!.instance)
        assertTrue(gate.release(new.token))
    }

    @Test
    fun `promoteNext hands the slot to the queue head in fifo order`() {
        val gate = ActiveInstanceGate()
        val a = gate.acquire("甲") as AcquireResult.Granted
        gate.acquire("乙"); gate.acquire("丙")
        assertNull(gate.promoteNext())           // 还占着，不能提升
        gate.release(a.token)
        assertEquals("乙", gate.promoteNext()!!.instance)
        assertEquals(listOf("丙"), gate.queue())
    }

    @Test
    fun `promoteNext returns null on an empty queue`() {
        val gate = ActiveInstanceGate()
        assertNull(gate.promoteNext())
    }

    @Test
    fun `cancel removes a waiter`() {
        val gate = ActiveInstanceGate()
        val a = gate.acquire("甲") as AcquireResult.Granted
        gate.acquire("乙")
        assertTrue(gate.cancel("乙"))
        assertFalse(gate.cancel("乙"))
        gate.release(a.token)
        assertNull(gate.promoteNext())
    }

    @Test
    fun `held duration uses the injected clock and never auto preempts`() {
        var now = 1_000L
        val gate = ActiveInstanceGate { now }
        gate.acquire("甲")
        now = 61_000L
        assertEquals(60_000L, gate.heldForMillis())
        // 超时不会自动让位：仍然是"甲"持有，"乙"仍然只能排队
        assertTrue(gate.acquire("乙") is AcquireResult.Busy)
        assertEquals("甲", gate.holder()!!.instance)
    }

    @Test
    fun `concurrent acquires grant exactly one holder`() {
        val gate = ActiveInstanceGate()
        val start = CountDownLatch(1)
        val granted = AtomicInteger()
        val threads = (1..16).map { i ->
            thread {
                start.await()
                if (gate.acquire("实例$i") is AcquireResult.Granted) granted.incrementAndGet()
            }
        }
        start.countDown()
        threads.forEach { it.join() }
        assertEquals(1, granted.get())
        assertEquals(15, gate.queue().size)
    }
}
