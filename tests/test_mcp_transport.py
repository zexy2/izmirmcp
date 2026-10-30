from __future__ import annotations

import pytest

from app.core.mcp_transport import INVALID_REQUEST, PARSE_ERROR, validate_message


def test_accepts_a_minimal_request():
    ok, problem, request_id = validate_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert ok is True
    assert problem is None
    assert request_id == 1


def test_accepts_a_notification_without_id():
    ok, _problem, _rid = validate_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert ok is True


def test_rejects_a_non_object_message():
    ok, problem, _rid = validate_message([1, 2, 3])
    assert ok is False
    assert "object" in problem


def test_rejects_a_wrong_jsonrpc_version():
    ok, problem, _rid = validate_message({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert ok is False
    assert "2.0" in problem


def test_rejects_a_missing_method():
    ok, problem, rid = validate_message({"jsonrpc": "2.0", "id": 7})
    assert ok is False
    assert "method" in problem
    assert rid == 7


def test_rejects_a_non_string_method():
    ok, _problem, _rid = validate_message({"jsonrpc": "2.0", "id": 1, "method": 5})
    assert ok is False


def test_rejects_an_oversized_method():
    ok, _problem, _rid = validate_message({"jsonrpc": "2.0", "id": 1, "method": "x" * 500})
    assert ok is False


def test_rejects_bool_id():
    ok, problem, _rid = validate_message({"jsonrpc": "2.0", "id": True, "method": "ping"})
    assert ok is False
    assert "id" in problem


def test_rejects_an_oversized_id():
    ok, _problem, _rid = validate_message({"jsonrpc": "2.0", "id": "x" * 200, "method": "ping"})
    assert ok is False


def test_rejects_scalar_params():
    ok, problem, _rid = validate_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "nope"})
    assert ok is False
    assert "params" in problem


def test_accepts_object_and_array_params():
    assert validate_message({"jsonrpc": "2.0", "id": 1, "method": "a", "params": {}})[0]
    assert validate_message({"jsonrpc": "2.0", "id": 1, "method": "a", "params": []})[0]


def test_error_codes_are_protocol_values():
    assert PARSE_ERROR == -32700
    assert INVALID_REQUEST == -32600
