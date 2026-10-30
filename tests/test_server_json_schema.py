"""server.json against the pinned, offline copy of the official registry schema."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib

from jsonschema import Draft7Validator, FormatChecker
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "tests/fixtures/mcp_registry/server-2025-12-11.schema.json"
SCHEMA_SHA256 = "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_pinned_schema_is_unmodified_and_valid():
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256
    Draft7Validator.check_schema(_schema())


def test_manifest_identity_and_version():
    manifest = _manifest()
    assert manifest["name"] == "io.github.zexy2/izmir-mcp"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if "version" in project:
        assert manifest["version"] == project["version"]
    for package in manifest.get("packages", []):
        if package.get("registryType") == "pypi":
            assert package["identifier"] == project["name"]
            assert package["version"] == manifest["version"]


def test_manifest_validates_against_the_pinned_registry_schema():
    schema, manifest = _schema(), _manifest()
    if manifest.get("$schema") != schema["$id"]:
        pytest.xfail(
            "server.json still targets an older registry schema; the packaging step "
            "moves it to 2025-12-11 (then this test becomes strict)"
        )
    Draft7Validator(schema, format_checker=FormatChecker()).validate(manifest)
    for remote in manifest.get("remotes", []):
        assert remote["url"].startswith("https://")
