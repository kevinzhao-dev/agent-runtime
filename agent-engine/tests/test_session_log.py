"""Tests for engine/session_log.py — session file logger."""

import json
from pathlib import Path

from engine.session_log import SessionLog


def test_creates_log_file(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    assert log.path.exists()
    log.close()


def test_writes_session_start(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.close()
    lines = log.path.read_text().strip().split("\n")
    first = json.loads(lines[0])
    assert first["event"] == "session_start"


def test_writes_session_end(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.close()
    lines = log.path.read_text().strip().split("\n")
    last = json.loads(lines[-1])
    assert last["event"] == "session_end"


def test_log_user_input(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_user_input("hello")
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "user_input"
    assert record["text"] == "hello"


def test_log_tool_use(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_tool_use("bash", "t1", {"command": "ls"})
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "tool_use"
    assert record["name"] == "bash"
    assert record["input"] == {"command": "ls"}


def test_log_tool_result(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_tool_result("t1", "output", False)
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "tool_result"
    assert record["content"] == "output"
    assert record["is_error"] is False


def test_log_error(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_error("broke", True)
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "error"
    assert record["recoverable"] is True


def test_log_done(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_done("end_turn", 3)
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "done"
    assert record["turn_count"] == 3


def test_log_command(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_command("/help")
    log.close()
    lines = log.path.read_text().strip().split("\n")
    record = json.loads(lines[1])
    assert record["event"] == "slash_command"
    assert record["command"] == "/help"


def test_all_records_have_timestamp(tmp_path):
    log = SessionLog(working_dir=str(tmp_path))
    log.log_user_input("test")
    log.log_done("end_turn", 1)
    log.close()
    for line in log.path.read_text().strip().split("\n"):
        record = json.loads(line)
        assert "ts" in record


def test_log_dir_created(tmp_path):
    wd = tmp_path / "deep" / "nested"
    log = SessionLog(working_dir=str(wd))
    assert (wd / ".agent-engine" / "logs").is_dir()
    log.close()
