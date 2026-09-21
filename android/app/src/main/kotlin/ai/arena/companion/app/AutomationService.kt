// spec: docs/mcp-android-implementation-plan.md §7（安卓特有约束：后台执行）
package ai.arena.companion.app

import ai.arena.companion.automation.RetryController
import ai.arena.companion.data.JobStateStore
// R 生成在 namespace ai.arena.companion 下，本文件在 .app 子包，必须显式导入。
import ai.arena.companion.R
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 自动化跑在前台服务 + 常驻通知里（§7 第 1 条）。
 *
 * WebView 在后台无法可靠运行，而自动化链路完全依赖 WebView，所以这个服务的作用不是
 * "让任务在后台跑"，而是**尽量延长进程存活并让状态对用户可见**。真被系统杀掉时，
 * 靠 [JobStateStore] 恢复为 paused（§7 第 3、4 条）。
 */
class AutomationService : Service() {

    private val job = SupervisorJob()
    private val scope = CoroutineScope(Dispatchers.Main + job)
    private var ticker: Job? = null

    /** 由 Application/Activity 注入的当前控制器与状态存储。 */
    var controller: RetryController? = null
    var stateStore: JobStateStore? = null
    var instanceName: String = ""

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, notification("正在准备…"))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PAUSE -> controller?.pause("已从通知暂停；不会自动重发已提交的问题")
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
            else -> startTicking()
        }
        // 不用 START_STICKY 自动重启：重启后的进程没有页面上下文，
        // 自动续跑等于盲目重放。恢复一律走 JobStateStore 的 paused 路径。
        return START_NOT_STICKY
    }

    private fun startTicking() {
        if (ticker?.isActive == true) return
        ticker = scope.launch {
            while (true) {
                val c = controller
                if (c != null) {
                    try {
                        c.tick()
                    } catch (e: Exception) {
                        c.pause("自动化循环异常：${e.message}")
                    }
                    persist(c, clean = false)
                    notify(describe(c))
                }
                delay(TICK_INTERVAL_MILLIS)
            }
        }
    }

    private fun persist(c: RetryController, clean: Boolean) {
        val store = stateStore ?: return
        if (!c.hasPendingWork && clean) { store.clear(); return }
        try {
            store.save(store.capture(instanceName, c, clean, Instant.now().toString()))
        } catch (_: Exception) {
            // 状态写入失败不应打断任务；下一次 tick 会再试。
        }
    }

    private fun describe(c: RetryController): String = buildString {
        append("第 ").append(c.rounds + 1).append(" 轮 · ").append(c.phase)
        if (!c.running) append(" · 已暂停")
        append(" — ").append(c.message)
    }

    override fun onDestroy() {
        controller?.let { persist(it, clean = true) }
        ticker?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    // ---- 通知 -------------------------------------------------------------

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.channel_automation), NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun notification(text: String): Notification =
        Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()

    private fun notify(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }

    companion object {
        const val CHANNEL_ID = "automation"
        const val NOTIFICATION_ID = 1001
        const val ACTION_PAUSE = "ai.arena.companion.PAUSE"
        const val ACTION_STOP = "ai.arena.companion.STOP"
        /** 与桌面端 UI 轮询节奏一致的量级；不是网络请求频率。 */
        const val TICK_INTERVAL_MILLIS = 1000L
    }
}
