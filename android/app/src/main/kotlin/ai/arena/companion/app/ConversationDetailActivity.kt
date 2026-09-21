// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/SavedConversationWindow.cs
// spec: docs/mcp-android-implementation-plan.md §5 ui/ ConversationScreen
package ai.arena.companion.app

import ai.arena.companion.R

import ai.arena.companion.data.ArchiveStore
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import java.io.File

class ConversationDetailActivity : AppCompatActivity() {

    private var instance: String = ""
    private var entryId: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_conversation_detail)
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(findViewById<View>(R.id.scroller)),
        )

        instance = intent.getStringExtra(EXTRA_INSTANCE).orEmpty()
        entryId = intent.getStringExtra(EXTRA_ENTRY_ID).orEmpty()
        if (entryId.isEmpty()) { finish(); return }

        val store = ArchiveStore(archiveRoot())
        val entry = store.all().firstOrNull { it.id == entryId }
        if (entry == null) {
            Toast.makeText(this, "记录不存在或已删除", Toast.LENGTH_LONG).show()
            finish(); return
        }
        supportActionBar?.title = entry.title?.takeUnless { it.isBlank() } ?: "会话详情"

        findViewById<TextView>(R.id.title).text = entry.title?.takeUnless { it.isBlank() } ?: "（无标题）"
        findViewById<TextView>(R.id.model).text = entry.model ?: "未识别"
        findViewById<TextView>(R.id.url).text = entry.url
        findViewById<TextView>(R.id.status).text = buildString {
            entry.email?.takeUnless { it.isBlank() }?.let { append("账号：").append(it).append("\n") }
            entry.prompt?.takeUnless { it.isBlank() }?.let { append("提示词：").append(it).append("\n") }
            entry.collectedAt?.let { append("收集时间：").append(it).append("\n") }
            entry.modelFolder?.let { append("归档目录：").append(it).append("\n") }
            entry.shortcut?.let { append("入口：").append(it).append("\n") }
            if (entry.renamed) append("已重命名\n")
            entry.renameError?.takeUnless { it.isBlank() }?.let { append("重命名未确认：").append(it).append("\n") }
            entry.exportedAt?.let { append("已导出到：").append(entry.exportedFolder).append(" @ ").append(it) }
            if (isEmpty()) append("暂无更多信息")
        }
        findViewById<TextView>(R.id.content).text = "提示词：\n" + (entry.prompt ?: "—") + "\n\n— 完整归档内容请在文件管理器中查看 —"

        // Add dynamic buttons programmatically below content card if needed, but layout already has toolbar; we reuse existing buttons via dialog actions
        // Long press on toolbar for actions
        toolbar.setOnMenuItemClickListener { false }
        // Add bottom actions via dialog on click
        findViewById<TextView>(R.id.content).setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle(entry.title ?: "会话")
                .setItems(arrayOf("在浏览器打开", "用本应用打开", "删除本地记录")) { _, which ->
                    when (which) {
                        0 -> runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(entry.url))) }.onFailure { toast("无法打开该地址") }
                        1 -> {
                            val link = store.deepLink?.invoke(entry.url) ?: "arena-companion://open?instance=$instance&url=${Uri.encode(entry.url)}"
                            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link))) }.onFailure { toast("无法打开 deep link") }
                        }
                        2 -> confirmDelete(store, entryId)
                    }
                }.show()
        }
    }

    private fun archiveRoot(): File {
        val instanceDir = if (instance.isEmpty()) filesDir else File(File(filesDir, "instances"), instance)
        val configured = File(instanceDir, "archive-destination.txt").takeIf { it.isFile }?.readText()?.trim()?.takeUnless { it.isBlank() }
        return when {
            configured == null -> File(instanceDir, "归档")
            File(configured).isAbsolute -> File(configured)
            else -> File(instanceDir, configured)
        }
    }

    private fun confirmDelete(store: ArchiveStore, id: String) {
        AlertDialog.Builder(this)
            .setTitle("删除记录")
            .setMessage("只删除本地归档记录与入口文件。Arena 网站上的归档动作不可逆，无法撤销。")
            .setPositiveButton("删除") { _, _ ->
                runCatching { store.delete(id) }
                    .onSuccess { toast("已删除"); finish() }
                    .onFailure { toast(it.message) }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun toast(msg: String?) { Toast.makeText(this, msg ?: "操作失败", Toast.LENGTH_LONG).show() }

    companion object {
        const val EXTRA_INSTANCE = "extra_instance"
        const val EXTRA_ENTRY_ID = "extra_entry_id"
    }
}
