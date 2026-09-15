"""分层规矩的硬检查：把 AGENTS.md 里的约定变成 CI 卡点。

检查四件事：
1. 跨层引用只能走对方的 api 窗口（绕过窗口直闯内部就红）；
2. api 窗口只做转出，不写逻辑；
3. 规划层与规则层保持纯函数（禁止时间、随机、I/O 相关模块）；
4. AGENTS.md 里列出的文件路径必须真实存在（文档不许漂移）。

规矩的完整说明见仓库根目录 AGENTS.md（规则层资产）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "vidrecap"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
ARCHITECTURE_MD = REPO_ROOT / "docs" / "ARCHITECTURE.md"

# 每层允许引用的层。跨层引用必须落在对方的 api 窗口上；同层内部自由引用。
ALLOWED_LAYER_DEPS: dict[str, set[str]] = {
    "user": {"user", "service", "monitor", "external", "data"},
    "service": {"service", "planning", "rules", "external", "data"},
    "planning": {"planning", "data"},
    "rules": {"rules", "data"},
    "data": {"data"},
    "external": {"external", "data"},
    "monitor": {"monitor", "service", "rules", "external", "data"},
}

# 规划层与规则层是纯判断：这些模块会引入时钟、随机或 I/O，一律禁止
PURE_LAYERS = {"planning", "rules"}
FORBIDDEN_MODULES_IN_PURE_LAYER = {
    "asyncio",
    "http",
    "multiprocessing",
    "os",
    "pathlib",
    "random",
    "socket",
    "subprocess",
    "threading",
    "time",
    "urllib",
}

# 包根下的文件（__init__.py / __main__.py）算用户层：它们是包门面与启动入口
ROOT_LAYER = "user"


def _package_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _api_windows() -> list[Path]:
    return sorted(p for p in _package_files() if "api" in p.relative_to(PACKAGE_ROOT).parts)


def _layer_of(py: Path) -> str:
    rel = py.relative_to(PACKAGE_ROOT)
    return rel.parts[0] if len(rel.parts) > 1 else ROOT_LAYER


def _imported_vidrecap_modules(py: Path) -> list[str]:
    """收集文件里所有以 vidrecap 开头的绝对 import 目标。"""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            targets.append(node.module)
    return [t for t in targets if t == "vidrecap" or t.startswith("vidrecap.")]


def _imported_top_modules(py: Path) -> set[str]:
    """收集文件里引用的顶层模块名（含标准库），用于纯净度检查。"""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _rel(py: Path) -> str:
    return py.relative_to(REPO_ROOT).as_posix()


@pytest.mark.parametrize("py", _package_files(), ids=_rel)
def test_cross_layer_imports_go_through_api_window(py: Path):
    own_layer = _layer_of(py)
    allowed = ALLOWED_LAYER_DEPS[own_layer]

    for target in _imported_vidrecap_modules(py):
        parts = target.split(".")
        if len(parts) < 2:  # import vidrecap —— 包门面，按同层处理
            continue
        target_layer = parts[1]
        assert target_layer in allowed, (
            f"{_rel(py)} 属于 {own_layer} 层，不许引用 {target_layer} 层（{target}）"
        )
        if target_layer == own_layer:
            continue
        assert len(parts) >= 3 and parts[2] == "api", (
            f"{_rel(py)} 跨层引用必须走 api 窗口，实际写的是 {target}"
        )


@pytest.mark.parametrize("py", _api_windows(), ids=_rel)
def test_api_windows_only_reexport(py: Path):
    """api 窗口只准放文档、import 和 __all__，不准写逻辑。"""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    allowed_node_types = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.Expr)
    for node in tree.body:
        assert isinstance(node, allowed_node_types), (
            f"{_rel(py)} 的 api 窗口里出现了逻辑：{type(node).__name__}"
        )
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ), f"{_rel(py)} 的 api 窗口里只能有文档字符串，不能有语句"


@pytest.mark.parametrize(
    "py",
    [p for p in _package_files() if _layer_of(p) in PURE_LAYERS],
    ids=_rel,
)
def test_pure_layers_stay_pure(py: Path):
    """规划层与规则层只做纯判断：不读时钟、不用随机、不做 I/O。"""
    banned = _imported_top_modules(py) & FORBIDDEN_MODULES_IN_PURE_LAYER
    assert not banned, (
        f"{_rel(py)} 属于纯判断层，禁止引用 {sorted(banned)}"
        "（纯函数要求：同样输入同样输出、不碰时间与 I/O）"
    )


def test_agents_md_lists_only_existing_files():
    """AGENTS.md 的受检清单必须与真实文件同步，防止文档讲了不存在的东西。"""
    assert AGENTS_MD.exists(), "仓库根目录必须有 AGENTS.md（规则层资产）"
    assert ARCHITECTURE_MD.exists(), "docs/ARCHITECTURE.md 必须存在（架构讲解）"

    text = AGENTS_MD.read_text(encoding="utf-8")
    block = re.search(r"<!--\s*files:begin\s*-->(.*?)<!--\s*files:end\s*-->", text, re.S)
    assert block, "AGENTS.md 里必须有 <!-- files:begin --> ... <!-- files:end --> 受检清单"

    listed = re.findall(r"vidrecap/[\w./]+\.py", block.group(1))
    assert listed, "受检清单里没有列出任何文件"
    missing = [p for p in listed if not (REPO_ROOT / p).exists()]
    assert not missing, f"AGENTS.md 列了不存在的文件：{missing}"
