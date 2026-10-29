"""Stage 04 read-only application orchestration with explicit planner opt-in."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from industrial_rag_factory.config import Settings

from .planner import DeepSeekPlanner, RulePlanner
from .runner import DAGRunner
from .tools import RunContext, ToolRegistry, build_tool_registry


class AgentService:
    def __init__(self, settings: Settings, *, registry: ToolRegistry | None = None,
                 planner: Any = None, root: str | Path = ".", mode: str = "rules"):
        if mode not in ("rules","deepseek"):
            raise ValueError("Planner mode must be rules or deepseek")
        self.settings=settings
        self.registry=registry or build_tool_registry(settings,root)
        self._owns_registry=registry is None
        if planner is None:
            planner=(RulePlanner() if mode=="rules" else DeepSeekPlanner(
                api_key=settings.deepseek_api_key,base_url=settings.deepseek_base_url,
                model=settings.deepseek_model))
        self.planner=planner
        self.runner=DAGRunner(self.registry)

    def plan(self, question: str) -> dict:
        return self.planner.plan(question).to_dict()

    def query(self, question: str) -> dict:
        proposal=self.planner.plan(question)
        context=RunContext(self.settings.tenant_id,self.settings.groups)
        outcome=self.runner.run(proposal,context)
        outcome["planner"]=getattr(self.planner,"name","unknown")
        outcome["plan"]=proposal.to_dict()
        return outcome

    def close(self) -> None:
        if self._owns_registry:
            self.registry.close()
