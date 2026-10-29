"""Dependency-free, escaped static HTML receipt; no raw industrial content."""
from __future__ import annotations

import html
import json


def render_html(report: dict) -> str:
    if report.get("stage")!="S07":
        raise ValueError("Only S07 report contract supported")
    escape=lambda x:html.escape(str(x),quote=True)
    summary=report["summary"]
    champ=report["retrieval"]["champion_dev_selected"]
    ci=report["retrieval"]["champion_test_ci"]["mrr_at_k"]
    delta=report["retrieval"]["paired_delta_vs_sparse"]["mrr_at_k"]
    trial_rows=[]
    for run in report["retrieval"]["runs"]:
        f=run["factor"]
        trial_rows.append("<tr><td>"+escape(run["run_id"])+"</td>"
            "<td>"+escape(f["chunk_size"])+"</td><td>"+escape(f["overlap"])+"</td>"
            "<td>"+escape(f["mode"])+"</td><td>"+escape(f["seed"])+"</td>"
            "<td>"+f'{run["metrics"]["dev"]["mrr_at_k"]:.3f}'+"</td><td>"
            +f'{run["metrics"]["test"]["mrr_at_k"]:.3f}'+"</td></tr>")
    limits="".join("<li>"+escape(item)+"</li>" for item in report["limitations"])
    meta=json.dumps(report["identity"]["input_fingerprints"],ensure_ascii=False,
                    indent=2,sort_keys=True)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Industrial RAG Factory — Stage 07</title>
<style>
:root{{color-scheme:light;font-family:system-ui,-apple-system,sans-serif}}
body{{max-width:1150px;margin:3rem auto;padding:0 1.5rem;color:#172a39}}
h1,h2{{letter-spacing:-.02em}}p,li{{line-height:1.55}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(195px,1fr));gap:12px}}
.card{{border:1px solid #cad4df;border-radius:8px;padding:18px}}
.card strong{{font-size:1.7rem;display:block}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}
td,th{{padding:.6rem;border-bottom:1px solid #ddd;text-align:left}}
th{{background:#f0f4f7;position:sticky;top:0}}
.wrapper{{overflow:auto;max-height:460px}}
code,pre{{font-family:ui-monospace,monospace}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:14px}}
.note{{border-left:3px solid #536d88;padding-left:14px}}
</style></head><body>
<h1>Stage 07 · Offline Ablation Factory</h1>
<p><strong>Experiment:</strong> <code>{escape(report["experiment_id"])}</code>.
Results are synthetic and are not production RAG quality estimates.</p>
<div class="cards">
<div class="card"><strong>{summary["retrieval_trials"]}</strong>retrieval trials</div>
<div class="card"><strong>{summary["retrieval_test_cases"]}</strong>held-out test cases</div>
<div class="card"><strong>{ci["estimate"]:.3f}</strong>DEV-selected TEST MRR@K</div>
<div class="card"><strong>{summary["claim_enabled_accuracy"]:.3f}</strong>typed claims fixture accuracy</div>
</div>
<h2>Precommitted selection and uncertainty</h2>
<p>DEV-selected run <code>{escape(champ["run_id"])}</code>,
chunk={champ["factor"]["chunk_size"]}, overlap={champ["factor"]["overlap"]},
retrieval={escape(champ["factor"]["mode"])}.</p>
<p>TEST MRR: {ci["estimate"]:.3f}, 95% cluster-bootstrap
CI [{ci["lower"]:.3f}, {ci["upper"]:.3f}] across {ci["independent_groups"]} asset groups.
Paired MRR delta vs sparse: {delta["estimate"]:+.3f},
95% CI [{delta["lower"]:+.3f}, {delta["upper"]:+.3f}].</p>
<p class="note">Seeds vary indexing order only; bootstrap resamples source groups.
Do not interpret small synthetic CI bounds as model-generalization guarantees.</p>
<h2>Negative control comparisons (separate tasks)</h2>
<table><thead><tr><th>Task</th><th>Enabled</th><th>Fail-closed control</th></tr></thead>
<tbody>
<tr><td>Graph exact match (S02)</td><td>{summary["graph_enabled_accuracy"]:.3f}</td>
<td>{summary["graph_fail_closed_accuracy"]:.3f}</td></tr>
<tr><td>Planner tool sequence (S04)</td><td>{summary["planner_enabled_tool_accuracy"]:.3f}</td>
<td>{summary["planner_document_only_accuracy"]:.3f}</td></tr>
<tr><td>Claim status match (S05)</td><td>{summary["claim_enabled_accuracy"]:.3f}</td>
<td>{summary["claim_fail_closed_accuracy"]:.3f}</td></tr>
</tbody></table>
<h2>Retrieval factorial trials</h2><div class="wrapper"><table>
<thead><tr><th>Run ID</th><th>Chunk</th><th>Overlap</th><th>Mode</th><th>Seed</th>
<th>DEV MRR@K</th><th>TEST MRR@K</th></tr></thead>
<tbody>{"".join(trial_rows)}</tbody></table></div>
<h2>Limitations</h2><ul>{limits}</ul>
<h2>Exact source fingerprints</h2><pre>{escape(meta)}</pre>
<p>Machine-readable case-level data and full experiment configuration:
<strong>outputs/stage07_ablation.json</strong>.</p></body></html>"""
