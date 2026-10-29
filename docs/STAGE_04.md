# Stage 04 - Typed Query Planner and Read-Only Agent Orchestration

## Goal

Introduce an offline-first, verifiable query planner and DAG execution runtime
above the Stage 01 document index, Stage 02 ontology graph and Stage 03
structured/temporal evidence services. Preserve Flask and configurable
DeepSeek API. No production OT access or autonomous physical operations.

## Components

| Category | Source | Responsibilities |
|---|---|---|
| Schema | agent/contracts.py | PlanStep, QueryPlan, explicit tool fields and validation |
| Planning | agent/planner.py | RulePlanner and optional DeepSeekPlanner |
| Tools | agent/tools.py | Six scoped read-only operator contracts |
| Runtime | agent/runner.py | Topological scheduling, refs, bounded soft deadlines |
| Service | agent/service.py | Trusted settings, user query and result façade |
| Evaluation | agent/evaluation.py | Eight synthetic planner/execution gold cases |
| Transport | CLI and Flask | Local-only command and question-only JSON endpoint |

## Query plan contract

Version stage04-v1. Each step declares an ID, allowlisted tool, strict
argument object, dependencies, timeout in 50..5000 ms and optional retry
count 0..1. Maximum eight steps per plan. Dependency cycles, undeclared
references, identity override, unknown tools and arbitrary commands fail
before dispatch.

A reference from a graph step may read identity.canonical_id from an
earlier entity.resolve step, but only if that step is a declared dependency.
Arguments are checked both when the plan is parsed and after dynamic
reference resolution. An unresolved reference fails the step and blocks
dependent steps.

Tool names: document.search, entity.resolve, graph.traverse, mes.by_batch,
historian.read, batch.assess. The model cannot register new names.

## Execution and failure semantics

Valid plans execute in deterministic topological order. Step states are
succeeded, failed, blocked; overall states completed, partial, failed.
Each trace event has step ID, tool name, attempts, duration and a generic
error code; no plaintext source credentials or prompt contents are logged.

A transient, idempotent read may retry once. A timeout is never retried,
because Python threads cannot be forcibly stopped. Budget and result-size
limits are enforced, and dependent steps are blocked after failure. The
Stage 04 timeout is **soft**, not a production process-level cancellation.

## DeepSeek planner (opt-in)

DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_API_KEY is read from environment, never source code.
IRF_PLANNER=deepseek enables the paid JSON planning path.
Default IRF_PLANNER=rules requires no API key or provider call.

The provider output is untrusted and must conform to the exact plan schema.
Offline CI only tests provider adapter behavior using a fake client.
No claim is made that real DeepSeek tool-selection performance was measured.

## Local runbook

    pip install -e '.[api,llm,pdf,docx,ontology,dev]'
    irf agent-plan "B-104 振动异常"
    irf agent-query "B-104 振动异常"
    irf agent-query "ERP EQ-00037 的测点"
    irf agent-evaluate
    python scripts/stage04_evaluate.py
    pytest -q
    ruff check src tests

The development Flask endpoint POST /v1/agent/query accepts the JSON object
with exactly one question field. The caller cannot choose an execution
planner, tenant, group, or toolset; these remain server-side settings.

## Acceptance test matrix

- [x] Typed schema, bounded plan and tool allowlist.
- [x] Cycle and reference validation; dependent steps cannot execute after failures.
- [x] Runtime reference resolution followed by schema revalidation.
- [x] Tenant/group filtering remains inside each read-only source adapter.
- [x] Re-entrant SQLite reads use independent thread-local connections.
- [x] Safe transient retries, timeout without retry, result and total budget.
- [x] Redacted step telemetry without secret-bearing parameter dumps.
- [x] DeepSeek JSON adapter uses mock provider in offline CI.
- [x] Eight synthetic planner/execution benchmark cases with CI JSON artifact.
- [x] Stage 01–03 regression tests remain part of the test suite.
- [ ] Real DeepSeek production credentials, paid performance/cost benchmarks.
- [ ] Killable worker-process isolation and distributed cancellation.
- [ ] Production authenticated principals, policy revocation and OT security.
- [ ] Claim-level source entailment, uncertainty and abstention (Stage 05).

## Test fixture limitations

RulePlanner uses simple regular expressions and a fixed synthetic October
2026 reference timestamp for equipment mappings. It cannot infer actual
historical state, live data, root cause or manufacturing quality. Eight
fixture cases are integration smoke tests, not general planner accuracy.

## Stage 05 handoff

Introduce EvidenceBundle, ClaimGraph, supported/refuted/conflicting/insufficient
states, provenance and applicability verification; abstain on unsupported
natural-language assertions. Keep the Stage 04 typed tool boundary intact.
