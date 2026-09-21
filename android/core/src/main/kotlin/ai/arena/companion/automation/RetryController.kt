// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.Tick.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.RateLimit.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.ModelRetention.cs
// spec: docs/mcp-android-implementation-plan.md §3.1 / §3.4 / §3.5
//
// 全项目最高保真要求的文件。任何"顺手优化"都不允许：
// 所有失败都是"暂停 + 可读原因 + 等人工"，没有一处自动重试有副作用的操作。
package ai.arena.companion.automation

import ai.arena.companion.identity.ConversationIdentity
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.random.Random

class RetryController(
    private val page: ArenaPage,
    private val probe: ProbeReader?,
    private val rename: RenamePage?,
    private val clock: () -> Instant = { Instant.now() },
    private val preparation: RequestPreparation? = null,
    private val retryJitter: () -> Double = { Random.Default.nextDouble() },
    private val stepJitter: () -> Double = { Random.Default.nextDouble() },
) {

    // ---- 可观察状态 -------------------------------------------------------
    var running: Boolean = false; private set
    var finished: Boolean = false; private set
    var phase: String = "idle"; private set
    var message: String = "先打开 Arena 并登录，然后点“开始”"; private set
    var prompt: String? = null; private set
    var rounds: Int = 0; private set
    var attempt: Int = 0; private set
    var limit: Int = 0; private set
    var lastModel: String? = null; private set
    var waitingForVerification: Boolean = false; private set
    var lastSuccessfulRead: Instant? = null; private set
    var lastReadGenerating: Boolean = false; private set
    var lastReadThinking: Boolean = false; private set
    var lastReadUrl: String? = null; private set
    var rateLimitRetries: Int = 0; private set
    var retryAt: Instant? = null; private set
    var websiteArchivedRounds: Int = 0; private set

    val isBusy: Boolean get() = busy
    val trackedUrl: String? get() = expectedUrl
    val hasPendingWork: Boolean
        get() = phase != "idle" && (running || waitingForVerification || !finished || phase == "cooldown")

    // ---- 可调参数（默认值与 C# 一致，不得改动语义） ------------------------
    /** 一轮内"内容长时间无实质变化"的上限，5 分钟。 */
    var maximumNoProgressSeconds: Int = 300
    /** 等探针给出本轮模型名的上限；实测一轮约 30~65 秒。 */
    var modelWaitSeconds: Int = 150
    var stepPauseSeconds: Double = 3.0
    var stepPauseJitterSeconds: Double = 2.0

    var retentionPolicy: ModelRetentionPolicy = ModelRetentionPolicy.KEEP_ALL
    /** (会话地址, 模型名, 会话标题) → 归档。为空表示只重命名、不归档。 */
    var archiveSink: (suspend (String?, String?, String?) -> Unit)? = null
    /** (会话地址, generationStamp, active) → 网站归档。 */
    var websiteArchive: (suspend (String?, String?, () -> Boolean) -> Unit)? = null

    var onChanged: (() -> Unit)? = null
    var onRoundStarted: (() -> Unit)? = null
    var onRoundCompleted: ((String?, String?) -> Unit)? = null

    // ---- 内部状态 ---------------------------------------------------------
    private var stepPauseUntil: Instant? = null
    private var meaningfulProgressAt: Instant? = null
    private var meaningfulSignature: String? = null
    private var noProgressSignature: String? = null
    private var noProgressSince: Instant? = null
    private var completionIdentitySince: Instant? = null
    private var modelSince: Instant? = null
    private var probeMissingSince: Instant? = null
    private var baselineRunId: String? = null
    private var pendingTitle: String? = null
    private var busy = false
    private var sawGeneration = false
    private var sidebarExpansionAttempted = false
    private var termsAttempted = false
    private var termsPendingSince: Instant? = null
    private var epoch = 0
    private var readFailures = 0
    private var nextRead: Instant = Instant.MIN
    private var readFailureSince: Instant = Instant.MIN
    private var expectedUrl: String? = null
    private var signature: String? = null
    private var until: Instant = Instant.MIN
    private var phaseSince: Instant = Instant.MIN
    private var stableSince: Instant = Instant.MIN
    private var contentMissingSince: Instant? = null
    private var awaitingConversationRoute = false
    private var routeMissingSince: Instant = Instant.MIN
    /** 「连续不在 Arena 对话页」的起算点；Instant.MIN 表示当前处在允许路由上。 */
    private var notAllowedSince: Instant = Instant.MIN
    private var lastModelSayBucket = -1

    // 限流
    private var seenRateLimit = 0
    private var rateLimitPrimed = false
    private var rateLimitPendingSubmission = false
    private var cooldownUrl: String? = null
    private var retryPrepared = false
    private var retryDraftFilled = false
    private var retryPreparationSince: Instant = Instant.MIN

    // 保留策略
    private var runRetention: ModelRetentionPolicy = ModelRetentionPolicy.KEEP_ALL
    private var rejectedModelUrl: String? = null
    private var completedGenerationStamp: String? = null
    private var websiteArchiveStarted = false

    val roundPauseSeconds: Int
        get() {
            val u = stepPauseUntil
            return if (phase == "roundPause" && u != null)
                max(0.0, ceil(secondsBetween(clock(), u))).toInt() else 0
        }

    val cooldownSeconds: Int
        get() {
            val r = retryAt ?: return 0
            return min(Int.MAX_VALUE.toDouble(), max(0.0, ceil(secondsBetween(clock(), r)))).toInt()
        }

    // ---- 生命周期 ---------------------------------------------------------
    private fun say(text: String) {
        message = text
        onChanged?.invoke()
    }

    private fun move(next: String) {
        when (next) {
            "confirm" -> awaitingConversationRoute = ConversationIdentity.isNew(expectedUrl)
            "inspect", "new" -> awaitingConversationRoute = false
        }
        phase = next
        stepPauseUntil = null
        meaningfulProgressAt = null; meaningfulSignature = null
        noProgressSince = null; completionIdentitySince = null; contentMissingSince = null
        if (next == "new") sidebarExpansionAttempted = false
        if (next == "model") { modelSince = clock(); probeMissingSince = null }
        phaseSince = clock()
        until = phaseSince.plusSeconds(120)
    }

    fun start(prompt: String?, limit: Int) {
        if (busy) throw IllegalStateException("上一操作仍在结束，请稍后重试")
        if (running) return
        if (prompt.isNullOrBlank()) throw IllegalArgumentException("请先设置每轮发送的消息")
        if (limit < 0) throw IllegalArgumentException("次数不能为负数；0 表示不限次数")
        lastSuccessfulRead = null; lastReadUrl = null
        lastReadGenerating = false; lastReadThinking = false
        runRetention = retentionPolicy
        websiteArchivedRounds = 0; rejectedModelUrl = null; websiteArchiveStarted = false
        epoch++
        this.prompt = prompt.trim(); this.limit = limit
        attempt = 0; rounds = 0; lastModel = null
        expectedUrl = null; signature = null; sawGeneration = false
        termsAttempted = false; termsPendingSince = null
        seenRateLimit = 0; rateLimitPrimed = false; resetRateLimitRetry()
        readFailures = 0; nextRead = Instant.MIN; stepPauseUntil = null; notAllowedSince = Instant.MIN
        waitingForVerification = false; baselineRunId = null; pendingTitle = null
        preparation?.beginRound()
        running = true; finished = false
        until = clock().plusSeconds(120)
        move("inspect")
        onRoundStarted?.invoke()
        say("正在检查页面，请稍候…")
    }

    fun pause(reason: String) {
        epoch++; running = false; waitingForVerification = false; say(reason)
    }

    private fun pauseForVerification(reason: String) {
        contentMissingSince = null; signature = null
        epoch++; running = false; waitingForVerification = true; nextRead = Instant.MIN
        say("$reason，请在右侧完成；通过后将自动继续当前进度")
    }

    fun resume() {
        if (busy) throw IllegalStateException("上一操作仍在结束，请稍后重试")
        if (running || finished || phase == "idle") return
        if (awaitingConversationRoute) routeMissingSince = clock()
        meaningfulProgressAt = null; meaningfulSignature = null
        if (phase != "roundPause") stepPauseUntil = null
        contentMissingSince = null
        completionIdentitySince = null; noProgressSince = null; signature = null
        epoch++; running = true; waitingForVerification = false
        until = clock().plusSeconds(120); phaseSince = clock()
        nextRead = Instant.MIN; readFailures = 0; notAllowedSince = Instant.MIN
        say("继续当前进度，不重复发送已提交的问题")
    }

    private fun done(text: String) { finished = true; running = false; say(text) }

    private val limitReached: Boolean get() = limit > 0 && rounds >= limit

    private fun late(seconds: Int): Boolean = secondsBetween(phaseSince, clock()) >= seconds

    fun endPausedTaskForManualSend() {
        if (running || busy || waitingForVerification)
            throw IllegalStateException("请先暂停并等待当前操作结束")
        finished = true; move("idle")
        pause("已结束暂停的自动任务；已完成记录不变，不再自动继续原进度")
    }

    fun cancelForRecovery() {
        finished = true; pause("已取消当前任务；恢复后重新开始即可")
    }

    /** 仅在一轮全部工作成功后调用。 */
    private fun prepareNextRound() {
        if (limitReached) { done("已完成 $rounds 轮，达到次数上限；可打开模型归档查看"); return }
        move("roundPause")
        if (waitForStepPause("本轮处理完成，轮次间隔：")) {
            move("new"); say("轮次间隔结束，准备下一轮")
        }
    }

    /** 每轮间隔只抽一次抖动；暂停/继续保留截止时间，轮询不会延长等待。 */
    private fun waitForStepPause(reason: String): Boolean {
        val pending = stepPauseUntil
        if (pending == null) {
            val baseSeconds = max(0.0, min(60.0, stepPauseSeconds))
            val range = max(0.0, min(30.0, stepPauseJitterSeconds))
            val jitter = if (range <= 0) 0.0 else (max(0.0, min(1.0, stepJitter())) * 2 - 1) * range
            val seconds = baseSeconds + jitter
            if (seconds <= 0) return true
            stepPauseUntil = clock().plusMillis((seconds * 1000).toLong())
            say(reason + String.format("%.1f", seconds) + " 秒后继续…")
            return false
        }
        if (clock().isBefore(pending)) return false
        stepPauseUntil = null
        return true
    }

    /** 单次 DOM 快照不完整不算超时；衡量的是一段连续无法读取的时间。 */
    private fun waitForReadableContent(reason: String?): Boolean {
        if (reason == null) { contentMissingSince = null; return false }
        signature = null
        val since = contentMissingSince ?: clock().also { contentMissingSince = it }
        if (secondsBetween(since, clock()) >= 20) pause(reason)
        return true
    }

    // ---- 阶段机 -----------------------------------------------------------
    /**
     * inspect → new → waitNew → fill → send → confirm → observe → model → rename → [collect] → roundPause → new …
     */
    suspend fun tick() {
        if (busy) return
        if (!running && !waitingForVerification) return
        busy = true
        val currentEpoch = epoch
        try {
            if (phase == "roundPause") {
                if (!running) return
                if (waitForStepPause("轮次间隔：")) { move("new"); say("轮次间隔结束，准备下一轮") }
                return
            }
            if (clock().isBefore(nextRead)) return
            if (phase == "websiteArchive") { archiveExcludedModel(currentEpoch); return }

            val v: PageState
            try {
                v = page.read(prompt) ?: return
                readFailures = 0; readFailureSince = Instant.MIN
                lastSuccessfulRead = clock()
                lastReadGenerating = v.generating; lastReadThinking = v.thinking; lastReadUrl = v.url
            } catch (e: PageReadTimeoutException) {
                // 流式渲染时主线程繁忙，读取超时属正常现象；指数退避重试，
                // 只有连续失败达到阈值才暂停。
                readFailures++
                val backoff = min(20.0, 2.0.pow(min(4, readFailures)))
                nextRead = clock().plusMillis((backoff * 1000).toLong())
                if (readFailureSince == Instant.MIN) readFailureSince = clock()
                if (secondsBetween(readFailureSince, clock()) >= 120)
                    pause("网页连续 2 分钟无法读取，已暂停；检查右侧页面后点“继续”")
                return
            }
            if (epoch != currentEpoch) return
            if (!v.snapshotConsistent) return   // 原生地址与 DOM 不一致，等下一次稳定快照
            if (!page.isAllowed(v.url)) {
                // 有意偏离桌面端：C# 的 Read() 在 !IsAllowed 时返回只带 url 的 stub（main=false），
                // 由 inspect 分支 20 秒后以「页面尚未就绪」暂停；安卓端 read() 不做这层包装，
                // 于是这里自行计时：不在 /agent 连续 20 秒（与桌面端 Late(20) 对齐）就暂停，
                // 并给出可读原因。否则会静默空转 —— 表现为一直停在检查页面、既不推进也不报错。
                if (notAllowedSince == Instant.MIN) notAllowedSince = clock()
                if (secondsBetween(notAllowedSince, clock()) >= 20)
                    pause("当前页面不是 Arena 对话页，已暂停；请打开 arena.ai/agent 后点“继续”")
                return
            }
            notAllowedSince = Instant.MIN

            if (waitingForVerification) {
                if (v.blocker.isNullOrEmpty()) {
                    waitingForVerification = false; running = true; epoch++
                    until = clock().plusSeconds(120); nextRead = Instant.MIN
                    say("验证已通过，继续当前进度")
                } else return
            }

            // 首次发送的条款弹窗会遮住已提交的问题。必须在 main/promptConfirmed 可见性判断之前
            // 处理，且不重发、不推进阶段。
            if (v.termsPending) {
                contentMissingSince = null
                if (!termsAttempted) {
                    termsAttempted = true
                    termsPendingSince = clock()
                    say("正在确认网站使用条款，等待弹窗关闭…")
                    page.act("terms", prompt)
                    return
                }
                val since = termsPendingSince
                if (since == null || secondsBetween(since, clock()) >= 20)
                    pause("网站使用条款尚未关闭，已暂停；请检查弹窗并手动处理后点“继续”，不会重复点击同意或重发消息")
                return
            }
            if (termsPendingSince != null) {
                termsPendingSince = null
                contentMissingSince = null
                phaseSince = clock()
                say("网站条款弹窗已关闭，继续确认原任务，不重复发送…")
            }

            val needsPrompt = phase == "observe" || phase == "confirm"
            val readableReason = when {
                !v.main -> "页面内容连续 20 秒无法读取，已暂停；恢复后点“继续”"
                needsPrompt && !v.promptConfirmed -> "当前问题连续 20 秒无法确认，已暂停，不会自动重发"
                else -> null
            }
            if (waitForReadableContent(readableReason)) return

            if (handleCooldown(v, currentEpoch)) return
            if (epoch != currentEpoch || !running) return

            if (!v.blocker.isNullOrEmpty()) {
                if (v.blocker == BLOCKER_VERIFICATION) { pauseForVerification(v.blocker!!); return }
                pause(v.blocker!!); return
            }

            if (phase != "observe" && phase != "model" && late(120)) {
                pause("当前步骤超过 2 分钟未完成，已暂停；检查网页后点“继续”")
                return
            }

            when (phase) {
                "inspect" -> {
                    if (!v.main) { if (late(20)) pause("页面尚未就绪，请确认右侧已打开 Arena"); return }
                    expectedUrl = v.url
                    move("new")
                    say("页面已连接，准备开启新对话")
                    return
                }
                "new" -> {
                    if (limitReached) { done("已完成 $rounds 轮，达到次数上限；可打开模型归档查看"); return }
                    if (v.newLinks != 1) {
                        if (v.newLinks > 1) { pause("检测到多个 New Chat 入口，已暂停，避免误操作"); return }
                        if (v.canExpand && !sidebarExpansionAttempted) {
                            sidebarExpansionAttempted = true
                            page.act("expand", prompt); return
                        }
                        if (late(20)) pause("未能确认 New Chat 入口，请手动展开网页侧栏后点“继续”")
                        return
                    }
                    move("waitNew"); expectedUrl = null; signature = null; sawGeneration = false
                    preparation?.beginRound()
                    onRoundStarted?.invoke()
                    page.act("new", prompt); return
                }
                "waitNew" -> {
                    if (!v.conversation && !v.generating && v.editor) { expectedUrl = v.url; move("fill") }
                    else if (late(20)) pause("未能打开新对话，请检查页面后继续")
                    return
                }
                "fill" -> {
                    if (!v.editor || v.conversation || v.generating) {
                        pause("当前不是空白新对话，请先打开新对话再继续"); return
                    }
                    if (!v.draft.isNullOrEmpty() && v.draft != prompt) {
                        pause("右侧有不同的草稿，已保留；请自行处理后继续"); return
                    }
                    page.act("fill", prompt)
                    // ref: RetryController.Tick.cs L127 直接 Move("send")：桌面端的附件在 Configure 时已经由
                    //      CDP 塞进 input，prepare 阶段只是兜底。安卓端投递必须发生在草稿填好、发送之前，
                    //      所以有附件要求时先经 prepare；没有附件（或未注入 preparation）行为与桌面端完全一致。
                    if (running && epoch == currentEpoch) move(if (preparation?.required == true) "prepare" else "send")
                    return
                }
                "prepare" -> {
                    val prep = preparation ?: run { move("send"); return }
                    if (prep.prepare()) { if (running && epoch == currentEpoch) move("send") }
                    else if (late(60)) pause("附件上传尚未确认，已暂停，不会无附件发送")
                    return
                }
                "send" -> {
                    if (preparation != null && !preparation.check()) {
                        pause("发送前附件发生改变，请检查后重新开始"); return
                    }
                    if (!running || epoch != currentEpoch) return
                    if (v.draft != prompt || v.conversation || v.generating) {
                        pause("发送前页面或草稿改变，已暂停"); return
                    }
                    if (!v.sendReady) { if (late(20)) pause("发送按钮暂不可用，请检查页面"); return }
                    if (limitReached) { done("已达到次数上限"); return }
                    // 记下本轮基线 runId：发送后服务端会下发新的 run 令牌，
                    // 只有 runId 变化且带名字，才说明探针读到的是本轮结果。
                    baselineRunId = tryReadRunId()
                    attempt++; sawGeneration = false; signature = null
                    move("confirm")
                    say("已提交第 $attempt 次，等待网页确认…")
                    page.act("send", prompt); return
                }
                "confirm" -> {
                    move("observe")
                    say("第 $attempt 次：等待回答…")
                    return
                }
                "observe" -> { observe(v); return }
                "model" -> { model(currentEpoch); return }
                "rename" -> { renamePhase(v, currentEpoch); return }
                "collect" -> { collect(v, currentEpoch); return }
            }
        } catch (e: Exception) {
            pause("操作已暂停：" + (e.message ?: e.toString()))
        } finally {
            busy = false
        }
    }

    private fun observe(v: PageState) {
        expectedUrl = v.url
        if (!v.failed && (v.generating || v.response)) resetRateLimitRetry()
        val progress = v.progressSignature ?: v.responseSignature ?: ""
        val at = meaningfulProgressAt
        if (at == null || progress != meaningfulSignature) {
            meaningfulSignature = progress; meaningfulProgressAt = clock()
        } else if (secondsBetween(at, clock()) >= max(60, maximumNoProgressSeconds)) {
            pause("回答内容长时间没有实质变化，已暂停保留任务；不会自动重发，请检查右侧页面后继续")
            return
        }
        if (v.failed) { pause("网页回答已停止或出错，本轮作废；请检查后重新开始"); return }
        sawGeneration = sawGeneration || v.generating
        // 完成证据：页面不再生成/无活动、拿到非空回答，且满足任意一条——
        // 观察到过生成、出现完成标记、或本轮问题已在页面上被确认。
        val finishedEvidence = !v.generating && !v.activity && v.response &&
            (sawGeneration || v.completionConfirmed || v.promptConfirmed)
        if (finishedEvidence && !v.responseSignature.isNullOrEmpty()) {
            noProgressSince = null
            if (signature != v.responseSignature) {
                signature = v.responseSignature; stableSince = clock(); completionIdentitySince = null
            } else if (secondsBetween(stableSince, clock()) >= 10) {
                // 重命名需要具体对话身份（/agent/<uuid>），否则侧栏里定位不到这条对话
                if (ConversationIdentity.created(v.url) == null && !page.demo) {
                    val since = completionIdentitySince
                    if (since == null) {
                        completionIdentitySince = clock(); say("回答已稳定，正在等待具体对话身份…")
                    } else if (secondsBetween(since, clock()) >= 120) {
                        pause("回答已完成，但具体对话身份仍未确认，已暂停；地址就绪后点“继续”，不必重新发送")
                    }
                    return
                }
                completedGenerationStamp = v.generationStamp
                move("model")
                lastModelSayBucket = -1
                say("回答已完成，正在读取本轮的模型名…")
            }
        } else {
            completionIdentitySince = null
            if (v.generating || v.activity) { noProgressSince = null; signature = null }
            else {
                signature = null
                val since = noProgressSince
                if (noProgressSignature != v.responseSignature || since == null) {
                    noProgressSignature = v.responseSignature; noProgressSince = clock()
                } else if (secondsBetween(since, clock()) >= 60) {
                    pause("页面已停止生成，但始终拿不到可靠完成证据，已暂停；请检查右侧回答后点“继续”，不会自动重发")
                }
            }
        }
    }

    private suspend fun model(currentEpoch: Int) {
        if (page.demo) { completeRound("演示模型（模拟）", clock()); return }
        if (modelSince == null) modelSince = clock()
        val snap = try { probe?.read() } catch (_: Exception) { null } // 探针读取失败按未取到处理
        if (!running || epoch != currentEpoch) return

        if (snap == null || !snap.api) {
            // 探针没注入：本机缺 assets 产物，或页面不在 arena.ai
            val since = probeMissingSince ?: clock().also { probeMissingSince = it }
            if (secondsBetween(since, clock()) >= 20) {
                completeRound("未识别（探针未加载）", clock())
            }
            return
        }
        probeMissingSince = null
        val newRun = !snap.runId.isNullOrEmpty() && snap.runId != baselineRunId
        if (newRun && !snap.name.isNullOrEmpty()) { completeRound(snap.name, clock()); return }

        val waited = secondsBetween(modelSince!!, clock())
        if (waited >= modelWaitSeconds) {
            val reason = when {
                snap.runId.isNullOrEmpty() -> "未取到 run 令牌"
                snap.lastError.isNullOrEmpty() -> "run trace 未给出模型名"
                else -> snap.lastError
            }
            completeRound("未识别（$reason）", clock())
            return
        }
        val bucket = waited.toInt() / 15
        if (bucket != lastModelSayBucket) {
            lastModelSayBucket = bucket
            say("回答已完成，正在读取本轮的模型名…（已等 ${waited.toInt()} 秒）")
        }
    }

    private suspend fun renamePhase(v: PageState, currentEpoch: Int) {
        val renamer = rename ?: run { finishRound(); return }
        // 离线演示页不改网页标题，只保留同样的 rename 阶段后进入模拟归档。
        if (page.demo) { finishRound(); return }
        // 重命名要在侧栏里定位当前对话，侧栏折叠时找不到入口。
        if (v.newLinks != 1) {
            if (v.canExpand) { page.act("expand", prompt); return }
            if (late(20)) pause("重命名前未能展开网页侧栏，已暂停；请手动展开侧栏后点“继续”")
            return
        }
        try {
            say("正在把对话重命名为「$pendingTitle」…")
            renamer.rename(pendingTitle ?: "", { running && epoch == currentEpoch }) {
                if (running && epoch == currentEpoch) say(it)
            }
        } catch (e: Exception) {
            if (!running || epoch != currentEpoch) return
            pause("重命名未完成：" + (e.message ?: e.toString()))
            return
        }
        if (!running || epoch != currentEpoch) return
        finishRound()
    }

    private suspend fun collect(v: PageState, currentEpoch: Int) {
        val sink = archiveSink ?: run { prepareNextRound(); return }
        if (page.demo) {
            if (limitReached) done("离线演示完成：已模拟读取模型名、重命名和归档（未写入真实归档）")
            else { say("离线演示：已模拟归档（未写入文件）"); prepareNextRound() }
            return
        }
        if (ConversationIdentity.created(v.url) == null) {
            if (late(30)) pause("归档前无法确认具体对话身份，已暂停；本条未归档")
            return
        }
        try {
            say("正在把本轮会话归档到「" + (lastModel.takeUnless { it.isNullOrEmpty() } ?: "未识别") + "」…")
            sink(v.url, lastModel, pendingTitle)
        } catch (e: Exception) {
            pause("归档未完成：" + (e.message ?: e.toString()))
            return
        }
        if (!running || epoch != currentEpoch) return
        if (limitReached) { done("已完成 $rounds 轮，达到次数上限；可打开模型归档查看"); return }
        prepareNextRound()
    }

    private suspend fun tryReadRunId(): String? = try { probe?.read()?.runId } catch (_: Exception) { null }

    private fun completeRound(model: String?, at: Instant) {
        lastModel = model
        pendingTitle = buildTitle(model, at)
        if (!page.demo && runRetention.excludes(model)) {
            rejectedModelUrl = ConversationIdentity.created(expectedUrl)
            websiteArchiveStarted = false
            if (rejectedModelUrl == null) { pause("未保留模型的具体对话身份无法确认，未执行归档"); return }
            move("websiteArchive")
            say("模型「$model」未勾选保留，准备仅移入 Arena 网站归档（不重命名、不存本地）")
            return
        }
        move("rename")
        lastModelSayBucket = -1
        say("本轮模型：$model，准备重命名为「$pendingTitle」")
    }

    private fun finishRound() {
        attempt = 0
        rounds++
        onRoundCompleted?.invoke(lastModel, pendingTitle)
        say("第 $rounds 轮完成：$lastModel" + if (limitReached) "（已达到次数上限）" else "")
        if (archiveSink != null) move("collect") else prepareNextRound()
    }

    // ---- 保留策略：未保留模型仅移入网站归档 --------------------------------
    private suspend fun archiveExcludedModel(token: Int) {
        try {
            val archive = websiteArchive
            if (archive == null || page.demo)
                throw IllegalStateException("网站归档不可用；不会改用删除或本地归档")
            if (!websiteArchiveStarted) {
                val state = page.read(prompt)
                if (!running || epoch != token) return
                if (state == null || !state.snapshotConsistent ||
                    ConversationIdentity.created(state.url) != rejectedModelUrl ||
                    !state.main || !state.promptConfirmed || state.generating || state.activity ||
                    state.failed || !state.blocker.isNullOrEmpty() ||
                    completedGenerationStamp.isNullOrEmpty() ||
                    state.generationStamp != completedGenerationStamp
                ) throw IllegalStateException("归档前当前对话或生成状态改变；未点击归档")
                websiteArchiveStarted = true
            }
            archive(rejectedModelUrl, completedGenerationStamp) { running && epoch == token }
            if (!running || epoch != token) return
            rounds++; attempt = 0; websiteArchivedRounds++
            expectedUrl = null; rejectedModelUrl = null; websiteArchiveStarted = false
            onRoundCompleted?.invoke(lastModel, pendingTitle)
            if (limitReached) done("已完成 $rounds 轮，其中网站归档 $websiteArchivedRounds 条未保留会话（未存本地）")
            else { say("未保留模型「$lastModel」已确认移入网站归档，未保存本地"); prepareNextRound() }
        } catch (e: Exception) {
            if (running && epoch == token)
                pause("未保留会话归档未完成：" + (e.message ?: e.toString()) + "；本轮保留，可检查后继续，不会自动重发")
        }
    }

    // ---- 限流 -------------------------------------------------------------
    private fun resetRateLimitRetry() {
        rateLimitRetries = 0; retryAt = null; rateLimitPendingSubmission = false
        cooldownUrl = null; retryPrepared = false; retryDraftFilled = false
        retryPreparationSince = Instant.MIN
    }

    private fun isRateLimitNotice(text: String?) = text == "网站限流，请稍后继续"

    private fun cooldownActive(token: Int) = running && epoch == token && phase == "cooldown"

    private fun exhaustRateLimit() {
        finished = true
        pause("限流后已自动重试 5/5 次，仍收到 HTTP 429，已暂停；不会自动换号或切换 IP。请稍后重新开始。")
    }

    private fun retryDeadline(now: Instant, completed: Int, jitter: Double, serverUntil: Instant): Instant {
        val basis = 5.0 * (1 shl min(4, max(0, completed)))
        val j = if (jitter.isNaN() || jitter.isInfinite()) 0.0 else jitter
        val delay = basis * (1 + 0.2 * max(0.0, min(1.0, j)))
        val local = now.plusMillis((delay * 1000).toLong())
        return if (serverUntil.isAfter(local)) serverUntil else local
    }

    private suspend fun handleCooldown(v: PageState, token: Int): Boolean {
        var fresh = v.rateLimitId > seenRateLimit
        if (!rateLimitPrimed) { rateLimitPrimed = true; seenRateLimit = v.rateLimitId; fresh = false }
        if (phase == "cooldown" && !ConversationIdentity.same(v.url, cooldownUrl)) {
            pause("限流等待期间对话已切换，已暂停；不会向其他对话重发。"); return true
        }
        val failedSubmission = fresh && attempt > 0 && (phase == "confirm" || phase == "observe")
        val submissionPhase = phase == "inspect" || phase == "fill" || phase == "prepare" ||
            phase == "send" || phase == "waitNew"
        val serverWait = submissionPhase && !v.conversation && !v.generating &&
            v.rateLimitRetryAt.isAfter(clock())
        if (fresh) seenRateLimit = v.rateLimitId
        if (failedSubmission || (fresh && phase == "cooldown") || serverWait) {
            rateLimitPendingSubmission = rateLimitPendingSubmission || failedSubmission
            retryPrepared = false; retryDraftFilled = false; retryPreparationSince = Instant.MIN
            if (phase != "cooldown") cooldownUrl = v.url
            move("cooldown")
            if (rateLimitRetries >= MAXIMUM_RATE_LIMIT_RETRIES) { exhaustRateLimit(); return true }
            val deadline = retryDeadline(clock(), rateLimitRetries, retryJitter(), v.rateLimitRetryAt)
            val current = retryAt
            if (current == null || deadline.isAfter(current)) retryAt = deadline
        }
        if (phase != "cooldown") return false
        if (v.rateLimitRetryAt.isAfter(clock()) &&
            (retryAt == null || v.rateLimitRetryAt.isAfter(retryAt))
        ) {
            retryAt = v.rateLimitRetryAt; retryPrepared = false; retryPreparationSince = Instant.MIN
        }
        if (v.termsPending || (!v.blocker.isNullOrEmpty() && !isRateLimitNotice(v.blocker))) {
            pause("限流重试已暂停：" + (if (v.termsPending) "网站条款尚未处理" else v.blocker) +
                "；请手动处理，不会自动换号。")
            return true
        }
        if (v.conversation || v.generating) {
            if (v.promptConfirmed && !v.failed && (v.generating || v.response || v.thinking)) {
                resetRateLimitRetry(); sawGeneration = v.generating; expectedUrl = v.url; move("observe")
                say("当前回答已开始，继续观察，不重复发送。")
            } else pause("限流重试前发现已有对话，但无法确认当前问题已开始回答，已暂停，避免重复提交。")
            return true
        }
        if (rateLimitRetries >= MAXIMUM_RATE_LIMIT_RETRIES) { exhaustRateLimit(); return true }
        val deadline = retryAt
        if (deadline != null && clock().isBefore(deadline)) {
            val text = if (rateLimitPendingSubmission)
                "HTTP 429 限流 · 等待 $cooldownSeconds 秒后尝试第 ${rateLimitRetries + 1}/5 次重试（已重试 $rateLimitRetries/5 次）；遵守网站等待时间，可暂停。"
            else
                "网站要求继续等待 $cooldownSeconds 秒，随后首次提交当前问题（不计入 5 次重试），可暂停。"
            if (message != text) say(text)
            return true
        }
        if (!v.main || !v.editor || v.failed || (!v.draft.isNullOrEmpty() && v.draft != prompt)) {
            pause("限流重试前页面或草稿与预期不符，已保留内容并暂停。"); return true
        }
        if (v.draft != prompt) {
            if (retryDraftFilled) { pause("限流重试的草稿填入结果尚未确认，已暂停，不重复填入。"); return true }
            say("限流等待结束，正在恢复同一条问题的草稿（不创建新对话）…")
            if (!cooldownActive(token)) return true
            retryDraftFilled = true; page.act("retryFill", prompt); return true
        }
        if (preparation != null && preparation.required && !retryPrepared) {
            if (retryPreparationSince == Instant.MIN) retryPreparationSince = clock()
            val prepared = preparation.prepare()
            if (!cooldownActive(token)) return true
            if (prepared) retryPrepared = true
            else if (secondsBetween(retryPreparationSince, clock()) >= 60)
                pause("限流重试前附件尚未就绪，已暂停，不会重复提交。")
            return true
        }
        if (preparation != null && !preparation.check()) {
            if (cooldownActive(token)) pause("限流重试前附件已改变，已暂停。")
            return true
        }
        if (!cooldownActive(token)) return true
        // 异步附件检查后必须重读；陈旧 DOM 绝不能授权一次发送。
        val latest = page.read(prompt) ?: return true
        if (!cooldownActive(token)) return true
        if (!latest.snapshotConsistent) return true
        if (latest.rateLimitId > seenRateLimit || latest.rateLimitRetryAt.isAfter(clock())) return true
        if (!ConversationIdentity.same(latest.url, cooldownUrl) || !latest.main || !latest.editor ||
            latest.conversation || latest.generating || latest.failed || latest.termsPending ||
            latest.draft != prompt || !latest.sendReady ||
            (!latest.blocker.isNullOrEmpty() && !isRateLimitNotice(latest.blocker))
        ) {
            pause("限流重试发送前页面状态发生变化，已暂停，未重复提交。"); return true
        }
        say(if (rateLimitPendingSubmission)
            "正在进行限流重试 ${rateLimitRetries + 1}/5：同一条问题，等待网页确认…"
        else "网站等待结束，准备首次提交当前问题（不计入重试次数）…")
        if (!cooldownActive(token)) return true
        if (rateLimitPendingSubmission) rateLimitRetries++ else attempt++
        rateLimitPendingSubmission = false; retryAt = null; retryPrepared = false
        sawGeneration = false; signature = null; expectedUrl = latest.url
        move("confirm")
        page.act("retrySend", prompt)
        return true
    }

    // ---- 手动收集的模型归属判定（四段式） ----------------------------------
    /** 绝不把上一轮缓存的 trace 安到本轮回答上。 */
    fun manualCollectionModel(state: PageState?, snapshot: ProbeSnapshot?): String {
        if (state == null || !ConversationIdentity.same(expectedUrl, state.url)) return UNIDENTIFIED
        if (!completedGenerationStamp.isNullOrEmpty() &&
            completedGenerationStamp == state.generationStamp && !lastModel.isNullOrEmpty()
        ) return lastModel!!
        if (!state.promptConfirmed) return UNIDENTIFIED
        return if (snapshot != null && snapshot.api && !snapshot.runId.isNullOrEmpty() &&
            snapshot.runId != baselineRunId && !snapshot.name.isNullOrBlank()
        ) snapshot.name else UNIDENTIFIED
    }

    fun manualCollectionExcluded(model: String?): Boolean =
        (if (hasPendingWork) runRetention else retentionPolicy).excludes(model)

    companion object {
        const val MAXIMUM_RATE_LIMIT_RETRIES = 5
        const val UNIDENTIFIED = "未识别"
        const val BLOCKER_VERIFICATION = "需要人机验证"

        private val TITLE_TIME: DateTimeFormatter =
            DateTimeFormatter.ofPattern("MM-dd HH:mm").withZone(ZoneId.systemDefault())

        /** <模型名> · MM-dd HH:mm；arena 侧上限 100 字符，只截断模型段。 */
        fun buildTitle(model: String?, at: Instant): String {
            var name = (model ?: "").trim()
            if (name.isEmpty()) name = UNIDENTIFIED
            val suffix = " · " + TITLE_TIME.format(at)
            var budget = 100 - suffix.length
            if (budget < 1) budget = 1
            if (name.length > budget) name = name.substring(0, budget)
            return name + suffix
        }

        private fun secondsBetween(from: Instant, to: Instant): Double =
            (to.toEpochMilli() - from.toEpochMilli()) / 1000.0
    }
}

private fun secondsBetween(from: Instant, to: Instant): Double =
    (to.toEpochMilli() - from.toEpochMilli()) / 1000.0
