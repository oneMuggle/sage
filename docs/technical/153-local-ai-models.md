# 本地 AI 模型内置与离线导入

> 2026-11-14 · 涉及 Electron 打包、后端模型路径解析、模型导入 IPC

Sage 有两个本地 AI 模型：**OCR 文字识别**（RapidOCR PP-OCRv6 tiny，~6MB）与
**记忆语义嵌入**（bge-small-zh-v1.5 ONNX，~91MB）。两者原本依赖运行时联网下载。
内网部署环境无法访问公网，因此改为**随安装包内置**，并提供**本地文件导入**通道，
用于内网分发与后续模型热更新。

---

## 1. 模型清单

| 模型 | 用途 | 文件 | 体积 | 来源 |
| --- | --- | --- | --- | --- |
| RapidOCR PP-OCRv6 tiny | 截图 / 图片文字识别 | `rapidocr/det.onnx`、`rapidocr/rec.onnx` | ~6MB | ModelScope `RapidAI/RapidOCR` v3.10.0 |
| bge-small-zh-v1.5 ONNX | 记忆语义检索 | `bge-small-zh-v1.5/model.onnx`、`bge-small-zh-v1.5/tokenizer.json` | ~91MB | HuggingFace `Xenova/bge-small-zh-v1.5`（经 hf-mirror） |

所有文件以 SHA-256 校验。清单的单一真相源是 `scripts/download-models.sh`
（下载侧）与 `electron/modelDownloadIpc.ts` 的 `*_MODEL_MANIFEST`（运行时下载/导入侧），
两处哈希必须保持一致。

---

## 2. 路径解析优先级

打包后，Electron 主进程通过环境变量向后端注入模型目录。后端按以下顺序解析：

```
1. SAGE_OCR_MODEL_DIR / SAGE_EMBEDDING_MODEL_DIR   ← 用户显式覆盖（最高优先）
2. SAGE_USER_DATA_DIR/models/<name>                ← 用户手动放置的新版本
3. SAGE_BUNDLED_MODELS_DIR/<name>                  ← 安装包内置（resources/models）
4. <repo>/backend/data/models/<name>               ← 开发态仓库默认
5. 无 → 降级或使用包内默认
```

对应实现：

- OCR：`backend/services/ocr/engines/rapidocr.py::resolve_model_dir`
- Embedding：`backend/memory/embedder_factory.py::onnx_model_dir`

`electron/main.ts` 在 `spawnBackend()` 时计算实际目录：

- 若 `<userData>/models/rapidocr` 存在，注入 `SAGE_OCR_MODEL_DIR` 指向它；
- 若为打包态且 `resources/models/rapidocr` 存在，退而指向内置目录；
- 同时注入 `SAGE_BUNDLED_MODELS_DIR = <resourcesPath>/models`，供后端做内置 fallback。

用户只要把新版本模型放进 `userData/models/`，即可**无需重装**覆盖内置模型。

---

## 3. 打包集成

`electron-builder.yml` 通过 `extraResources` 把 `resources/models/` 拷贝进安装目录的
`resources/models/`：

```yaml
extraResources:
  - from: "resources/models"
    to: "models"
    filter:
      - "**/*"
```

`resources/models/` 被 `.gitignore` 排除（模型不入库）。构建前须运行：

```bash
bash scripts/download-models.sh          # 全部
bash scripts/download-models.sh ocr      # 仅 OCR
bash scripts/download-models.sh --check  # 仅校验
```

脚本幂等：已存在且 SHA-256 匹配的文件会跳过，只补缺失/损坏的。默认下载源为国内镜像
（ModelScope / hf-mirror），便于本地与 CI 访问。

### CI

三份构建 workflow 在 `electron-builder` 之前新增缓存 + 下载步骤，确保
`resources/models/` 非空：

- `.github/workflows/ci.yml`（桌面构建 job）
- `.github/workflows/release.yml`
- `.github/workflows/release-win7.yml`

```yaml
- name: Restore local AI models cache
  uses: actions/cache@v4
  with:
    path: resources/models
    key: ${{ runner.os }}-sage-models-${{ hashFiles('scripts/download-models.sh') }}
- name: Fetch local AI models
  shell: bash
  run: bash scripts/download-models.sh
```

