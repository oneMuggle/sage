# 71 — Pillow 提升为 main 正式依赖（Round 27）

> 日期: 2026-09-14 · 分支: `feat/pillow-main-requirements`
> 系列: Word/Office 写作能力增强第 18 轮（R22 图片管线 #720 的依赖正式化）

## 1. 变更

`backend/requirements.txt` 增加 `Pillow>=10.0`（注释沿 matplotlib/formulas
的"main 通道 only"惯例），`requirements-optional.txt` 同步移除（避免双处
声明漂移）。**效果**：R22 图片压缩管线开箱生效——>8MB 嵌入图片自动降
采样，不再依赖用户手工安装 optional 依赖。

## 2. 影响面评估

- **win7 bundle**：不受影响——`requirements-bundled.txt`/`py38` 列表本就
  不含 Pillow，image_optimize 缺库懒加载旁路（R22 设计）；
- **CI**：ubuntu py3.11 全量安装，Pillow wheel 齐全（manylinux）；
- **API 稳定性**：image_optimize 仅用 `Image.open/convert/resize/save`
  等十年未变的稳定 API，`Pillow>=10.0` 下限即可。

## 3. 测试

`test_image_optimize.py` 全套（含真 Pillow roundtrip 用例——正式依赖后
该用例在 CI 不再 skip，真实覆盖压缩管线）。

## 4. Round 28 候选

TOC 域更新收尾（headless/COM）、Word 横排分节的表格宽页组合、
report-writing 技能图片管线提示。
