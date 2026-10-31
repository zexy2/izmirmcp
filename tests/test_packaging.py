"""Packaging pass (P2): container image, registry manifest, CI and changelog.

These tests read repository files only; no network, no Docker daemon. They pin
the properties that made the packaging pass worth doing: the image must not bake
local state (``.data/`` and ``.venv/``), the GTFS timetable store must be
rebuildable at run time, the registry manifest must point at the same version the
package advertises, and CI must actually run the suite.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
SERVER_JSON = ROOT / "server.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CHANGELOG = ROOT / "CHANGELOG.md"


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _version() -> str:
    """The single-sourced version (``app.__version__`` via hatch dynamic)."""
    project = _pyproject()["project"]
    if "version" in project:
        return project["version"]
    assert "version" in project.get("dynamic", [])
    match = re.search(
        r'^__version__ = "([^"]+)"$',
        (ROOT / "app" / "__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "app/__init__.py must define __version__"
    return match.group(1)


def _instructions(text: str) -> list[str]:
    """Return Dockerfile lines without comments or blank lines."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _from_images(text: str) -> list[str]:
    images = []
    for line in _instructions(text):
        parts = line.split()
        if parts[0].upper() == "FROM":
            # FROM [--platform=...] image [AS name]: the stage alias is not an image.
            images.append(next(part for part in parts[1:] if not part.startswith("--")))
    return images


def test_dockerfile_exists_and_uses_pinned_python_slim_image():
    assert DOCKERFILE.is_file()
    images = _from_images(DOCKERFILE.read_text(encoding="utf-8"))
    assert images, "Dockerfile must declare at least one FROM image"
    for image in images:
        assert image.startswith("python:3.11-slim"), image
        assert "@sha256:" in image, f"{image} must be pinned by digest"


def test_dockerfile_runs_as_non_root_and_exposes_http_port():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^USER\s+(?!root\b)\w+", text, re.MULTILINE), "image must drop root"
    assert re.search(r"^EXPOSE\s+8000\b", text, re.MULTILINE)
    assert "app.main:app" in text
    assert "app.stdio" in text, "stdio transport must stay runnable in the image"


def test_dockerfile_ships_the_gtfs_build_entrypoint_for_runtime_rebuild():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "app.storage.gtfs_schedule" in text


def test_dockerfile_declares_gtfs_store_path_outside_the_image_layer():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "IZMIR_MCP_DATABASE_PATH" in text
    assert "/data" in text


def test_dockerignore_excludes_local_state_and_virtualenv():
    assert DOCKERIGNORE.is_file()
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert ".data" in patterns or ".data/" in patterns
    assert ".venv" in patterns or ".venv/" in patterns
    for pattern in (".git", "tests", "reports"):
        assert pattern in patterns or f"{pattern}/" in patterns, pattern


def test_dockerignore_keeps_app_data_places_json():
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "app/data" not in patterns
    assert ".data" in patterns or ".data/" in patterns


