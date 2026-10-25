# R120：RRF 融合 + ASR 能力单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；R22-D8 ASR 扩展名白名单安全约束
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`memory/fusion.py`（79 行，RRF 混合检索融合，memory 域检索链的收口件）
与 `services/multimodal/asr.py`（83 行，语音转写能力，含 R22-D8 扩展名
白名单/25MB 上传上限两道安全闸）此前零测试。两者均为纯逻辑，补齐后
multimodal 能力族（ASR/TTS/ImageGen）测试闭环。

## 覆盖矩阵

### `backend/tests/unit/memory/test_fusion.py`（10 例）

1. 空输入 → []；2. docstring 场景：两路都出现的 id 融合分最高；
3. 分数数学：单路 rank1 等权 → 1/(60+1)；k 参数生效；
4. 权重加权：0.6/0.4 与 0.5/0.5 排序差异；
5. weights 长度不符 → warning + 等权回退（不抛错）；
6. 同 id 跨路去重累计；7. memory_id 字段回退；无 id 字段 → 不崩溃且
   各自独立；8. 原始列表/字典不被修改（浅拷贝 + 新增 rrf_score 键）；
9. 结果按 rrf_score 降序；10. 三路两权重的 shortest-zip 语义（第三路
   被忽略，行为钉死防意外变更）。

### `backend/tests/unit/services/test_multimodal_asr.py`（13 例）

1. file_content 路径：multipart files 结构（filename=upload.ogg）、
   data.model、URL 拼接、timeout 默认；2. language 有/无；
3. api_key 头有/无；4. 超过 25MB → ValueError；
5. file_path 路径：白名单扩展名读取真实文件（tmp_path .mp3）、
   filename 取文件名；6. 非白名单扩展名（.txt）→ ValueError 且提示
   允许列表；7. 大写扩展名（.MP3）按 lower() 放行；
8. 文件超限 → ValueError（MAX_UPLOAD_BYTES 压小验证，不造 26MB 文件）；
9. file_path 与 file_content 均缺省 → ValueError；
10. parse_response 非 200 → ValueError 含状态码；11. 200 →
    text/language 提取；缺键 → 空串；12. kind/settings_slot；
13. 白名单常量完整性（7 种音频扩展名）。

## 验证

- pytest 新文件 + memory/services 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- `model_catalog/snapshots.py` 的 merge_fields/clear 语义较微妙，留作
  独立轮次专项覆盖；
- 不测 ASR 的 HTTP 发送层（属集成域）。
