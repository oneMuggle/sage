"""
platform.win7 — Win7 LTS 适配层

设计目标：把散在 963 个 backend 文件里的 win7 兼容散弹，
收敛到这一个包，后续 cherry-pick 只需改这里。

子模块：
  pydantic_compat — pydantic 1.x vs 2.x 兼容垫片
  win_compat      — Windows 路径/重解析/多行 with 兼容
"""
