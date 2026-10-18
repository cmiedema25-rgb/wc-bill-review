"""Scoring at the task bands (same as tests/test_outputs.py)."""
import numpy as np
import pandas as pd
LINE_TOL, LINE_FLOOR, LINE_SHARE = 0.005, 0.50, 0.99
BILL_TOL, BILL_FLOOR, BILL_SHARE = 0.005, 1.00, 0.997
TOTAL_TOL = 0.0025


def score(df, T):
    k = [f"{b}|{l}" for b, l in zip(df.bill_id, df.line_no)]
    ta = np.array([T["lines"][x][0] for x in k]); tp = np.array([T["lines"][x][1] for x in k])
    a, p = df.allowed.values, df.payable.values
    sa = float(np.mean(np.abs(a - ta) <= np.maximum(LINE_TOL * ta, LINE_FLOOR)))
    sp = float(np.mean(np.abs(p - tp) <= np.maximum(LINE_TOL * tp, LINE_FLOOR)))
    g = pd.DataFrame(dict(b=df.bill_id.values, p=p, t=tp)).groupby("b").sum()
    sb = float(np.mean(np.abs(g.p - g.t) <= np.maximum(BILL_TOL * g.t, BILL_FLOOR)))
    ea = float(a.sum() / T["total_allowed_usd"] - 1); ep = float(p.sum() / T["total_payable_usd"] - 1)
    ok = sa >= LINE_SHARE and sp >= LINE_SHARE and sb >= BILL_SHARE and abs(ea) <= TOTAL_TOL and abs(ep) <= TOTAL_TOL
    return dict(allowed_share=sa, payable_share=sp, bill_share=sb, total_allowed=ea, total_payable=ep, ok=bool(ok))
