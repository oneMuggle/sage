package ai.arena.companion

import ai.arena.companion.account.AccountBalanceClient
import ai.arena.companion.register.ArenaTransport
import ai.arena.companion.register.HttpResponse
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class AccountBalanceClientTest {

    private class MockTransport(
        val responder: (String) -> HttpResponse
    ) : ArenaTransport {
        val calls = mutableListOf<String>()
        override suspend fun post(url: String, json: String, referer: String?): HttpResponse =
            throw UnsupportedOperationException()
        override suspend fun get(url: String, referer: String?): HttpResponse {
            calls.add(url)
            return responder(url)
        }
    }

    @Test
    fun `parses standard credits response`() = runTest {
        val body = """{"creditsRemaining": 15000, "totalCredits": 20000}"""
        val transport = MockTransport { HttpResponse(200, body, it) }
        val client = AccountBalanceClient(transport)

        val balance = client.getBalance(retries = 1)
        assertNotNull(balance)
        assertEquals(15000L, balance.creditsRemaining)
        assertEquals(20000L, balance.totalCredits)
    }

    @Test
    fun `parses string formatted credits response`() = runTest {
        val body = """{"creditsRemaining": "14850", "totalCredits": "15000"}"""
        val transport = MockTransport { HttpResponse(200, body, it) }
        val client = AccountBalanceClient(transport)

        val balance = client.getBalance(retries = 1)
        assertNotNull(balance)
        assertEquals(14850L, balance.creditsRemaining)
        assertEquals(15000L, balance.totalCredits)
    }

    @Test
    fun `retries on 429 or server errors and succeeds`() = runTest {
        var attempts = 0
        val transport = MockTransport {
            attempts++
            if (attempts < 3) {
                HttpResponse(429, "Too Many Requests", it)
            } else {
                HttpResponse(200, """{"creditsRemaining": 12000}""", it)
            }
        }
        val client = AccountBalanceClient(transport)
        var sleepCount = 0
        val balance = client.getBalance(retries = 4, delayMs = 10L, sleep = { sleepCount++ })

        assertNotNull(balance)
        assertEquals(12000L, balance.creditsRemaining)
        assertEquals(3, attempts)
        assertEquals(2, sleepCount)
    }

    @Test
    fun `exhausts retries and returns null`() = runTest {
        val transport = MockTransport { HttpResponse(500, "Internal Server Error", it) }
        val client = AccountBalanceClient(transport)
        val balance = client.getBalance(retries = 2, delayMs = 10L)
        assertNull(balance)
    }
}
