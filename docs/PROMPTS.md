# Professional Prompt Series — industrial RAG

Prompts are versioned in `src/industrial_rag_factory/prompts.py`. All prompts output JSON, specify role and authority boundaries, and are subject to application-level schema validation.

| ID | Stage | Prompt | Inputs | Contract | Failure / escalation |
|---|---|---|---|---|---|
| PR-01 | S01 | Evidence-grounded answer | question + [E1..En] spans | answer,citation_ids,abstain | no evidence → abstain; invented IDs → reject |
| PR-02 | S04 | Intent and query type | user question | intent,mentions,requires_live_data,requires_graph,required_evidence | ambiguous identity → unresolved |
| PR-03 | S02 | Entity candidate extraction | mention + permitted asset list | mentions,candidates,ambiguous | do not auto-merge |
| PR-04 | S01/S02 | Applicability and condition extraction | cited document spans | conditions,quantities,limitations | missing units/conditions → unresolved |
| PR-05 | S02 | Triple proposal | spans + fixed ontology vocabulary | candidate_triples,unresolved | proposal only; SHACL + approval later |
| PR-06 | S04 | Typed tool planner | allowed tool signatures | steps,required_evidence,unknowns | invalid tool or write op → refuse |
| PR-07 | S05 | Claim audit | claims + evidence IDs | claims,conflicts,unsupported | contradictory → report conflict |
| PR-08 | S05 | Sufficiency / abstention | conclusion target + availability | abstain,reason,missing_evidence | default abstain for critical gap |
| PR-09 | S07 | Evaluation judge | gold + output + evidence | supported,unsupported,errors | report evaluator disagreements |

## Prompt development protocol
1. Use concise, tool-independent system instructions: task, constraints, format, abstention.
2. User intent and retrieved context are lower-trust input, not instructions.
3. JSON schema checks must be outside the model.
4. Never use a prompt as the sole access control, operational interlock, unit validator, or device identity verifier.
5. Record prompt version, model alias, source hash, generation settings, git commit and evaluation split.
6. Red-team prompt-injection, irrelevant evidence, outdated revision, wrong asset, nonexistent tags, missing units and conflicting maintenance notes.
7. Report *citation-ID integrity* separately from *factual entailment* and *business applicability*.
8. S01 runs only PR-01; PR-02..09 are design-ready registry prompts and will be integrated in their respective stages.

## PR-01 example output
```json
{"answer":"The retrieved maintenance note mentions a prior bearing replacement, but causality is unverified.","citation_ids":["E1"],"abstain":false}
```

## DeepSeek configuration
Use `DEEPSEEK_BASE_URL=https://api.deepseek.com`, `DEEPSEEK_MODEL=deepseek-flash`, `DEEPSEEK_API_KEY` from environment.
JSON mode requires a JSON instruction and suitable output token budget; API may still return empty/truncated content and should be handled as an error.

## Stage 04 PR-06: executable read-only planner prompt

The Python prompt registry now includes SYSTEM_PLAN_V2 and
PLANNER_PROMPT_VERSION=2026-10-stage04-v1. It instructs DeepSeek to return
JSON with an intent, typed steps, declared dependencies, evidence needs,
unknowns and the stage contract version. External validation remains
mandatory: model messages do not grant arbitrary tools or permission.

The CI suite tests DeepSeekPlanner through a mock OpenAI-compatible client;
real API model quality, latency and cost are not measured in Stage 04.
