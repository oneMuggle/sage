// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AttachmentUpload.cs
// spec: docs/mcp-android-prompt-confirm-timeout-20260921.md §6 B35
package ai.arena.companion.automation

import ai.arena.companion.data.BoundAttachment
import ai.arena.companion.data.TaskSettingsStore
import ai.arena.companion.identity.ConversationIdentity

/** `PageBridge.attachmentEntry()` 的返回：入口数量、是否有可触摸的触发器及其视口坐标（CSS px）。 */
data class AttachmentEntry(
    val count: Int = 0,
    val reason: String? = null,
    val trigger: Boolean = false,
    val label: String? = null,
    val x: Double = 0.0,
    val y: Double = 0.0,
    val width: Double = 0.0,
    val height: Double = 0.0,
    /** 视觉视口相对布局视口的偏移与缩放（CSS px / 倍数）、设备像素比；原生侧换算触摸坐标用。 */
    val offsetX: Double = 0.0,
    val offsetY: Double = 0.0,
    val scale: Double = 1.0,
    val dpr: Double = 1.0,
)

/**
 * 页面侧附件能力，由 app 层用 WebView 实现。
 * - [ready]：`attachmentsReady(names)`，一次 evaluate 返回布尔。
 * - [entry]：`attachmentEntry()`，定位唯一 input[type=file] 并给出可触摸入口。
 * - [deliver]：把绑定文件交给页面。安卓上 = 「原生侧准备好本轮文件 → 派发真实触摸 → 页面打开
 *   文件选择 → WebChromeClient.onShowFileChooser 直接回填这些文件」。返回 false 表示这轮没有交付成功
 *   （选择器没被触发 / 被别的页面元素抢走），调用方按「未就绪」处理，绝不重复投递。
 */
interface AttachmentPage {
    suspend fun ready(names: List<String>): Boolean
    suspend fun entry(): AttachmentEntry?
    suspend fun deliver(entry: AttachmentEntry, files: List<BoundAttachment>): Boolean
}

/**
 * 对 C# `AttachmentUpload : IRequestPreparation`，语义 1:1：
 * - [required]：有绑定附件才需要准备；
 * - [check]：`Required` 时先确认仍在 arena.ai/agent，再问页面 attachmentsReady；
 * - [prepare]：先 check，未就绪且本轮尚未投递过才投递一次（`submitted` 守卫），返回 false 让阶段机下轮再查；
 * - [beginRound]：每轮开始清 `submitted`。
 *
 * 与桌面端的唯一差异是交付方式：桌面端用 CDP `DOM.setFileInputFiles` 直接塞文件；安卓没有 CDP，
 * 只能由页面自己打开文件选择器、再由 app 层 `onShowFileChooser` 回填。因此 [prepare] 在投递前多做一次
 * `attachmentEntry()` 前置校验（对齐桌面端 Stage 的「唯一可用入口」检查）。
 */
class AttachmentUpload(
    private val page: AttachmentPage,
    private val currentUrl: () -> String?,
    private val verify: (Iterable<BoundAttachment>) -> Unit = TaskSettingsStore::verify,
) : RequestPreparation {

    private var files: List<BoundAttachment> = emptyList()
    private var submitted = false

    /** 上一次投递的结果说明；仅供状态栏 / 诊断，不参与判定。 */
    var lastNote: String? = null
        private set

    override val required: Boolean get() = files.isNotEmpty()

    val names: List<String> get() = files.map { it.name }

    /** 对 Configure：换清单前三项全查（存在 / 字节数 / 哈希），并重置本轮状态。 */
    fun configure(files: Iterable<BoundAttachment>) {
        val list = files.toList()
        verify(list)
        this.files = list
        beginRound()
    }

    override fun beginRound() {
        submitted = false
    }

    override suspend fun check(): Boolean {
        if (required) ensureArena()
        return page.ready(names)
    }

    override suspend fun prepare(): Boolean {
        if (check()) return true
        if (!submitted) {
            submitted = true
            stage()
        }
        return false
    }

    /** 对 Stage：只在空白新对话、唯一 input[type=file] 且找得到可触摸入口时投递一次；否则抛错让阶段机暂停。 */
    suspend fun stage() {
        ensureArena()
        verify(files)
        if (!required) return
        val entry = page.entry() ?: throw IllegalStateException("附件入口读取失败")
        if (entry.count != 1) throw IllegalStateException("没有找到唯一可用的附件上传入口")
        if (!entry.trigger) throw IllegalStateException("附件入口无法触发：页面没有可点击的附件按钮")
        val delivered = page.deliver(entry, files)
        lastNote = if (delivered) "已把 ${files.size} 个附件交给页面，等待网页确认" else "页面没有打开文件选择，本轮不再重试"
        if (!delivered) throw IllegalStateException("附件入口已变化")
    }

    private fun ensureArena() {
        val route = ConversationIdentity.route(currentUrl())
        if (route == null || !(route == "https://arena.ai/agent" || route.startsWith("https://arena.ai/agent/")))
            throw IllegalStateException("仅可向 Arena Agent 页面上传绑定附件")
    }
}
