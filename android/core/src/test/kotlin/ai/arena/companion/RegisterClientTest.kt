package ai.arena.companion

import ai.arena.companion.register.ArenaProtocolException
import ai.arena.companion.register.ArenaRateLimitedException
import ai.arena.companion.register.ArenaRegisterClient
import ai.arena.companion.register.ArenaTransport
import ai.arena.companion.register.HttpResponse
import ai.arena.companion.register.MailProvider
import ai.arena.companion.register.Mailbox
import ai.arena.companion.register.PasswordPolicy
import ai.arena.companion.register.registerOne
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RegisterClientTest {

    private class FakeTransport(
        val handler: (String, String?) -> HttpResponse,
    ) : ArenaTransport {
        val calls = mutableListOf<String>()
        override suspend fun post(url: String, json: String, referer: String?): HttpResponse {
            calls += "POST $url"
            return handler(url, json)
        }
        override suspend fun get(url: String, referer: String?): HttpResponse {
            calls += "GET $url"
            return handler(url, null)
        }
    }

    private class FakeMail(val email: String = "a@b.c", val link: String? = "https://arena.ai/nextjs-api/callback?x=1") : MailProvider {
        override suspend fun createMailbox() = Mailbox(email)
        override suspend fun waitForLink(mailbox: Mailbox, pattern: Regex, timeoutSeconds: Int) = link
    }

    private fun ok(body: String = "{}", finalUrl: String = "") = HttpResponse(200, body, finalUrl)

    private fun happyPath() = FakeTransport { url, _ ->
        when {
            url.endsWith("/sign-up") -> ok("""{"access_token":"t"}""")
            url.endsWith("/magic-link") -> ok()
            url.contains("/callback") -> ok("", "https://arena.ai/set?token=TK&next=1")
            url.endsWith("/set-password") -> ok()
            url.endsWith("/sign-in/email") -> ok()
            url.endsWith("/api/me") -> ok("""{"user":{"id":"u-1"}}""")
            url.endsWith("/billing/balance") -> ok("""{"creditsRemaining":42}""")
            else -> HttpResponse(404, "", "")
        }
    }

    @Test
    fun `generated passwords always satisfy the arena rule`() {
        repeat(50) { assertTrue(PasswordPolicy.valid(PasswordPolicy.generate())) }
        assertFalse(PasswordPolicy.valid("short1A"))
        assertFalse(PasswordPolicy.valid("alllowercase1!"))
        assertFalse(PasswordPolicy.valid("NoDigits!!"))
        assertFalse(PasswordPolicy.valid(null))
    }

    @Test
    fun `signup sends empty recaptcha token`() = runTest {
        var captured = ""
        val t = object : ArenaTransport {
            override suspend fun post(url: String, json: String, referer: String?): HttpResponse {
                captured = json; return ok("""{"access_token":"x"}""")
            }
            override suspend fun get(url: String, referer: String?) = ok()
        }
        assertEquals("x", ArenaRegisterClient(transport = t).createUser())
        assertTrue(captured.contains(""""recaptchaToken":""""))
    }

    @Test
    fun `429 surfaces as rate limited with cloudflare detection`() = runTest {
        val cf = ArenaRegisterClient(transport = object : ArenaTransport {
            override suspend fun post(url: String, json: String, referer: String?) =
                HttpResponse(429, "<html>Just a moment...</html>", "")
            override suspend fun get(url: String, referer: String?) = ok()
        })
        val e = assertFailsWith<ArenaRateLimitedException> { cf.createUser() }
        assertTrue(e.cf)

        val plain = ArenaRegisterClient(transport = object : ArenaTransport {
            override suspend fun post(url: String, json: String, referer: String?) =
                HttpResponse(429, """{"error":"slow down"}""", "")
            override suspend fun get(url: String, referer: String?) = ok()
        })
        assertFalse(assertFailsWith<ArenaRateLimitedException> { plain.createUser() }.cf)
    }

    @Test
    fun `magic link without token is rejected`() = runTest {
        val c = ArenaRegisterClient(transport = object : ArenaTransport {
            override suspend fun post(url: String, json: String, referer: String?) = ok()
            override suspend fun get(url: String, referer: String?) = ok("", "https://arena.ai/oops")
        })
        assertFailsWith<ArenaProtocolException> { c.confirmLink("https://arena.ai/nextjs-api/callback?x") }
    }

    @Test
    fun `happy path registers one account`() = runTest {
        val t = happyPath()
        val r = registerOne(FakeMail(), t, sleep = { })
        assertTrue(r.ok, r.error)
        assertEquals("a@b.c", r.email)
        assertEquals("u-1", r.userId)
        assertEquals("42", r.credits)
        assertTrue(PasswordPolicy.valid(r.password))
    }

    @Test
    fun `password is redacted in event payloads`() = runTest {
        val r = registerOne(FakeMail(), happyPath(), sleep = { })
        assertEquals("***", r.redacted()["password"])
    }

    @Test
    fun `set-password is retried exactly once with the same token`() = runTest {
        var setPasswordCalls = 0
        var signInCalls = 0
        val t = FakeTransport { url, _ ->
            when {
                url.endsWith("/sign-up") -> ok("""{"access_token":"t"}""")
                url.endsWith("/magic-link") -> ok()
                url.contains("/callback") -> ok("", "https://arena.ai/set?token=TK")
                url.endsWith("/set-password") -> { setPasswordCalls++; ok() }
                url.endsWith("/sign-in/email") -> { signInCalls++; if (signInCalls == 1) HttpResponse(401, "", "") else ok() }
                url.endsWith("/api/me") -> ok("""{"user":{"id":"u"}}""")
                url.endsWith("/billing/balance") -> ok("""{"creditsRemaining":1}""")
                else -> HttpResponse(404, "", "")
            }
        }
        val r = registerOne(FakeMail(), t, sleep = { })
        assertTrue(r.ok)
        assertEquals(2, setPasswordCalls)   // 恰好一次重试，不是循环
        assertEquals(2, signInCalls)
    }

    @Test
    fun `persistent signin failure gives up without a retry storm`() = runTest {
        var setPasswordCalls = 0
        val t = FakeTransport { url, _ ->
            when {
                url.endsWith("/sign-up") -> ok("""{"access_token":"t"}""")
                url.endsWith("/magic-link") -> ok()
                url.contains("/callback") -> ok("", "https://arena.ai/set?token=TK")
                url.endsWith("/set-password") -> { setPasswordCalls++; ok() }
                url.endsWith("/sign-in/email") -> HttpResponse(401, "", "")
                else -> HttpResponse(404, "", "")
            }
        }
        val r = registerOne(FakeMail(), t, sleep = { })
        assertFalse(r.ok)
        assertEquals(2, setPasswordCalls)
        assertTrue(r.error.contains("无法登录"))
    }

    @Test
    fun `mail timeout never raises`() = runTest {
        val r = registerOne(FakeMail(link = null), happyPath(), sleep = { })
        assertFalse(r.ok)
        assertTrue(r.error.contains("等待验证邮件超时"))
    }

    @Test
    fun `cancellation stops before sending any magic link`() = runTest {
        val t = happyPath()
        val r = registerOne(FakeMail(), t, cancelled = { true }, sleep = { })
        assertFalse(r.ok)
        assertEquals("cancelled", r.error)
        assertTrue(t.calls.none { it.contains("magic-link") })
    }

    @Test
    fun `balance lookup retries a bounded number of times`() = runTest {
        var calls = 0
        val c = ArenaRegisterClient(transport = object : ArenaTransport {
            override suspend fun post(url: String, json: String, referer: String?) = ok()
            override suspend fun get(url: String, referer: String?): HttpResponse {
                calls++; return HttpResponse(429, "", "")
            }
        })
        assertEquals(null, c.getBalance(retries = 4, sleep = { }))
        assertEquals(4, calls)
    }
}
