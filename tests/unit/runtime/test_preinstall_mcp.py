from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "docker" / "preinstall_mcp.py"
spec = importlib.util.spec_from_file_location("preinstall_mcp", SCRIPT)
assert spec and spec.loader
pre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pre)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["uvx", "awslabs.roda-mcp-server@1.2.3"], ("uvx", "awslabs.roda-mcp-server==1.2.3")),
        (["uvx", "stac-mcp==0.4.1", "--flag"], ("uvx", "stac-mcp==0.4.1")),
        (["uvx", "--from", "pkg==2.0.0", "cmd"], ("uvx", "pkg==2.0.0")),
        (["uvx", "--quiet", "pkg@0.1.0rc1"], ("uvx", "pkg==0.1.0rc1")),
        (["uv", "tool", "run", "pkg@3.1"], ("uvx", "pkg==3.1")),
        (["npx", "-y", "@scope/server@1.0.0"], ("npx", "@scope/server@1.0.0")),
        (["python", "-m", "clay_embeddings", "--data", "data/embeddings"], None),
        ([], None),
    ],
)
def test_package_spec(command: list[str], expected: tuple[str, str] | None) -> None:
    assert pre.package_spec(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        ["uvx", "awslabs.roda-mcp-server"],  # no version
        ["uvx", "pkg@<pinned>"],  # the placeholder from the architecture sketch
        ["uvx", "pkg@latest"],
        ["uvx", "--from", "pkg>=1.0", "cmd"],
        ["npx", "-y", "server"],
        ["npx", "-y", "server@latest"],
    ],
)
def test_unpinned_servers_are_rejected(command: list[str]) -> None:
    with pytest.raises(pre.Unpinned):
        pre.package_spec(command)


def write_toolset(root: Path, name: str, commands: list[list[str]]) -> None:
    servers = "\n".join(
        f"  - name: s{i}\n    command: {c!r}\n".replace("'", '"') for i, c in enumerate(commands)
    )
    (root / f"{name}.yaml").write_text(f"name: {name}\nservers:\n{servers}\n")


def test_collect_dedupes_across_tool_sets(tmp_path: Path) -> None:
    write_toolset(tmp_path, "T0", [["uvx", "a@1.0"], ["python", "-m", "ours"]])
    write_toolset(tmp_path, "T1", [["uvx", "a@1.0"], ["uvx", "b@2.0"]])
    assert pre.collect(tmp_path) == [("uvx", "a==1.0"), ("uvx", "b==2.0")]


def test_main_without_a_toolsets_directory_is_a_no_op(tmp_path: Path) -> None:
    assert pre.main(["x", str(tmp_path / "missing")]) == 0


def test_main_fails_the_build_on_an_unpinned_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_toolset(tmp_path, "T1", [["uvx", "a@<pinned>"]])
    assert pre.main(["x", str(tmp_path)]) == 1
    assert "not pinned" in capsys.readouterr().err


def test_main_warms_the_cache_for_each_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_toolset(tmp_path, "T1", [["uvx", "a@1.0"], ["npx", "-y", "b@2.0"]])
    ran: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool = False) -> Any:
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(pre.subprocess, "run", fake_run)
    monkeypatch.setattr(pre.shutil, "which", lambda name: "/usr/bin/npm")
    assert pre.main(["x", str(tmp_path)]) == 0
    assert ran == [
        ["uvx", "--from", "a==1.0", "python", "-c", "pass"],
        ["npm", "install", "--global", "b@2.0"],
    ]


def test_main_reports_a_failed_install_and_missing_npm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_toolset(tmp_path, "T1", [["uvx", "a@1.0"]])
    monkeypatch.setattr(
        pre.subprocess, "run", lambda cmd, check=False: subprocess.CompletedProcess(cmd, 3)
    )
    assert pre.main(["x", str(tmp_path)]) == 3

    write_toolset(tmp_path, "T1", [["npx", "-y", "b@2.0"]])
    monkeypatch.setattr(pre.shutil, "which", lambda name: None)
    assert pre.main(["x", str(tmp_path)]) == 1
