"""Multi-agent system — spawn, coordinate, observe."""
from agent_runtime.agents.config import AgentConfig, AgentResult
from agent_runtime.agents.manager import AgentManager
from agent_runtime.agents.coordinator import WorkflowStep, impl_then_verify, run_workflow
