# Stage 08 — Offline Release Engineering & Recovery Gates

## Intent and non-production boundary

This stage ships a **local, development-only immutable-index release prototype**
for the synthetic Stage 01 data and Stage 01–07 offline evaluation process.
It does not connect to an industrial network, deploy to OT, authorize
enterprise identities, or certify operational readiness. The prior Stage 06
security research gate and Stage 07 benchmark remain independent.

## Architecture

    Trusted local source manifest (fixture:// and datasets/ only)
                     |
          source hashes / byte budget
                     |
              compare to active
                     |
           incremental changed/removed
                     |
       detached SQLite database via backup
                     |
          full rebuild of changed sources
              + purge deleted sources
                     |
         SQLite backup / quick_check
                     |
          immutable snapshot database
           + HMAC-signed manifest
                     |
        staged release in WAL catalog
                     |
       explicit compare-and-swap publish
                     |
         active logical version pointer
                     |
        pinned immutable read-only query
                     |
    rollback via CAS to a verified version

The active pointer is a single row in a transactional SQLite release
catalog. It is **not** a symlink, remote load balancer, Kubernetes
deployment controller or shared distributed consensus system. Competing
writers are serialized by POSIX advisory locks. The source snapshot is
never modified by the operational query method.

## Contracts and constraints

- Manifest format: `{"version":"stage08-v1","sources":[{"source_uri":
  "fixture://...","path":"datasets/...","revision":"..."}]}`.
- Sources may only be text files under the local workspace `datasets/`
  tree and synthetic `fixture://` names. No network or file fetching.
- Source revisions, hashes and exact source set are stored in a signed release
  record. Changed sources are reingested; removed sources are physically
  purged from the **staged** snapshot including FTS/embedding records.
- A clean SQLite index is copied into a new content-derived versioned file
  before registration, and integrity and HMAC signature are checked on
  publication and query. Signed metadata is **local HMAC**, not a trusted
  third-party provenance or software supply-chain attestation.
- Publish and rollback require the caller to supply an expected current
  version; stale CAS requests cannot change active release.
- Read-only queries pin the active release under a shared advisory lock and
  use `mode=ro&immutable=1` rather than DDL-opening `Store.__init__`.
- Simulated failures after indexing or before registration leave the active
  pointer untouched. A failed new release never replaces active content.
- Fixed cost proxy is changed source bytes / 4; it is not an LLM token
  count, API bill, cloud price or production cost prediction.
- Maximum 64 sources, <=128 KiB each, <=2 MiB staged corpus, <=2 MiB
  incremental ingest budget in the local baseline.

## Operability / telemetry

Optional OpenTelemetry API instrumentation creates bounded spans for stage,
publish, rollback and query; a real SDK/collector/exporter **is not**
configured. Span names contain operation categories only, never user prompts,
raw evidence, secret signing keys or source paths.

The local catalog records a query duration and success bit and reports an
observed p95 over at most 500 samples, without exporting query contents.
This is a tiny synthetic smoke signal, **not** an SLO measurement on actual
production request traffic. The readiness report always sets
`production_ready=false` regardless of how many green tests occur.

## Failure drills and acceptance

Run:

```bash
pip install -e '.[api,llm,pdf,docx,ontology,dev]'
pytest -q
python scripts/stage08_drill.py
ruff check src tests
```

`stage08_drill.py` creates an ephemeral copy of the synthetic documents,
builds and promotes the initial version, injects two build faults, checks
that the old version survives, validates stale-CAS rejection, publishes a
changed source, verifies the new index, and rolls back. It exports a JSON
report and readiness blockers. It does not handle real documents or access
any OT systems.

Optional local CLI (NOT an authenticated deployment service):

```bash
export IRF_OPS_HMAC_KEY="<ephemeral random local secret >=32 bytes>"
export IRF_OPS_ROOT="data/stage08"
irf ops-stage --manifest config/stage08_manifest.json
irf ops-status
irf ops-publish <staged-version>  # expected-active omitted only for initial publish
irf ops-query "P-102A bearing"
irf ops-history
irf ops-readiness
```

For subsequent publishes use
`irf ops-publish <version> --expected-active <current-version>`.
For rollback use
`irf ops-rollback <old-version> --expected-active <current-version>`.
A green `ops-readiness` output authorizes **local demo only**.

## Current acceptance matrix

| Requirement | Research implementation | Production prerequisite |
| --- | --- | --- |
| Blue/green index | Detached immutable SQLite snapshots and atomic CAS catalog | Multi-node atomic routing and cross-region state consistency |
| Incremental ingestion | Content hashes / deleted-source purge in staged snapshot | Actual source-side CDC and watermark reconciliation |
| Signed provenance | HMAC-protected local manifest and SHA256 snapshot | External signing authority, key escrow, tamper-resistant storage |
| Rollback | CAS back to previously verified snapshot | Runbook, ownership and production rehearsals |
| Telemetry | Optional OpenTelemetry API spans, local query p95 | Exporter/collector, secret filter, production SLO history |
| Cost | Source-byte ingestion proxy and explicit max-change budget | Real token/API/network/GPU pricing and accounting |
| Recovery | Fault injection and rollback on synthetic documents | Independent-site backup and restoration test |
| Security | No OT endpoints or HTTP admin release API; S06 tests | Enterprise IAM, signed policy, independent OT boundary |
| Release gate | Local integrity check, always blocked production gate | Risk approval, control evidence and site-owner sign-off |

This stage deliberately does not introduce a Flask release-management API:
doing so in the existing unauthenticated development service would create a
new high-risk privileged endpoint.

## Remaining work after Stage 08

Integrate a real authenticated out-of-band release controller, restore
backups to a separate host, perform failover drills, replace synthetic
datasets with explicitly approved independent industrial data, attach OTel
SDK exporters and observe real request SLOs and costs. Keep a mandatory
security/OT sign-off before production authorization.

## References

- OpenTelemetry Python tracing:
  https://opentelemetry.io/docs/languages/python/instrumentation/
- SQLite online backup API:
  https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup
