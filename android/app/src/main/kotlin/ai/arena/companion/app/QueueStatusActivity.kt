// spec: docs/mcp-android-implementation-plan.md §4.1 排队状态可视化（串行化单活动实例的 UI 落点）
package ai.arena.companion.app

import ai.arena.companion.R

import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar

class QueueStatusActivity : AppCompatActivity() {

    private lateinit var holderView: TextView
    private lateinit var queueView: TextView
    private lateinit var waitView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_queue_status)
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(findViewById<View>(R.id.content)),
        )

        holderView = findViewById(R.id.holder)
        queueView = findViewById(R.id.queueInfo)
        waitView = findViewById(R.id.waitTime)
        findViewById<View>(R.id.btnRefresh).setOnClickListener { refresh() }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val gate = AppState.launcher.gate
        val holder = gate.holder()
        if (holder == null) {
            holderView.text = "当前没有活动实例"
            holderView.setTextColor(getColor(R.color.md_onSurfaceVariant))
        } else {
            val secs = gate.heldForMillis() / 1000
            holderView.text = "正在运行：" + holder.instance + "  ·  已运行 " + secs + "s"
            holderView.setTextColor(getColor(R.color.md_primary))
        }
        val q = gate.queue()
        queueView.text = if (q.isEmpty()) "队列为空 — 其他实例可直接启动" else buildString {
            append("排队中（${q.size}）：\n")
            q.forEachIndexed { i, name -> append("${i + 1}. $name\n") }
        }
        waitView.text = "说明：代理设置是进程级的，同一时刻只有一个活动实例才能运行。其他实例会排队等待，不会悄悄用错 IP。"
    }
}
