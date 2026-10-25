# R123：office 进度注册表 + 会话导出路由单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；P7 进度注册表 / P12 ContextVar 关联 /
  U18 导出路由 / R18-C markdown 导出
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`office/progress.py`（95 行，进程内长任务进度注册表：互斥锁 dict +
单调百分比钳制 + ContextVar 任务关联 + None 探针全 no-op）与
`api/export_routes.py`（95 行，会话 HTML/Markdown 导出：主题归一化、
Accept 双形态、404 映射、同步 def 线程池声明）此前零测试。

## 覆盖矩阵

### `backend/tests/unit/office/test_progress.py`（13 例）

1. track 建立条目（title/开始/0）并经 reporter 上报更新；
2. 百分比钳制 [0,100]（150→100、-5→0）；3. 单调不回退（50 后报 30
   保持 50）；4. track 正常退出移除条目（snapshot → None）；
5. 异常路径同样移除（finally 保证）；6. task_id=None：reporter/report
   全 no-op、不产生条目；7. report() 未知 task_id no-op（无 KeyError）；
8. P12：track 内 report_current 经 ContextVar 写当前任务；track 外
   no-op；track 退出后 token 复位再 no-op；9. snapshot 返回副本
   （改快照不影响注册表）；10. 多线程并发上报无异常且钳制语义成立。

### `backend/tests/unit/api/test_export_routes.py`（9 例）

handler 直调（与 worktree_routes 同风格），monkeypatch 三个服务函数：

1. 缺省 JSON 信封五键齐全（html/filename/session_id/message_count/
   theme）；2. 非法 theme 归一化为 auto 传给服务层；
3. format=markdown → 调 markdown 导出函数、theme 恒 auto；
4. Accept: text/html（无 JSON 意图）→ HTMLResponse 且
   Content-Disposition attachment + filename；
5. Accept 同时含 text/html 与 application/json → JSON 信封；
6. SessionNotFoundError → HTTPException 404；7. body=None → 缺省；
8. ExportSessionRequest extra=forbid（未知键拒绝）；
9. format 非法值 → 回落 html。

## 验证

- pytest 新文件 + office/api 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 session_export 服务的渲染细节（渲染层已有用例，路由层只测
  委托与形态）。