def test_server_json_matches_registry_schema_and_package_version():
    assert SERVER_JSON.is_file()
    manifest = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    assert manifest["$schema"] == ("https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
    assert re.fullmatch(r"io\.github\.[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", manifest["name"])
    assert manifest["version"] == _version()
    assert manifest["description"].strip()
    assert len(manifest["description"]) <= 100, "registry schema caps description at 100"
    assert manifest["description"] == _pyproject()["project"]["description"]


def test_server_json_is_oci_only_with_stdio_transport():
    """Until PyPI trusted publishing exists the registry entry is the GHCR image only."""
    manifest = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    packages = manifest["packages"]
    assert isinstance(packages, list) and packages
    assert {package["registryType"] for package in packages} == {"oci"}
    oci = packages[0]
    assert oci["transport"]["type"] == "stdio"
    assert [arg["value"] for arg in oci["packageArguments"]] == ["izmir-mcp", "stdio"]
    env = {item["name"]: item.get("default") for item in oci.get("environmentVariables", [])}
    assert env.get("IZMIR_MCP_SKIP_GTFS_BUILD") == "1"
    assert oci["identifier"].rpartition(":")[2] == _version(), "oci tag must equal the package version"


def test_release_metadata_script_agrees():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_release_metadata.py"), "--tag", f"v{_version()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    bad = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_release_metadata.py"), "--tag", "v0.0.0-nope"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1


def test_release_workflow_pins_publisher_and_gates_pypi():
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "releases/latest" not in text
    assert "sha256sum -c" in text
    assert "vars.PUBLISH_PYPI == 'true'" in text
    assert "needs: [ghcr]" in text
    assert "latest=auto" in text
    assert "type=raw,value=latest" not in text
    assert "aquasecurity/trivy-action@" in text and "ignore-unfixed: true" in text
    assert "check_release_metadata.py" in text


def test_server_json_oci_image_is_the_one_the_dockerfile_builds():
    manifest = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    oci = [p for p in manifest["packages"] if p["registryType"] == "oci"]
    assert oci, "an oci package entry is required for docker run"
    image = oci[0]["identifier"]
    assert "/izmir-mcp" in image
    assert ":" in image, "image must be tag or digest pinned"
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "python -m app.main" in text


def test_ci_workflow_runs_tests_live_smoke_and_import_checks():
    assert CI_WORKFLOW.is_file()
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "python-version" in text
    assert "3.11" in text
    assert "pytest" in text
    assert "scripts/smoke_live.py" in text
    assert "app.mcp.registry" in text or "import app" in text


def test_ci_workflow_checks_out_installs_package_and_starts_server():
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout" in text
    assert "pip install" in text
    assert '".[dev]"' in text or ".[dev]" in text
    assert "app.main" in text


def test_ci_gates_the_docker_image_build():
    """The image is only proven buildable if CI builds it on every push."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "docker build" in text
    assert "docker run" in text or "docker container run" in text
    assert "healthz" in text


def test_changelog_opens_with_current_version_and_packaging_entry():
    assert CHANGELOG.is_file()
    text = CHANGELOG.read_text(encoding="utf-8")
    version = _version()
    first_heading = next(line for line in text.splitlines() if line.startswith("## "))
    assert version in first_heading, first_heading
    assert "Docker" in text
    assert "server.json" in text


def test_wheel_can_actually_be_built():
    """`pip install .` in the Dockerfile builds a wheel; a broken wheel config
    (for example force-including a path already covered by ``packages``) fails
    there but not under an editable install, so assert the config directly."""
    config = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]
    forced = config.get("force-include", {})
    packages = config.get("packages", [])
    for source in forced:
        assert not any(source == package or source.startswith(package.rstrip("/") + "/") for package in packages), (
            f"force-include '{source}' duplicates a path inside packages {packages}; "
            "hatchling fails with 'A second file is being added to the wheel archive'"
        )


def test_protocol_smoke_script_exists_and_is_wired_into_ci():
    """`smoke_mcp.py` proves the wire protocol without live city sources.

    `smoke_live.py` exercises the service layer against third-party APIs, so it
    cannot run offline or block a merge. The protocol smoke starts a real local
    server and checks handshake, surface, envelope and guards.
    """
    script = ROOT / "scripts" / "smoke_mcp.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "initialize" in text and "tools/list" in text
    assert "izmir://coverage" in text
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/smoke_mcp.py" in ci, "CI must run the offline protocol smoke"


# --- packaging pass 2: multi-stage, lockfile, label, compose, licence -------


def test_dockerfile_is_multi_stage_and_installs_locked_deps_before_the_app():
    lines = _instructions(DOCKERFILE.read_text(encoding="utf-8"))
    froms = [i for i, line in enumerate(lines) if line.upper().startswith("FROM ")]
    assert len(froms) == 2, "builder + runtime stages"
    builder = lines[froms[0] : froms[1]]
    lock = next(i for i, line in enumerate(builder) if "requirements.lock" in line and line.startswith("RUN"))
    copy_app = next(i for i, line in enumerate(builder) if line.startswith("COPY app"))
    assert "--require-hashes" in builder[lock]
    assert lock < copy_app, "dependency layer must precede COPY app for caching"
    runtime = lines[froms[1] :]
    assert any(line.startswith("COPY --from=builder") for line in runtime)
    assert not any(line.startswith("COPY app") for line in runtime)


def test_dockerfile_keeps_uid_healthcheck_and_mcp_label():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--uid 10001" in text
    assert "HEALTHCHECK" in text and "/healthz" in text
    assert 'io.modelcontextprotocol.server.name="io.github.zexy2/izmir-mcp"' in text
    assert f"ARG VERSION={_version()}" in text


def test_lockfiles_pin_every_runtime_dependency_with_hashes():
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert (ROOT / "uv.lock").is_file()
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==", lock, re.MULTILINE)
    assert pins and lock.count("--hash=sha256:") >= len(pins)
    names = {name.lower().replace("_", "-") for name in pins}
    for dependency in _pyproject()["project"]["dependencies"]:
        name = re.split(r"[<>=!~\[ ]", dependency, maxsplit=1)[0].lower()
        assert name in names, f"{name} missing from requirements.lock"
    assert "izmir-mcp" not in names, "the project itself is installed separately"


def test_runtime_dependencies_have_upper_bounds():
    for dependency in _pyproject()["project"]["dependencies"]:
        assert "<" in dependency, f"{dependency} needs an upper bound"


def test_console_scripts_stay_backward_compatible():
    scripts = _pyproject()["project"]["scripts"]
    assert scripts["izmir-mcp"] == "app.main:run"
    assert scripts["izmir-mcp-stdio"] == "app.stdio:main"


def test_izmir_mcp_script_accepts_a_stdio_mode(monkeypatch):
    import sys

    import app.main as main_module
    import app.stdio as stdio_module

    called = []
    monkeypatch.setattr(stdio_module, "main", lambda: called.append("stdio"))
    monkeypatch.setattr(sys, "argv", ["izmir-mcp", "stdio"])
    main_module.run()
    assert called == ["stdio"]
    monkeypatch.setattr(sys, "argv", ["izmir-mcp", "bogus"])
    import pytest

    with pytest.raises(SystemExit):
        main_module.run()


def test_server_json_packages_use_valid_runtime_hints():
    manifest = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    by_type = {package["registryType"]: package for package in manifest["packages"]}
    oci = by_type["oci"]
    pypi = by_type.get("pypi")
    if pypi is not None:  # re-added once PyPI trusted publishing is live
        assert pypi["identifier"] == _pyproject()["project"]["name"]
        assert pypi["runtimeHint"] == "uvx"
        assert [arg["value"] for arg in pypi["packageArguments"]] == ["stdio"]
    assert oci["identifier"] == f"ghcr.io/zexy2/izmir-mcp:{_version()}"
    assert oci["runtimeHint"] == "docker"
    for package in manifest["packages"]:
        assert package["version"] if "version" in package else True
        assert "127.0.0.1" not in json.dumps(package)


def test_compose_runs_read_only_with_dropped_capabilities():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+read_only:\s*true", text, re.MULTILINE)
    assert "tmpfs:" in text
    assert re.search(r"cap_drop:\s*\n\s*-\s*ALL", text)
    assert "127.0.0.1:8000:8000" in text


def test_license_is_mit_and_declared():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "zexy2" in text
    assert _pyproject()["project"]["license"] == "MIT"


def test_env_example_has_no_duplicate_keys_and_covers_settings():
    keys = [
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(keys) == len(set(keys)), "duplicate keys in .env.example"
    settings_text = (ROOT / "app" / "core" / "settings.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'"(IZMIR_MCP_[A-Z0-9_]+)"', settings_text))
    missing = declared - set(keys)
    assert not missing, f".env.example misses {sorted(missing)}"
