# Pillow 图片管线（懒加载可选压缩）Round 22 实施计划

> 日期: 2026-09-13 · 分支: `feat/pillow-image-pipeline` · 基于 main @ 44ff4a59
> 系列: Word/Office 写作能力增强第 14 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> Pillow 为**可选依赖**（requirements-optional.txt 声明，不进
> requirements.txt / bundled——沿 matplotlib/formulas 的 main-only 懒加载
> 降级模式）；缺失时管线完全旁路，行为零变化。
> 冲突规避: 不触碰 journal/media 区域。

## 背景（Round 21 合并后再分析）

`charts.resolve_image_payload` 对嵌入图片强制 ≤10MB（`MAX_IMAGE_BYTES`）——
超限直接拒绝。对"随手拍的现场照片/高分辨率扫描"这类合法素材，用户被迫
手工压缩。本轮引入 **Pillow 懒加载压缩管线**：嵌入前若图片超阈值且
Pillow 可用，自动降采样/转码压缩到阈值内；Pillow 缺失或压缩后仍超限 →
保留既有拒绝行为。

## 批次任务

### A. `backend/office/image_optimize.py`（新）

- `optimize_image_bytes(data, max_bytes=8MB) -> bytes`：
  - Pillow 可用性探测（`importlib.util.find_spec("PIL")`，缺失返回原
    bytes 并 debug 日志）
  - 策略：JPEG/PNG → 按比例降采样（最长边 ≤2000px）→ JPEG 质量 85
    逐级（85→75→65）重编码直至 ≤max_bytes；GIF/位图等跳过优化原样返回
  - 全程 best-effort：任何 Pillow 异常 → 原样返回 + warning
- `is_pillow_available() -> bool` 供诊断/测试

### B. 接入（charts.py）

`resolve_image_payload` 返回字节后接入 `optimize_image_bytes`（仅当超
`OPTIMIZE_THRESHOLD_BYTES = 8MB` 触发；≤8MB 原样）。既有 ≤10MB 校验
保持不变（压缩失败的超大图仍被拒，错误信息提示"可安装 Pillow 启用自动
压缩"）。

### C. 依赖声明（requirements-optional.txt）

`Pillow>=10.0` 注释块（main 通道可选，不进 win7 bundle/py38——Pillow
10+ 不支持 py38，与既有懒加载降级模式一致）。

### D. 测试（`backend/tests/unit/office/test_image_optimize.py`）

- 大 JPEG（>8MB 合成）→ 压缩后 ≤8MB 且可解析
- 小图原样通过（不触发重编码，字节相等）
- GIF 原样跳过
- Pillow 缺失场景（mock find_spec 为 None）→ 原样返回
- 超大且不可压缩 → 保持原样由上层校验拒绝
- charts resolve 接入点回归（R14 既有 image 测试全绿）

## Round 23 候选

- TOC 域更新收尾（headless/COM）
- Word 页面横排分节（宽表格场景）
- Excel 打印设置（打印区域/缩放）
