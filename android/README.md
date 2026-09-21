# Arena Companion — Android

独立安卓 App，按 `docs/mcp-android-implementation-plan.md` 实现。
进度与逐条保真记录见 `docs/mcp-android-implementation-progress.md`。

## 模块

| 模块 | 类型 | 说明 |
|---|---|---|
| `:core` | 纯 JVM Kotlin 库 | 阶段机、归档、设置、实例管理、注册协议。**不依赖 Android API，可直接单测。** |
| `:app`  | Android 应用 | WebView、探针注入、前台服务、Compose UI。需要 Android SDK。 |

## 构建

```bash
# 只跑核心层测试（不需要 Android SDK）
./gradlew :core:test

# 构建 APK（需要 Android SDK 与 local.properties）
./gradlew :app:assembleDebug
```

### 环境要求

- **JDK 17 或 21**。Gradle 8.13 **不支持 JDK 25**——本机 `JAVA_HOME` 若指向 jdk25 需覆盖：
  ```bash
  JAVA_HOME=/path/to/jdk17 ./gradlew :core:test
  ```
- Android SDK（platform 35、build-tools 35）。在 `android/local.properties` 写：
  ```properties
  sdk.dir=D\:\\Android\\Sdk
  ```
  该文件不入库。

## 状态

`:core` 已完成并全部单测通过。`:app` 目前是骨架：结构、权限、服务声明与探针注入
时机已就位。页面桥选择器的校准状态（方案 §9 第 3 项）：

- 输入框 / 发送按钮 / New Chat 入口 / 侧栏展开 / 条款弹窗 / pointer 点击序列：已在真机校准（第二十八至三十批）。
- 对话区读取（`promptConfirmed` / `response` / `completionConfirmed` / `failed` / `generationStamp`）与
  会话重命名（`ModelRename.js`）：第三十一批按 2026-09-21 抓取的 arena.ai 真实 DOM 重映射，
  依据见 `docs/mcp-android-prompt-confirm-timeout-20260921.md`；**真机 CDP 复核尚未完成**，
  在此之前不要把「发送 → 回答 → 重命名 → 归档」闭环当作已验证功能。
- 未保留模型的网站归档（`ModelArchive.js` + `WebsiteArchiver.kt`）：第三十二批按桌面端逐句移植并接入
  `RetryController.websiteArchive`；只有离线回归，**真机未验证**。
- 附件上传（`AttachmentUpload` + `WebViewAttachmentPage`）：第三十三批按桌面端 `AttachmentUpload.cs` 移植。
  安卓没有 CDP `DOM.setFileInputFiles`，交付改为「原生触摸附件入口 → 页面打开文件选择 →
  `WebChromeClient.onShowFileChooser` 回填 `content://` URI」；`fill` 后有附件时先进 `prepare`，
  `attachmentsReady` 确认「Remove <name>」清单一致才允许发送。只有离线回归与构建，**真机未验证**，
  尤其是附件入口按钮的定位规则（`PageBridge.attachmentEntry`）。

### 附件交付（B35）

| 步骤 | 位置 | 失败时 |
|---|---|---|
| 校验绑定附件（存在 / 字节 / 哈希） | `AttachmentUpload.configure`（`startAutomation` 开始前） | 阻止启动 |
| 定位唯一 `input[type=file]` 与可触摸入口 | `PageBridge.attachmentEntry()` | 暂停：「没有找到唯一可用的附件上传入口」/「附件入口无法触发」 |
| 武装回调 → 派发真实触摸 → 页面打开文件选择 | `WebViewAttachmentPage.deliver` | 4 秒内无回调 → 暂停：「附件入口已变化」 |
| 回调时再核 URL / 单多选兼容后交 URI | `onShowFileChooser` | 交空值并按失败处理 |
| 等 `Remove <name>` 清单一致且无进度条 | `prepare` 阶段 ≤ 60 秒 | 暂停：「附件上传尚未确认，已暂停，不会无附件发送」 |

每轮只投递一次（`submitted` 守卫），发送瞬间还会再 `check()` 一次；未武装期间 `onShowFileChooser` 返回 false。
文件经 `FileProvider`（`<applicationId>.attachments`，`res/xml/attachment_paths.xml`）以只读 `content://` 暴露，
来源是 `TaskSettingsStore.import` 复制到应用私有目录的副本。

### 运行参数（设置页）

| 设置项 | 默认 | 下限 | 去向 |
|---|---|---|---|
| 轮次上限 | 0（不限） | 0 | `RetryController.start(prompt, limit)` |
| 无进展上限（秒） | 300 | 60 | `maximumNoProgressSeconds` |
| 等待模型名（秒） | 150 | 30 | `modelWaitSeconds` |
| 要归档的模型（多选） | 全部保留 | — | `retentionPolicy = 目录.policy(excludedModels)` |

「要归档的模型」的候选目录 = 本地归档里出现过的模型名 ∪ `<实例目录>/model-observed-names.json`
（每轮完成时记录，同桌面端）。策略只对目录里已知且被勾选的模型生效，未知模型一律保留。

## 页面桥离线回归（node + jsdom）

`android/app/src/main/assets/*.js` 的选择器改错时，真机上只会表现为 20 秒后「无法确认」；
所以 `app/src/test/js` 下用 jsdom 按真实 DOM 结构做离线回归，`:app:preBuild` 会自动跑它：

```bash
cd android/app/src/test/js
npm install          # 只需一次；未安装时会回退复用 reference/.../tests/node_modules 里的 jsdom
npm test             # = node run-all.cjs（page-bridge / rename-bridge / archive-bridge 三个 .test.cjs）

# 或通过 Gradle（构建 APK 时自动执行；找不到 node 会跳过并提示）
./gradlew :app:bridgeJsTest
./gradlew :app:assembleDebug -PskipBridgeJsTest=true   # 明确跳过
```

`android/core/src/main/resources/web/PageBridge.js` 曾是一份漂移的旧副本，已删除；
`ProbeBridge.kt` 只从 `app/src/main/assets` 读取脚本，请保持单一来源。

## 入库注意

仓库根 `.gitignore` 里有一条 `data/`，会把 `ai/arena/companion/data/` 这样的源码目录一起忽略；
`android/.gitignore` 用 `!**/data/` 放回。新增目录后请用 `git status --ignored --short android`
确认只剩 `build/`、`.gradle/`、`.kotlin/`、`local.properties` 被忽略。
