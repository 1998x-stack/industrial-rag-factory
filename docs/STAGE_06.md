# Stage 06 — Security, Governance and OT Boundaries

## Scope and security claim

This stage implements a **development-only security gate**, not enterprise
production authentication. Everything runs against synthetic industrial
fixtures. No real OT network, PLC, SCADA, historian connector or control
interface is contacted. Passing Stage 06 tests does not certify an
installation, a safety instrumented system, or OT network segmentation.

The primary objective is to establish a *testable* deny-by-default trust
boundary around the already implemented Stage 01–05 pipeline while retaining
backwards-compatible offline development.

## Threat model and protection layers

| Area | Stage 06 mechanism | Explicit limitation |
| --- | --- | --- |
| Identity | HMAC short-lived developer capability, audience+expiry | No SSO/OIDC, MFA, identity proofing |
| Revocation | Per-principal active flag/generation and policy reload | Filesystem is locally trusted; no distributed revocation SLA |
| Authorization | Server-owned tenant, groups and explicit tool list | Synthetic ACL labels; not independent policy authority |
| Record scope | Nested source_uri prefix checks, fail-closed | No fine-grained ERP/MES external source governance |
| Prompt injection | Untrusted plan schemas, fixed RulePlanner in secure mode | Does not prove safe general LLM prompt isolation |
| Sensitive fields | Explicit output field redaction after source checks | No semantic PII/secret discovery; no data loss prevention suite |
| Auditing | Local HMAC chain, event pseudonyms, integrity check | Cannot prove write-once retention or non-repudiation |
| OT | No live protocol driver; denylist for known OT target schemes | Not a firewall, DMZ or proven network separation |
| Response check | Policy re-read after execution before output | Final response may race a concurrent policy change |

## S06 code map

- `security/auth.py`: local short-lived HMAC capability verification and
  trusted test mint function; deliberately no HTTP enrollment endpoint.
- `security/policy.py`: strict JSON principal policies, current generation,
  tool/scope/source prefixes and source traversal.
- `security/gateway.py`: scoped read-only ToolRegistry and S05 verification,
  rule-only planner and response-time redaction.
- `security/boundary.py`: independent six-tool allowlist and protocol guard.
- `security/audit.py`: POSIX local HMAC-chained minimal event log.
- `config/security_demo_policy.json`: synthetic principals only.
- `tests/test_stage06.py`: adversarial regression cases.
- `scripts/stage06_evaluate.py`: standalone, hashed offline evaluation.

## HTTP security mode

By default, security mode is OFF. The original development /v1 routes are
unauthenticated, unchanged, and must not be exposed to untrusted networks.

With `IRF_SECURITY_MODE=demo` and a trusted 32-byte (minimum) secret,
Flask denies all previous /v1 endpoints and adds:

- `POST /v1/secure/grounding/verify`: JSON containing canonical batch_id
  and optional typed bounded claims, NOT evidence or selected tools.
- `POST /v1/secure/agent/query`: JSON containing only a question. It uses
  **RulePlanner** regardless of the other configured model planner.

The token must be sent in `Authorization: Bearer <capability>` and is minted
only from a trusted local test/admin context; there is intentionally no HTTP
login or token-mint route.

## Revocation semantics

A policy change is applied on disk by the local administrator. For immediate
token invalidation, set active=false or increment the principal generation.
The gateway reads policy on each request, before and after each read-only
tool call, and before response serialization. A token itself supplies only
the subject, generation, audience and short expiration, never user groups.

Operational caveat: the filesystem policy is trusted, and a caller with local
filesystem write privileges could tamper with that trust anchor. Enterprise
policy signing, distributed consistency and user identity verification
remain unimplemented.

## Local verification

```bash
pip install -e '.[api,llm,pdf,docx,ontology,dev]'
python scripts/stage06_evaluate.py
pytest -q
ruff check src tests
```

To manually run secure endpoints, configure a random secret and enable
demo mode. A test capability can be minted only within the same trusted
local process (e.g., a Python shell with `TokenVerifier`,
`PolicyStore`, `mint_demo_token`). NEVER use the bundled test secrets for
non-test deployments.

Do not put capability tokens, API keys or sensitive raw evidence into
GitHub Actions artifacts, logs, tickets or README examples. The offline
evaluation script does not publish them.

## Acceptance checklist

- [x] Signed, audience-bound, short-lived developer capability contract.
- [x] Subject active flag + generation revocation and policy rechecks.
- [x] Fixed read-only tool rights and tenant/group context loaded server-side.
- [x] Source prefix checks and output redaction.
- [x] Legacy unsecured /v1 route bypass blocked in demo security mode.
- [x] Token expiry/tamper, unauthorized tool, data scope and revoked user tests.
- [x] Query-injection attempts do not authorize a new or mutating tool.
- [x] HMAC chained privacy-minimized local audit with tamper detection.
- [x] Simulated OT protocol targets and unknown tools rejected by pure guards.
- [x] CI Python 3.10/3.12 and deterministic offline security evaluation.
- [ ] Enterprise IdP/OIDC+MFA, robust authentication and token issuance.
- [ ] Source-of-truth per-document/field ACL and DLP scanning.
- [ ] Immutable external audit with retention and independent verification.
- [ ] Real OT firewall/DMZ, network-level deny-all and penetration review.
- [ ] Process cancellation, distributed policy freshness and secret rotation.
- [ ] Approved architecture, release checklist and operational certification.

**Exit status:** development prototype delivered; **production approval NOT granted.**

## References

- NIST SP 800-82 Rev.3 (final): https://csrc.nist.gov/pubs/sp/800/82/r3/final
- NIST SP 800-82 Rev.4: initial public draft as of October 2026, not final
- OWASP 2025 LLM Top 10: https://genai.owasp.org/llm-top-10/

## Stage 07 handoff

Measure security-gated retrieval versus unrestricted offline baselines,
sensitivity to ACL scope, and the effects of masking on retrieval utility
without making unauthorized evidence accessible. Continue Stage 07 factorial
ablation across parser, chunks, retrieval, graph, evidence verification,
planner, prompt and model, with fixed splits and confidence intervals.
