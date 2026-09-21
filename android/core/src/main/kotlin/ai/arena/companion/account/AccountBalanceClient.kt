package ai.arena.companion.account

import ai.arena.companion.register.ArenaTransport
import ai.arena.companion.register.HttpResponse

/**
 * 账号额度信息。
 */
data class AccountBalance(
    val creditsRemaining: Long,
    val totalCredits: Long? = null,
    val timestamp: Long = System.currentTimeMillis(),
)

/**
 * 账号额度查询客户端。
 *
 * 对接 Arena.ai 官方端点：
 * GET /api/billing/balance
 * headers: Referer: https://arena.ai/
 */
class AccountBalanceClient(
    private val transport: ArenaTransport,
    private val log: (String) -> Unit = {},
) {
    suspend fun getBalance(
        retries: Int = 4,
        delayMs: Long = 3000L,
        sleep: suspend (Long) -> Unit = { },
    ): AccountBalance? {
        var lastErr = ""
        for (i in 0 until maxOf(1, retries)) {
            try {
                val resp: HttpResponse = transport.get(
                    url = "$ARENA/api/billing/balance",
                    referer = "$ARENA/"
                )
                if (resp.status == 200) {
                    val credits = parseCreditsRemaining(resp.body)
                    if (credits != null) {
                        val total = parseTotalCredits(resp.body)
                        return AccountBalance(creditsRemaining = credits, totalCredits = total)
                    }
                    lastErr = "未找到 creditsRemaining 字段"
                } else {
                    lastErr = "HTTP ${resp.status}"
                }
            } catch (e: Exception) {
                lastErr = "${e::class.simpleName}: ${e.message}"
            }
            if (i < retries - 1) {
                sleep(delayMs)
            }
        }
        log("[!] 查额度失败($lastErr)")
        return null
    }

    companion object {
        const val ARENA = "https://arena.ai"

        fun parseCreditsRemaining(body: String): Long? {
            val m = Regex("\"creditsRemaining\"\\s*:\\s*(\\d+)").find(body)
                ?: Regex("\"creditsRemaining\"\\s*:\\s*\"(\\d+)\"").find(body)
            return m?.groupValues?.get(1)?.toLongOrNull()
        }

        fun parseTotalCredits(body: String): Long? {
            val m = Regex("\"totalCredits\"\\s*:\\s*(\\d+)").find(body)
                ?: Regex("\"totalCredits\"\\s*:\\s*\"(\\d+)\"").find(body)
            return m?.groupValues?.get(1)?.toLongOrNull()
        }
    }
}
