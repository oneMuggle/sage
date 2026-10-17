"""
闲时自主目标执行系统 — 检查点管理器

CheckpointManager: 检查点生成（LLM）与验证
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.domain.autonomous_goals import Checkpoint, CheckpointType, Goal

logger = logging.getLogger(__name__)


# LLM Prompt 模板：生成检查点
GENERATE_CHECKPOINTS_PROMPT = """你是一个任务规划专家。根据用户的目标描述，生成可自动验证的检查点。

## 目标信息
- 名称: {goal_name}
- 描述: {goal_description}

## 检查点类型
1. **file**: 文件检查（存在性、行数、内容匹配）
   - 需要提供: file_path（文件路径）, expected_pattern（可选：行数或正则）
   - 示例: 检查 "output.md" 是否存在且包含至少 100 行

2. **command**: 命令执行检查（测试通过、覆盖率达标）
   - 需要提供: verification_command（验证命令）, expected_pattern（可选：输出正则）
   - 示例: 运行 "pytest --cov=backend" 且输出包含 "coverage: 80%"

## 输出格式
返回 JSON 数组，每个元素包含:
```json
{{
  "type": "file|command",
  "description": "检查点描述（中文）",
  "file_path": "文件路径（file 类型必填）",
  "verification_command": "验证命令（command 类型必填）",
  "expected_pattern": "期望模式（可选）"
}}
```

## 要求
1. 生成 3-7 个检查点，覆盖目标的关键成果
2. 每个检查点必须是**可自动验证**的（文件存在、命令执行、正则匹配）
3. 避免需要人工判断的主观检查点
4. 检查点应该是**渐进式**的（从简单到复杂）

## 示例输出
```json
[
  {{
    "type": "file",
    "description": "检查输出文件是否存在",
    "file_path": "output/report.md",
    "verification_command": null,
    "expected_pattern": null
  }},
  {{
    "type": "file",
    "description": "检查报告至少包含 50 行内容",
    "file_path": "output/report.md",
    "verification_command": null,
    "expected_pattern": "50"
  }},
  {{
    "type": "command",
    "description": "检查测试覆盖率达标",
    "file_path": null,
    "verification_command": "pytest --cov=backend --cov-report=term-missing",
    "expected_pattern": "coverage.*\\\\d+%.*pass"
  }}
]
```

