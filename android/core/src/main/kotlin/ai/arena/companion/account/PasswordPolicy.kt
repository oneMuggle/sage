// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/PasswordPolicy.cs:L5-L33
package ai.arena.companion.account

/**
 * 本地主密码强度校验（保险库口令）。返回空串表示通过——**逐字沿用 C# 的三条规则与文案**。
 *
 * 注意与 `register.PasswordPolicy` 区分：那个是 **arena 服务端**对注册密码的规则
 * （大写+小写+数字+符号），这个是 C# 桌面端对**用户自设本地口令**的规则（8 位+大写+符号）。
 * 两者规则不同，不能合并。
 */
object VaultPasswordPolicy {
    fun error(password: String?): String {
        // ref: PasswordPolicy.cs:L7-L10
        if (password.isNullOrEmpty() || password.length < 8) return "密码至少需要 8 个字符"
        var hasUpper = false
        var hasSymbol = false
        for (c in password) {
            if (c.isUpperCase()) hasUpper = true              // ref: L15-L18
            if (!c.isLetterOrDigit()) hasSymbol = true         // ref: L19-L22
        }
        if (!hasUpper) return "密码至少需要一个大写字母"        // ref: L24-L27
        if (!hasSymbol) return "密码至少需要一个符号"            // ref: L28-L31
        return ""
    }

    fun isValid(password: String?): Boolean = error(password).isEmpty()
}
