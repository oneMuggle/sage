// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/InstancePicker.cs
// spec: docs/mcp-android-implementation-plan.md §5 ui/
package ai.arena.companion.app

import ai.arena.companion.R

import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.AccountReplacement
import ai.arena.companion.account.ReplacementOutcome
import ai.arena.companion.data.InstanceManager
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.card.MaterialCardView
import com.google.android.material.chip.Chip
import com.google.android.material.floatingactionbutton.ExtendedFloatingActionButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import java.io.File

class InstancePickerActivity : AppCompatActivity() {

    private lateinit var manager: InstanceManager
    private lateinit var recycler: RecyclerView
    private lateinit var emptyState: View
    private lateinit var queueBanner: MaterialCardView
    private lateinit var queueHint: TextView
    private lateinit var adapter: InstanceAdapter
    private var names: List<String> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_instance_picker)

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.title = "Arena 助手"
        supportActionBar?.subtitle = "选择实例"

        val root = File(filesDir, "instances")
        manager = InstanceManager(root) { dir -> dir.name == AppState.launcher.holder() }

        recycler = findViewById(R.id.recycler)
        emptyState = findViewById(R.id.emptyState)
        queueBanner = findViewById(R.id.queueBanner)
        queueHint = findViewById(R.id.queueHint)
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(recycler, emptyState),
            floating = findViewById<View>(R.id.fabCreate),
        )

        recycler.layoutManager = LinearLayoutManager(this)
        adapter = InstanceAdapter(
            onClick = { open(it) },
            onLongClick = { promptActions(it) }
        )
        recycler.adapter = adapter

        findViewById<View>(R.id.fabCreate).setOnClickListener { promptCreate() }
        findViewById<View>(R.id.btnEmptyCreate).setOnClickListener { promptCreate() }
        findViewById<View>(R.id.btnViewQueue).setOnClickListener {
            startActivity(Intent(this, QueueStatusActivity::class.java))
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        names = manager.list()
        val holder = AppState.launcher.holder()
        val queue = AppState.launcher.queue()

        adapter.submit(names, holder)

        val hasData = names.isNotEmpty()
        recycler.visibility = if (hasData) View.VISIBLE else View.GONE
        emptyState.visibility = if (hasData) View.GONE else View.VISIBLE

        // queue banner: only show when there is holder or queue
        if (holder == null && queue.isEmpty()) {
            queueBanner.visibility = View.GONE
        } else {
            queueBanner.visibility = View.VISIBLE
            queueHint.text = if (holder == null) {
                "队列中: ${queue.joinToString(", ")}"
            } else {
                val secs = AppState.launcher.gate.heldForMillis() / 1000
                "正在运行: $holder · ${secs}s  ·  排队: ${if (queue.isEmpty()) "无" else queue.joinToString(", ")}"
            }
        }
        supportActionBar?.subtitle = if (names.isEmpty()) "还没有实例" else "${names.size} 个实例" + (holder?.let { " · $it 运行中" } ?: "")
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "会话工作台").setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM)
        menu.add(0, 2, 0, "排队状态").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> startActivity(Intent(this, GalleryActivity::class.java))
            2 -> startActivity(Intent(this, QueueStatusActivity::class.java))
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    private fun promptCreate() {
        if (names.isNotEmpty()) {
            try {
                ProfileManager.requireMultiProfile()
            } catch (e: ProfileIsolationUnavailableException) {
                AlertDialog.Builder(this)
                    .setTitle("无法创建第二个实例")
                    .setMessage(e.message)
                    .setPositiveButton("知道了", null)
                    .show()
                return
            }
        }
        val form = layoutInflater.inflate(R.layout.dialog_text_input, null)
        form.findViewById<TextInputLayout>(R.id.inputLayout).apply {
            hint = "实例名称"
            helperText = "1～40 个字符：字母 / 数字 / 下划线 / 空格 / 横线"
        }
        val input = form.findViewById<TextInputEditText>(R.id.input)
        AlertDialog.Builder(this)
            .setTitle("新建实例")
            .setView(form)
            .setPositiveButton("创建") { _, _ ->
                runCatching { manager.create(input.text?.toString().orEmpty()) }
                    .onSuccess { refresh() }
                    .onFailure { toast(it.message) }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun promptActions(name: String) {
        val items = arrayOf("打开", "设置", "归档", "重命名", "删除", "更换邮箱", "查看排队", "会话聚合工作台")
        AlertDialog.Builder(this)
            .setTitle(name)
            .setItems(items) { _, which ->
                when (which) {
                    0 -> open(name)
                    1 -> startActivity(Intent(this, SettingsActivity::class.java).putExtra(MainActivity.EXTRA_INSTANCE, name))
                    2 -> startActivity(Intent(this, GalleryActivity::class.java).putExtra(MainActivity.EXTRA_INSTANCE, name))
                    3 -> promptRename(name)
                    4 -> promptDelete(name)
                    5 -> promptReplace(name)
                    6 -> startActivity(Intent(this, QueueStatusActivity::class.java))
                    7 -> startActivity(Intent(this, GalleryActivity::class.java))
                }
            }
            .show()
    }

    private fun promptRename(name: String) {
        if (AppState.launcher.holder() == name) {
            toast("该实例正在运行，请先停止后再重命名")
            return
        }
        val form = layoutInflater.inflate(R.layout.dialog_text_input, null)
        form.findViewById<TextInputLayout>(R.id.inputLayout).hint = "新名称"
        val input = form.findViewById<TextInputEditText>(R.id.input).apply { setText(name); selectAll() }
        AlertDialog.Builder(this)
            .setTitle("重命名实例")
            .setView(form)
            .setPositiveButton("确认") { _, _ ->
                runCatching { manager.rename(name, input.text?.toString().orEmpty()) }
                    .onSuccess { refresh() }
                    .onFailure { toast(it.message) }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun promptDelete(name: String) {
        if (AppState.launcher.holder() == name) {
            toast("该实例正在运行，请先停止后再删除")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("删除实例")
            .setMessage("将删除实例「$name」的本地数据目录，并尝试清理其登录态 Profile。删除后同名实例重建时不会带回旧登录态。")
            .setPositiveButton("删除") { _, _ ->
                runCatching { manager.delete(name) }
                    .onSuccess {
                        ProfileManager.delete(name)
                        refresh()
                    }
                    .onFailure { toast(it.message) }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun promptReplace(name: String) {
        if (AppState.launcher.holder() == name) {
            toast("该实例正在运行，请先停止后再更换邮箱")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("更换邮箱")
            .setMessage("会新建一个实例，沿用当前昵称和密码，并把旧邮箱加入排除列表。旧实例、账号和记录全部保留，不会被覆盖。")
            .setPositiveButton("新建并切换") { _, _ ->
                try {
                    ProfileManager.requireMultiProfile()
                } catch (e: ProfileIsolationUnavailableException) {
                    toast(e.message); return@setPositiveButton
                }
                val replacement = AccountReplacement(
                    File(filesDir, "instances"),
                    vaultFactory = { dir -> AccountVault(dir, KeystoreCipher()) },
                )
                val result = replacement.replace(name, pauseAndPersist = {}, activate = {})
                when (result) {
                    is ReplacementOutcome.Done -> {
                        refresh()
                        AlertDialog.Builder(this)
                            .setTitle("已创建新实例")
                            .setMessage("新实例：${result.newInstance}\n旧实例「$name」已原样保留。")
                            .setPositiveButton("打开新实例") { _, _ -> open(result.newInstance) }
                            .setNegativeButton("留在列表", null)
                            .show()
                    }
                    is ReplacementOutcome.Failed -> toast(result.reason)
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun open(name: String) {
        startActivity(Intent(this, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_INSTANCE, name))
    }

    private fun toast(message: String?) {
        Toast.makeText(this, message ?: "操作失败", Toast.LENGTH_LONG).show()
    }

    private inner class InstanceAdapter(
        private val onClick: (String) -> Unit,
        private val onLongClick: (String) -> Unit,
    ) : RecyclerView.Adapter<InstanceAdapter.VH>() {
        private var items: List<String> = emptyList()
        private var holder: String? = null
        fun submit(list: List<String>, holderName: String?) {
            items = list; holder = holderName; notifyDataSetChanged()
        }
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context).inflate(R.layout.item_instance, parent, false)
            return VH(v)
        }
        override fun getItemCount() = items.size
        override fun onBindViewHolder(h: VH, pos: Int) {
            val name = items[pos]
            h.name.text = name
            h.icon.text = name.take(1).uppercase().ifBlank { "A" }
            val isRunning = name == holder
            h.subtitle.text = if (isRunning) "运行中 · 点击打开会话" else "就绪 · 长按更多操作"
            h.chip.visibility = if (isRunning) View.VISIBLE else View.GONE
            h.itemView.setOnClickListener { onClick(name) }
            h.itemView.setOnLongClickListener { onLongClick(name); true }
        }
        inner class VH(v: View) : RecyclerView.ViewHolder(v) {
            val name: TextView = v.findViewById(R.id.name)
            val subtitle: TextView = v.findViewById(R.id.subtitle)
            val icon: TextView = v.findViewById(R.id.iconText)
            val chip: Chip = v.findViewById(R.id.statusChip)
        }
    }
}

object AppState {
    val launcher: SessionLauncher by lazy { SessionLauncher() }
}
