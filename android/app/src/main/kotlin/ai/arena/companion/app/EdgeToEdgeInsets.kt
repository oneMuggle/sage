// spec: docs/mcp-android-implementation-plan.md §5 ui/ —— 系统栏 / 刘海 / 输入法 insets 的唯一适配入口
package ai.arena.companion.app

import android.graphics.Color
import android.graphics.Rect
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.core.graphics.ColorUtils
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.color.MaterialColors

/**
 * 沉浸式（edge-to-edge）与安全区适配：状态栏、刘海 / 挖孔、导航栏、输入法。
 *
 * 根因：`targetSdk = 35` 之后 Android 15+ **强制** edge-to-edge——窗口内容直接铺到状态栏与前置摄像头
 * 挖孔之下，`android:statusBarColor` 之类的主题项被忽略。此前没有任何 insets 处理，所以每个页面的
 * 标题栏都顶进了摄像头区域。
 *
 * 处理原则：
 * 1. **不退回**（`windowOptOutEdgeToEdgeEnforcement` 已废弃，SDK 36 起失效）。改为在 minSdk 26 起的
 *    全部版本上显式开启 edge-to-edge，让 Android 8～16 表现一致，而不是只在某些版本上"碰巧不重叠"。
 * 2. insets 只施加到**明确指定的视图**：顶部栏吃 top + 左右；内容区 / 底部操作条吃 bottom + 左右；
 *    悬浮按钮吃 bottom + 右侧（margin）。避让量叠加在 XML 原有 padding / margin 之上，回调多次不会累加。
 * 3. 输入法高度加在根视图底部 padding 上，等价于旧 `adjustResize` 的"窗口变矮"：滚动容器随之
 *    `onSizeChanged`，自动把焦点输入框滚到键盘之上（API 30+ 不再自动 resize，必须自己做）。
 * 4. API 28+ 把刘海模式设为 `SHORT_EDGES`：横屏时内容延伸到刘海一侧，由 `displayCutout` insets 避让；
 *    Android 15 对 targetSdk 35 已强制 `ALWAYS`，这里只是让老版本对齐。
 * 5. 系统栏图标深浅按主题 `colorSurface` 的实际亮度决定，而不是按系统夜间模式：当前配色在 DayNight
 *    两种模式下都是浅色表面，按夜间模式取值会在深色模式下把图标刷成白色而看不见。
 */
object EdgeToEdgeInsets {

    /** 必须在 `super.onCreate` / `setContentView` 之前调用。 */
    fun install(activity: ComponentActivity) {
        val surface = MaterialColors.getColor(
            activity, com.google.android.material.R.attr.colorSurface, Color.WHITE
        )
        val style = if (ColorUtils.calculateLuminance(surface) > 0.5) {
            SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
        } else {
            SystemBarStyle.dark(Color.TRANSPARENT)
        }
        activity.enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val window = activity.window
            val attributes = window.attributes
            attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            window.attributes = attributes
        }
    }

    /**
     * @param root      接收 insets 的根视图（各页面的 CoordinatorLayout）；输入法高度加在它的底部。
     * @param topBar    顶部栏（AppBarLayout）：top + 左右 → padding。
     * @param contents  主内容区（列表 / 滚动容器 / 空态）：bottom + 左右 → padding。
     * @param bottomBar 可选底部操作条：bottom + 左右 → padding。
     * @param floating  可选悬浮按钮：bottom + 右侧 → margin。
     */
    fun apply(
        root: View,
        topBar: View? = null,
        contents: List<View> = emptyList(),
        bottomBar: View? = null,
        floating: View? = null,
    ) {
        val rootBase = paddingOf(root)
        val topBase = topBar?.let(::paddingOf)
        val contentBases = contents.map { it to paddingOf(it) }
        val bottomBase = bottomBar?.let(::paddingOf)
        val floatingBase = floating?.let(::marginOf)

        ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
            )
            val imeBottom = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            // 键盘弹出时它已经盖住导航栏：导航栏避让量归零，只由根视图为键盘让位。
            val barBottom = maxOf(bars.bottom - imeBottom, 0)

            root.setPadding(rootBase.left, rootBase.top, rootBase.right, rootBase.bottom + imeBottom)
            if (topBar != null && topBase != null) {
                topBar.setPadding(
                    topBase.left + bars.left, topBase.top + bars.top,
                    topBase.right + bars.right, topBase.bottom,
                )
            }
            for ((view, base) in contentBases) {
                view.setPadding(
                    base.left + bars.left, base.top,
                    base.right + bars.right, base.bottom + barBottom,
                )
            }
            if (bottomBar != null && bottomBase != null) {
                bottomBar.setPadding(
                    bottomBase.left + bars.left, bottomBase.top,
                    bottomBase.right + bars.right, bottomBase.bottom + barBottom,
                )
            }
            if (floating != null && floatingBase != null) {
                val lp = floating.layoutParams as? ViewGroup.MarginLayoutParams
                if (lp != null) {
                    lp.setMargins(
                        floatingBase.left, floatingBase.top,
                        floatingBase.right + bars.right, floatingBase.bottom + barBottom,
                    )
                    floating.layoutParams = lp
                }
            }
            insets
        }
        ViewCompat.requestApplyInsets(root)
    }

    private fun paddingOf(v: View) = Rect(v.paddingLeft, v.paddingTop, v.paddingRight, v.paddingBottom)

    private fun marginOf(v: View): Rect {
        val lp = v.layoutParams as? ViewGroup.MarginLayoutParams ?: return Rect()
        return Rect(lp.leftMargin, lp.topMargin, lp.rightMargin, lp.bottomMargin)
    }
}
