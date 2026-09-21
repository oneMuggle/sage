// ref: backend/services/arena_protocol.py (ArenaRegisterClient / register_one)
// spec: docs/mcp-android-implementation-plan.md §5 register/ 、§8「只保留单账号注册」
//
// 方案 §1 决策：注册能力从 sage 已收敛的 backend/services/arena_protocol.py 取行为，
// **不从 ArenCard 原始代码取**。方案 §8 明确：批量注册、每账号换 IP、验证码绕过均不实现。
package ai.arena.companion.register

import java.security.SecureRandom

/** 协议层失败（状态码异常、字段缺失、超时）。 */
open class ArenaProtocolException(message: String) : Exception(message)

/** HTTP 429。`cf` 标记 Cloudflare 挑战——此时等待无用，出口 IP 已被标记。 */
class ArenaRateLimitedException(message: String, val cf: Boolean = false) :
    ArenaProtocolException(message)

/** 一次 HTTP 往返的结果。由 Android 侧用 OkHttp 或 WebView 页面上下文 fetch 实现。 */
data class HttpResponse(val status: Int, val body: String, val finalUrl: String)

/**
 * HTTP 传输抽象。
 *
 * 方案 §9 第 5 项：OkHttp 直连 arena.ai 可能被 Cloudflare 403
 * （`arena_http.py` D3 记录了桌面端 curl_cffi 被 403、httpx 反而通过的反直觉结果）。
 * 若真机实测 403，改用 WebView 页面上下文 fetch 的实现替换本接口即可，协议逻辑不动。
 */
interface ArenaTransport {
    suspend fun post(url: String, json: String, referer: String? = null): HttpResponse
    suspend fun get(url: String, referer: String? = null): HttpResponse
}

/** 临时邮箱 provider 接口。邮件流量**绝不走代理**（provider 自己拥有出口）。 */
interface MailProvider {
    suspend fun createMailbox(): Mailbox
    /** 轮询收件箱直到出现匹配 [pattern] 的链接；超时返回 null。 */
    suspend fun waitForLink(mailbox: Mailbox, pattern: Regex, timeoutSeconds: Int): String?
}

data class Mailbox(val email: String, val token: String? = null)

data class RegisterResult(
    val email: String = "",
    val password: String = "",
    val userId: String = "",
    val credits: String = "",
    val ok: Boolean = false,
    val error: String = "",
) {
    /** 事件负载用。密码永不出现在日志或 job 事件里。 */
    fun redacted(): Map<String, Any> = mapOf(
        "email" to email,
        "password" to if (password.isNotEmpty()) "***" else "",
        "userId" to userId,
        "credits" to credits,
        "ok" to ok,
        "error" to error,
    )
}

object PasswordPolicy {
    private const val UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    private const val LOWER = "abcdefghijklmnopqrstuvwxyz"
    private const val DIGITS = "0123456789"
    private const val SYMBOLS = "!@#$%^&*"

    /** arena 规则：≥8 位，含大写 + 小写 + 数字 + 特殊字符。 */
    fun valid(p: String?): Boolean {
        if (p == null || p.length < 8) return false
        return p.any { it.isUpperCase() } && p.any { it.isLowerCase() } &&
            p.any { it.isDigit() } && p.any { !it.isLetterOrDigit() }
    }

    fun generate(length: Int = 14): String {
        val pool = UPPER + LOWER + DIGITS + SYMBOLS
        val rng = SecureRandom()
        repeat(50) {
            val chars = mutableListOf(
                UPPER[rng.nextInt(UPPER.length)],
                LOWER[rng.nextInt(LOWER.length)],
                DIGITS[rng.nextInt(DIGITS.length)],
                SYMBOLS[rng.nextInt(SYMBOLS.length)],
            )
            repeat(maxOf(4, length - 4)) { chars += pool[rng.nextInt(pool.length)] }
            chars.shuffle(java.util.Random(rng.nextLong()))
            val out = chars.joinToString("")
            if (valid(out)) return out
        }
        return "Arena!" + (1..8).map { (LOWER + DIGITS)[rng.nextInt(36)] }.joinToString("")
    }
}

