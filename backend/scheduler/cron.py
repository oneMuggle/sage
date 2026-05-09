"""
进化任务调度器
基于 time.sleep 的简单定时调度实现，兼容 Win7
"""
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any
from croniter import croniter  # 轻量级 cron 表达式解析

logger = logging.getLogger(__name__)


class EvolutionScheduler:
    """
    进化任务调度器
    
    支持调度方式:
    - "daily" - 每天执行
    - "weekly" - 每周执行
    - "hourly" - 每小时执行
    - cron 表达式 - 如 "0 3 * * *" 表示每天凌晨3点
    
    使用方法:
        scheduler = EvolutionScheduler()
        scheduler.add_task("daily_summary", task_func, "daily", hour=3, minute=0)
        scheduler.start()
    """
    
    def __init__(self):
        """初始化调度器"""
        self.tasks: List[Dict[str, Any]] = []
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def add_task(
        self,
        name: str,
        task: Callable,
        schedule: str = "daily",
        hour: int = 3,
        minute: int = 0,
        day_of_week: int = None  # 0=周一, 6=周日
    ) -> None:
        """
        添加进化任务
        
        Args:
            name: 任务名称
            task: 可调用的任务函数（可以是 async 函数或普通函数）
            schedule: 调度类型 "daily", "weekly", "hourly", 或 cron 表达式
            hour: 执行小时 (0-23)
            minute: 执行分钟 (0-59)
            day_of_week: 星期几执行 (0=周一, 6=周日)，仅 weekly 模式使用
        """
        task_info = {
            "name": name,
            "task": task,
            "schedule": schedule,
            "hour": hour,
            "minute": minute,
            "day_of_week": day_of_week,
            "last_run": None,
            "next_run": None
        }
        
        # 计算下次执行时间
        task_info["next_run"] = self._calculate_next_run(task_info)
        
        self.tasks.append(task_info)
        logger.info(f"添加进化任务: {name}, 调度: {schedule}, 下次执行: {task_info['next_run']}")
    
    def _calculate_next_run(self, task_info: Dict[str, Any]) -> datetime:
        """
        计算任务下次执行时间
        
        Args:
            task_info: 任务信息字典
            
        Returns:
            下次执行的 datetime
        """
        now = datetime.now()
        schedule = task_info["schedule"]
        hour = task_info["hour"]
        minute = task_info["minute"]
        
        if schedule == "hourly":
            # 下个小时的指定分钟
            next_run = now.replace(minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(hours=1)
            return next_run
        
        elif schedule == "daily":
            # 今天的指定时间
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run
        
        elif schedule == "weekly":
            # 本周指定星期几的指定时间
            day_of_week = task_info["day_of_week"] if task_info["day_of_week"] is not None else 6
            days_ahead = day_of_week - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            elif days_ahead == 0:
                # 同一天，检查时间是否已过
                target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target_time <= now:
                    days_ahead = 7
            
            next_run = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return next_run
        
        else:
            # 尝试解析为 cron 表达式
            try:
                cron = croniter(schedule, now)
                return cron.get_next(datetime)
            except Exception:
                # 默认每天凌晨3点
                logger.warning(f"无法解析 cron 表达式: {schedule}，使用默认调度")
                return now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=1)
    
    def start(self) -> None:
        """启动调度器（在单独线程中运行）"""
        if self.running:
            logger.warning("调度器已在运行中")
            return
        
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"进化调度器启动，共 {len(self.tasks)} 个任务")
    
    def stop(self) -> None:
        """停止调度器"""
        if not self.running:
            return
        
        self.running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        
        logger.info("进化调度器已停止")
    
    def _run_loop(self) -> None:
        """调度器主循环（在单独线程中运行）"""
        while self.running and not self._stop_event.is_set():
            now = datetime.now()
            
            for task_info in self.tasks:
                if self._should_run(task_info, now):
                    self._run_task(task_info)
            
            # 每分钟检查一次
            self._stop_event.wait(timeout=60)
        
        # 更新所有任务的下次执行时间
        self._update_all_next_run()
    
    def _should_run(self, task_info: Dict[str, Any], now: datetime) -> bool:
        """
        判断任务是否应该执行
        
        Args:
            task_info: 任务信息
            now: 当前时间
            
        Returns:
            是否应该执行
        """
        next_run = task_info["next_run"]
        if next_run is None:
            return False
        
        # 考虑1分钟内的误差
        return now >= next_run and (now - next_run).total_seconds() < 60
    
    def _run_task(self, task_info: Dict[str, Any]) -> None:
        """
        执行任务
        
        Args:
            task_info: 任务信息
        """
        name = task_info["name"]
        task = task_info["task"]
        
        logger.info(f"开始执行进化任务: {name}")
        start_time = time.time()
        
        try:
            # 判断是 async 函数还是普通函数
            import asyncio
            if asyncio.iscoroutinefunction(task):
                # 创建新的事件循环来运行 async 函数
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(task())
                finally:
                    loop.close()
            else:
                # 普通函数直接调用
                task()
            
            task_info["last_run"] = datetime.now()
            task_info["next_run"] = self._calculate_next_run(task_info)
            
            elapsed = time.time() - start_time
            logger.info(f"进化任务完成: {name} ({elapsed:.2f}秒)")
            
        except Exception as e:
            logger.error(f"进化任务失败: {name}, 错误: {str(e)}")
            # 任务失败后仍计算下次执行时间，避免死循环
            task_info["next_run"] = self._calculate_next_run(task_info)
    
    def _update_all_next_run(self) -> None:
        """更新所有任务的下次执行时间"""
        for task_info in self.tasks:
            task_info["next_run"] = self._calculate_next_run(task_info)
    
    def get_task_status(self) -> List[Dict[str, Any]]:
        """
        获取所有任务状态
        
        Returns:
            任务状态列表
        """
        return [
            {
                "name": t["name"],
                "schedule": t["schedule"],
                "last_run": t["last_run"].isoformat() if t["last_run"] else None,
                "next_run": t["next_run"].isoformat() if t["next_run"] else None,
                "running": self.running
            }
            for t in self.tasks
        ]
    
    def trigger_task(self, name: str) -> bool:
        """
        手动触发任务
        
        Args:
            name: 任务名称
            
        Returns:
            是否成功触发
        """
        for task_info in self.tasks:
            if task_info["name"] == name:
                # 在单独线程中执行任务
                thread = threading.Thread(target=self._run_task, args=(task_info,), daemon=True)
                thread.start()
                logger.info(f"手动触发进化任务: {name}")
                return True
        
        logger.warning(f"任务不存在: {name}")
        return False


# 全局调度器实例
_scheduler: Optional[EvolutionScheduler] = None


def get_scheduler() -> EvolutionScheduler:
    """获取全局调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = EvolutionScheduler()
    return _scheduler


def start_scheduler() -> None:
    """启动全局调度器"""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler() -> None:
    """停止全局调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
