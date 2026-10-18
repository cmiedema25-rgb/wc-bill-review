"""Independent bill review: a line-by-line rules engine written separately from solution/solve.py.

It walks bills in received order with plain dictionaries, keeps a ledger of the services still payable,
prices each line with every rule applied in sequence and rounds at each pricing step to the cent.
"""
import csv
from collections import defaultdict
from pathlib import Path


def rows(p):
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def run(data):
    D = Path(data)
    bills = {r["bill_id"]: r for r in rows(D / "bills.csv")}
    lines = defaultdict(list)
    for r in rows(D / "bill_lines.csv"):
        r["units"] = int(r["units"]); r["billed"] = float(r["billed_usd"]); r["line_no"] = int(r["line_no"])
        lines[r["bill_id"]].append(r)
    claims = {r["claim_id"]: r for r in rows(D / "claims.csv")}
    # latest determination per claim/body part
    dets = sorted(rows(D / "body_part_determinations.csv"), key=lambda r: r["determination_date"])
    latest = {}
    for r in dets:
        latest[(r["claim_id"], r["body_part"])] = r["determination"]
    part_of = {r["icd10_code"]: r["body_part"] for r in rows(D / "diagnosis_body_part_map.csv")}
    prof = {(r["state"], r["code"]): r for r in rows(D / "professional_fee_schedule.csv")}
    fac = {(r["state"], r["hcpcs"]): r for r in rows(D / "facility_fee_schedule.csv")}
    cfs = defaultdict(list)
    for r in rows(D / "conversion_factors.csv"):
        if r["status"] == "adopted":
            cfs[(r["state"], r["schedule"])].append((r["effective_from"], float(r["conversion_factor"])))
    edits = {(r["column1_code"], r["column2_code"]): r["modifier_indicator"] for r in rows(D / "procedure_edits.csv")}
    disc = {r["network"]: float(r["discount_pct"]) / 100 for r in rows(D / "network_contracts.csv")}
    spans = defaultdict(list)
    for r in rows(D / "provider_network_participation.csv"):
        spans[r["npi"]].append(r)
    base_rule = {  # network agreements, reimbursement clause by jurisdiction
        "KHN": dict(KY="fs", ID="fs", NM="charge", SC="charge"),
        "SUM": dict(KY="charge", ID="charge", NM="fs", SC="fs"),
        "MER": dict(KY="fs", ID="fs", NM="fs", SC="charge")}
    asst = dict(KY=16, NM=20, SC=16, ID=20)
    third = dict(KY=50, NM=25, SC=50, ID=25)
    poc = dict(KY=65, NM=55, SC=60, ID=70)

    # 1. bill history
    state = {b: "active" for b in bills}
    for b, r in sorted(bills.items(), key=lambda kv: (kv[1]["received_date"], kv[0])):
        if r["frequency_code"] == "8":
            state[b] = "dead"; state[r["original_bill_ref"]] = "dead_void"
        elif r["frequency_code"] == "7":
            state[r["original_bill_ref"]] = "dead"
    for b in bills:
        if bills[b]["frequency_code"] == "8": state[b] = "dead_void"
    fingerprint = {}
    for b, r in sorted(bills.items(), key=lambda kv: (kv[1]["received_date"], kv[0])):
        if r["frequency_code"] != "1" or state[b] != "active":
            continue
        fp = (r["claim_id"], r["provider_npi"], frozenset((l["service_date"], l["revenue_code"], l["procedure_code"], l["modifiers"], l["units"], l["billed"]) for l in lines[b]))
        if fp in fingerprint and state[fingerprint[fp]] == "active":
            state[b] = "dead"
        else:
            fingerprint[fp] = b

    def cf(s, kind, dos):
        v = None
        for e, c in sorted(cfs[(s, kind)]):
            if e <= dos: v = c
        return v

    def which_states(juris, loc):
        if loc == juris or loc not in poc: return [juris]
        return {"NM": [loc], "SC": [juris, loc]}.get(juris, [juris])

    # 2. compensability and edits
    work = []
    by_svc_day = defaultdict(list)
    for b, r in bills.items():
        c = claims[r["claim_id"]]
        for l in lines[b]:
            w = dict(l, bill=b, claim=r["claim_id"], npi=r["provider_npi"], form=r["form_type"], juris=c["jurisdiction_state"],
                     loc=r["service_facility_state"], ok=state[b] == "active")
            if w["ok"]:
                dx = r["principal_dx"] if r["form_type"] == "UB-04" else l["diagnosis_codes"].split(";")[0]
                w["ok"] = latest.get((r["claim_id"], part_of.get(dx, "?"))) == "accepted" and l["service_date"] >= c["injury_date"]
            work.append(w)
            if state[b] == "active" and r["form_type"] == "CMS-1500":
                by_svc_day[(w["claim"], w["npi"], w["service_date"])].append(w)
    for grp in by_svc_day.values():
        codes = {g["procedure_code"] for g in grp}
        for g in grp:
            mods = g["modifiers"].split()
            for a in codes:
                ind = edits.get((a, g["procedure_code"]))
                if ind is not None and not (ind == "1" and ({"59", "XS"} & set(mods))):
                    g["ok"] = False

    # 3. price per candidate state
    def price(w, s):
        mods = w["modifiers"].split()
        if w["form"] == "UB-04":
            if w["revenue_code"][:3] in ("037", "071"): return 0.0
            if not w["procedure_code"]: return round(w["billed"] * poc[s] / 100, 2)
            f = fac[(s, w["procedure_code"])]
            if f["status_indicator"] == "N": return 0.0
            return round(float(f["relative_weight"]) * cf(s, "facility", w["service_date"]), 2) * w["units"]
        p = prof[(s, w["procedure_code"])]
        unit = float(p["flat_fee_usd"]) if p["rvu"] == "" else round(float(p["rvu"]) * cf(s, "professional", w["service_date"]), 2)
        v = unit * w["units"]
        if "50" in mods and p["bilateral_indicator"] == "1": v = round(v * 1.5, 2)
        if "80" in mods: v = round(v * asst[s] / 100, 2) if p["assistant_surgeon"] == "1" else 0.0
        return v
    for w in work:
        w["fs"] = {s: price(w, s) for s in which_states(w["juris"], w["loc"])}
    for s in poc:
        prof_groups, fac_groups = defaultdict(list), defaultdict(list)
        for w in work:
            if not w["ok"] or s not in w["fs"]: continue
            if w["form"] == "CMS-1500" and prof[(s, w["procedure_code"])]["mpr_indicator"] == "2":
                prof_groups[(w["claim"], w["npi"], w["service_date"])].append(w)
            if w["form"] == "UB-04" and w["procedure_code"] and fac[(s, w["procedure_code"])]["status_indicator"] == "T":
                fac_groups[w["bill"]].append(w)
        for g in prof_groups.values():
            g.sort(key=lambda w: (-w["fs"][s], w["bill"], w["line_no"]))
            for i, w in enumerate(g[1:], 1):
                w["fs"][s] = round(w["fs"][s] * (50 if i == 1 else third[s]) / 100, 2)
        for g in fac_groups.values():
            g.sort(key=lambda w: (-w["fs"][s], w["line_no"]))
            for w in g[1:]:
                w["fs"][s] = round(w["fs"][s] / 2, 2)

    def net_on(npi, dos):
        for sp in spans[npi]:
            if sp["effective_from"] <= dos and (not sp["terminated_on"] or dos <= sp["terminated_on"]):
                return sp["network"]

    # 4. allowed, then credit earlier payments for the same service
    paid = defaultdict(float)
    where = {(w["bill"], w["line_no"]): w for w in work}
    for p in rows(D / "payment_history.csv"):
        w = where[(p["bill_id"], int(p["line_no"]))]
        if state[w["bill"]] == "dead_void": continue
        paid[(w["claim"], w["npi"], w["service_date"], w["procedure_code"], w["revenue_code"])] += float(p["amount_usd"])
    out = []
    for w in work:
        allowed = 0.0
        if w["ok"]:
            fs = min(w["fs"].values())
            amt = min(w["billed"], fs)
            n = net_on(w["npi"], w["service_date"])
            if n:
                basis = fs if base_rule[n][w["juris"]] == "fs" else w["billed"]
                amt = min(amt, round(basis * (1 - disc[n]), 2))
            allowed = round(amt, 2)
        due = 0.0
        if state[w["bill"]] == "active":
            due = max(0.0, round(allowed - paid[(w["claim"], w["npi"], w["service_date"], w["procedure_code"], w["revenue_code"])], 2))
        out.append((w["bill"], w["line_no"], allowed, due))
    import pandas as pd
    return pd.DataFrame(out, columns=["bill_id", "line_no", "allowed", "payable"]).sort_values(["bill_id", "line_no"]).reset_index(drop=True)
