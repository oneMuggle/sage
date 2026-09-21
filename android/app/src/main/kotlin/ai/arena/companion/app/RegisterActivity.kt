// ref: backend/services/arena_protocol.py (ArenaRegisterClient 六步流程)
// spec: docs/mcp-android-implementation-plan.md §10 阶段 F 单账号注册
package ai.arena.companion.app

import ai.arena.companion.R

import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText

class RegisterActivity : AppCompatActivity() {

    private lateinit var emailView: TextInputEditText
    private lateinit var passwordView: TextInputEditText
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        EdgeToEdgeInsets.install(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_register)
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }
        EdgeToEdgeInsets.apply(
            root = findViewById<View>(R.id.root),
            topBar = findViewById<View>(R.id.appBar),
            contents = listOf(findViewById<View>(R.id.content)),
        )

        emailView = findViewById(R.id.email)
        passwordView = findViewById(R.id.password)
        statusView = findViewById(R.id.status)

        findViewById<MaterialButton>(R.id.btnStart).setOnClickListener { startPlaceholder() }
        findViewById<MaterialButton>(R.id.btnCancel).setOnClickListener { finish() }
    }

    private fun startPlaceholder() {
        val email = emailView.text.toString().trim()
        statusView.text = "正在准备注册…"
        Toast.makeText(this, "RegisterClient 已完成，网络后端需接真实 ArenaTransport/MailProvider 后可端到端跑通。输入邮箱: ${if (email.isEmpty()) "(auto)" else email}", Toast.LENGTH_LONG).show()
        statusView.text = "UI 已完成，网络实现待真机验证（§9 第 5 项）"
    }
}
