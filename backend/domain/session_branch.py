"""A24 会话分支(Branching)树结构 — 领域模型(移植自 pi)。

pi coding-agent 的会话不是线性消息序列,而是一棵 entry 树:用户可以从任意
历史消息处 fork 新分支探索不同路径,并随时切回任一分支(参考
``packages/coding-agent/src/core/agent-session.ts`` 的 fork / switchSession)。

本模块移植其核心数据结构:

- ``SessionNode``:树节点,与一条消息(``message_id``)一一对应,持父指针与
  子列表。
- ``SessionBranch``:单个会话的分支管理器,维护节点表、根节点与当前位置
  游标。

**领域纯净性**:不读时钟、无外部 I/O、不依赖随机源——节点 id 由调用方
(适配器/应用层边界,如 ``uuid4``)生成后传入,与 ``agent_event.py`` 的
``ts`` / ``run_id`` 注入约定一致;落盘/重建属适配器层职责。

**不变式**:单根(一个会话树只允许一个根节点)+ 引用完整(``parent_id`` /
``children`` 必须指向已存在节点)。破坏不变式的操作抛 ``ValueError``。

Py3.8 兼容(release/win7 cherry-pick)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SessionNode:
    """会话树节点:与一条消息对应。

    Attributes:
        id: 节点唯一标识。
        parent_id: 父节点 id;``None`` 表示根节点。
        message_id: 节点对应的会话消息 id。
        children: 子节点 id 列表(按插入序)。
        metadata: 附加元数据(时间戳、分支摘要等,由调用方自定义)。
    """

    id: str
    parent_id: Optional[str]
    message_id: str
    children: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionBranch:
    """会话分支管理器:节点表 + 根节点 + 当前位置游标。"""

    session_id: str
    nodes: Dict[str, SessionNode] = field(default_factory=dict)
    current_node_id: Optional[str] = None
    root_node_id: Optional[str] = None

    def add_node(
        self,
        parent_id: Optional[str],
        message_id: str,
        *,
        node_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionNode:
        """在 ``parent_id`` 下添加新节点,并把当前游标移到该节点。

        ``parent_id`` 为 ``None`` 时创建根节点(仅空树允许)。``node_id``
        必传:由调用方在边界层生成(如 ``uuid4``),领域层不依赖随机源;
        持久化回填时传入原 id 以保持引用稳定。

        Raises:
            ValueError: 已有根节点时再次创建根;``parent_id`` 指向不存在
                的节点;``node_id`` 与已有节点冲突。
        """
        if parent_id is None:
            if self.root_node_id is not None:
                raise ValueError(
                    f"Session {self.session_id} already has root node "
                    f"{self.root_node_id}; a second root is not allowed"
                )
        elif parent_id not in self.nodes:
            raise ValueError(
                f"Parent node {parent_id} not found in session {self.session_id}"
            )

        new_id = node_id
        if new_id in self.nodes:
            raise ValueError(
                f"Node {new_id} already exists in session {self.session_id}"
            )

        node = SessionNode(
            id=new_id,
            parent_id=parent_id,
            message_id=message_id,
            metadata=dict(metadata) if metadata else {},
        )
        self.nodes[new_id] = node

        if parent_id is None:
            self.root_node_id = new_id
        else:
            self.nodes[parent_id].children.append(new_id)

        self.current_node_id = new_id
        return node

    def switch_branch(self, node_id: str) -> None:
        """把当前游标移到 ``node_id``(即切到含该节点的分支)。

        Raises:
            ValueError: ``node_id`` 不存在。
        """
        if node_id not in self.nodes:
            raise ValueError(
                f"Node {node_id} not found in session {self.session_id}"
            )
        self.current_node_id = node_id

    def get_path_to_root(self, node_id: Optional[str] = None) -> List[str]:
        """从 ``node_id``(默认当前游标)到根的路径,含两端,**根在前**。

        空树 / 游标未设置返回空列表。

        Raises:
            ValueError: 父引用悬空(指向不存在节点)或节点成环(数据损坏)。
        """
        current = self.current_node_id if node_id is None else node_id
        if current is None:
            return []

        reversed_path: List[str] = []
        visited: set = set()
        while current is not None:
            if current in visited:
                raise ValueError(
                    f"Cycle detected at node {current} in session {self.session_id}"
                )
            node = self.nodes.get(current)
            if node is None:
                raise ValueError(
                    f"Dangling parent reference {current} in session {self.session_id}"
                )
            visited.add(current)
            reversed_path.append(current)
            current = node.parent_id
        return list(reversed(reversed_path))

    def get_all_branches(self) -> List[List[str]]:
        """所有从根到叶子的路径(每条为节点 id 列表,根在前)。

        线性链只返回一条;中间节点分叉则返回多条。空树返回空列表。

        Raises:
            ValueError: 子引用悬空(指向不存在节点)。
        """
        if self.root_node_id is None:
            return []

        branches: List[List[str]] = []

        def dfs(node_id: str, path: List[str]) -> None:
            node = self.nodes.get(node_id)
            if node is None:
                raise ValueError(
                    f"Dangling child reference {node_id} in session {self.session_id}"
                )
            path.append(node_id)
            if not node.children:
                branches.append(list(path))
            else:
                for child_id in node.children:
                    dfs(child_id, path)
            path.pop()

        dfs(self.root_node_id, [])
        return branches
