// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/GalleryWindow.cs
// spec: docs/mcp-android-implementation-plan.md §5 ui/
package ai.arena.companion.app

import ai.arena.companion.R

import ai.arena.companion.data.ArchiveEntry
import ai.arena.companion.data.ArchiveStore
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import java.io.File

class GalleryActivity : AppCompatActivity() {

    private lateinit var store: ArchiveStore
    private lateinit var recycler: RecyclerView
    private lateinit var emptyState: View
    private lateinit var header: TextView
    private lateinit var filterChips: ChipGroup
    private var rows: List<ArchiveEntry> = emptyList()
    private var filtered: List<ArchiveEntry> = emptyList()
    private var instance: String = ""
    private var filterKey: String? = null
    private val selected = mutableSetOf<String>()

    private val pickExportTree = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri -> if (uri != null) runExport(uri) }

    private lateinit var adapter: ArchiveAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_gallery)
        instance = intent.getStringExtra(MainActivity.EXTRA_INSTANCE).orEmpty()

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }
        supportActionBar?.title = if (instance.isEmpty()) "会话聚合工作台" else "归档 · $instance"

        header = findViewById(R.id.header)
        filterChips = findViewById(R.id.filterChips)
        recycler = findViewById(R.id.recycler)
        emptyState = findViewById(R.id.emptyState)
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(recycler, emptyState),
            bottomBar = findViewById<View>(R.id.bottomBar),
        )

        store = ArchiveStore(archiveRoot())

        adapter = ArchiveAdapter(
            onClick = { entry ->
                if (selected.isNotEmpty()) toggleSelect(entry) else launchConversation(entry)
            },
            onLongClick = { entry -> open(entry) },
            isSelected = { selected.contains(it.id) }
        )
        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        findViewById<View>(R.id.btnExport).setOnClickListener { pickExportTree.launch(null) }
        findViewById<View>(R.id.btnDelete).setOnClickListener { promptDeleteSelected() }
    }

    override fun onResume() {
        super.onResume()
        refresh()
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

    private fun loadAllEntries(): List<ArchiveEntry> {
        val list = mutableListOf<ArchiveEntry>()
        val defaultRoot = File(filesDir, "归档")
        if (defaultRoot.isDirectory) {
            list.addAll(ArchiveStore(defaultRoot).all())
        }
        val instancesDir = File(filesDir, "instances")
        if (instancesDir.isDirectory) {
            instancesDir.listFiles()?.filter { it.isDirectory }?.forEach { instDir ->
                val configured = File(instDir, "archive-destination.txt").takeIf { it.isFile }?.readText()?.trim()?.takeUnless { it.isBlank() }
                val root = when {
                    configured == null -> File(instDir, "归档")
                    File(configured).isAbsolute -> File(configured)
                    else -> File(instDir, configured)
                }
                if (root.isDirectory) {
                    val entries = ArchiveStore(root).all().map { entry ->
                        if (entry.accountId.isNullOrBlank()) entry.copy(accountId = instDir.name) else entry
                    }
                    list.addAll(entries)
                }
            }
        }
        return list.distinctBy { it.id }
    }

    private fun launchConversation(entry: ArchiveEntry) {
        val targetInstance = entry.accountId ?: entry.profile.orEmpty()
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra(MainActivity.EXTRA_INSTANCE, targetInstance)
            putExtra(MainActivity.EXTRA_URL, entry.url)
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        startActivity(intent)
    }

    private fun refresh() {
        rows = (if (instance.isEmpty()) loadAllEntries() else store.all()).sortedWith(
            compareBy<ArchiveEntry> { it.modelFolder == null || it.modelFolder == ArchiveStore.UNIDENTIFIED }
                .thenBy { it.modelFolder ?: "" }
                .thenByDescending { it.collectedAt ?: "" }
        )
        val groups = rows.groupBy { it.modelFolder ?: ArchiveStore.UNIDENTIFIED }
        header.text = (if (instance.isEmpty()) "【聚合工作台】" else "") +
            "共 ${rows.size} 条 · ${groups.size} 个模型分组  ·  点击进入对话，长按详情${if (selected.isNotEmpty()) " · 已选 ${selected.size} 条" else ""}"

        // chips
        filterChips.removeAllViews()
        val allChip = Chip(this).apply {
            text = "全部 ${rows.size}"
            isCheckable = true
            isChecked = filterKey == null
            setOnClickListener { filterKey = null; applyFilter() }
        }
        filterChips.addView(allChip)
        groups.keys.sortedWith(compareBy({ it == ArchiveStore.UNIDENTIFIED }, { it })).forEach { key ->
            val count = groups[key]!!.size
            val chip = Chip(this).apply {
                text = "$key $count"
                isCheckable = true
                isChecked = filterKey == key
                setOnClickListener { filterKey = key; applyFilter() }
            }
            filterChips.addView(chip)
        }

        applyFilter()
    }

    private fun applyFilter() {
        filtered = if (filterKey == null) rows else rows.filter { (it.modelFolder ?: ArchiveStore.UNIDENTIFIED) == filterKey }
        // keep selection only for visible? keep global
        adapter.submit(filtered)
        emptyState.visibility = if (filtered.isEmpty()) View.VISIBLE else View.GONE
        recycler.visibility = if (filtered.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun toggleSelect(entry: ArchiveEntry) {
        if (selected.contains(entry.id)) selected.remove(entry.id) else selected.add(entry.id)
        adapter.notifyDataSetChanged()
        refreshHeader()
    }

    private fun refreshHeader() {
        val groups = rows.groupBy { it.modelFolder ?: ArchiveStore.UNIDENTIFIED }
        header.text = "共 ${rows.size} 条 · ${groups.size} 个模型分组  ·  点击查看详情，长按快速预览${if (selected.isNotEmpty()) " · 已选 ${selected.size} 条" else ""}"
    }

    private fun openDetail(entry: ArchiveEntry) {
        startActivity(Intent(this, ConversationDetailActivity::class.java)
            .putExtra(ConversationDetailActivity.EXTRA_INSTANCE, instance)
            .putExtra(ConversationDetailActivity.EXTRA_ENTRY_ID, entry.id))
    }

    private fun open(entry: ArchiveEntry) {
        AlertDialog.Builder(this)
            .setTitle(entry.title ?: "会话")
            .setMessage(buildString {
                append("模型：").append(entry.model ?: "未识别").append('\n')
                append("地址：").append(entry.url).append('\n')
                entry.email?.let { append("账号：").append(it).append('\n') }
                entry.prompt?.let { append("提示词：").append(it) }
            })
            .setPositiveButton("在浏览器打开") { _, _ ->
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(entry.url))) }
                    .onFailure { toast("无法打开该地址") }
            }
            .setNeutralButton("查看详情") { _, _ -> openDetail(entry) }
            .setNeutralButton("选择") { _, _ -> toggleSelect(entry) }
            .setNegativeButton("关闭", null)
            .show()
    }

    private fun promptDeleteSelected() {
        val ids = if (selected.isEmpty()) {
            // if nothing selected, prompt to select
            toast("长按卡片可选择，或点击卡片进入选择模式"); return
        } else selected.toList()
        AlertDialog.Builder(this)
            .setTitle("删除 ${ids.size} 条记录")
            .setMessage("只删除本地归档记录与入口文件。arena 网站上的归档动作不可逆，无法撤销。")
            .setPositiveButton("删除") { _, _ ->
                runCatching { store.deleteMany(ids) }
                    .onSuccess {
                        selected.clear()
                        refresh()
                        toast("已删除 ${it.size} 条")
                    }
                    .onFailure { toast(it.message) }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun toast(message: String?) {
        Toast.makeText(this, message ?: "操作失败", Toast.LENGTH_LONG).show()
    }

    private fun runExport(tree: Uri) {
        val report = ArchiveExporter.export(this, archiveRoot(), tree)
        AlertDialog.Builder(this)
            .setTitle(if (report.ok) "导出完成" else "导出部分失败")
            .setMessage(report.describe())
            .setPositiveButton("知道了", null)
            .show()
    }

    private inner class ArchiveAdapter(
        private val onClick: (ArchiveEntry) -> Unit,
        private val onLongClick: (ArchiveEntry) -> Unit,
        private val isSelected: (ArchiveEntry) -> Boolean
    ) : RecyclerView.Adapter<ArchiveAdapter.VH>() {
        private var items: List<ArchiveEntry> = emptyList()
        fun submit(list: List<ArchiveEntry>) { items = list; notifyDataSetChanged() }
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = VH(LayoutInflater.from(parent.context).inflate(R.layout.item_archive, parent, false))
        override fun getItemCount() = items.size
        override fun onBindViewHolder(h: VH, pos: Int) {
            val e = items[pos]
            h.title.text = e.title?.takeUnless { it.isBlank() } ?: "（无标题）"
            h.modelChip.text = e.modelFolder ?: ArchiveStore.UNIDENTIFIED
            h.time.text = e.collectedAt ?: ""
            h.driftBadge.visibility = if (e.modelDrifted) View.VISIBLE else View.GONE
            val acct = e.accountId ?: e.profile
            h.accountTag.text = if (acct.isNullOrBlank()) "" else "账号: $acct"
            if (!e.renameError.isNullOrBlank()) {
                h.error.visibility = View.VISIBLE
                h.error.text = "重命名未确认：" + e.renameError
            } else h.error.visibility = View.GONE
            val sel = isSelected(e)
            (h.itemView as com.google.android.material.card.MaterialCardView).apply {
                strokeColor = if (sel) getColor(R.color.md_primary) else getColor(R.color.card_stroke)
                strokeWidth = if (sel) 2 else 1
                setCardBackgroundColor(if (sel) getColor(R.color.md_primaryContainer) else getColor(android.R.color.white))
            }
            h.itemView.setOnClickListener { onClick(e) }
            h.itemView.setOnLongClickListener { onLongClick(e); true }
        }
        inner class VH(v: View) : RecyclerView.ViewHolder(v) {
            val title: TextView = v.findViewById(R.id.title)
            val modelChip: Chip = v.findViewById(R.id.modelChip)
            val driftBadge: TextView = v.findViewById(R.id.driftBadge)
            val accountTag: TextView = v.findViewById(R.id.accountTag)
            val time: TextView = v.findViewById(R.id.time)
            val error: TextView = v.findViewById(R.id.error)
        }
    }
}
