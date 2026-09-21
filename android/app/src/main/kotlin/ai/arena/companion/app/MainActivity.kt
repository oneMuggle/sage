// spec: docs/mcp-android-implementation-plan.md §5 ui/ 、§7 第 2、4、5 条 / §3.1 rename 阶段
package ai.arena.companion.app

import ai.arena.companion.R

import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.AuthFlow
import ai.arena.companion.account.LoginTaskStart
import ai.arena.companion.automation.ConversationRenamer
import ai.arena.companion.automation.ManualCollection
import ai.arena.companion.automation.ModelRetentionCatalog
import ai.arena.companion.automation.RetryController
import ai.arena.companion.automation.WebsiteArchiver
import ai.arena.companion.data.ArchiveEntry
import ai.arena.companion.data.ArchiveStore
import ai.arena.companion.data.JobStateStore
import ai.arena.companion.data.ObservedModelNames
import ai.arena.companion.data.RecoveryDecision
import ai.arena.companion.data.TaskSettings
import ai.arena.companion.data.TaskSettingsStore
import ai.arena.companion.net.ProxySettingsStore
import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.WindowManager
import android.webkit.WebView
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.appbar.MaterialToolbar
import java.io.File
import java.time.format.DateTimeFormatter
import java.time.ZoneId
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var authWebView: WebView
    private lateinit var status: TextView
    private lateinit var queueStatus: TextView
    private lateinit var probe: ProbeBridge
    private var instance: String = ""
    private var sessionToken: Long? = null
    private lateinit var page: WebViewArenaPage
    private lateinit var authPages: WebViewAuthPages
    private lateinit var probeReader: WebViewProbeReader
    private lateinit var renameExecutor: WebViewRenameExecutor
    private lateinit var archiveBridge: WebViewArchiveBridge
    private var controller: RetryController? = null
    private var authFlow: AuthFlow? = null
    private var loginTaskStart: LoginTaskStart? = null
    private var ticker: Job? = null
    private var authTicker: Job? = null
    private var lastAuthLogKey: String? = null
    private lateinit var startButton: Button
    private lateinit var collectButton: Button
    private lateinit var queueButton: Button

    /** 启动检查要等 WebView 应用代理（阻塞），不能占用主线程；结果再回主线程续跑。 */
    private val startExecutor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "session-launch").apply { isDaemon = true }
    }
    private var launching = false

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        instance = intent.getStringExtra(EXTRA_INSTANCE).orEmpty()
        setContentView(R.layout.activity_main)

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = if (instance.isEmpty()) "会话" else instance
        toolbar.setNavigationOnClickListener { finish() }
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(findViewById<View>(R.id.content)),
        )

        status = findViewById(R.id.status)
        queueStatus = findViewById(R.id.queueStatus)
        webView = findViewById(R.id.webView)
        startButton = findViewById(R.id.btnStart)
        collectButton = findViewById(R.id.btnCollect)
        queueButton = findViewById(R.id.btnQueue)

        startButton.setOnClickListener { toggleRun() }
        collectButton.setOnClickListener { collectManually() }
        queueButton.setOnClickListener { startActivity(Intent(this, QueueStatusActivity::class.java)) }

        WebView.setWebContentsDebuggingEnabled(true)
        authWebView = WebView(this).apply {
            visibility = View.INVISIBLE
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            alpha = 0f
        }
        findViewById<LinearLayout>(R.id.content).addView(authWebView, LinearLayout.LayoutParams(1, 1))
        configureWebView(webView, "Arena")
        configureWebView(authWebView, "Auth")

        probe = ProbeBridge(assets)
        probe.install(webView)
        if (!probe.injected) {
            status.text = "探针未加载：${probe.lastError ?: "未知原因"}"
        }

        if (instance.isNotEmpty() && !bindProfile()) return

        page = WebViewArenaPage(webView)
        authPages = WebViewAuthPages(webView, authWebView, assets)
        probeReader = WebViewProbeReader(webView)
        renameExecutor = WebViewRenameExecutor(webView)
        archiveBridge = WebViewArchiveBridge(webView)

        webView.postDelayed({ runCatching { BatteryOptimizationHelper.promptIfNeeded(this) } }, 2000)

        offerRecovery()
        val targetUrl = intent.getStringExtra(EXTRA_URL)
        if (!targetUrl.isNullOrBlank()) {
            webView.loadUrl(targetUrl)
        } else {
            // ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.cs:L221
            //      桌面端启动后就停在 https://arena.ai/agent。安卓端原先打开的是营销落地页
            //      "/"，而整个状态机（ConversationIdentity.route / ArenaPage.isAllowed /
            //      newLinks / sendReady）只认 /agent 路由：停在 "/" 时 route() 返回 null，
            //      tick() 里的 `if (!page.isAllowed(v.url)) return` 每轮静默退出 ——
            //      表现就是「点开始后一直停在『正在检查页面』」，而且不会走到任何超时暂停。
            webView.loadUrl("https://arena.ai/agent")
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "设置").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER)
        menu.add(0, 2, 0, "归档").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER)
        menu.add(0, 3, 0, "排队状态").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER)
        menu.add(0, 4, 0, "电池优化说明").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> startActivity(Intent(this, SettingsActivity::class.java).putExtra(EXTRA_INSTANCE, instance))
            2 -> startActivity(Intent(this, GalleryActivity::class.java).putExtra(EXTRA_INSTANCE, instance))
            3 -> startActivity(Intent(this, QueueStatusActivity::class.java))
            4 -> AlertDialog.Builder(this).setTitle("电池优化").setMessage(BatteryOptimizationHelper.romHint()).setPositiveButton("知道了", null).show()
            android.R.id.home -> finish()
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    private fun instanceDir(): File =
        (if (instance.isEmpty()) filesDir else File(File(filesDir, "instances"), instance))
            .also { it.mkdirs() }

    private fun configureWebView(view: WebView, tag: String) {
        view.webViewClient = object : android.webkit.WebViewClient() {
            override fun onPageFinished(v: WebView?, url: String?) {
                super.onPageFinished(v, url)
                android.util.Log.i("MainActivity", "$tag WebView page finished: $url")
            }
        }
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = true
    }

    private fun toggleRun() {
        val currentAuth = authFlow
        if (currentAuth != null && controller == null) {
            if (currentAuth.running || currentAuth.waitingForVerification) {
                cancelAuth("已手动停止自动登录")
                return
            }
            authFlow = null
            loginTaskStart = null
        }

        val current = controller
        if (current != null && current.running) {
            current.pause("已手动暂停；不会自动重发已提交的问题")
            refreshStatus()
            return
        }
        if (current != null) {
            runCatching { current.resume() }.onFailure { toast(it.message) }
            refreshStatus()
            return
        }

        val settings = runCatching { TaskSettingsStore(instanceDir()).load() }
            .getOrElse { toast(it.message); return }
        val proxy = runCatching { ProxySettingsStore(instanceDir()).load() }
            .getOrElse { toast("代理配置无法读取，已阻止启动：${it.message}"); return }

        if (launching) {
            toast("正在做启动检查，请稍候…")
            return
        }
        // 启动检查要先抢活动权、再验代理，而验代理会阻塞等 WebView 应用进程级 override；
        // 在主线程上等，会把 override 回调饿死（历史 bug：必然 10 秒超时）。所以挪到后台线程，
        // 结果回主线程续跑（WebView 相关的步骤只能在主线程做）。
        launching = true
        startButton.isEnabled = false
        val target = instance.ifEmpty { "默认" }
        startExecutor.execute {
            val outcome = runCatching { AppState.launcher.launch(target, proxy) }
                .getOrElse { LaunchOutcome.Blocked("启动前检查失败：${it.message}") }
            mainExecutor.execute {
                launching = false
                startButton.isEnabled = true
                onLaunched(outcome, settings)
            }
        }
    }

    /** [toggleRun] 的续跑段：启动检查的结果回到主线程后，才开始动 WebView。 */
    private fun onLaunched(outcome: LaunchOutcome, settings: TaskSettings) {
        when (outcome) {
            is LaunchOutcome.Queued -> {
                toast("「${outcome.holder}」正在运行，本实例排在第 ${outcome.position} 位。")
                refreshQueueStatus()
                return
            }
            is LaunchOutcome.Blocked -> {
                AlertDialog.Builder(this)
                    .setTitle("已阻止启动")
                    .setMessage(outcome.reason)
                    .setPositiveButton("知道了", null)
                    .show()
                return
            }
            is LaunchOutcome.Ready -> sessionToken = outcome.token
        }

        startAuthThenAutomation(settings)
    }

    private fun startAuthThenAutomation(settings: TaskSettings) {
        val vault = AccountVault(instanceDir(), KeystoreCipher())
        val flow = AuthFlow(authPages, vault)
        flow.onChanged = { refreshStatus() }
        authFlow = flow
        loginTaskStart = LoginTaskStart(pending = true)
        try {
            android.util.Log.i("AuthFlow", "starting automatic login for instance=$instance")
            flow.start()
        } catch (e: Exception) {
            authFlow = null
            loginTaskStart = null
            releaseSession()
            AlertDialog.Builder(this)
                .setTitle("无法自动登录")
                .setMessage(e.message ?: e.toString())
                .setPositiveButton("去设置") { _, _ ->
                    startActivity(Intent(this, SettingsActivity::class.java).putExtra(EXTRA_INSTANCE, instance))
                }
                .setNegativeButton("取消", null)
                .show()
            refreshStatus()
            return
        }
        keepScreenOn(true)
        startAuthTicking(flow, settings)
        refreshStatus()
    }

    private fun startAutomation(settings: TaskSettings) {
        authFlow = null
        loginTaskStart = null
        android.util.Log.i("MainActivity", "Starting automation after login for instance=$instance promptLength=${settings.prompt.length}")
        val archive = ArchiveStore(File(instanceDir(), "归档"))
        val observed = ObservedModelNames(instanceDir())
        val renamer = ConversationRenamer(
            currentUrl = { webView.url },
            executor = renameExecutor,
            clock = { java.time.Instant.now() },
            delay = { ms -> delay(ms) },
        )
        // ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.cs:L181 —— 未勾选保留的模型只移入网站归档。
        val archiver = WebsiteArchiver(
            step = archiveBridge::step,
            currentUrl = { webView.url },
            isAllowed = page::isAllowed,
            delay = { ms -> delay(ms) },
        )
        val c = RetryController(page, probeReader, renamer).apply {
            stepPauseSeconds = settings.stepPauseSeconds
            stepPauseJitterSeconds = settings.stepPauseJitterSeconds
            maximumNoProgressSeconds = settings.maximumNoProgressSeconds
            modelWaitSeconds = settings.modelWaitSeconds
            // ref: MainForm.TaskSettings.cs ApplyTaskSettings —— 目录 = 本地归档见过的模型 ∪ 观察缓存；未知模型默认保留。
            retentionPolicy = retentionCatalog(archive, observed).policy(settings.excludedModels)
            archiveSink = { url, model, title -> saveArchive(archive, url, model, title, settings.prompt) }
            websiteArchive = { url, stamp, active -> archiver.archive(url, settings.prompt, stamp, active) }
            onRoundCompleted = { model, _ -> runCatching { observed.record(model) } }
        }
        controller = c
        runCatching { c.start(settings.prompt, settings.roundLimit) }
            .onFailure {
                toast(it.message)
                controller = null
                keepScreenOn(false)
                releaseSession()
                return
            }
        keepScreenOn(true)
        startTicking(c)
        refreshStatus()
    }

    /** 保留策略目录：本地归档里出现过的模型名 ∪ model-observed-names.json；与 SettingsActivity.observedModels() 同源。 */
    private fun retentionCatalog(archive: ArchiveStore, observed: ObservedModelNames): ModelRetentionCatalog {
        val names = archive.all().mapNotNull { it.model } + observed.load()
        return ModelRetentionCatalog(2, emptyList()).withObserved(names)
    }

    private fun saveArchive(store: ArchiveStore, url: String?, model: String?,
                            title: String?, prompt: String) {
        if (url.isNullOrBlank()) return
        val existing = store.all().firstOrNull { it.url == url }
        val entry = if (existing != null) {
            val nextRound = (existing.modelHistory.maxOfOrNull { it.round } ?: 0) + 1
            existing.copy(title = title ?: existing.title, prompt = prompt)
                .recordRound(nextRound, model ?: "未识别", ts = System.currentTimeMillis())
        } else {
            val initial = ArchiveEntry(
                id = java.util.UUID.randomUUID().toString(),
                title = title, model = model, url = url,
                profile = instance, accountId = instance, prompt = prompt,
                collectedAt = STAMP.format(java.time.Instant.now().atZone(ZoneId.systemDefault())),
            )
            if (model != null) {
                initial.recordRound(1, model, ts = System.currentTimeMillis())
            } else {
                initial
            }
        }
        store.save(entry)
    }

    private fun startAuthTicking(flow: AuthFlow, settings: TaskSettings) {
        authTicker?.cancel()
        authTicker = lifecycleScope.launch {
            while (true) {
                try {
                    flow.tick()
                } catch (e: Exception) {
                    flow.stop("自动登录循环异常：${e.message}")
                }
                refreshStatus()
                val authLogKey = "${flow.running}|${flow.waitingForVerification}|${flow.phase}|${flow.message}"
                if (authLogKey != lastAuthLogKey) {
                    android.util.Log.i("AuthFlow", "phase=${flow.phase} running=${flow.running} waiting=${flow.waitingForVerification} message=${flow.message}")
                    lastAuthLogKey = authLogKey
                }
                if (loginTaskStart?.take(flow.running, flow.phase) == true) {
                    android.util.Log.i("LoginTaskStart", "released automation after login: running=${flow.running} phase=${flow.phase}")
                    startAutomation(settings)
                    break
                }
                if (!flow.running && !flow.waitingForVerification) {
                    keepScreenOn(false)
                    releaseSession()
                    break
                }
                delay(1000)
            }
        }
    }

    private fun cancelAuth(reason: String) {
        authFlow?.stop(reason)
        authTicker?.cancel()
        authTicker = null
        loginTaskStart = null
        keepScreenOn(false)
        releaseSession()
        refreshStatus()
    }

    private fun releaseSession() {
        sessionToken?.let { AppState.launcher.release(it) }
        sessionToken = null
        refreshQueueStatus()
    }

    private fun startTicking(c: RetryController) {
        ticker?.cancel()
        ticker = lifecycleScope.launch {
            while (true) {
                try {
                    c.tick()
                } catch (e: Exception) {
                    c.pause("自动化循环异常：${e.message}")
                }
                refreshStatus()
                if (!c.running && !c.hasPendingWork) { keepScreenOn(false); releaseSession(); break }
                delay(1000)
            }
        }
    }

    private fun refreshQueueStatus() {
        val holder = AppState.launcher.holder()
        val q = AppState.launcher.queue()
        queueStatus.text = if (holder == null) {
            if (q.isEmpty()) "" else "队列: ${q.joinToString(", ")}"
        } else {
            val secs = AppState.launcher.gate.heldForMillis() / 1000
            "活动: $holder (${secs}s) · 队列: ${if (q.isEmpty()) "无" else q.joinToString(", ")}"
        }
    }

    private fun refreshStatus() {
        refreshQueueStatus()
        val c = controller
        val auth = authFlow
        startButton.text = when {
            auth != null && controller == null && (auth.running || auth.waitingForVerification) -> "停止登录"
            auth != null && controller == null -> "重新登录"
            c == null -> "开始"
            c.running -> "暂停"
            else -> "继续"
        }
        status.text = when {
            auth != null && controller == null -> buildString {
                append("登录 · ").append(auth.phase)
                if (!auth.running && auth.waitingForVerification) append(" · 等待人工验证")
                else if (!auth.running) append(" · 已暂停")
                append("\n").append(auth.message)
            }
            c == null -> if (probe.injected) "就绪" else "探针未加载：${probe.lastError ?: "未知原因"}"
            else -> buildString {
                append("第 ").append(c.rounds + 1).append(" 轮 · ").append(c.phase)
                if (!c.running) append(" · 已暂停")
                append("\n").append(c.message)
            }
        }
    }

    private fun collectManually() {
        lifecycleScope.launch {
            try {
                val result = ManualCollection.read(
                    read = { page.read(null) },
                    probe = { probeReader.read() },
                    isActive = { !isFinishing },
                    delay = { ms -> delay(ms.toLong()) },
                )
                val store = ArchiveStore(File(instanceDir(), "归档"))
                saveArchive(store, result.state.url, result.probe.name, null,
                    TaskSettingsStore(instanceDir()).load().prompt)
                toast("已收集：${result.probe.name ?: "未识别"}")
            } catch (e: Exception) {
                toast(e.message)
            }
        }
    }

    private fun toast(message: String?) {
        Toast.makeText(this, message ?: "操作失败", Toast.LENGTH_LONG).show()
    }

    private fun bindProfile(): Boolean {
        val onlyInstance = java.io.File(filesDir, "instances")
            .listFiles { f -> f.isDirectory && !f.name.startsWith(".") }
            ?.size?.let { it <= 1 } ?: true
        return try {
            ProfileManager.attach(webView, instance, onlyInstance)
            ProfileManager.attach(authWebView, instance, onlyInstance)
            true
        } catch (e: ProfileIsolationUnavailableException) {
            AlertDialog.Builder(this)
                .setTitle("无法隔离登录态")
                .setMessage(e.message)
                .setCancelable(false)
                .setPositiveButton("返回") { _, _ -> finish() }
                .show()
            false
        }
    }

    override fun onDestroy() {
        ticker?.cancel()
        authTicker?.cancel()
        startExecutor.shutdownNow()
        controller?.takeIf { it.running }?.pause("界面已关闭；不会自动重发已提交的问题")
        authFlow?.takeIf { it.running || it.waitingForVerification }?.stop("界面已关闭，自动登录已停止")
        sessionToken?.let { AppState.launcher.release(it) }
        authWebView.destroy()
        super.onDestroy()
    }

    private fun offerRecovery() {
        val store = JobStateStore(filesDir)
        when (val decision = store.decide()) {
            is RecoveryDecision.Interrupted -> AlertDialog.Builder(this)
                .setTitle("上次任务被中断")
                .setMessage(decision.reason)
                .setPositiveButton(if (decision.canContinue) "保持暂停" else "重新开始") { _, _ -> }
                .setNegativeButton("清除记录") { _, _ -> store.clear() }
                .setCancelable(false)
                .show()
            is RecoveryDecision.Unusable -> AlertDialog.Builder(this)
                .setTitle("无法恢复上次任务")
                .setMessage(decision.reason)
                .setPositiveButton("知道了") { _, _ -> store.clear() }
                .show()
            else -> Unit
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val newInst = intent.getStringExtra(EXTRA_INSTANCE).orEmpty()
        val newUrl = intent.getStringExtra(EXTRA_URL)
        if (newInst.isNotEmpty() && newInst != instance) {
            instance = newInst
            bindProfile()
            supportActionBar?.title = instance
        }
        if (!newUrl.isNullOrBlank()) {
            webView.loadUrl(newUrl)
        }
    }

    fun keepScreenOn(on: Boolean) {
        if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    companion object {
        const val EXTRA_INSTANCE = "instance"
        const val EXTRA_URL = "url"
        private val STAMP: DateTimeFormatter =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
    }
}
