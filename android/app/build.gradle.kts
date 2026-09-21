plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("kapt")
}

android {
    namespace = "ai.arena.companion"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.arena.companion"
        // 方案 §10 阶段 G：minSdk 26 / target 35
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        // 侧载 APK，不上架
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.cardview:cardview:1.0.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("androidx.coordinatorlayout:coordinatorlayout:1.2.0")
    // 方案 §4：MULTI_PROFILE / DOCUMENT_START_SCRIPT / PROXY_OVERRIDE 均为 webkit 1.9.0 API
    implementation("androidx.webkit:webkit:1.12.1")
    // 方案 §4：导出走 SAF，需要 DocumentFile 遍历用户选定的目录树
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    // 方案 §6：Room 取代 JSON 文件树，保留全部语义（(instance, canonicalUrl) 唯一 → 幂等）
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    kapt("androidx.room:room-compiler:2.6.1")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:rules:1.6.1")
    androidTestImplementation("androidx.room:room-testing:2.6.1")
    androidTestImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
}

// 页面桥离线回归（node + jsdom，android/app/src/test/js）：PageBridge.js / ModelRename.js 的选择器一旦
// 改错，构建期就失败，而不是等真机上 20 秒超时（第三十一批）。找不到 node 时跳过并提示；
// 显式跳过：./gradlew -PskipBridgeJsTest=true …；指定解释器：-PnodeExecutable=/path/to/node
fun findNode(): String? {
    (project.findProperty("nodeExecutable") as String?)?.let { return it }
    val windows = System.getProperty("os.name").lowercase().contains("win")
    val names = if (windows) listOf("node.exe", "node.cmd") else listOf("node")
    return (System.getenv("PATH") ?: "").split(File.pathSeparator)
        .flatMap { dir -> names.map { File(dir, it) } }
        .firstOrNull { it.isFile }?.absolutePath
}

val bridgeJsTest by tasks.registering(Exec::class) {
    group = "verification"
    description = "Run PageBridge.js / ModelRename.js jsdom regression (android/app/src/test/js)"
    val node = findNode()
    val skip = (project.findProperty("skipBridgeJsTest") as String?)?.toBoolean() == true
    onlyIf {
        if (skip) logger.lifecycle("bridgeJsTest: skipped by -PskipBridgeJsTest")
        else if (node == null) logger.warn("bridgeJsTest: node not found on PATH, bridge regression skipped (pass -PnodeExecutable=/path/to/node)")
        !skip && node != null
    }
    workingDir = layout.projectDirectory.dir("src/test/js").asFile
    commandLine(node ?: "node", "run-all.cjs")
}

tasks.named("preBuild") { dependsOn(bridgeJsTest) }
