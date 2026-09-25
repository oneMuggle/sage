# R118：multimodal 能力层 + 中文分词器单测补齐（2026-09-24）

- **上游文档**：parity-loop-sop；multimodal capability（模板方法模式）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

扫描新 main 后选定三块零测试的小而核心模块：
`services/multimodal/tts.py`（59 行）、`services/multimodal/image_gen.py`
（79 行）、`memory/chinese_tokenizer.py`（70 行，FTS5 中文检索的预处理
底座）。三者均为纯函数/纯构建逻辑，测试性价比高。

## 覆盖矩阵

### `backend/tests/unit/services/test_multimodal_capabilities.py`（15 例）

TTS（OpenAI 兼容 /audio/speech）：
1. build_request：URL 拼接、POST 默认、timeout=120、body 全字段
   （model/input/voice/response_format/speed）及缺省值；
2. api_key 有/无 → Authorization Bearer 头有/无；
3. parse_response 非 200 → ValueError 含状态码与错误体前 200 字节解码；
4. parse_response 200 → MediaStore.save 以 kind=AUDIO / source="tts" /
   ext=response_format 调用；text_preview 截断 100 字符。

ImageGen（OpenAI 兼容 /images/generations）：
5. build_request：URL、body（prompt/size/quality/n/response_format 固定
   b64_json）、api_key 头；
6. parse_response 非 200 → ValueError；
7. b64_json 解码正确、每项生成 MediaRef（kind=IMAGE / ext=png /
   metadata 含 prompt + revised_prompt）；
8. 缺 b64_json 的项跳过；data 空 / json=None → 返回 []。

MediaStore 接缝：模块级 `MediaStore()` 在 tts/image_gen 命名空间解析，
monkeypatch 替换为捕获型 fake；另用真 `MediaStore(root=tmp_path)` 跑一条
落盘验证（文件存在 + file_size 正确），覆盖 fake 边界外的 save 真实行为。

### `backend/tests/unit/memory/test_chinese_tokenizer.py`（11 例）

tokenize：
1. 中文分词空格连接；2. 空串/纯空白 → ""；3. 英文原样（空白分隔）；
4. 中英混合不抛错且 token 非空；5. 输出无空 token（多空格输入）。

tokenize_for_search：
6. FTS5 OR 查询格式（每个 token 双引号包裹、OR 连接）；
7. 空串/纯空白 → '""'；8. 引号转义（FTS5 `""` doubling）；
9. 输出 token 无空白项。

不变量断言优先（token 非空、格式结构），不锁定 jieba 具体切分结果
（跨版本稳定）。

## 验证

- pytest 两个新文件 + services/memory 邻近用例回归；
- ruff（CI 同版本 0.4.4）。

## 明确不做

- 不改 MediaStore 默认根目录的相对路径问题（`data/media` 相对 CWD，
  属独立生产行为变更，另行评估）；
- 不测 ASR（已有上游覆盖）。
