"""
Skill Hot-Loader - Skill热加载系统
从文件系统动态加载 BaseSkill 子类，支持热更新
"""
import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from backend.skills.base import BaseSkill
from backend.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillHotLoader:
    """
    Skill 热加载器

    职责:
    - 从 skills/ 目录扫描并加载 BaseSkill 子类
    - 监控文件变更，支持热重载
    - 与 SkillRegistry 集成
    """

    def __init__(self, registry: SkillRegistry, skill_dirs: list[str] | None = None):
        self.registry = registry
        self._skill_dirs = skill_dirs or [str(Path(__file__).parent.parent / "skills" / "builtin")]
        self._file_hashes: dict[str, str] = {}
        self._loaded_skills: dict[str, str] = {}  # skill_name -> file_path
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保 Skill 目录存在"""
        for d in self._skill_dirs:
            os.makedirs(d, exist_ok=True)
            init_file = os.path.join(d, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    f.write("# Skills directory\n")

    def scan_and_load(self) -> int:
        """
        扫描所有 Skill 目录并加载新 Skill

        Returns:
            新加载的 Skill 数量
        """
        loaded = 0
        for skill_dir in self._skill_dirs:
            if not os.path.isdir(skill_dir):
                continue

            for filename in sorted(os.listdir(skill_dir)):
                if filename.endswith(".py") and not filename.startswith("_"):
                    file_path = os.path.join(skill_dir, filename)
                    if self._load_from_file(file_path):
                        loaded += 1

        logger.info(f"扫描加载完成: {loaded} new skills")
        return loaded

    def _load_from_file(self, file_path: str) -> bool:
        """
        从文件加载所有 BaseSkill 子类

        Returns:
            是否成功加载至少一个 Skill
        """
        try:
            module_name = f"skills_hot_{os.path.basename(file_path).replace('.py', '')}"
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            found = False
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, BaseSkill)
                        and attr is not BaseSkill):
                    try:
                        instance = attr()
                        self.registry.register(instance)
                        self._loaded_skills[instance.name] = file_path
                        self._file_hashes[file_path] = self._compute_hash(file_path)
                        found = True
                        logger.info(f"加载 Skill: {instance.name} from {filename}")
                    except Exception as e:
                        logger.error(f"实例化 Skill 失败: {attr_name}, error: {e}")

            return found

        except Exception as e:
            logger.error(f"加载 Skill 文件失败: {file_path}, error: {e}")
            return False

    def check_for_updates(self) -> list[str]:
        """检查文件变更"""
        updated = []
        for file_path, old_hash in list(self._file_hashes.items()):
            if not os.path.exists(file_path):
                continue
            if self._compute_hash(file_path) != old_hash:
                # 找到该文件加载的所有 Skill
                skills_to_reload = [
                    name for name, path in self._loaded_skills.items() if path == file_path
                ]
                updated.extend(skills_to_reload)
        return updated

    def hot_reload(self, skill_name: str) -> bool:
        """热重载指定 Skill"""
        file_path = self._loaded_skills.get(skill_name)
        if not file_path or not os.path.exists(file_path):
            return False

        # 注销旧实例
        self.registry.unregister(skill_name)

        # 重新加载文件
        result = self._load_from_file(file_path)
        if result:
            self._file_hashes[file_path] = self._compute_hash(file_path)
            logger.info(f"Skill 热重载成功: {skill_name}")
        return result

    def hot_reload_all(self) -> int:
        """热重载所有变更"""
        updated = self.check_for_updates()
        reloaded = 0
        for skill_name in updated:
            if self.hot_reload(skill_name):
                reloaded += 1
        return reloaded

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            "loaded_skills": len(self._loaded_skills),
            "watched_files": len(self._file_hashes),
            "skill_dirs": self._skill_dirs,
        }

    @staticmethod
    def _compute_hash(file_path: str) -> str:
        """计算文件哈希"""
        import hashlib
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
