"""python3 authoring/methods/sweep.py OUTDIR: pass counts and ranges per method."""
import json, sys
from pathlib import Path
from methods import METHODS
R = [json.loads(p.read_text()) for p in sorted(Path(sys.argv[1]).glob("*.json"))]
print(f"{len(R)} seeds")
for m in METHODS:
    v = [r[m] for r in R]
    rng = lambda k: f"{min(x[k] for x in v):.3f}-{max(x[k] for x in v):.3f}"
    rt = lambda k: f"{min(x[k] for x in v):+.4f} to {max(x[k] for x in v):+.4f}"
    print(f"{m:32s} pass {sum(x['ok'] for x in v):2d}/{len(v)}  lines(allowed) {rng('allowed_share')}  lines(payable) {rng('payable_share')}  bills {rng('bill_share')}  total allowed {rt('total_allowed')}  total payable {rt('total_payable')}")
