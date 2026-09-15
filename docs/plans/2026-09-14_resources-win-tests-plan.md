# R32 批次 C —— resources Windows 测试解锁（测试基建）

> 背景：W3（#722）曾将 `test_skill_md_resources` 模块级 skipif(nt)——但
> `resources.py` 的平台门（`_resource_index_platform_supported`）本就放行
> Windows（metadata 枚举 + 消费端复检路线），W3 时的 4 例失败实为
> **symlink 夹具需要特权**（WinError 1314），与产品行为无关。

## 改动（纯测试基建，零产品代码）
- 移除模块级 skipif(nt)；
- 4 处 symlink 夹具改为能力探测式 skip（`try: symlink_to / except
  OSError, NotImplementedError: pytest.skip`，同 #728 importer 先例）——
  本地无特权自动 skip；**GitHub windows runner 以管理员运行，4 个
  symlink 拒绝安全用例将真实执行**（验证 products 的 reparse 拒绝行为）。

## 验证
- 本地 Windows：59 passed + 4 skipped + 0 failed（此前 4F/63S）。
- 产品代码零改动；POSIX 行为不变。

## 后续（另行批次）
- 消费端复检升级为 handle 级校验（win_reparse_io 原语已具备，属增强）。
