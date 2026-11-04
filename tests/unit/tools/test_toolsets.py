"""Tool-set files: validation, pinning, capability map, registration (FR-1.10, FR-4.10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.registry import list_components, resolve
from claysandbox.contracts.tools import ServerDef, ToolSetDef
from claysandbox.tools.toolsets import (
    RegisteredToolSet,
    load_toolset,
    load_toolsets,
    package_of,
    register_toolsets,
)

REPO_TOOLSETS = Path(__file__).resolve().parents[3] / "toolsets"


def write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / f"{name}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = """
name: TA
servers:
  - name: roda
    command: ["uvx", "awslabs.roda-mcp-server@0.1.7"]
  - name: osm
    command: ["npx", "-y", "@cyanheads/openstreetmap-mcp-server@0.7.0"]
capabilities:
  dataset_discovery: [roda.search_datasets]
  geocode: [osm.openstreetmap_search_places]
"""


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["uvx", "awslabs.roda-mcp-server@0.1.7"], ("awslabs.roda-mcp-server", "0.1.7")),
        (["uvx", "stac-mcp==6.5.0"], ("stac-mcp", "6.5.0")),
        (["uvx", "--from", "pkg[extra]==1.0", "cmd"], ("pkg[extra]", "1.0")),
        (["npx", "-y", "@cyanheads/openstreetmap-mcp-server@0.7.0"],
         ("@cyanheads/openstreetmap-mcp-server", "0.7.0")),
        (["python", "-m", "clay_embeddings"], (None, None)),
        (["false"], (None, None)),
    ],
)
def test_package_of(command: list[str], expected: tuple[str | None, str | None]) -> None:
    assert package_of(ServerDef(name="s", command=command)) == expected


@pytest.mark.parametrize(
    "command",
    [["uvx", "stac-mcp"], ["uvx", "stac-mcp@latest"], ["npx", "-y", "pkg"], ["docker", "run", "x"]],
)
def test_unpinned_or_unknown_commands_are_rejected(command: list[str]) -> None:
    with pytest.raises(ConfigError):
        package_of(ServerDef(name="s", command=command))


def test_load_valid_toolset_and_capability_lookup(tmp_path: Path) -> None:
    ts = load_toolset(write(tmp_path, "TA", GOOD))
    assert [s.name for s in ts.servers] == ["roda", "osm"]
    assert ts.capability_of("osm", "openstreetmap_search_places") == "geocode"
    assert ts.capability_of("roda", "list_datasets") is None


def test_name_must_match_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file name"):
        load_toolset(write(tmp_path, "OTHER", GOOD))


def test_unpinned_server_in_file_is_rejected(tmp_path: Path) -> None:
    body = GOOD.replace("awslabs.roda-mcp-server@0.1.7", "awslabs.roda-mcp-server@latest")
    with pytest.raises(ConfigError, match="not pinned"):
        load_toolset(write(tmp_path, "TA", body))


@pytest.mark.parametrize(
    ("capabilities", "message"),
    [
        ({"x": ["nope.tool"]}, "unknown server"),
        ({"x": ["roda"]}, "not '<server>.<tool>'"),
        ({"x": ["roda.a"], "y": ["roda.a"]}, "mapped to both"),
    ],
)
def test_bad_capability_maps(capabilities: dict[str, list[str]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ToolSetDef(name="T", servers=[ServerDef(name="roda", command=["false"])],
                   capabilities=capabilities)


def test_duplicate_server_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ToolSetDef(name="T", servers=[ServerDef(name="a", command=["false"])] * 2)


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_toolset(write(tmp_path, "TA", GOOD + "\nextra_field: 1\n"))


def test_register_toolsets_registers_each_file_with_a_content_version(tmp_path: Path) -> None:
    write(tmp_path, "TA", GOOD)
    registered = register_toolsets(tmp_path)
    cls = resolve("toolset", "TA")
    assert registered["TA"] is cls and issubclass(cls, RegisteredToolSet)
    assert cls.definition.name == "TA" and len(cls.version) == 12  # type: ignore[attr-defined]
    entry = next(c for c in list_components("toolset") if c["name"] == "TA")
    assert entry["version"] == cls.version  # type: ignore[attr-defined]


def test_missing_directory_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        register_toolsets(tmp_path / "missing")


def test_repository_toolsets_are_valid_and_pinned() -> None:
    toolsets = load_toolsets(REPO_TOOLSETS)
    assert "T0" in toolsets
    for ts in toolsets.values():
        for server in ts.servers:
            package_of(server)
