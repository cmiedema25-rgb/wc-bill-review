"""python3 authoring/methods/run_seed.py SEED OUTDIR: generate the seed in a temp dir and score every method."""
import json, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent.parent / "solution")]
import generate_data, solve, score, independent
from methods import METHODS

seed, out = int(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
if (out / f"{seed}.json").exists():
    sys.exit(0)
with tempfile.TemporaryDirectory() as td:
    d, t = generate_data.generate(seed)
    generate_data.write(d, t, td + "/data", td + "/truth.json")
    T = json.load(open(td + "/truth.json"))
    res = {}
    for name, opt in METHODS.items():
        if opt == "independent":
            df = independent.run(td + "/data")
        elif opt == "billed":
            df = solve.run(td + "/data", ["no_ppo"]); import pandas as pd
            L = pd.read_csv(td + "/data/bill_lines.csv").sort_values(["bill_id", "line_no"])
            df["allowed"] = L.billed_usd.values; df["payable"] = L.billed_usd.values
        else:
            df = solve.run(td + "/data", opt)
        res[name] = score.score(df, T)
(out / f"{seed}.json").write_text(json.dumps(res))
print(seed, sum(v["ok"] for v in res.values()), "methods pass", flush=True)
