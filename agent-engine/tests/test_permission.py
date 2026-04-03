"""Tests for tools/permission.py — PermissionGate."""

import pytest

from tools.permission import PermissionDecision, PermissionGate, PermissionMode


class _FakeReadOnlyTool:
    def is_read_only(self):
        return True

    def is_destructive(self):
        return False


class _FakeDestructiveTool:
    def is_read_only(self):
        return False

    def is_destructive(self):
        return True


def test_yolo_mode_allows_all():
    gate = PermissionGate(mode=PermissionMode.YOLO)
    assert gate.check(_FakeReadOnlyTool()) == PermissionDecision.ALLOW
    assert gate.check(_FakeDestructiveTool()) == PermissionDecision.ALLOW


def test_strict_mode_asks_all():
    gate = PermissionGate(mode=PermissionMode.STRICT)
    assert gate.check(_FakeReadOnlyTool()) == PermissionDecision.ASK
    assert gate.check(_FakeDestructiveTool()) == PermissionDecision.ASK


def test_default_mode_allows_readonly():
    gate = PermissionGate(mode=PermissionMode.DEFAULT)
    assert gate.check(_FakeReadOnlyTool()) == PermissionDecision.ALLOW


def test_default_mode_asks_destructive():
    gate = PermissionGate(mode=PermissionMode.DEFAULT)
    assert gate.check(_FakeDestructiveTool()) == PermissionDecision.ASK


@pytest.mark.asyncio
async def test_request_permission_with_callback():
    async def always_allow(name, inp):
        return True

    gate = PermissionGate(ask_callback=always_allow)
    assert await gate.request_permission("bash", {"command": "rm -rf /"}) is True


@pytest.mark.asyncio
async def test_request_permission_no_callback_denies():
    gate = PermissionGate()
    assert await gate.request_permission("bash", {}) is False
