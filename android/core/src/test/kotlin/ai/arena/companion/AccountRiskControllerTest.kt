package ai.arena.companion

import ai.arena.companion.account.AccountRiskController
import ai.arena.companion.account.AccountState
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class AccountRiskControllerTest {

    @Test
    fun `initial state is Available`() {
        val controller = AccountRiskController()
        assertEquals(AccountState.Available, controller.getState("acct-1"))
    }

    @Test
    fun `429 steps through ladder and triggers rebinding at level 2`() {
        var now = Instant.parse("2026-09-20T10:00:00Z")
        val controller = AccountRiskController(clock = { now })

        val s0 = controller.noteRateLimited("acct-1")
        assertIs<AccountState.Cooling>(s0)
        assertEquals(0, s0.level)
        assertEquals(now.plusSeconds(15), s0.until)

        now = now.plusSeconds(20)
        assertEquals(AccountState.Available, controller.getState("acct-1"))

        val s1 = controller.noteRateLimited("acct-1")
        assertIs<AccountState.Cooling>(s1)
        assertEquals(1, s1.level)
        assertEquals(now.plusSeconds(30), s1.until)

        now = now.plusSeconds(35)
        assertEquals(AccountState.Available, controller.getState("acct-1"))

        val s2 = controller.noteRateLimited("acct-1")
        assertIs<AccountState.Rebinding>(s2)
        assertTrue(s2.reason.contains("自动触发换 IP"))

        controller.rebindingCompleted("acct-1")
        assertEquals(AccountState.Available, controller.getState("acct-1"))
    }

    @Test
    fun `cloudflare challenge triggers immediate rebinding`() {
        val controller = AccountRiskController()
        val state = controller.noteRateLimited("acct-1", isCloudflare = true, message = "Just a moment...")
        assertIs<AccountState.Rebinding>(state)
        assertTrue(state.cfChallenge)
    }

    @Test
    fun `depleted quota marks DepletedToday and recovers after reset time`() {
        var now = Instant.parse("2026-09-20T10:00:00Z")
        val controller = AccountRiskController(clock = { now })

        val state = controller.noteBalance("acct-1", creditsRemaining = 50L)
        assertIs<AccountState.DepletedToday>(state)
        assertEquals(50L, state.remainingCredits)

        assertEquals(state, controller.getState("acct-1"))

        now = now.plusSeconds(13 * 3600L)
        assertEquals(AccountState.Available, controller.getState("acct-1"))
    }

    @Test
    fun `verification required transitions to NeedVerification and resolves`() {
        val controller = AccountRiskController()
        val state = controller.noteVerificationRequired("acct-1", prompt = "Please solve turnstile")
        assertIs<AccountState.NeedVerification>(state)
        assertEquals("Please solve turnstile", state.prompt)

        controller.verificationResolved("acct-1")
        assertEquals(AccountState.Available, controller.getState("acct-1"))
    }

    @Test
    fun `selectNextAvailable picks first non-blocked account`() {
        val controller = AccountRiskController()
        controller.noteBalance("acct-1", creditsRemaining = 0L)
        controller.noteRateLimited("acct-2", isCloudflare = true)

        val candidates = listOf("acct-1", "acct-2", "acct-3", "acct-4")
        val next = controller.selectNextAvailable(candidates)
        assertEquals("acct-3", next)
    }
}
