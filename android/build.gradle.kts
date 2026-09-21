// Root build file. Android application module lands in stage G; stage A/C core is
// a pure-JVM Kotlin library so the ported state machine is unit-testable without a device.
plugins {
    kotlin("jvm") version "2.0.21" apply false
    // AGP 8.7 起移除了 com.android.build.gradle.api.BaseVariant，而 Kotlin 2.0.21 的
    // android 插件仍依赖它。两者版本必须在根节点一起固定，否则子模块会各自解析出不兼容组合。
    id("com.android.application") version "8.5.2" apply false
    kotlin("android") version "2.0.21" apply false
    kotlin("kapt") version "2.0.21" apply false
}
