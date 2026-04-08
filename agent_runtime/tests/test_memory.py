"""Tests for the 3-layer memory model."""
from pathlib import Path

from agent_runtime.prompt.memory import list_topics, load_memory_index, load_rules, load_topic


class TestLoadRules:
    def test_load_existing_file(self, tmp_path):
        agent_md = tmp_path / "AGENT.md"
        agent_md.write_text("# Rules\nBe helpful.")
        result = load_rules(agent_md)
        assert "AGENT.md" in result
        assert "Be helpful" in result

    def test_load_multiple_files(self, tmp_path):
        (tmp_path / "AGENT.md").write_text("Rule A")
        (tmp_path / "PROJECT.md").write_text("Rule B")
        result = load_rules(tmp_path / "AGENT.md", tmp_path / "PROJECT.md")
        assert "Rule A" in result
        assert "Rule B" in result

    def test_missing_file_skipped(self, tmp_path):
        result = load_rules(tmp_path / "nonexistent.md")
        assert result == ""

    def test_empty_file_skipped(self, tmp_path):
        (tmp_path / "AGENT.md").write_text("")
        result = load_rules(tmp_path / "AGENT.md")
        assert result == ""


class TestLoadMemoryIndex:
    def test_load_existing_index(self, tmp_path):
        idx = tmp_path / "MEMORY.md"
        idx.write_text("- [Auth](auth.md) — auth system notes\n- [DB](db.md) — database schema")
        result = load_memory_index(idx)
        assert "Auth" in result
        assert "DB" in result

    def test_missing_index(self, tmp_path):
        result = load_memory_index(tmp_path / "MEMORY.md")
        assert result == ""

    def test_index_truncated_at_200_lines(self, tmp_path):
        idx = tmp_path / "MEMORY.md"
        lines = [f"- entry {i}" for i in range(300)]
        idx.write_text("\n".join(lines))
        result = load_memory_index(idx)
        assert "truncated" in result
        assert result.count("\n") <= 201  # 200 lines + truncation message


class TestLoadTopic:
    def test_load_existing_topic(self, tmp_path):
        topic = tmp_path / "auth.md"
        topic.write_text("# Auth\nOAuth2 flow details...")
        result = load_topic(topic)
        assert "OAuth2" in result

    def test_missing_topic(self, tmp_path):
        result = load_topic(tmp_path / "nope.md")
        assert "not found" in result


class TestListTopics:
    def test_list_topics(self, tmp_path):
        (tmp_path / "auth.md").write_text("auth")
        (tmp_path / "db.md").write_text("db")
        (tmp_path / "MEMORY.md").write_text("index")  # excluded
        (tmp_path / "AGENT.md").write_text("rules")   # excluded

        topics = list_topics(tmp_path)
        names = [t.name for t in topics]
        assert "auth.md" in names
        assert "db.md" in names
        assert "MEMORY.md" not in names
        assert "AGENT.md" not in names

    def test_empty_dir(self, tmp_path):
        assert list_topics(tmp_path) == []

    def test_nonexistent_dir(self):
        assert list_topics("/nonexistent") == []
