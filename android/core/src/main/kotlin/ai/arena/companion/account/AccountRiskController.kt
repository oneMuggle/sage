package ai.arena.companion.account

import java.time.Instant

/**
 * 账号健康与风控状态。
 */
sealed class AccountState {
    /** 正常可用。 */
    data object Available : AccountState()

    /** 遭遇限流，处于退避冷却中。 */
    data class Cooling(val until: Instant, val level: Int, val reason: String) : AccountState()

    /** 触发换 IP 阈值或遭遇 Cloudflare 挑战，需要重新绑定代理。 */
    data class Rebinding(val reason: String, val cfChallenge: Boolean) : AccountState()

    /** 遇到强人机图片验证（Captcha / Turnstile），自动化挂起，需人工介入。 */
    data class NeedVerification(val prompt: String, val since: Instant = Instant.now()) : AccountState()

    /** 今日额度已耗尽，需轮换下一个账号，次日重置。 */
    data class DepletedToday(val resetAt: Instant, val remainingCredits: Long) : AccountState()

    /** 凭据彻底失效或被封禁。 */
    data class Invalid(val reason: String) : AccountState()
}

/**
 * 账号风控与状态机调度器。
 *
 * 实现了 ArenCard 中的：
 * 1. 账号级独立 429 阶梯（15s -> 30s -> 60s -> 90s）；
 * 2. 60s 档位自动换 IP；
 * 3. Cloudflare 挑战（429/403 含 "Just a moment..."）立即换 IP；
 * 4. 额度耗尽自动标记 DepletedToday 并触发换号轮换；
 * 5. 人机验证 NeedVerification 挂起态。
 */
class AccountRiskController(
    private val clock: () -> Instant = { Instant.now() },
    private val switchAtLevel: Int = 2,
) {
    private val states = mutableMapOf<String, AccountState>()
    private val ladder = listOf(15L, 30L, 60L, 90L)
    private val levels = mutableMapOf<String, Int>()
    private val lastRateLimited = mutableMapOf<String, Instant>()

    fun getState(accountId: String): AccountState {
        val current = states[accountId] ?: AccountState.Available
        if (current is AccountState.Cooling) {
            if (clock().isAfter(current.until)) {
                states[accountId] = AccountState.Available
                return AccountState.Available
            }
        }
        if (current is AccountState.DepletedToday) {
            if (clock().isAfter(current.resetAt)) {
                states[accountId] = AccountState.Available
                return AccountState.Available
            }
        }
        return current
    }

    /** 记录遭遇限流或 Cloudflare 挑战。 */
    fun noteRateLimited(accountId: String, isCloudflare: Boolean = false, message: String = ""): AccountState {
        val now = clock()
        if (isCloudflare) {
            val state = AccountState.Rebinding(
                reason = "Cloudflare 挑战（出口 IP 污染，必须更换）: $message",
                cfChallenge = true
            )
            states[accountId] = state
            levels[accountId] = 0
            return state
        }

        val last = lastRateLimited[accountId]
        var currentLevel = levels.getOrDefault(accountId, 0)
        if (last != null && now.epochSecond - last.epochSecond > 240) {
            currentLevel = maxOf(0, currentLevel - 1)
        }

        val stepSeconds = ladder.getOrElse(currentLevel) { ladder.last() }
        val until = now.plusSeconds(stepSeconds)
        lastRateLimited[accountId] = now

        if (currentLevel >= switchAtLevel) {
            val state = AccountState.Rebinding(
                reason = "429 限流达到第 $currentLevel 档(${stepSeconds}s)，自动触发换 IP",
                cfChallenge = false
            )
            states[accountId] = state
            levels[accountId] = 0
            return state
        }

        levels[accountId] = currentLevel + 1
        val state = AccountState.Cooling(until = until, level = currentLevel, reason = "HTTP 429 退避 ${stepSeconds}s")
        states[accountId] = state
        return state
    }

    /** 记录额度检查结果。若不足则标记今日耗尽。 */
    fun noteBalance(accountId: String, creditsRemaining: Long, threshold: Long = 100L): AccountState {
        if (creditsRemaining < threshold) {
            val reset = clock().plusSeconds(12 * 3600L)
            val state = AccountState.DepletedToday(resetAt = reset, remainingCredits = creditsRemaining)
            states[accountId] = state
            return state
        }
        if (states[accountId] is AccountState.DepletedToday) {
            states[accountId] = AccountState.Available
        }
        return getState(accountId)
    }

    /** 记录遇到强人机验证。 */
    fun noteVerificationRequired(accountId: String, prompt: String): AccountState {
        val state = AccountState.NeedVerification(prompt = prompt, since = clock())
        states[accountId] = state
        return state
    }

    /** 人工完成验证后恢复。 */
    fun verificationResolved(accountId: String) {
        if (states[accountId] is AccountState.NeedVerification) {
            states[accountId] = AccountState.Available
        }
    }

    /** 完成换 IP 绑定后恢复。 */
    fun rebindingCompleted(accountId: String) {
        if (states[accountId] is AccountState.Rebinding) {
            states[accountId] = AccountState.Available
            levels[accountId] = 0
        }
    }

    /** 标记账号失效。 */
    fun markInvalid(accountId: String, reason: String) {
        states[accountId] = AccountState.Invalid(reason)
    }

    /** 在账号池中挑选下一个最适合工作的可用账号。 */
    fun selectNextAvailable(candidates: List<String>): String? {
        return candidates.firstOrNull { getState(it) is AccountState.Available }
    }
}
