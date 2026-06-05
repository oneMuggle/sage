# features/

用户场景：send-message / switch-session / run-tool / manage-settings / edit-memory 等。

- 一个 feature = 一个用户能完成的具体动作
- 可被 widgets / features / pages 引用
- 不可 import：app / processes / widgets（避免反向依赖）
