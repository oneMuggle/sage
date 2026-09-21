// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AuthFlow.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/IAuthPages.cs
package ai.arena.companion.account

import java.net.URI
import java.time.Duration
import java.time.Instant
import kotlinx.coroutines.delay

/**
 * AuthFlow 操作的页面抽象。`:core` 只描述状态机；`:app` 用 WebView 实现。
 *
 * `arena` 是主会话 WebView，`auth` 是隐藏的邮箱/确认 WebView。二者必须绑定到同一
 * WebView Profile，确认邮件回调写入的登录态才能被主页面看到。
 */
interface AuthPages {
    suspend fun read(target: String): Map<String, Any?>
    suspend fun act(target: String, action: String, data: AccountData)
    fun navigate(target: String, url: String)
}

private class AuthActionCancelledException : RuntimeException()

/**
 * 桌面端自动登录/注册状态机的 Kotlin 版本。
 *
 * 保留关键语义：
 * - 每次 UI 动作前等待 1 秒，读取仍然只轮询；
 * - 人机验证暂停，解除后按原 phase 继续；
 * - 未确认页面推进时停止，避免重复提交；
 * - 注册邮箱必须从同一 `auth` 页面稳定读取，临时邮箱变化时不覆盖旧账号。
 */
class AuthFlow(
    private val pages: AuthPages,
    private val vault: AccountVault,
    private val clock: () -> Instant = { Instant.now() },
    private val existingOnly: Boolean = false,
    private val loginDelay: suspend (Long) -> Unit = { delay(it) },
) {
    var mailboxRecoveryPending: Boolean = false
        private set
    var running: Boolean = false
        private set
    var phase: String = "idle"
        private set
    var message: String = "自动登录尚未开始"
        private set
    var waitingForVerification: Boolean = false
        private set
    var onChanged: (() -> Unit)? = null

    val isBusy: Boolean get() = busy
    val email: String get() = account.email

    private var account: AccountData = AccountData()
    private var busy: Boolean = false
    private var epoch: Int = 0
    private var deadline: Instant = clock()
    private var changedAt: Instant = clock()
    private var previousStage: String = ""
    private var verificationPhase: String = ""
    private var verificationTarget: String = "arena"
    private var mailboxMismatchSince: Instant? = null
    private var mailboxCandidate: String? = null
    private var mailboxCandidateSince: Instant? = null
    private var mailboxAcquiredThisRun: Boolean = false
    private var mailboxRestoreSince: Instant? = null

    fun takeMailboxRecoveryRequest(): Boolean {
        if (running || busy || !mailboxRecoveryPending) return false
        mailboxRecoveryPending = false
        return true
    }

    private fun requestMailboxRecovery(reason: String) {
        stop(reason)
        mailboxRecoveryPending = !existingOnly && !account.verified
    }

    fun start() {
        if (busy || running) throw IllegalStateException("登录流程正在运行")
        mailboxRecoveryPending = false
        account = vault.load()
        if (account.email.isEmpty() && !account.mailboxChangeConfirmed) {
            account = account.copy(mailboxRefreshRequested = false)
        }
        if (account.password.isEmpty()) throw IllegalStateException("请先设置登录密码")
        if (!existingOnly && AccountData.nicknameError(account.name).isNotEmpty()) {
            throw IllegalStateException("请先在初始设置中填写有效的注册昵称")
        }
        if (existingOnly && account.email.isBlank()) throw IllegalStateException("保存项中没有账号")

        epoch++
        running = true
        waitingForVerification = false
        deadline = clock().plus(Duration.ofMinutes(8))
        previousStage = ""
        mailboxMismatchSince = null
        mailboxCandidate = null
        mailboxCandidateSince = null
        mailboxAcquiredThisRun = false
        mailboxRestoreSince = null
        pages.navigate("arena", "https://arena.ai/agent")
        say("inspect", "正在检查 Arena 登录状态")
    }

    fun stop(reason: String) {
        epoch++
        running = false
        waitingForVerification = false
        say("paused", reason)
    }

    private fun pauseForVerification(target: String, reason: String) {
        verificationPhase = phase
        verificationTarget = target
        epoch++
        running = false
        waitingForVerification = true
        say("verification", "$reason，请在当前页面完成；通过后将自动继续登录")
    }

    private fun say(nextPhase: String, nextMessage: String) {
        phase = nextPhase
        message = nextMessage
        changedAt = clock()
        onChanged?.invoke()
    }

    private suspend fun action(target: String, action: String) {
        val generation = epoch
        loginDelay(1000)
        if (!running || generation != epoch) throw AuthActionCancelledException()
        pages.act(target, action, account)
    }

    suspend fun tick() {
        if ((!running && !waitingForVerification) || busy) return
        busy = true
        val generation = epoch
        try {
            if (waitingForVerification) {
                val state = pages.read(verificationTarget)
                if (waitingForVerification && generation == epoch && value(state, "blocker").isEmpty()) {
                    waitingForVerification = false
                    running = true
                    phase = verificationPhase
                    deadline = clock().plus(Duration.ofMinutes(8))
                    previousStage = ""
                    say(phase, "人机验证已完成，自动继续登录流程")
                }
                return
            }
            if (clock().isAfter(deadline)) {
                stop("登录超时，保留账号；可再次自动登录")
                return
            }
            val target = if (phase in AUTH_TARGET_PHASES) "auth" else "arena"
            val state = pages.read(target)
            if (!running || generation != epoch) return

            val stage = value(state, "stage")
            val blocker = value(state, "blocker")
            if (blocker.isNotEmpty()) {
                pauseForVerification(target, blocker)
                return
            }
            if (stage == "invalid") {
                stop("邮箱确认链接无效，请在 Arena 重新发送确认邮件后重试")
                return
            }
            if (Duration.between(changedAt, clock()).seconds > 60 && stage == previousStage && phase != "mail") {
                stop("页面未进入下一步，保留当前页面，请检查后重试")
                return
            }
            previousStage = stage
            advance(target, stage, state)
        } catch (_: AuthActionCancelledException) {
            // 显式停止/epoch 变化后的动作延迟结束；保持当前停止状态即可。
        } catch (e: Exception) {
            if (generation != epoch) return
            val reason = if (e is IllegalStateException) e.message ?: e.javaClass.simpleName else e.javaClass.simpleName
            stop("登录步骤未确认（$phase）：$reason；已停止重复提交")
        } finally {
            busy = false
        }
    }

    private suspend fun advance(target: String, stage: String, state: Map<String, Any?>) {
        when {
            stage == "authenticated" -> {
                val shown = value(state, "account")
                if (account.email.isNotEmpty() && !shown.equals(account.email, ignoreCase = true)) {
                    stop("当前页面登录了其他账号，请先确认账号")
                    return
                }
                if (target == "auth") {
                    pages.navigate("arena", "https://arena.ai/agent")
                    say("return", "密码已提交，正在确认 Arena 主页面登录状态")
                    return
                }
                account = account.copy(email = shown, verified = true)
                vault.save(account)
                running = false
                pages.navigate("auth", "about:blank")
                say("complete", "已确认登录：$shown")
            }
            stage == "expand" -> action(target, "expand")
            phase == "mailbox" -> acquireMailbox(stage, state)
            phase == "mail" -> readMail(stage, state)
            phase == "verify" && stage == "setPassword" -> {
                action("auth", "password")
                say("passwordFilled", "已填写密码，等待提交")
            }
            phase == "passwordFilled" -> {
                say("passwordSubmitted", "已提交设置密码，等待确认")
                action("auth", "submitPassword")
            }
            phase != "passwordSubmitted" && phase != "return" -> arenaStep(stage)
        }
    }

    private suspend fun acquireMailbox(stage: String, state: Map<String, Any?>) {
        if (stage != "mail") {
            mailboxCandidate = null
            mailboxCandidateSince = null
            return
        }
        val shown = value(state, "mailbox").trim()
        if (!EMAIL_RE.matches(shown)) {
            mailboxCandidate = null
            mailboxCandidateSince = null
            return
        }
        if (shown.equals(account.mailboxBeforeRefresh, ignoreCase = true)) {
            mailboxCandidate = null
            mailboxCandidateSince = null
        }
        when {
            !account.mailboxRefreshRequested -> {
                if (value(state, "canChangeMailbox") == "True") {
                    account = account.copy(
                        mailboxBeforeRefresh = shown,
                        mailboxRefreshRequested = true,
                    )
                    vault.save(account)
                    say("mailbox", "已请求更改邮箱地址，正在等待新地址确认")
                    action("auth", "refreshMail")
                }
            }
            !account.mailboxChangeConfirmed && value(state, "canConfirmMailboxChange") == "True" -> {
                account = account.copy(mailboxChangeConfirmed = true)
                vault.save(account)
                say("mailbox", "已确认更换邮箱，等待地址变化")
                action("auth", "confirmRefreshMail")
            }
            !shown.equals(account.mailboxBeforeRefresh, ignoreCase = true) -> {
                if (account.excludedEmails.any { it.equals(shown, ignoreCase = true) }) {
                    stop("邮箱地址已被其他实例使用，未提交注册")
                    return
                }
                if (value(state, "canConfirmMailboxChange") == "True") {
                    mailboxCandidate = null
                    mailboxCandidateSince = null
                    return
                }
                if (!mailboxCandidate.equals(shown, ignoreCase = true)) {
                    mailboxCandidate = shown
                    mailboxCandidateSince = clock()
                    say("mailbox", "新邮箱地址已出现，等待连续稳定确认…")
                    return
                }
                val since = mailboxCandidateSince ?: return
                if (Duration.between(since, clock()).seconds < 3) return
                mailboxAcquiredThisRun = true
                account = account.copy(email = shown, verified = false)
                vault.save(account)
                say("inspect", "已确认邮箱地址更换，正在打开注册")
            }
        }
    }

    private suspend fun readMail(stage: String, state: Map<String, Any?>) {
        if (stage != "mail") return
        val verifyUrl = value(state, "verifyUrl")
        if (verifyUrl.isNotEmpty()) {
            if (!isAllowedVerifyUrl(verifyUrl)) {
                stop("确认邮件的链接地址不匹配")
                return
            }
            say("verify", "已收到确认邮件，正在打开 Arena 设置密码页面")
            pages.navigate("auth", verifyUrl)
        } else if (value(state, "mailAvailable") == "True") {
            action("auth", "openMail")
        } else if (!value(state, "mailbox").equals(account.email, ignoreCase = true)) {
            val first = mailboxMismatchSince ?: clock().also { mailboxMismatchSince = it }
            if (Duration.between(first, clock()).seconds >= 30) {
                requestMailboxRecovery("当前收件箱与原注册地址不一致，且未找到确认邮件；原账号已保留，可新建实例重新注册")
            }
        } else {
            mailboxMismatchSince = null
        }
    }

    /** 只读已有邮箱页；绝不在这里刷新或换邮箱。 */
    private suspend fun confirmRegistrationMailbox(step: String): Boolean {
        val generation = epoch
        val state = pages.read("auth")
        if (!running || generation != epoch) return false
        if (value(state, "stage") == "loading") {
            val first = mailboxRestoreSince
            if (first == null) {
                mailboxRestoreSince = clock()
                pages.navigate("auth", "https://10minutemail.one/zh")
                say(phase, "正在恢复原实例的收件箱，加载完成后核对注册地址；不会更换邮箱…")
            } else if (Duration.between(first, clock()).seconds >= 30) {
                stop("原收件箱页面未能加载，未提交注册；请检查网络后再点自动注册 / 登录")
            }
            return false
        }
        val shown = value(state, "mailbox").trim()
        if (value(state, "stage") != "mail" || !EMAIL_RE.matches(shown)) {
            stop("${step}前未能读取有效的收件箱地址，未提交；请检查原邮箱页面，账号未改变")
            return false
        }
        if (value(state, "blocker").isNotEmpty() || value(state, "canConfirmMailboxChange") == "True") {
            stop("${step}前邮箱页面仍有验证或更换地址窗口，未提交；请先处理原邮箱页面")
            return false
        }
        if (!shown.equals(account.email, ignoreCase = true)) {
            requestMailboxRecovery("${step}前收件箱地址与原账号不一致，无法继续原注册；旧实例已保留，可新建实例重新注册")
            return false
        }
        return true
    }

    private suspend fun arenaStep(stage: String) {
        if (existingOnly && (stage == "create" || stage == "verification")) {
            stop("网站要求注册或额外验证，请在当前页面检查已保存账号后重试登录")
            return
        }
        when (stage) {
            "loggedOut" -> action("arena", "openLogin")
            "email" -> when {
                account.email.isEmpty() -> {
                    pages.navigate("auth", "https://10minutemail.one/zh")
                    say("mailbox", "正在获取临时邮箱")
                }
                phase == "emailFilled" -> {
                    if (!existingOnly && (mailboxAcquiredThisRun || !account.verified) &&
                        !confirmRegistrationMailbox("提交邮箱")
                    ) return
                    say("emailSubmitted", "已提交邮箱，等待网站判断登录或注册")
                    action("arena", "submitEmail")
                }
                phase != "emailSubmitted" -> {
                    if (!existingOnly && !account.verified && !confirmRegistrationMailbox("恢复注册")) return
                    action("arena", "email")
                    say("emailFilled", "已填写邮箱")
                }
            }
            "create" -> when {
                phase == "nameFilled" -> {
                    if (!confirmRegistrationMailbox("创建账号")) return
                    say("createSubmitted", "已提交注册，等待确认邮件")
                    action("arena", "create")
                }
                phase != "createSubmitted" -> {
                    action("arena", "name")
                    say("nameFilled", "已填写姓名")
                }
            }
            "verification" -> {
                val mailState = pages.read("auth")
                if (value(mailState, "stage") != "mail") {
                    pages.navigate("auth", "https://10minutemail.one/zh")
                }
                say("mail", "正在等待 Arena 确认邮件")
            }
            "loginPassword" -> when {
                phase == "loginFilled" -> {
                    say("loginSubmitted", "已提交登录密码，等待确认")
                    action("arena", "submitPassword")
                }
                phase != "loginSubmitted" -> {
                    action("arena", "password")
                    say("loginFilled", "已填写已保存账号的密码")
                }
            }
        }
    }

    private fun isAllowedVerifyUrl(url: String): Boolean = runCatching {
        val uri = URI(url)
        uri.scheme == "https" && uri.host == "arena.ai" && uri.path == "/nextjs-api/callback/email"
    }.getOrDefault(false)

    companion object {
        private val AUTH_TARGET_PHASES = setOf("mailbox", "mail", "verify", "passwordFilled", "passwordSubmitted")
        private val EMAIL_RE = Regex("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")

        fun value(data: Map<String, Any?>, key: String): String = when (val v = data[key]) {
            null -> ""
            is Boolean -> if (v) "True" else "False"
            else -> v.toString()
        }
    }
}
