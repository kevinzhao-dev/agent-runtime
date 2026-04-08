"""Tests for the 4-layer prompt builder."""
from agent_runtime.prompt import PromptConfig, PromptLayer, build_prompt


class TestPromptLayer:
    def test_defaults(self):
        layer = PromptLayer(name="base", content="hello", source="base")
        assert layer.cacheable is True

    def test_dynamic_layer(self):
        layer = PromptLayer(name="mode", content="plan", source="runtime", cacheable=False)
        assert layer.cacheable is False


class TestBuildPrompt:
    def test_base_only(self):
        config = build_prompt()
        assert len(config.layers) == 1
        assert config.layers[0].name == "base"
        assert config.layers[0].cacheable is True
        assert "AI agent" in config.system_prompt

    def test_all_layers(self):
        config = build_prompt(
            project_rules="Follow PEP8",
            runtime_mode="Plan mode active",
            task_context="Working on tests",
            tool_descriptions="- read_file: reads files",
        )
        assert len(config.layers) == 4
        names = [l.name for l in config.layers]
        assert names == ["base", "project_rules", "runtime_mode", "task_context"]

    def test_layer_ordering(self):
        """Layers are in correct precedence order."""
        config = build_prompt(
            project_rules="rules",
            runtime_mode="mode",
            task_context="context",
        )
        prompt = config.system_prompt
        base_pos = prompt.index("[base]")
        project_pos = prompt.index("[project]")
        runtime_pos = prompt.index("[runtime]")
        task_pos = prompt.index("[task]")
        assert base_pos < project_pos < runtime_pos < task_pos

    def test_source_labels_in_output(self):
        config = build_prompt(project_rules="rules here")
        assert "[base]" in config.system_prompt
        assert "[project]" in config.system_prompt

    def test_cache_dynamic_split(self):
        config = build_prompt(
            project_rules="cacheable rules",
            runtime_mode="dynamic mode",
            task_context="dynamic task",
        )
        cacheable = config.cacheable_prefix
        assert "cacheable rules" in cacheable
        assert "dynamic mode" not in cacheable
        assert "dynamic task" not in cacheable

    def test_empty_layers_omitted(self):
        config = build_prompt(project_rules="", runtime_mode="")
        assert len(config.layers) == 1  # only base

    def test_tool_descriptions_in_base(self):
        config = build_prompt(tool_descriptions="- bash: run commands")
        assert "bash: run commands" in config.system_prompt

    def test_get_layer(self):
        config = build_prompt(project_rules="rules")
        assert config.get_layer("base") is not None
        assert config.get_layer("project_rules") is not None
        assert config.get_layer("nonexistent") is None
