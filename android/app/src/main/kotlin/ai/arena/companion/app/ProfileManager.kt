// spec: docs/mcp-android-implementation-plan.md §9 第 1 项
//       「MULTI_PROFILE 不支持时必须禁止多实例并明确告知，绝不退回共享 CookieManager 假装隔离」
package ai.arena.companion.app

import android.webkit.WebView
import androidx.webkit.Profile
import androidx.webkit.ProfileStore
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

/** 多实例隔离不可用。**必须禁止多实例，不得假装隔离**。 */
class ProfileIsolationUnavailableException(message: String) : RuntimeException(message)

/**
 * 实例 ↔ WebView Profile 映射。
 *
 * 桌面端靠"每实例一个用户数据目录"做隔离。安卓上对等物是 `androidx.webkit` 的
 * Profile API，但它需要较新的 WebView。**不支持时的正确行为是拒绝，不是降级**：
 * 退回共享 `CookieManager` 会让两个实例共用登录态，用户以为在用两个号，
 * 实际全在同一个号上操作——这比"用不了多实例"糟糕得多。
 */
object ProfileManager {

    /** 单实例始终可用；多实例需要 MULTI_PROFILE。 */
    val isMultiProfileSupported: Boolean
        get() = WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE)

    const val UNSUPPORTED_MESSAGE: String =
        "当前系统 WebView 不支持多用户数据隔离，已禁止创建/切换到第二个实例。" +
            "继续使用会让多个实例共用同一份登录态（看起来是两个号，实际是同一个号）。" +
            "请升级系统 WebView 后重试，或只使用单个实例。"

    /** Profile 名只允许安全字符，避免实例名里的路径字符影响底层存储。 */
    fun profileName(instance: String): String {
        val cleaned = instance.trim().map { if (it.isLetterOrDigit()) it else '_' }.joinToString("")
        // 加一段稳定哈希，避免"甲/乙"这类全被清洗成相同下划线串后互相串号。
        val hash = Integer.toHexString(instance.trim().hashCode())
        return "inst_${cleaned.take(24)}_$hash"
    }

    /**
     * 把 WebView 绑到该实例的 Profile 上。
     *
     * @param isOnlyInstance 只有一个实例时，即使不支持 MULTI_PROFILE 也可以用默认 Profile，
     *        因为此时不存在串号风险。多于一个实例则必须抛。
     */
    fun attach(webView: WebView, instance: String, isOnlyInstance: Boolean) {
        if (!isMultiProfileSupported) {
            if (isOnlyInstance) return          // 单实例：默认 Profile 即可，没有隔离问题
            throw ProfileIsolationUnavailableException(UNSUPPORTED_MESSAGE)
        }
        val name = profileName(instance)
        ProfileStore.getInstance().getOrCreateProfile(name)
        WebViewCompat.setProfile(webView, name)
    }

    /** 创建/切换到新实例前的守卫。 */
    fun requireMultiProfile() {
        if (!isMultiProfileSupported) throw ProfileIsolationUnavailableException(UNSUPPORTED_MESSAGE)
    }

    fun profiles(): List<String> =
        if (isMultiProfileSupported) ProfileStore.getInstance().allProfileNames else emptyList()

    /**
     * 删除实例时一并删掉它的 Profile。删不掉要让调用方知道——
     * 残留的 Profile 会在同名实例重建时带回旧登录态。
     */
    fun delete(instance: String): Boolean {
        if (!isMultiProfileSupported) return false
        return ProfileStore.getInstance().deleteProfile(profileName(instance))
    }

    /** 当前 WebView 绑定的 Profile，供诊断显示。 */
    fun currentProfile(webView: WebView): Profile? =
        if (isMultiProfileSupported) WebViewCompat.getProfile(webView) else null
}
