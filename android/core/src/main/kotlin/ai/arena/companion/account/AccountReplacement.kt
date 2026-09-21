// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.AccountReplacement.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ReplacementHandoff.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/LoginTaskStart.cs
package ai.arena.companion.account

import java.io.File

/**
 * 登录完成后自动开跑的一次性标志。逐条对 `LoginTaskStart.cs`。
 *
 * `take` 的三个条件缺一不可，且**成功后立即清零**——这保证"登录后自动开始"
 * 只会发生一次，不会因为界面定时器重入而反复触发。
 */
class LoginTaskStart(pending: Boolean) {
    var pending: Boolean = pending
        private set

    fun cancel() { pending = false }

    /** ref: LoginTaskStart.cs:L17-L25 */
    fun take(loginRunning: Boolean, phase: String): Boolean {
        if (!pending || loginRunning || phase != "complete") return false
        pending = false
        return true
    }
}

/** 换号的每一步结果。**除 [Done] 外都不得让新实例开始跑任务**。 */
sealed interface ReplacementOutcome {
    data class Done(val newInstance: String, val directory: File) : ReplacementOutcome
    /** 交接失败。**旧实例原样保留**，文案必须说清这一点。 */
    data class Failed(val reason: String) : ReplacementOutcome
}

/**
 * 换号（更换邮箱）流程。
 *
 * 桌面端靠"启动新进程 + 命名管道握手 + 45 秒就绪等待"来交接（`ReplacementHandoff.cs`）。
 * 安卓是**单进程**，没有第二个窗口可开，所以交接退化为**进程内实例切换**：
 * 新建实例目录 → 继承昵称与密码 → 把旧邮箱加入排除列表 → 切换活动实例。
 * 管道握手与 45 秒超时因此不再需要；但**它保护的那条语义必须保住**：
 * **新实例没准备好之前，旧实例的数据一个字节都不能动**。
 *
 * 所以本类的顺序是：先把旧实例的任务暂停并落盘 → 再创建新实例 → 全部成功才切换。
 * 任何一步失败都返回 [ReplacementOutcome.Failed] 且旧实例完好。
 */
class AccountReplacement(
    private val instancesRoot: File,
    private val vaultFactory: (File) -> AccountVault = { AccountVault(it) },
) {

    /**
     * 为 [current] 派生一个新实例名。沿用桌面端"原名 + 序号"的形式，
     * 并保证不与已有目录冲突。
     */
    fun deriveName(current: String): String {
        val base = current.trim().ifEmpty { "实例" }
            .replace(Regex("-\\d+$"), "")        // 已经是派生名则不再层层叠加
        var index = 2
        while (File(instancesRoot, "$base-$index").exists()) {
            index++
            if (index > 9999) throw IllegalStateException("无法为「$current」找到可用的新实例名")
        }
        return "$base-$index"
    }

    /**
     * 执行换号。
     *
     * @param pauseAndPersist 暂停旧实例并落盘的回调。抛异常即中止，**不会创建新实例**。
     * @param activate 切换到新实例的回调。
     */
    fun replace(
        current: String,
        pauseAndPersist: () -> Unit,
        activate: (String) -> Unit,
    ): ReplacementOutcome {
        val oldDir = File(instancesRoot, current)
        if (!oldDir.isDirectory) return ReplacementOutcome.Failed("当前实例不存在，已取消换号。")

        // ① 先停旧的。失败就到此为止——绝不在任务还在跑的时候动数据。
        try {
            pauseAndPersist()
        } catch (e: Exception) {
            return ReplacementOutcome.Failed("无法暂停当前任务，已取消换号（旧实例未改动）：${e.message}")
        }

        val oldVault = vaultFactory(oldDir)
        val previous = try {
            oldVault.load()
        } catch (e: VaultUnavailableException) {
            // 读不出旧账号就没法继承昵称密码，也没法把旧邮箱加进排除列表。
            return ReplacementOutcome.Failed("无法读取当前账号，已取消换号（旧实例未改动）：${e.message}")
        }

        val name = try { deriveName(current) } catch (e: Exception) {
            return ReplacementOutcome.Failed(e.message ?: "无法命名新实例")
        }
        val newDir = File(instancesRoot, name)
        if (!newDir.mkdirs()) return ReplacementOutcome.Failed("无法创建新实例目录：$name")

        try {
            // ② 继承昵称和密码（桌面端同样沿用），但**不继承邮箱与已验证状态**。
            //    并把旧邮箱写进排除列表，避免新注册又撞回同一个地址。
            val excluded = (previous.excludedEmails + previous.email)
                .filter { it.isNotBlank() }.distinct()
            vaultFactory(newDir).save(
                AccountData(
                    email = "",
                    password = previous.password,
                    name = previous.name,
                    verified = false,
                    mailboxBeforeRefresh = previous.email,
                    mailboxRefreshRequested = true,
                    mailboxChangeConfirmed = false,
                    excludedEmails = excluded,
                )
            )
            // ③ 任务设置跟着走，省得用户重配。
            File(oldDir, "task-settings.json").takeIf { it.isFile }
                ?.copyTo(File(newDir, "task-settings.json"), overwrite = true)
            File(oldDir, "proxy-settings.json").takeIf { it.isFile }
                ?.copyTo(File(newDir, "proxy-settings.json"), overwrite = true)

            activate(name)
            return ReplacementOutcome.Done(name, newDir)
        } catch (e: Exception) {
            // 新实例没建成 → 清掉半成品，旧实例保持原样。
            newDir.deleteRecursively()
            return ReplacementOutcome.Failed("新实例交接未完成，旧实例已保留，可重试换号：${e.message}")
        }
    }
}
