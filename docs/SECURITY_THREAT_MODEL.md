# Industrial RAG Factory — Threat Model (S06 research implementation)

## Assets

1. Industrial documents, source metadata and structured operational records.
2. Canonical identity mappings and effective-time equipment relationships.
3. Historian observations and approved specifications.
4. Generated evidence, claims, source citations and trace metadata.
5. Developer capability secret, policy registry and audit log.

## Trust boundaries

- Client/LLM text is untrusted; only typed read-only operations are allowed.
- Authenticated developers are modelled by server-signed local capabilities;
  no user-controlled tenant or group labels are accepted.
- A trusted policy fixture gates tool access and source URI prefixes, with
  post-call and pre-response revalidation.
- A read-only adapter is NOT an authorized OT communications path. The
  research code contains no controller driver or actuator call.
- Local audit and filesystem are developer-owned, not independently trusted.

## Risks and controls

| Threat | Current mitigation | Residual risk |
| --- | --- | --- |
| Forged identity | HMAC and audience/time verification | Secret compromise, no IdP |
| Stale entitlement | Reload policy and compare active/generation | Local policy update race |
| Cross-tenant result | Server-selected tenant/groups through each S01-S05 layer | Fixture labels do not replace enterprise ACL |
| Legacy route bypass | Block all /v1/* except /v1/secure/* in demo mode | Default offline mode still has unauthenticated routes |
| Document injection | Treat contents as context; secure gateway uses deterministic planner | Cannot certify general LLM resistance |
| Arbitrary SQL/tools | Existing typed Stage 04 allowlist + independent S06 freeze | Future changes require code review |
| Sensitive evidence | Source-prefix gating and field redaction | No generalized PII recognition |
| Silent audit modification | HMAC chain checks on every append and authorization | File deletion or shared key compromise |
| OT control leakage | No control tool, no live driver, pure endpoint denylist | Network isolation not verified |

## Required production follow-up

- Conduct threat modelling and OT risk assessment with facility stakeholders.
- Delegate identity proof and key management to enterprise services.
- Use independent policy services with verified real-time revocation.
- Apply source-side row/column policies and prevent data ingestion leakage.
- Add external audit with integrity, retention and monitoring guarantees.
- Separate enterprise IT, gateway/DMZ and OT zones using infrastructure
  enforcement; prove only approved unidirectional/read-only data transfer.
- Require full security review and authorization before production use.

No stage of this codebase is permitted to operate physical equipment.
