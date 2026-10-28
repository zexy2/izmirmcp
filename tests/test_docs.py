"""Documentation pass (P3): docs must be derived from code, not invented.

These tests read repository files only; no network, no live source. Each
assertion pins a fact that also exists in code, so a behaviour change that
forgets the docs turns the suite red instead of shipping a stale contract.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import settings as settings_module
from app.core.envelope import ResponseEnvelope
from app.core.settings import Settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, create_mcp_server
from app.services import sources as extra_sources

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONTRACT = DOCS / "response-contract.md"
TOOL_REF = DOCS / "tool-reference.md"
DEPLOYMENT = DOCS / "deployment.md"
SOURCES_DOC = DOCS / "sources.md"
MONITORING = DOCS / "monitoring.md"
README = ROOT / "README.md"

ALL_DOCS = (CONTRACT, TOOL_REF, DEPLOYMENT, SOURCES_DOC, MONITORING)


def _text(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text(encoding="utf-8")


def _settings_fields() -> dict:
    return Settings.__dataclass_fields__


def _env_names() -> list[str]:
    """Every IZMIR_MCP_* name read by get_settings()."""
    source = (ROOT / "app" / "core" / "settings.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'"(IZMIR_MCP_[A-Z0-9_]+)"', source)))


def test_all_five_documents_exist_and_are_non_trivial():
    for path in ALL_DOCS:
        text = _text(path)
        assert len(text.splitlines()) >= 25, f"{path.name} is too thin to document anything"
        assert text.lstrip().startswith("# "), f"{path.name} needs an H1 title"


def test_readme_links_every_document():
    text = _text(README)
    for path in ALL_DOCS:
        assert f"docs/{path.name}" in text, f"README must link docs/{path.name}"


def test_response_contract_lists_every_envelope_field():
    contract = _text(CONTRACT)
    for field in ResponseEnvelope.model_fields:
        assert f"`{field}`" in contract, f"envelope field {field} is undocumented"


def test_response_contract_documents_every_error_code_in_code():
    contract = _text(CONTRACT)
    app_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app").rglob("*.py")
    )
    codes = sorted(set(re.findall(r'code="([a-z_]+)"', app_text)))
    assert "validation_error" in codes
    for code in codes:
        assert f"`{code}`" in contract, f"error code {code} is undocumented"


def test_response_contract_documents_freshness_statuses():
    contract = _text(CONTRACT)
    for status in ("fresh", "stale", "unknown", "broken"):
        assert f"`{status}`" in contract


def test_response_contract_documents_result_scopes_in_code():
    contract = _text(CONTRACT)
    app_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "app" / "services").glob("*.py")
    )
    # Only result_info scopes, not Source(scope=...) declarations.
    scopes = sorted(set(re.findall(r'scope="([a-z_]+)"', app_text)))
    source_scopes = set(re.findall(r'^\s+scope="([a-z_]+)"', app_text, flags=re.MULTILINE))
    scopes = [scope for scope in scopes if scope not in source_scopes]
    assert scopes
    for scope in scopes:
        assert f"`{scope}`" in contract, f"result_info scope {scope} is undocumented"


def test_tool_reference_covers_every_advertised_tool():
    text = _text(TOOL_REF)
    for name in DEFAULT_TOOL_NAMES:
        assert f"`{name}`" in text, f"tool {name} is undocumented"


@pytest.mark.asyncio
async def test_tool_reference_inputs_match_advertised_schemas():
    """Every advertised input property must be named in the tool's doc section."""
    text = _text(TOOL_REF)
    server = create_mcp_server(Settings())
    for tool in await server.list_tools():
        assert f"### `{tool.name}`" in text, f"{tool.name} needs its own section"
        section = text.split(f"### `{tool.name}`", 1)[1].split("\n### ", 1)[0]
        for prop in tool.input_schema.get("properties", {}):
            assert f"`{prop}`" in section, f"{tool.name}.{prop} input is undocumented"


def test_tool_reference_states_the_tool_count():
    text = _text(TOOL_REF)
    count = len(DEFAULT_TOOL_NAMES)
    assert re.search(rf"\b{count}\b", text)


def test_deployment_documents_every_environment_variable():
    text = _text(DEPLOYMENT)
    names = _env_names()
    assert names, "expected IZMIR_MCP_* variables in settings.py"
    for name in names:
        assert f"`{name}`" in text, f"env var {name} is undocumented"


def test_deployment_documents_defaults_that_match_settings():
    text = _text(DEPLOYMENT)
    defaults = Settings()
    for field in ("default_limit", "max_limit", "max_radius_m"):
        value = getattr(defaults, field)
        assert f"`{field}`" in text or field in text
        assert re.search(rf"\b{value}\b", text), f"{field}={value} missing from deployment doc"


def test_deployment_documents_http_status_codes_from_guards():
    """Guard rejections are HTTP codes, not envelopes; they must be listed."""
    text = _text(DEPLOYMENT)
    for code in ("413", "429", "401", "403", "503"):
        assert code in text, f"HTTP {code} guard response is undocumented"
    for error_code in ("payload_too_large", "rate_limited", "unauthorized",
                        "origin_not_allowed", "server_busy"):
        assert error_code in text


def test_deployment_lists_the_console_scripts_and_transports():
    text = _text(DEPLOYMENT)
    for entry in ("izmir-mcp", "izmir-mcp-stdio", "app.main", "app.stdio", "/mcp/"):
        assert entry in text, f"{entry} is undocumented"


def test_sources_doc_lists_every_declared_source_publisher():
    text = _text(SOURCES_DOC)
    publisher_names = {
        value.name
        for value in vars(extra_sources).values()
        if hasattr(value, "publisher") and hasattr(value, "scope")
    }
    assert publisher_names
    for name in publisher_names:
        assert name in text, f"source {name} is missing from sources.md"


def test_sources_doc_records_unavailable_endpoints_honestly():
    text = _text(SOURCES_DOC)
    lowered = text.lower()
    assert "500" in text and "ariza" in lowered.replace("ı", "i"), "İZSU fault failure"
    assert "izban" in lowered
    assert "odbl" in lowered
    assert "lisans" in lowered


def test_sources_doc_points_at_reports_evidence():
    text = _text(SOURCES_DOC)
    assert "reports/" in text


def test_monitoring_documents_every_http_endpoint():
    text = _text(MONITORING)
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for route in re.findall(r'Route\("([^"]+)"', main_source):
        assert route in text, f"endpoint {route} is undocumented"


def test_monitoring_documents_readyz_never_checks_upstream():
    text = _text(MONITORING)
    assert "not_checked" in text
    assert "upstream_health" in text


def test_monitoring_documents_log_fields_from_code():
    text = _text(MONITORING)
    log_source = (ROOT / "app" / "core" / "http_logging.py").read_text(encoding="utf-8")
    for field in re.findall(r'^\s+"([a-z_]+)"\s*:', log_source, flags=re.MULTILINE):
        assert f"`{field}`" in text, f"access log field {field} is undocumented"
    assert "izmir_mcp.access" in text
