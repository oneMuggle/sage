// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.TaskSettings.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/EnvironmentSettingsDialog.cs
// spec: docs/mcp-android-implementation-plan.md §5 ui/ 、§3.6、§4.1
package ai.arena.companion.app

import ai.arena.companion.R

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.VaultUnavailableException
import ai.arena.companion.automation.ModelRetentionCatalog
import ai.arena.companion.automation.ModelRetentionGroup
import ai.arena.companion.data.ArchiveStore
import ai.arena.companion.data.AttachmentGarbage
import ai.arena.companion.data.BoundAttachment
import ai.arena.companion.data.ObservedModelNames
import ai.arena.companion.data.TaskSettings
import ai.arena.companion.data.TaskSettingsStore
import ai.arena.companion.net.ProxyMode
import ai.arena.companion.net.ProxySettings
import ai.arena.companion.net.ProxySettingsStore
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import java.io.File
import java.util.Locale

/**
 * 设置：任务参数 + 代理 + 附件 + 模型取舍 + 账号。
 *
 * 一条贯穿的原则：**校验失败就不保存**。桌面端的 `ProxySettingsStore.Save` 也是先跑
 * `ProxyUri()` 再落盘——存下一份非法配置，下次启动时要么崩要么悄悄变直连，两种都不行。
 *
 * 界面由 `activity_settings.xml` 静态声明（MD3 卡片 + TextInputLayout），
 * 这里只负责取值、回填与校验；可见文案与控件排布以布局文件为准。
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var instanceDir: File
    private lateinit var tasks: TaskSettingsStore
    private lateinit var proxies: ProxySettingsStore
    private lateinit var vault: AccountVault

    private lateinit var prompt: TextInputEditText
    private lateinit var stepPause: TextInputEditText
    private lateinit var jitter: TextInputEditText
    private lateinit var roundLimit: TextInputEditText
    private lateinit var noProgress: TextInputEditText
    private lateinit var modelWait: TextInputEditText
    private lateinit var proxyModeGroup: MaterialButtonToggleGroup
    private lateinit var proxyHost: TextInputEditText
    private lateinit var proxyPort: TextInputEditText
    private lateinit var proxyUser: TextInputEditText
    private lateinit var proxyPass: TextInputEditText
    private lateinit var accountSummary: TextView
    private lateinit var attachmentSummary: TextView
    private lateinit var attachmentChips: ChipGroup
    private lateinit var retentionSummary: TextView
    private var excludedModels: MutableList<String> = mutableListOf()
    private var attachments: MutableList<BoundAttachment> = mutableListOf()

    /**
     * 附件通过 SAF 选取。安卓拿不到普通文件路径，必须先把内容流复制到缓存，
     * 再交给 `TaskSettingsStore.import` 做内容寻址与复制后重哈希校验。
     */
    private val pickAttachment = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri -> if (uri != null) importAttachment(uri) }

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        val instance = intent.getStringExtra(MainActivity.EXTRA_INSTANCE).orEmpty()
        instanceDir = (if (instance.isEmpty()) filesDir
        else File(File(filesDir, "instances"), instance)).also { it.mkdirs() }

        tasks = TaskSettingsStore(instanceDir)
        proxies = ProxySettingsStore(instanceDir)
        vault = AccountVault(instanceDir, KeystoreCipher())

        setContentView(R.layout.activity_settings)
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = if (instance.isEmpty()) "设置" else "设置 · $instance"
        toolbar.setNavigationOnClickListener { finish() }
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(findViewById<View>(R.id.content)),
            bottomBar = findViewById<View>(R.id.bottomBar),
        )

        prompt = findViewById(R.id.prompt)
        stepPause = findViewById(R.id.stepPause)
        jitter = findViewById(R.id.jitter)
        roundLimit = findViewById(R.id.roundLimit)
        noProgress = findViewById(R.id.noProgress)
        modelWait = findViewById(R.id.modelWait)
        proxyModeGroup = findViewById(R.id.proxyModeGroup)
        proxyHost = findViewById(R.id.proxyHost)
        proxyPort = findViewById(R.id.proxyPort)
        proxyUser = findViewById(R.id.proxyUser)
        proxyPass = findViewById(R.id.proxyPass)
        accountSummary = findViewById(R.id.accountSummary)
        attachmentSummary = findViewById(R.id.attachmentSummary)
        attachmentChips = findViewById(R.id.attachmentChips)
        retentionSummary = findViewById(R.id.retentionSummary)

        // 「遇到人机验证时暂停」在布局里已是选中且禁用：方案要求一律停下等人工，不给关。
        findViewById<View>(R.id.btnAddAttachment).setOnClickListener { pickAttachment.launch(arrayOf("*/*")) }
        findViewById<View>(R.id.btnClearAttachments).setOnClickListener { attachments.clear(); refreshAttachments() }
        findViewById<View>(R.id.btnCollectGarbage).setOnClickListener { promptCollect() }
        findViewById<View>(R.id.btnRetention).setOnClickListener { promptRetention() }
        findViewById<View>(R.id.btnAccount).setOnClickListener { promptAccountSetup() }
        findViewById<View>(R.id.btnSave).setOnClickListener { save() }
        proxyModeGroup.addOnButtonCheckedListener { _, _, _ -> refreshProxyFields() }

        load()
    }

    // ---- 代理方式：三选一按钮组 ↔ ProxyMode.wire ----

    private fun selectedProxyMode(): String = when (proxyModeGroup.checkedButtonId) {
        R.id.modeHttp -> ProxyMode.HTTP.wire
        R.id.modeSocks5 -> ProxyMode.SOCKS5.wire
        else -> ProxyMode.SYSTEM.wire
    }

    private fun checkProxyMode(mode: String) {
        val id = when (mode.trim().lowercase()) {
            ProxyMode.HTTP.wire -> R.id.modeHttp
            ProxyMode.SOCKS5.wire -> R.id.modeSocks5
            else -> R.id.modeSystem
        }
        proxyModeGroup.check(id)
        refreshProxyFields()
    }

    /**
     * 跟随系统时地址 / 端口 / 认证不参与校验（`ProxySettings.proxyUri()` 对 system 直接返回 null），
     * 所以置灰但保留已填内容，切回代理时不用重填；保存时仍原样写盘，与旧行为一致。
     */
    private fun refreshProxyFields() {
        val enabled = proxyModeGroup.checkedButtonId != R.id.modeSystem
        listOf(proxyHost, proxyPort, proxyUser, proxyPass).forEach { it.isEnabled = enabled }
    }

    private fun load() {
        val t = tasks.load()
        prompt.setText(t.prompt)
        stepPause.setText(t.stepPauseSeconds.toString())
        jitter.setText(t.stepPauseJitterSeconds.toString())
        roundLimit.setText(t.roundLimit.toString())
        noProgress.setText(t.maximumNoProgressSeconds.toString())
        modelWait.setText(t.modelWaitSeconds.toString())
        attachments = t.attachments.toMutableList()
        refreshAttachments()
        excludedModels = t.excludedModels.toMutableList()
        refreshRetention()

        // 代理配置读失败不能静默用默认值顶上——那等于悄悄变直连。
        try {
            val p = proxies.load()
            checkProxyMode(p.mode)
            proxyHost.setText(p.host)
            proxyPort.setText(if (p.port == 0) "" else p.port.toString())
            proxyUser.setText(p.username); proxyPass.setText(p.password)
        } catch (e: Exception) {
            checkProxyMode(ProxyMode.SYSTEM.wire)
            AlertDialog.Builder(this)
                .setTitle("代理配置无法读取")
                .setMessage("${e.message}\n\n已把方式重置为“跟随系统”，保存后才会生效。")
                .setPositiveButton("知道了", null)
                .show()
        }

        refreshAccount()
    }

    private fun refreshAttachments() {
        attachmentSummary.text = if (attachments.isEmpty()) "未绑定附件。"
        else "已绑定 ${attachments.size} 个附件，点击条目可查看完整哈希。"
        attachmentChips.removeAllViews()
        for (bound in attachments) {
            val chip = layoutInflater.inflate(R.layout.chip_attachment, attachmentChips, false) as Chip
            chip.text = "${bound.name} · ${formatBytes(bound.bytes)}"
            chip.setOnClickListener { toast("${bound.name}\nSHA-256 ${bound.sha256}") }
            chip.setOnCloseIconClickListener {
                // 只改内存里的列表，点「保存」才落盘；与「移除全部」同一条路径。
                attachments.removeAll { it.name == bound.name }
                refreshAttachments()
            }
            attachmentChips.addView(chip)
        }
        attachmentChips.visibility = if (attachments.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1L shl 20 -> String.format(Locale.ROOT, "%.1f MB", bytes / 1048576.0)
        bytes >= 1L shl 10 -> String.format(Locale.ROOT, "%.1f KB", bytes / 1024.0)
        else -> "$bytes B"
    }

    private fun refreshRetention() {
        retentionSummary.text = if (excludedModels.isEmpty()) "当前全部保留。"
        else "将归档 ${excludedModels.size} 个模型：\n" + excludedModels.joinToString("、")
    }

    /**
     * 模型目录来自已观察到的模型名（`withObserved`），而不是硬编码清单——
     * 硬编码会在 arena 上新模型时静默失效。没观察到任何模型时只能提示，
     * **不要自造一个猜测的列表**。
     */
    private fun promptRetention() {
        val observed = observedModels()
        if (observed.isEmpty()) {
            toast("还没有观察到任何模型名，先跑一轮或手工收集一次再来设置")
            return
        }
        val catalog = ModelRetentionCatalog(2, observed.map { ModelRetentionGroup(it, listOf(it)) })
        val names = catalog.names.toTypedArray()
        val checked = BooleanArray(names.size) { i -> excludedModels.any { it.equals(names[i], true) } }
        AlertDialog.Builder(this)
            .setTitle("选择要归档的模型")
            .setMultiChoiceItems(names, checked) { _, which, isChecked -> checked[which] = isChecked }
            .setPositiveButton("确定") { _, _ ->
                excludedModels = names.filterIndexed { i, _ -> checked[i] }.toMutableList()
                refreshRetention()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 见过的模型名 = 本地归档记录 ∪ model-observed-names.json（每轮完成时由 MainActivity 记录）。 */
    private fun observedModels(): List<String> {
        val store = ArchiveStore(File(instanceDir, "归档"))
        val cached = runCatching { ObservedModelNames(instanceDir).load() }.getOrDefault(emptyList())
        return ObservedModelNames.filter(cached, store.all().mapNotNull { it.model })
    }

    private fun importAttachment(uri: Uri) {
        val name = displayName(uri)
        val staging = File(cacheDir, "attach-import").apply { mkdirs() }
        val temp = File(staging, name)
        try {
            contentResolver.openInputStream(uri)?.use { input ->
                temp.outputStream().use { input.copyTo(it) }
            } ?: run { toast("无法读取所选文件"); return }
            val bound = tasks.import(temp)
            // 同名附件不允许重复（TaskSettingsStore.verify 会拒），这里先挡掉。
            if (attachments.any { it.name == bound.name }) { toast("已存在同名附件：${bound.name}"); return }
            attachments += bound
            refreshAttachments()
        } catch (e: Exception) {
            toast(e.message)
        } finally {
            temp.delete()
        }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (i >= 0 && c.moveToFirst()) return c.getString(i)
        }
        return uri.lastPathSegment?.substringAfterLast('/') ?: "attachment"
    }

    /** 先 dryRun 告知将清理多少，由用户确认后才真删。 */
    private fun promptCollect() {
        val live = tasks.load().also { it.attachments = attachments }
        val (count, bytes) = AttachmentGarbage.collect(instanceDir, listOf(live), dryRun = true)
        if (count == 0) { toast("没有可清理的附件文件"); return }
        AlertDialog.Builder(this)
            .setTitle("清理无引用的附件")
            .setMessage("将删除 $count 个不再被任何设置引用的附件目录，释放约 ${bytes / 1024} KB。")
            .setPositiveButton("清理") { _, _ ->
                val (done, freed) = AttachmentGarbage.collect(instanceDir, listOf(live))
                toast("已清理 $done 项，释放 ${freed / 1024} KB")
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun refreshAccount() {
        accountSummary.text = try {
            val a = vault.load()
            when {
                a.password.isEmpty() -> "尚未设置昵称和密码。"
                else -> "昵称：${a.name.ifEmpty { "（未填）" }} · 密码已加密保存" +
                    (a.email.takeUnless { it.isEmpty() }?.let { " · 邮箱 $it" } ?: "")
            }
        } catch (e: VaultUnavailableException) {
            // 保险库锁定：明确告知，且此时任何写入都会被拒绝，旧数据不会被覆盖。
            "账号保险库当前无法解开：${e.message}"
        }
    }

    private fun promptAccountSetup() {
        val existing = runCatching { vault.load() }.getOrNull()
        val hasSaved = existing?.password?.isNotEmpty() == true
        val form = layoutInflater.inflate(R.layout.dialog_account_setup, null)
        val nickname = form.findViewById<TextInputEditText>(R.id.nickname)
        val pw = form.findViewById<TextInputEditText>(R.id.password)
        val confirm = form.findViewById<TextInputEditText>(R.id.confirm)
        nickname.setText(existing?.name ?: "")
        form.findViewById<TextInputLayout>(R.id.passwordLayout).hint =
            if (hasSaved) "新密码（留空则保留原密码）" else "密码"

        AlertDialog.Builder(this)
            .setTitle("昵称和密码设置")
            .setMessage("密码至少 8 位，包含一个大写字母和一个符号。仅在本机加密保存。")
            .setView(form)
            .setPositiveButton("保存") { _, _ ->
                val error = vault.validateSetup(
                    nickname.str(), pw.str(), confirm.str(), hasSaved)
                if (error.isNotEmpty()) { toast(error); return@setPositiveButton }
                val current = existing ?: AccountData()
                val updated = vault.applySetup(
                    current, nickname.str(), pw.str(), hasSaved)
                runCatching {
                    if (vault.locked) promptVaultReset(updated) else vault.save(updated)
                }.onFailure { toast(it.message) }
                refreshAccount()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 保险库锁定时的唯一出口：必须由用户明确确认"丢弃旧数据"。 */
    private fun promptVaultReset(updated: AccountData) {
        AlertDialog.Builder(this)
            .setTitle("需要确认")
            .setMessage("现有账号数据无法解开（可能是更换了设备或清除了凭据）。" +
                "继续保存会覆盖它，且旧数据无法找回。")
            .setPositiveButton("覆盖并保存") { _, _ ->
                runCatching { vault.resetAfterUserConfirmation(updated) }
                    .onFailure { toast(it.message) }
                refreshAccount()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun save() {
        // 先把代理校验跑完再动任何文件：任一非法就整体不保存。
        val proxy = ProxySettings(
            mode = selectedProxyMode(),
            host = proxyHost.str().trim().ifEmpty { "127.0.0.1" },
            port = proxyPort.str().trim().toIntOrNull() ?: 0,
            username = proxyUser.str(),
            password = proxyPass.str(),
        )
        try {
            proxy.proxyUri()
        } catch (e: IllegalArgumentException) {
            toast(e.message); return
        }

        // 运行参数：非数字或越界一律不保存（与代理校验同一原则）。
        val limit = roundLimit.str().trim().toIntOrNull()
        if (limit == null || limit < 0) { toast("轮次上限须为不小于 0 的整数（0 表示不限）"); return }
        val noProgressSeconds = noProgress.str().trim().toIntOrNull()
        if (noProgressSeconds == null || noProgressSeconds < TaskSettings.MIN_NO_PROGRESS_SECONDS) {
            toast("无进展上限须为不小于 ${TaskSettings.MIN_NO_PROGRESS_SECONDS} 的整数秒"); return
        }
        val waitSeconds = modelWait.str().trim().toIntOrNull()
        if (waitSeconds == null || waitSeconds < TaskSettings.MIN_MODEL_WAIT_SECONDS) {
            toast("模型名等待须为不小于 ${TaskSettings.MIN_MODEL_WAIT_SECONDS} 的整数秒"); return
        }

        val t = tasks.load().apply {
            prompt = this@SettingsActivity.prompt.str()
            stepPauseSeconds = stepPause.str().toDoubleOrNull() ?: stepPauseSeconds
            stepPauseJitterSeconds = jitter.str().toDoubleOrNull() ?: stepPauseJitterSeconds
            roundLimit = limit
            maximumNoProgressSeconds = noProgressSeconds
            modelWaitSeconds = waitSeconds
            pauseOnCaptcha = true
            attachments = this@SettingsActivity.attachments
            excludedModels = this@SettingsActivity.excludedModels
        }
        runCatching {
            tasks.save(t)
            proxies.save(proxy)
        }.onSuccess { toast("已保存"); finish() }.onFailure { toast(it.message) }
    }

    /** `TextInputEditText.getText()` 标注为可空，统一收口成非空字符串。 */
    private fun TextInputEditText.str(): String = text?.toString().orEmpty()

    private fun toast(message: String?) {
        Toast.makeText(this, message ?: "操作失败", Toast.LENGTH_LONG).show()
    }
}
