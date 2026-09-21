// spec: docs/mcp-android-implementation-plan.md \u00a77 \u5b89\u5353\u7279\u6709\u7ea6\u675f\uff1a\u540e\u53f0\u6267\u884c / Doze / \u5382\u5546 ROM \u6740\u540e\u53f0
package ai.arena.companion.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.appcompat.app.AlertDialog

object BatteryOptimizationHelper {

    fun isIgnoringBatteryOptimizations(context: Context): Boolean {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(context.packageName)
    }

    fun requestIgnoreBatteryOptimizations(context: Context) {
        try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:${context.packageName}")
            }
            context.startActivity(intent)
        } catch (_: Exception) {
            try {
                context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {}
        }
    }

    fun promptIfNeeded(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        if (isIgnoringBatteryOptimizations(context)) return
        AlertDialog.Builder(context)
            .setTitle("\u7535\u6c60\u4f18\u5316\u63d0\u793a")
            .setMessage(
                "\u68c0\u6d4b\u5230\u7cfb\u7edf\u5df2\u5f00\u542f\u7535\u6c60\u4f18\u5316\uff0c\u53ef\u80fd\u4f1a\u5728\u606f\u5c4f\u540e\u6740\u6389\u540e\u53f0\u4efb\u52a1\u3002\n\n" +
                "Android \u7684 Doze\u3001\u540e\u53f0\u8fdb\u7a0b\u56de\u6536\u548c\u5c0f\u7c73/\u534e\u4e3a/OPPO \u7684\u5382\u5546\u6740\u540e\u53f0\u4f1a\u5bfc\u81f4\u81ea\u52a8\u5316\u4e2d\u65ad\u3002\n" +
                "\u5efa\u8bae\u4e3a\u672c\u5e94\u7528\u5173\u95ed\u7535\u6c60\u4f18\u5316\uff0c\u5e76\u5728\u7cfb\u7edf\u8bbe\u7f6e\u4e2d\u5141\u8bb8\u81ea\u542f\u52a8\u548c\u540e\u53f0\u8fd0\u884c\u3002"
            )
            .setPositiveButton("\u53bb\u8bbe\u7f6e") { _, _ -> requestIgnoreBatteryOptimizations(context) }
            .setNegativeButton("\u6682\u4e0d\u8bbe\u7f6e", null)
            .show()
    }

    fun romHint(): String = buildString {
        append("\u5c0f\u7c73\uff1a\u8bbe\u7f6e \u2192 \u7535\u6c60 \u2192 \u5e94\u7528\u7701\u7535\u7b56\u7565 \u2192 \u672c\u5e94\u7528 \u2192 \u65e0\u9650\u5236\uff1b\u6743\u9650 \u2192 \u81ea\u542f\u52a8\u7ba1\u7406 \u2192 \u5141\u8bb8\n")
        append("\u534e\u4e3a\uff1a\u8bbe\u7f6e \u2192 \u7535\u6c60 \u2192 \u5e94\u7528\u542f\u52a8\u7ba1\u7406 \u2192 \u672c\u5e94\u7528 \u2192 \u624b\u52a8\u7ba1\u7406 \u2192 \u5168\u90e8\u5f00\u542f\n")
        append("OPPO/vivo\uff1a\u8bbe\u7f6e \u2192 \u7535\u6c60 \u2192 \u540e\u53f0\u9ad8\u8017\u7535 \u2192 \u5141\u8bb8\u540e\u53f0\u8fd0\u884c")
    }
}