请根据目标生成检查点，只返回 JSON 数组，不要其他解释：
"""


@dataclass
class VerificationResult:
    """验证结果"""
    checkpoint_id: str
    passed: bool
    actual_value: str
    expected_value: str
    error_message: Optional[str] = None


@dataclass
class CheckpointReport:
    """检查点报告"""
    total: int
    passed: int
    failed: int
    pending: int
    results: List[VerificationResult]
    progress_percentage: float


class CheckpointManager:
    """检查点生成与验证器（基础版）"""

    async def verify_checkpoint(self, checkpoint: Checkpoint) -> VerificationResult:
        """
        自动验证单个检查点

        根据检查点类型调用不同的验证方法：
        - FILE: 检查文件存在性、行数、内容匹配
        - COMMAND: 执行命令并检查退出码/输出
        - CODE: 代码质量检查（预留）
        - CUSTOM: 自定义检查（预留）
        """
        try:
            if checkpoint.type == CheckpointType.FILE:
                return await self._verify_file_checkpoint(checkpoint)
            elif checkpoint.type == CheckpointType.COMMAND:
                return await self._verify_command_checkpoint(checkpoint)
            elif checkpoint.type == CheckpointType.CODE:
                # 预留：代码质量检查
                return VerificationResult(
                    checkpoint_id=checkpoint.id,
                    passed=False,
                    actual_value="not_implemented",
                    expected_value="implemented",
                    error_message="CODE checkpoint type not yet implemented",
                )
            elif checkpoint.type == CheckpointType.CUSTOM:
                # 预留：自定义检查
                return VerificationResult(
                    checkpoint_id=checkpoint.id,
                    passed=False,
                    actual_value="not_implemented",
                    expected_value="implemented",
                    error_message="CUSTOM checkpoint type not yet implemented",
                )
            else:
                return VerificationResult(
                    checkpoint_id=checkpoint.id,
                    passed=False,
                    actual_value="unknown_type",
                    expected_value=checkpoint.type.value,
                    error_message=f"Unknown checkpoint type: {checkpoint.type}",
                )
        except Exception as e:
            logger.error(f"Failed to verify checkpoint {checkpoint.id}: {e}")
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="error",
                expected_value="success",
                error_message=str(e),
            )

    async def verify_all(self, checkpoints: List[Checkpoint]) -> CheckpointReport:
        """
        验证所有检查点，生成进度报告
        """
        if not checkpoints:
            return CheckpointReport(
                total=0,
                passed=0,
                failed=0,
                pending=0,
                results=[],
                progress_percentage=0.0,
            )

        # 并行验证所有检查点
        tasks = [self.verify_checkpoint(cp) for cp in checkpoints]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        passed = 0
        failed = 0
        pending = 0
        valid_results = []

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Checkpoint verification failed with exception: {result}")
                failed += 1
                continue

            valid_results.append(result)
            if result.passed:
                passed += 1
            else:
                failed += 1

        total = len(checkpoints)
        progress_percentage = (passed / total * 100) if total > 0 else 0.0

        return CheckpointReport(
            total=total,
            passed=passed,
            failed=failed,
            pending=pending,
            results=valid_results,
            progress_percentage=progress_percentage,
        )

    async def _verify_file_checkpoint(self, checkpoint: Checkpoint) -> VerificationResult:
        """
        验证文件检查点

        支持：
        - 文件存在性检查
        - 行数检查（如果 expected_pattern 是数字）
        - 内容匹配（如果 expected_pattern 是正则表达式）
        """
        if not checkpoint.file_path:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="no_file_path",
                expected_value="file_path_required",
                error_message="FILE checkpoint requires file_path",
            )

        file_path = Path(checkpoint.file_path)

        # 1. 检查文件是否存在
        if not file_path.exists():
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="file_not_found",
                expected_value=str(file_path),
                error_message=f"File not found: {file_path}",
            )

        # 2. 如果没有 expected_pattern，只检查存在性
        if not checkpoint.expected_pattern:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=True,
                actual_value="file_exists",
                expected_value=str(file_path),
            )

        # 3. 读取文件内容
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="read_error",
                expected_value=checkpoint.expected_pattern,
                error_message=f"Failed to read file: {e}",
            )

        # 4. 检查是否为行数检查（expected_pattern 是纯数字）
        if checkpoint.expected_pattern.isdigit():
            expected_lines = int(checkpoint.expected_pattern)
            actual_lines = len(content.splitlines())

            # 允许 10% 的误差
            tolerance = expected_lines * 0.1
            passed = abs(actual_lines - expected_lines) <= tolerance

            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=passed,
                actual_value=f"{actual_lines} lines",
                expected_value=f"{expected_lines} lines (±10%)",
            )

        # 5. 正则表达式匹配
        try:
            pattern = re.compile(checkpoint.expected_pattern)
            match = pattern.search(content)
            passed = match is not None

            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=passed,
                actual_value="matched" if passed else "not_matched",
                expected_value=checkpoint.expected_pattern,
            )
        except re.error as e:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="regex_error",
                expected_value=checkpoint.expected_pattern,
                error_message=f"Invalid regex pattern: {e}",
            )

    async def _verify_command_checkpoint(self, checkpoint: Checkpoint) -> VerificationResult:
        """
        验证命令检查点

        执行 verification_command 并检查：
        - 退出码是否为 0
        - 输出是否包含期望内容（如果指定了 expected_pattern）
        """
        if not checkpoint.verification_command:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="no_command",
                expected_value="command_required",
                error_message="COMMAND checkpoint requires verification_command",
            )

        try:
            # 执行命令（超时 60 秒）
            process = await asyncio.create_subprocess_shell(
                checkpoint.verification_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60.0,
            )

            exit_code = process.returncode
            output = stdout.decode("utf-8", errors="ignore")

            # 检查退出码
            if exit_code != 0:
                error_output = stderr.decode("utf-8", errors="ignore")
                return VerificationResult(
                    checkpoint_id=checkpoint.id,
                    passed=False,
                    actual_value=f"exit_code={exit_code}",
                    expected_value="exit_code=0",
                    error_message=f"Command failed with exit code {exit_code}: {error_output[:200]}",
                )

            # 如果指定了 expected_pattern，检查输出是否匹配
            if checkpoint.expected_pattern:
                try:
                    pattern = re.compile(checkpoint.expected_pattern)
                    match = pattern.search(output)
                    passed = match is not None

                    return VerificationResult(
                        checkpoint_id=checkpoint.id,
                        passed=passed,
                        actual_value="matched" if passed else "not_matched",
                        expected_value=checkpoint.expected_pattern,
                    )
                except re.error as e:
                    return VerificationResult(
                        checkpoint_id=checkpoint.id,
                        passed=False,
                        actual_value="regex_error",
                        expected_value=checkpoint.expected_pattern,
                        error_message=f"Invalid regex pattern: {e}",
                    )

            # 只检查退出码
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=True,
                actual_value="exit_code=0",
                expected_value="exit_code=0",
            )

        except asyncio.TimeoutError:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="timeout",
                expected_value="completed_within_60s",
                error_message="Command execution timed out (60s limit)",
            )
        except Exception as e:
            return VerificationResult(
                checkpoint_id=checkpoint.id,
                passed=False,
                actual_value="execution_error",
                expected_value="success",
                error_message=f"Failed to execute command: {e}",
            )

    # ─── LLM 检查点生成 ──────────────────────────────────────────────

    async def generate_checkpoints(
        self,
        goal: Goal,
        llm_config: Optional[object] = None,
    ) -> List[Checkpoint]:
        """
        使用 LLM 根据目标描述生成可验证的检查点

        Args:
            goal: 目标对象（包含 name 和 description）
            llm_config: LLM 配置对象（来自 load_llm_config_from_settings()）

        Returns:
            List[Checkpoint]: 生成的检查点列表

        如果 LLM 不可用或解析失败，返回空列表。
        """
        if llm_config is None:
            logger.warning("generate_checkpoints: no llm_config provided, returning empty list")
            return []

        prompt = GENERATE_CHECKPOINTS_PROMPT.format(
            goal_name=goal.name,
            goal_description=goal.description,
        )

        try:
            # 调用 LLM
            llm_client = llm_config.create_client()
            response = await llm_client.chat_completion(
                model=llm_config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个任务规划专家，负责生成可自动验证的检查点。只返回 JSON，不要其他解释。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning("generate_checkpoints: LLM returned empty content")
                return []

            # 解析 JSON（提取 ```json ... ``` 代码块或纯 JSON）
            checkpoints = self._parse_checkpoints_json(content)

            logger.info(
                f"Generated {len(checkpoints)} checkpoints for goal {goal.id}: {goal.name}"
            )
            return checkpoints

        except Exception as e:
            logger.error(f"generate_checkpoints failed for goal {goal.id}: {e}")
            return []

    def _parse_checkpoints_json(self, content: str) -> List[Checkpoint]:
        """
        解析 LLM 返回的 JSON 内容为 Checkpoint 对象列表

        支持：
        - 纯 JSON 数组
        - ```json ... ``` 代码块包裹
        - 文本中嵌入的 JSON 数组
        """
        # 1. 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)

        # 2. 尝试找到 JSON 数组（[ ... ]）
        array_match = re.search(r"\[.*\]", content, re.DOTALL)
        if array_match:
            content = array_match.group(0)

        # 3. 解析 JSON
        try:
            items = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse checkpoints JSON: {e}")
            return []

        if not isinstance(items, list):
            logger.warning(f"Expected JSON array, got {type(items).__name__}")
            return []

        # 4. 转换为 Checkpoint 对象
        checkpoints = []
        for item in items:
            if not isinstance(item, dict):
                continue

            try:
                checkpoint_type = item.get("type", "file")
                if checkpoint_type not in ("file", "command"):
                    logger.warning(f"Unknown checkpoint type: {checkpoint_type}, skipping")
                    continue

                checkpoint = Checkpoint(
                    id=f"ckpt_{uuid.uuid4().hex[:8]}",
                    type=CheckpointType(checkpoint_type),
                    description=item.get("description", "Unnamed checkpoint"),
                    file_path=item.get("file_path"),
                    verification_command=item.get("verification_command"),
                    expected_pattern=item.get("expected_pattern"),
                    verified=False,
                )
                checkpoints.append(checkpoint)
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to create checkpoint from item: {e}")
                continue

        return checkpoints
