pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
        google()
    }
    plugins {
        // AGP 8.7 起移除了 com.android.build.gradle.api.BaseVariant，
        // 而 Kotlin 2.0.21 的 android 插件仍依赖它。固定在最后一个兼容版本。
        id("com.android.application") version "8.5.2"
    }
}
dependencyResolutionManagement {
    repositories {
        mavenCentral()
        google()
    }
}

rootProject.name = "arena-companion-android"
include(":core")

// :app 需要 Android SDK。没有 local.properties / ANDROID_HOME 时自动跳过，
// 这样在纯 JVM 环境下 `./gradlew :core:test` 依然可用。
val sdkDir = file("local.properties").takeIf { it.exists() }
    ?.let { java.util.Properties().apply { it.inputStream().use(::load) }.getProperty("sdk.dir") }
    ?: System.getenv("ANDROID_HOME")
    ?: System.getenv("ANDROID_SDK_ROOT")
if (sdkDir != null && file(sdkDir).isDirectory) {
    include(":app")
} else {
    logger.lifecycle("[arena] 未找到 Android SDK，跳过 :app 模块（只构建 :core）。参见 android/README.md")
}
