# entities/

业务实体：Message / Session / Tool / Skill / Agent / Memory。

- 实体 = 业务模型 + 该实体的 store / hook
- 实体之间通过 **id 引用**（不直接 import 对方代码）
- 可被 features / widgets / pages 引用
- 不可 import：app / processes / pages / widgets / features