缓存 key 绑定脚本内容（脚本内嵌 SHA-256 清单），模型或清单变更时缓存自动失效。

---

## 4. 内网离线导入

安装包已内置模型，正常安装即用。若需在内网分发**更新**的模型文件，或安装包未携带模型：

1. IT 将模型文件（U 盘 / 内网文件服务器）分发到用户机器；
2. 用户在设置页点击「从本地导入」；
3. 弹出目录选择框，选择包含模型文件的目录；
4. Electron 主进程复制文件到 `<userData>/models/<name>/` 并逐个 SHA-256 校验；
5. 校验通过后刷新状态，功能立即可用。

IPC 通道（`electron/modelDownloadIpc.ts`）：

| 通道 | 说明 |
| --- | --- |
| `models:embedder:import-local` | 导入嵌入模型（期望 `model.onnx` + `tokenizer.json`） |
| `models:ocr:import-local` | 导入 OCR 模型（期望 `det.onnx` + `rec.onnx`） |

目录布局宽松：文件可位于所选目录根层，也可位于**一层子目录**中（如
`onnx/model.onnx`），处理器会递归一层定位。任一文件缺失或哈希不匹配即整体失败并
返回明确错误，不会留下半套文件。

前端入口：

- OCR：设置 → 本地 OCR → 「从本地导入」（`LocalOcrCard.tsx`）
- 语义嵌入：设置 → 记忆 → 语义嵌入区 → 「从本地导入」（`MemoryTab.tsx`）

---

## 5. 降级行为

模型缺失时功能不会崩溃，而是显式降级：

- **OCR**：RapidOCR 不可用时回退 Tesseract（若可用）；两者都不可用时 OCR 功能标记为不可用。
- **Embedding**：ONNX 模型或 `onnxruntime` 缺失时降级 `HashEmbedder(256)`
  （零依赖字面 n-gram 匹配），语义检索退化为近似字面匹配。

降级会记录 warning 日志，设置页可看到当前嵌入器类型与维度。

---

## 6. 升级模型

替换模型需同时更新三处 SHA-256：

1. `scripts/download-models.sh` 的 `OCR_FILES` / `EMBEDDER_FILES`
2. `electron/modelDownloadIpc.ts` 的 `OCR_MODEL_MANIFEST` / `EMBEDDER_MODEL_MANIFEST`
3. 若目录名变化，同步 `backend/memory/embedder_factory.py` 的 `DEFAULT_ONNX_MODEL_DIR_NAME`

然后重新运行下载脚本、提交 PR。CI 缓存因脚本哈希变化自动失效，下次构建重新下载。

---

## 7. 故障排查

| 现象 | 排查 |
| --- | --- |
| 安装后 OCR/语义检索不可用 | 检查安装目录 `resources/models/` 是否存在；确认 CI 是否在打包前跑了下载步骤 |
| 用了旧模型 | 用户 `userData/models/` 下旧文件优先于内置；删除或替换该目录 |
| 导入报「sha256 不匹配」 | 所选目录里的文件与清单版本不一致；用官方分发的最新模型 |
| 导入报「找不到文件」 | 确认所选目录（或其一层子目录）含要求的全部文件 |
| CI 构建失败于下载步骤 | 下载源公网不可达；重试或检查镜像可用性。缓存命中可绕过 |

---

## 8. 相关文件

| 文件 | 职责 |
| --- | --- |
| `scripts/download-models.sh` | 下载 + SHA-256 校验模型到 `resources/models/` |
| `electron-builder.yml` | `extraResources` 打包 `resources/models/` |
| `electron/main.ts` | 注入 `SAGE_OCR_MODEL_DIR` / `SAGE_BUNDLED_MODELS_DIR` |
| `electron/modelDownloadIpc.ts` | 模型下载与本地导入 IPC |
| `electron/preload.ts` | 暴露 `modelDownload.importLocal` / `importLocalOcr` |
| `backend/services/ocr/engines/rapidocr.py` | OCR 模型目录解析 |
| `backend/memory/embedder_factory.py` | 嵌入模型目录解析与降级 |
| `src/pages/settings/LocalOcrCard.tsx` | OCR 导入 UI |
| `src/pages/settings/MemoryTab.tsx` | 嵌入模型导入 UI |
