"""
CircuitBreaker 测试 (A13 from LLM_Simple)

测试相同参数重复调用的熔断行为。
"""

import pytest

from backend.application.services.middleware import CircuitBreaker


class TestCircuitBreakerBlocking:
    """熔断触发测试"""

    def test_allows_up_to_max_repeats_then_blocks(self):
        """前 max_repeats(3) 次相同调用放行，第 4 次阻断"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=3)
        args = {"command": "pytest"}

        # Act & Assert: 前 3 次放行
        for _ in range(3):
            assert breaker.check("terminal", args) is None

        # 第 4 次阻断
        block = breaker.check("terminal", args)
        assert block is not None
        assert "CIRCUIT BREAKER" in block
        assert "terminal" in block
        assert "4 times" in block

    def test_blocked_call_keeps_blocking(self):
        """阻断后继续相同调用 → 持续阻断且计数递增"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)
        args = {"path": "/tmp/x.txt"}

        # Act
        assert breaker.check("read_file", args) is None
        block_2 = breaker.check("read_file", args)
        block_3 = breaker.check("read_file", args)

        # Assert
        assert block_2 is not None
        assert "2 times" in block_2
        assert block_3 is not None
        assert "3 times" in block_3

    def test_different_arguments_tracked_independently(self):
        """不同参数 → 独立计数，互不熔断"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        # Act & Assert: 同一工具不同参数各放行
        assert breaker.check("terminal", {"command": "ls"}) is None
        assert breaker.check("terminal", {"command": "pwd"}) is None

        # 各自第 2 次才阻断
        assert breaker.check("terminal", {"command": "ls"}) is not None
        assert breaker.check("terminal", {"command": "pwd"}) is not None

    def test_different_tools_tracked_independently(self):
        """不同工具 → 独立计数"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        # Act & Assert
        assert breaker.check("read_file", {"path": "a.txt"}) is None
        assert breaker.check("write_file", {"path": "a.txt"}) is None
        assert breaker.check("read_file", {"path": "a.txt"}) is not None
        # write_file 仍未熔断
        assert breaker.check("write_file", {"path": "a.txt"}) is not None


class TestCircuitBreakerCanonicalization:
    """参数规范化测试"""

    def test_argument_key_order_irrelevant(self):
        """参数键插入顺序不同 → 视为同一调用"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        # Act
        assert breaker.check("terminal", {"a": 1, "b": 2}) is None
        block = breaker.check("terminal", {"b": 2, "a": 1})

        # Assert
        assert block is not None
        assert breaker.call_count("terminal", {"a": 1, "b": 2}) == 2

    def test_nested_arguments_normalized(self):
        """嵌套 dict 的键顺序也参与规范化"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        # Act
        assert breaker.check("terminal", {"opts": {"x": 1, "y": 2}}) is None
        block = breaker.check("terminal", {"opts": {"y": 2, "x": 1}})

        # Assert
        assert block is not None

    def test_unicode_arguments_normalized(self):
        """中文参数值正确规范化（ensure_ascii=False）"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        # Act
        assert breaker.check("write_file", {"内容": "你好"}) is None
        block = breaker.check("write_file", {"内容": "你好"})

        # Assert
        assert block is not None

    def test_unserializable_arguments_do_not_crash(self):
        """不可 JSON 序列化对象 → default=str 兜底，不抛异常"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)

        class Custom:
            def __str__(self):
                return "custom-obj"

        # Act & Assert: 不抛异常，且相同对象表示视为同一调用
        assert breaker.check("terminal", {"obj": Custom()}) is None
        block = breaker.check("terminal", {"obj": Custom()})
        assert block is not None


class TestCircuitBreakerReset:
    """计数重置测试"""

    def test_mark_success_resets_counter(self):
        """mark_success 清零该 (tool, args) 计数 → 恢复放行"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)
        args = {"command": "pytest"}
        assert breaker.check("terminal", args) is None
        assert breaker.check("terminal", args) is not None  # 已熔断

        # Act: 成功后清零  # noqa: ERA001
        breaker.mark_success("terminal", args)

        # Assert: 重新放行  # noqa: ERA001
        assert breaker.call_count("terminal", args) == 0
        assert breaker.check("terminal", args) is None

    def test_mark_success_does_not_affect_other_calls(self):
        """mark_success 只清零指定键"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)
        assert breaker.check("terminal", {"command": "ls"}) is None
        assert breaker.check("terminal", {"command": "pwd"}) is None

        # Act
        breaker.mark_success("terminal", {"command": "ls"})

        # Assert: ls 清零，pwd 不受影响（第 2 次仍熔断）
        assert breaker.check("terminal", {"command": "ls"}) is None
        assert breaker.check("terminal", {"command": "pwd"}) is not None

    def test_reset_clears_all_counters(self):
        """reset() 清零所有计数"""
        # Arrange
        breaker = CircuitBreaker(max_repeats=1)
        breaker.check("terminal", {"command": "ls"})
        breaker.check("read_file", {"path": "a.txt"})
        assert breaker.call_count("terminal", {"command": "ls"}) == 1

        # Act
        breaker.reset()

        # Assert
        assert breaker.call_count("terminal", {"command": "ls"}) == 0
        assert breaker.call_count("read_file", {"path": "a.txt"}) == 0
        assert breaker.check("terminal", {"command": "ls"}) is None

    def test_invalid_max_repeats_raises(self):
        """max_repeats < 1 抛 ValueError"""
        with pytest.raises(ValueError, match="max_repeats"):
            CircuitBreaker(max_repeats=0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
