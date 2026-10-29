"""Deterministic DAG executor with bounded read-only tools and redacted trace.

Thread timeouts return promptly but do NOT kill a running Python function;
Stage 04 tools are local, read-only and idempotent. Worker-process termination
is explicitly a later production-hardening task.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .contracts import PlanValidationError, QueryPlan, ref_info
from .tools import RunContext, ToolRegistry, TransientToolError


def resolve_refs(value: Any, completed: dict[str, dict]) -> Any:
    ref=ref_info(value)
    if ref:
        step_id,path=ref
        if step_id not in completed:
            raise PlanValidationError("Referenced step is unavailable")
        current: Any = completed[step_id]
        for fragment in path.split("."):
            if isinstance(current, dict) and fragment in current:
                current=current[fragment]
            elif isinstance(current, list) and fragment.isdigit() and int(fragment)<len(current):
                current=current[int(fragment)]
            else:
                raise PlanValidationError("Referenced output field does not exist")
        return deepcopy(current)
    if isinstance(value, dict):
        return {key:resolve_refs(item,completed) for key,item in value.items()}
    if isinstance(value,list):
        return [resolve_refs(item,completed) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class ExecutionPolicy:
    total_timeout_ms: int = 15000
    max_steps: int = 8
    max_output_chars: int = 30000
    circuit_breaker_after: int = 2

    def __post_init__(self):
        if (not 100 <= self.total_timeout_ms <= 60000 or
            not 1 <= self.max_steps <= 8 or
            not 1000 <= self.max_output_chars <= 200000 or
            not 1 <= self.circuit_breaker_after <= 5):
            raise ValueError("Invalid execution policy")


class DAGRunner:
    def __init__(self, registry: ToolRegistry, policy: ExecutionPolicy | None = None):
        self.registry = registry
        self.policy = policy or ExecutionPolicy()

    @staticmethod
    def _once(registry: ToolRegistry, tool: str, args: dict,
              context: RunContext, timeout_ms: int) -> dict:
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="irf-readonly")
        future=executor.submit(registry.execute,tool,args,context)
        try:
            return future.result(timeout=timeout_ms / 1000)
        except FutureTimeout:
            future.cancel()
            raise
        finally:
            # On a timeout the thread may finish later. No Stage 04 write tools exist.
            executor.shutdown(wait=False,cancel_futures=True)

    def run(self, plan: QueryPlan | dict, context: RunContext) -> dict:
        raw=plan.to_dict() if isinstance(plan,QueryPlan) else plan
        checked=QueryPlan.from_dict(raw)
        if len(checked.steps)>self.policy.max_steps:
            raise PlanValidationError("Step budget exceeded")
        if not set(s.tool for s in checked.steps) <= set(self.registry.names()):
            raise PlanValidationError("Plan references unregistered tools")
        started=time.monotonic()
        deadline=started+self.policy.total_timeout_ms/1000
        results: dict[str,dict]={}
        states: dict[str,str]={}
        trace=[]
        circuit:dict[str,int]={}

        for step in checked.ordered_steps():
            if any(states.get(dependency)!="succeeded" for dependency in step.depends_on):
                states[step.id]="blocked"
                trace.append({"step_id":step.id,"tool":step.tool,"state":"blocked",
                              "attempts":0,"elapsed_ms":0,"error_code":"dependency_failed"})
                continue
            if circuit.get(step.tool,0)>=self.policy.circuit_breaker_after:
                states[step.id]="failed"
                trace.append({"step_id":step.id,"tool":step.tool,"state":"failed",
                              "attempts":0,"elapsed_ms":0,"error_code":"circuit_open"})
                continue
            outcome=None
            error=None
            attempts=0
            step_start=time.monotonic()
            try:
                args=resolve_refs(step.args,results)
                # Arguments are revalidated AFTER reference resolution by ToolRegistry.
                for attempt in range(step.max_retries+1):
                    attempts=attempt+1
                    available_ms=int((deadline-time.monotonic())*1000)
                    if available_ms<=0:
                        error="total_budget_exceeded"
                        break
                    try:
                        outcome=self._once(self.registry,step.tool,args,context,
                                           min(step.timeout_ms,available_ms))
                        if len(json.dumps(outcome,ensure_ascii=False)) > self.policy.max_output_chars:
                            outcome=None
                            error="output_budget_exceeded"
                        break
                    except FutureTimeout:
                        error="step_timeout"
                        # Never retry a timed-out call: its thread may still be running.
                        break
                    except TransientToolError:
                        circuit[step.tool]=circuit.get(step.tool,0)+1
                        error="transient_tool_error"
                        if (attempt>=step.max_retries or
                                circuit[step.tool]>=self.policy.circuit_breaker_after):
                            break
                    except (ValueError,TypeError,KeyError,RuntimeError):
                        error="tool_error"
                        break
            except (PlanValidationError,ValueError,TypeError,KeyError):
                error="invalid_resolved_arguments"
            elapsed=int((time.monotonic()-step_start)*1000)
            if outcome is None:
                states[step.id]="failed"
                trace.append({"step_id":step.id,"tool":step.tool,"state":"failed",
                              "attempts":attempts,"elapsed_ms":elapsed,
                              "error_code":error or "unknown_error"})
            else:
                states[step.id]="succeeded"
                results[step.id]=outcome
                trace.append({"step_id":step.id,"tool":step.tool,"state":"succeeded",
                              "attempts":attempts,"elapsed_ms":elapsed,"error_code":None})
        completed=sum(s=="succeeded" for s in states.values())
        overall="completed" if completed==len(checked.steps) else (
            "partial" if completed else "failed")
        return {"status":overall,"intent":checked.intent,"planner_contract":checked.version,
                "results":results,"step_status":states,"trace":trace,
                "unknowns":list(checked.unknowns),
                "limitations":[
                  "Execution success does not prove evidence truth or answer entailment.",
                  "Stage 04 local read-only tools are not industrial operational controls.",
                ],
                "elapsed_ms":int((time.monotonic()-started)*1000)}
