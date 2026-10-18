"""Verifier for wc-bill-review.

Reads only /app/output/bill_review.csv. Ground truth (/tests/truth.json, baked into the verifier image) is the
allowed and still-payable amount of every bill line, computed by the data generator from how each bill was
created and the state fee schedule rules, network agreements and payment history.
Bands: at least 99% of lines within 0.5% (or $0.50, if larger) for allowed_usd and, separately, payable_usd;
at least 99.7% of bills with total payable_usd within 0.5% (or $1.00); total allowed and total payable within 0.25%.
"""
import csv, json, math
from collections import defaultdict
from pathlib import Path

OUT = Path("/app/output/bill_review.csv")
T = json.loads(Path("/tests/truth.json").read_text())
KEYS = sorted(T["lines"])
HEADER = ["bill_id", "line_no", "allowed_usd", "payable_usd"]
LINE_TOL, LINE_FLOOR, LINE_SHARE = 0.005, 0.50, 0.99
BILL_TOL, BILL_FLOOR, BILL_SHARE = 0.005, 1.00, 0.997
TOTAL_TOL, SUM_TOL = 0.0025, 0.0001


def _read():
    assert OUT.is_file() and not OUT.is_symlink(), "/app/output/bill_review.csv was not written as a regular file"
    with OUT.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        header = [(h or "").strip() for h in (rd.fieldnames or [])]
        rows = list(rd)
    assert header == HEADER, f"header must be exactly {','.join(HEADER)}, got {header}"
    out = {}
    for r in rows:
        assert None not in r, "a row has more fields than the header"
        b = (r["bill_id"] or "").strip()
        ln = (r["line_no"] or "").strip()
        if b == "total":
            assert ln == "", "the total row must have an empty line_no"
            k = "total"
        else:
            try:
                k = f"{b}|{int(ln)}"
            except ValueError:
                raise AssertionError(f"line_no is not an integer: {ln!r}")
        assert k not in out, f"duplicate row {k}"
        vals = []
        for c in HEADER[2:]:
            try:
                v = float((r[c] or "").strip())
            except ValueError:
                raise AssertionError(f"{k}.{c} is not a number: {r[c]!r}")
            assert math.isfinite(v) and v >= 0, f"{k}.{c} must be a finite non-negative number"
            vals.append(v)
        out[k] = vals
    assert sorted(out) == sorted(KEYS + ["total"]), "rows must be exactly the lines in bill_lines.csv plus total"
    return out


def _share(col):
    b = _read()
    ok = sum(abs(b[k][col] - T["lines"][k][col]) <= max(LINE_TOL * T["lines"][k][col], LINE_FLOOR) for k in KEYS)
    return ok / len(KEYS)


def test_file_contract():
    """Exact header, one row per bill line plus total, finite non-negative amounts."""
    _read()


def test_total_row_sums_lines():
    """The total row equals the sums of the line rows."""
    b = _read()
    for i, name in enumerate(HEADER[2:]):
        s = sum(b[k][i] for k in KEYS)
        assert abs(b["total"][i] - s) <= SUM_TOL * s + 1, f"total {name} is not the sum of the lines"


def test_allowed_lines_within_band():
    """At least 99% of lines have allowed_usd within 0.5% (or $0.50, if larger)."""
    s = _share(0)
    print(f"allowed_usd: {s:.2%} of lines within band")
    assert s >= LINE_SHARE, f"only {s:.2%} of lines have allowed_usd within 0.5% / $0.50"


def test_payable_lines_within_band():
    """At least 99% of lines have payable_usd within 0.5% (or $0.50, if larger)."""
    s = _share(1)
    print(f"payable_usd: {s:.2%} of lines within band")
    assert s >= LINE_SHARE, f"only {s:.2%} of lines have payable_usd within 0.5% / $0.50"


def test_bills_within_band():
    """At least 99.7% of bills have total payable_usd within 0.5% (or $1.00, if larger)."""
    b = _read()
    got, want = defaultdict(float), defaultdict(float)
    for k in KEYS:
        bill = k.split("|")[0]
        got[bill] += b[k][1]; want[bill] += T["lines"][k][1]
    ok = sum(abs(got[x] - want[x]) <= max(BILL_TOL * want[x], BILL_FLOOR) for x in want)
    s = ok / len(want)
    print(f"{ok} of {len(want)} bills within band ({s:.2%})")
    assert s >= BILL_SHARE, f"only {s:.2%} of bills have total payable_usd within 0.5% / $1.00"


def test_totals_within_band():
    """Total allowed and total payable are each within 0.25% of the correct totals."""
    b = _read()
    for i, key in enumerate(["total_allowed_usd", "total_payable_usd"]):
        e = b["total"][i] / T[key] - 1
        print(f"{key}: {b['total'][i]:,.2f} vs {T[key]:,.2f} ({e:+.3%})")
        assert abs(e) <= TOTAL_TOL, f"{key} is {e:+.3%} from the correct total"