/** 一个实例一个客户端（Cookie 隔离）。 */
class ArenaRegisterClient(
    var email: String = "",
    var password: String = "",
    private val transport: ArenaTransport,
    private val log: (String) -> Unit = {},
) {

    private fun check(response: HttpResponse, what: String) {
        if (response.status == 429)
            throw ArenaRateLimitedException("$what HTTP 429", isCloudflareChallenge(response.body))
        if (response.status != 200)
            throw ArenaProtocolException("$what HTTP ${response.status}: ${response.body.take(150)}")
    }

    /** 步骤 2：sign-up。`recaptchaToken` 服务端不校验（参考实测，方案 §2）。 */
    suspend fun createUser(): String {
        val body = """{"recaptchaToken":"","provisionalUserId":"${java.util.UUID.randomUUID()}"}"""
        val response = transport.post("$ARENA/nextjs-api/sign-up", body)
        check(response, "sign-up")
        return jsonString(response.body, "access_token") ?: ""
    }

    /** 步骤 3：请求验证邮件。 */
    suspend fun sendMagicLink(email: String, fullName: String = "Arena User") {
        val body = buildString {
            append("""{"email":"""); append(jsonQuote(email))
            append(""","fullName":"""); append(jsonQuote(fullName.ifBlank { "Arena User" }))
            append(""","shouldLinkHistory":false,"marketingConsent":false,"registeredCountryCode":"US"}""")
        }
        check(transport.post("$ARENA/nextjs-api/sign-up/magic-link", body), "magic-link")
    }

    /** 步骤 4b：跟随 magic link，取出 set-password token。 */
    suspend fun confirmLink(link: String): String {
        val response = transport.get(link)
        val match = TOKEN_RE.find(response.finalUrl)
            ?: throw ArenaProtocolException("verification link returned no set-password token")
        return match.groupValues[1]
    }

    /** 步骤 5。 */
    suspend fun setPassword(token: String, password: String) {
        val body = """{"password":${jsonQuote(password)},"token":${jsonQuote(token)}}"""
        check(transport.post("$ARENA/nextjs-api/auth/set-password", body), "set-password")
    }

    /** 步骤 6a：邮箱密码登录。 */
    suspend fun signIn(): Boolean {
        val body = """{"email":${jsonQuote(email)},"password":${jsonQuote(password)}}"""
        return transport.post("$ARENA/nextjs-api/sign-in/email", body, referer = "$ARENA/").status == 200
    }

    suspend fun getMe(): String? {
        val response = transport.get("$ARENA/api/me", referer = "$ARENA/")
        if (response.status != 200) return null
        return jsonString(response.body, "id")
    }

    /**
     * 查额度。短时限流会重试；**退避是固定间隔且次数有限，不做重试风暴**。
     */
    suspend fun getBalance(
        retries: Int = 4,
        delayMillis: Long = 3000,
        sleep: suspend (Long) -> Unit,
    ): String? {
        var last = ""
        for (attempt in 0 until maxOf(1, retries)) {
            try {
                val response = transport.get("$ARENA/api/billing/balance", referer = "$ARENA/")
                if (response.status == 200) return jsonString(response.body, "creditsRemaining")
                last = "HTTP ${response.status}"
            } catch (e: Exception) {
                last = e.message ?: e.toString()
            }
            if (attempt < retries - 1) sleep(delayMillis)
        }
        log("[!] 查额度失败($last)")
        return null
    }

    companion object {
        const val ARENA = "https://arena.ai"
        val VERIFY_LINK_RE = Regex("""https://arena\.ai/nextjs-api/callback\S+""")
        private val TOKEN_RE = Regex("""token=([^&]+)""")
        private val CF_MARKERS = listOf("just a moment", "cf-chl", "attention required")

        fun isCloudflareChallenge(text: String?): Boolean {
            val body = (text ?: "").take(800).lowercase()
            if (body.isEmpty()) return false
            if (CF_MARKERS.any { body.contains(it) }) return true
            return body.contains("cloudflare") && body.contains("<html")
        }

        fun jsonQuote(value: String): String = buildString {
            append('"')
            for (c in value) when (c) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
            }
            append('"')
        }

        /** 极简取值：只为读几个顶层标量，不引入完整 JSON 解析依赖。 */
        fun jsonString(body: String, key: String): String? {
            val m = Regex("\"" + Regex.escape(key) + "\"\\s*:\\s*(\"([^\"\\\\]*(\\\\.[^\"\\\\]*)*)\"|[-\\d.]+)")
                .find(body) ?: return null
            val raw = m.groupValues[1]
            return if (raw.startsWith("\"")) raw.substring(1, raw.length - 1) else raw
        }
    }
}

/**
 * 端到端注册一个账号。**永不抛出**，失败信息走 [RegisterResult.error]。
 *
 * 与桌面端一致的容错：set-password 偶发服务端抖动，用**同一个 token** 重试一次；
 * 仍失败则报错退出，不进入任何重试循环（方案 §10 阶段 F 验收：失败退避不重试风暴）。
 */
suspend fun registerOne(
    mailProvider: MailProvider,
    transport: ArenaTransport,
    log: (String) -> Unit = {},
    cancelled: () -> Boolean = { false },
    mailTimeoutSeconds: Int = 90,
    sleep: suspend (Long) -> Unit = { },
): RegisterResult {
    var email = ""
    var password = ""
    try {
        val mailbox = mailProvider.createMailbox()
        email = mailbox.email
        log("[*] 邮箱: $email")
        if (cancelled()) return RegisterResult(email = email, error = "cancelled")

        val client = ArenaRegisterClient(email = email, transport = transport, log = log)
        client.createUser()
        log("[*] 已创建用户")
        if (cancelled()) return RegisterResult(email = email, error = "cancelled")

        client.sendMagicLink(email)
        log("[*] 验证邮件已发送")

        val link = mailProvider.waitForLink(
            mailbox, ArenaRegisterClient.VERIFY_LINK_RE, mailTimeoutSeconds
        ) ?: throw ArenaProtocolException("等待验证邮件超时")
        if (cancelled()) return RegisterResult(email = email, error = "cancelled")

        val token = client.confirmLink(link)
        password = PasswordPolicy.generate()
        client.setPassword(token, password)
        client.password = password
        log("[*] 密码已设置")

        if (!client.signIn()) {
            log("[!] 首次登录失败，重新设置密码...")
            try {
                client.setPassword(token, password)
                sleep(1000)
            } catch (e: ArenaProtocolException) {
                log("[!] 重设密码异常: ${e.message}")
            }
            if (!client.signIn()) throw ArenaProtocolException("注册后无法登录（密码设置失败）")
        }
        log("[*] 登录验证通过")

        val userId = client.getMe() ?: ""
        val credits = client.getBalance(sleep = sleep) ?: ""
        log("[+] 注册成功: $email | 额度 $credits")
        return RegisterResult(email, password, userId, credits, ok = true)
    } catch (e: Exception) {
        val error = "${e::class.simpleName}: ${e.message}"
        log("[!] 失败: $error")
        return RegisterResult(email = email, password = password, ok = false, error = error)
    }
}
