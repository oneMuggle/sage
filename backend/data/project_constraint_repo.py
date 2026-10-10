"""项目约束仓储（项目类型分类系统，2026-09-24；多项目形态组织增强，2026-10-10）。

项目约束是结构化的 AI 行为指导规则，替代纯文本 instructions。按类别分类
（coding_style/security/testing/academic_writing/document_format 等），支持触发模式匹配（glob）和优先级排序。

约束在构建系统提示词时注入，影响 AI 在该项目中的行为。
"""

from __future__ import annotations

import fnmatch
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


@dataclass
class ProjectConstraint:
    """project_constraints 表一行。"""

    id: str
    project_id: str
    category: str
    content: str
    trigger_pattern: Optional[str] = None
    priority: int = 5
    enabled: bool = True
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "category": self.category,
            "content": self.content,
            "trigger_pattern": self.trigger_pattern,
            "priority": self.priority,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_constraint(row) -> ProjectConstraint:  # noqa: ANN001 — sqlite3.Row
    return ProjectConstraint(
        id=row["id"],
        project_id=row["project_id"],
        category=row["category"],
        content=row["content"],
        trigger_pattern=row["trigger_pattern"],
        priority=row["priority"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now_ms(now_ms: Optional[int] = None) -> int:
    return int(time.time() * 1000) if now_ms is None else now_ms


#: 预设约束模板。键为模板名（含四大项目类型同名的综合模板与细分领域模板），值为约束列表。
CONSTRAINT_TEMPLATES = {
    # ── 四大核心项目形态默认综合模板（供项目类型一键导入） ─────────────────────
    "coding": [
        {"category": "coding_style", "content": "Python 代码遵循 PEP 8，单函数不超过 50 行并补充类型注解", "trigger_pattern": "*.py", "priority": 6},
        {"category": "architecture", "content": "前端与业务模块遵循分层架构边界（pages -> widgets -> features -> shared），禁止跨层逆向导入", "trigger_pattern": "src/**", "priority": 8},
        {"category": "security", "content": "禁止硬编码密钥或凭据，所有数据库查询与外部输入必须参数化与严格校验", "trigger_pattern": "always", "priority": 9},
        {"category": "testing", "content": "新增或修改核心逻辑必须补充对应单元测试并保持检查门禁通过", "trigger_pattern": "always", "priority": 8},
    ],
    "research": [
        {"category": "citation_integrity", "content": "严禁虚构参考文献、作者、年份或 DOI；所有学术论断必须绑定真实文献或已入库项目资料", "trigger_pattern": "always", "priority": 10},
        {"category": "academic_writing", "content": "使用规范学术引用格式（APA/IEEE/GB-T7714），避免主观臆断，首次出现的数学符号与缩写须明确定义", "trigger_pattern": "always", "priority": 7},
        {"category": "experiment_record", "content": "实验记录须包含日期与随机种子、基准方法与超参数、定量指标（均值±标准差）及消融或误差分析", "trigger_pattern": "*.ipynb", "priority": 8},
    ],
    "business": [
        {"category": "document_format", "content": "公文与商务文档遵循标准版式规范，标题层级清晰，字号字体与段落缩进统一", "trigger_pattern": "*.docx", "priority": 7},
        {"category": "confidentiality", "content": "案卷文档须标注保密等级与版本号，严禁修改或覆盖 01_原始依据 目录下的原始佐证材料", "trigger_pattern": "always", "priority": 9},
        {"category": "terminology", "content": "全案卷统一甲乙方简称、项目全称及金额/日期大小写一致性核验", "trigger_pattern": "always", "priority": 8},
    ],
    "personal": [
        {"category": "note_structure", "content": "笔记采用结论先行与结构化要点组织，关联主题使用双链或分类标签归档", "trigger_pattern": "*.md", "priority": 6},
        {"category": "privacy", "content": "个人隐私、账号与敏感凭据信息须脱敏处理后保存", "trigger_pattern": "always", "priority": 8},
    ],
    # ── 细分领域预设模板 ─────────────────────────────────────────────────────
    "python_default": [
        {"category": "coding_style", "content": "使用双引号字符串", "trigger_pattern": "*.py", "priority": 5},
        {"category": "coding_style", "content": "函数不超过 50 行", "trigger_pattern": "*.py", "priority": 5},
        {"category": "testing", "content": "新功能必须有单元测试", "trigger_pattern": "always", "priority": 7},
    ],
    "typescript_react": [
        {"category": "coding_style", "content": "TypeScript 严禁使用裸 any，组件 Props 须显式声明接口", "trigger_pattern": "*.tsx", "priority": 7},
        {"category": "design_tokens", "content": "UI 组件字号与配色必须使用语义化 Design Token（text-ui-*），禁止硬编码像素字号", "trigger_pattern": "src/**/*.tsx", "priority": 7},
    ],
    "security_basic": [
        {"category": "security", "content": "禁止硬编码密钥或密码", "trigger_pattern": "always", "priority": 9},
        {"category": "security", "content": "所有数据库查询使用参数化查询，防止 SQL 注入", "trigger_pattern": "always", "priority": 9},
        {"category": "security", "content": "用户输入必须验证和清理", "trigger_pattern": "always", "priority": 8},
    ],
    "academic_writing": [
        {"category": "academic_writing", "content": "使用 APA 引用格式", "trigger_pattern": "always", "priority": 5},
        {"category": "academic_writing", "content": "避免第一人称，使用被动语态", "trigger_pattern": "always", "priority": 5},
        {"category": "experiment_record", "content": "实验记录须包含日期、方法、结果、分析", "trigger_pattern": "always", "priority": 7},
    ],
    "citation_strict": [
        {"category": "citation_integrity", "content": "零幻觉引用护栏：任何文献引用必须来自工作区 .bib 文件或已索引项目资料，无依据处标注 [待补充文献支撑]", "trigger_pattern": "always", "priority": 10},
        {"category": "reproducibility", "content": "图表与实验结论必须指明对应的数据集路径与生成脚本名称", "trigger_pattern": "always", "priority": 8},
    ],
    "grant_proposal": [
        {"category": "proposal_structure", "content": "课题申报书严格按照「立项依据-研究内容-研究目标-拟解决关键科学问题-技术路线-可行性分析」组织", "trigger_pattern": "always", "priority": 8},
    ],
    "document_format": [
        {"category": "document_format", "content": "标题使用宋体三号", "trigger_pattern": "*.docx", "priority": 5},
        {"category": "confidentiality", "content": "文档须标注保密等级", "trigger_pattern": "always", "priority": 6},
    ],
    "archive_dossier_cn": [
        {"category": "document_format", "content": "行政公文与归档案卷遵循 GB/T 9704 版式规范，成文日期、发文字号与签发人要素齐全", "trigger_pattern": "*.docx", "priority": 7},
        {"category": "spreadsheet_audit", "content": "报表台账金额列统一千分位与两位小数，汇总行必须使用公式而非硬编码数值", "trigger_pattern": "*.xlsx", "priority": 8},
        {"category": "archive_integrity", "content": "归档定稿须同步生成文件清单与版本核对摘要", "trigger_pattern": "always", "priority": 7},
    ],
    "contract_review": [
        {"category": "legal_compliance", "content": "合同审查须逐条核验权利义务对等性、违约责任上限、争议解决管辖与保密条款", "trigger_pattern": "always", "priority": 9},
        {"category": "terminology", "content": "合同正文与附件中的标的金额大小写、履行期限、主体全称必须完全一致", "trigger_pattern": "*.docx", "priority": 9},
    ],
}


def _matches_trigger(trigger_pattern: Optional[str], candidate_files: List[str]) -> bool:
    """判断单条约束的 trigger_pattern 是否匹配候选文件列表。"""
    if trigger_pattern is None or trigger_pattern in ("", "always", "*"):
        return True
    if not candidate_files:
        return False
    norm_pattern = trigger_pattern.replace("\\", "/")
    for raw_file in candidate_files:
        norm_file = raw_file.replace("\\", "/")
        basename = PurePosixPath(norm_file).name
        if fnmatch.fnmatch(norm_file, norm_pattern) or fnmatch.fnmatch(basename, norm_pattern):
            return True
    return False


class ProjectConstraintRepository:
    """project_constraints 表 CRUD。"""

    def __init__(self) -> None:
        self.db = get_database()

    def create(
        self,
        project_id: str,
        category: str,
        content: str,
        trigger_pattern: Optional[str] = None,
        priority: int = 5,
        now_ms: Optional[int] = None,
    ) -> ProjectConstraint:
        """创建一条约束。"""
        ts = _now_ms(now_ms)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        constraint_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO project_constraints
                (id, project_id, category, content, trigger_pattern, priority, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (constraint_id, project_id, category, content, trigger_pattern, priority, ts, ts),
        )
        conn.commit()
        return ProjectConstraint(
            id=constraint_id,
            project_id=project_id,
            category=category,
            content=content,
            trigger_pattern=trigger_pattern,
            priority=priority,
            enabled=True,
            created_at=ts,
            updated_at=ts,
        )

    def get(self, constraint_id: str) -> Optional[ProjectConstraint]:
        """按 ID 获取约束。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM project_constraints WHERE id = ?", (constraint_id,)
        ).fetchone()
        return None if row is None else _row_to_constraint(row)

    def list_by_project(
        self, project_id: str, enabled_only: bool = False
    ) -> List[ProjectConstraint]:
        """列出项目的所有约束（按优先级降序）。"""
        conn = self.db.get_connection()
        query = "SELECT * FROM project_constraints WHERE project_id = ?"
        params: list = [project_id]
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY priority DESC, created_at ASC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_constraint(row) for row in rows]

    def update(
        self,
        constraint_id: str,
        category: Optional[str] = None,
        content: Optional[str] = None,
        trigger_pattern: Optional[str] = None,
        priority: Optional[int] = None,
        enabled: Optional[bool] = None,
        now_ms: Optional[int] = None,
    ) -> bool:
        """更新约束字段（仅更新非 None 参数）。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        updates = []
        params: list = []
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if trigger_pattern is not None:
            updates.append("trigger_pattern = ?")
            params.append(trigger_pattern)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(int(enabled))
        if not updates:
            return self.get(constraint_id) is not None
        updates.append("updated_at = ?")
        params.append(_now_ms(now_ms))
        params.append(constraint_id)
        cursor.execute(
            f"UPDATE project_constraints SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, constraint_id: str) -> bool:
        """删除约束。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_constraints WHERE id = ?", (constraint_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_by_project(self, project_id: str) -> int:
        """删除项目的所有约束，返回删除数量。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_constraints WHERE project_id = ?", (project_id,)
        )
        conn.commit()
        return cursor.rowcount

    def import_template(
        self, project_id: str, template_name: str, now_ms: Optional[int] = None
    ) -> List[ProjectConstraint]:
        """从预设模板导入约束到项目。"""
        if template_name not in CONSTRAINT_TEMPLATES:
            raise ValueError(
                f"Unknown constraint template: {template_name}. "
                f"Available: {list(CONSTRAINT_TEMPLATES.keys())}"
            )
        template = CONSTRAINT_TEMPLATES[template_name]
        created = []
        for item in template:
            constraint = self.create(
                project_id=project_id,
                category=item["category"],
                content=item["content"],
                trigger_pattern=item.get("trigger_pattern"),
                priority=item.get("priority", 5),
                now_ms=now_ms,
            )
            created.append(constraint)
        return created

    def resolve_active(
        self,
        project_id: str,
        current_file: Optional[str] = None,
        active_files: Optional[List[str]] = None,
    ) -> List[ProjectConstraint]:
        """解析当前上下文应激活的约束。"""
        candidates: List[str] = []
        if current_file:
            candidates.append(current_file)
        if active_files:
            candidates.extend(f for f in active_files if f)

        all_enabled = self.list_by_project(project_id, enabled_only=True)
        active = [
            c for c in all_enabled if _matches_trigger(c.trigger_pattern, candidates)
        ]
        return sorted(active, key=lambda c: c.priority, reverse=True)


__all__ = [
    "CONSTRAINT_TEMPLATES",
    "ProjectConstraint",
    "ProjectConstraintRepository",
]
