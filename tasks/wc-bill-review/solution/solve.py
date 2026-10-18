#!/usr/bin/env python3
"""Reference bill review for wc-bill-review. Writes /app/output/bill_review.csv.

run(data_dir, opts) returns one row per bill line with allowed_usd and payable_usd. opts switch off
individual steps; the shipped solution uses none.
"""
import re, sys
from pathlib import Path
import numpy as np
import pandas as pd

STATES = ["KY", "NM", "SC", "ID"]
# rules read from regulations/*.md and network_agreements/*.md
ASSIST_PCT = {"KY": 0.16, "NM": 0.20, "SC": 0.16, "ID": 0.20}
MPR_THIRD = {"KY": 0.50, "NM": 0.25, "SC": 0.50, "ID": 0.25}
PCT_CHARGES = {"KY": 0.65, "NM": 0.55, "SC": 0.60, "ID": 0.70}
PPO_BASE = {"KHN": {"KY": "schedule", "ID": "schedule", "NM": "billed", "SC": "billed"},
            "SUM": {"KY": "billed", "ID": "billed", "NM": "schedule", "SC": "schedule"},
            "MER": {"KY": "schedule", "ID": "schedule", "NM": "schedule", "SC": "billed"}}


def run(data, o=None):
    o = set(o or [])
    D = Path(data)
    rd = lambda f: pd.read_csv(D / f, dtype=str, keep_default_na=False)
    B, L, C = rd("bills.csv"), rd("bill_lines.csv"), rd("claims.csv")
    L["units"] = L.units.astype(int); L["billed_usd"] = L.billed_usd.astype(float); L["line_no"] = L.line_no.astype(int)
    B["frequency_code"] = B.frequency_code.astype(int)
    prof, fac = rd("professional_fee_schedule.csv"), rd("facility_fee_schedule.csv")
    cf = rd("conversion_factors.csv"); cf["conversion_factor"] = cf.conversion_factor.astype(float)
    if "cf_proposed" not in o:
        cf = cf[cf.status == "adopted"]
    det, dxm = rd("body_part_determinations.csv"), rd("diagnosis_body_part_map.csv")
    part, net, pay, pv = rd("provider_network_participation.csv"), rd("network_contracts.csv"), rd("payment_history.csv"), rd("providers.csv")
    pay["amount_usd"] = pay.amount_usd.astype(float); pay["line_no"] = pay.line_no.astype(int)

    # ---- bill status: voids, replacements (chains), duplicates of an active bill
    status = {b: "live" for b in B.bill_id}
    if "no_freq" not in o:
        for r in B[B.frequency_code == 8].itertuples():
            status[r.bill_id] = "void"; status[r.original_bill_ref] = "voided"
        for r in B[B.frequency_code == 7].itertuples():
            if status.get(r.original_bill_ref) == "live" or status.get(r.original_bill_ref) == "replaced":
                status[r.original_bill_ref] = "replaced"
    if "no_dup" not in o:
        sig = L.assign(t=list(zip(L.service_date, L.revenue_code, L.procedure_code, L.modifiers, L.units, L.billed_usd))).groupby("bill_id").t.apply(lambda s: tuple(sorted(s)))
        Bs = B.assign(sig=B.bill_id.map(sig)).sort_values(["received_date", "bill_id"])
        seen = {}
        for r in Bs.itertuples():
            if r.frequency_code != 1:
                continue
            k = (r.claim_id, r.provider_npi, r.sig)
            if k in seen and (status[seen[k]] == "live" or "dup_any" in o):
                status[r.bill_id] = "duplicate"
            elif status[r.bill_id] == "live" or "dup_any" in o:
                seen[k] = r.bill_id
    B["status"] = B.bill_id.map(status)

    M = L.merge(B, on="bill_id").merge(C[["claim_id", "jurisdiction_state", "injury_date", "claimed_body_parts"]], on="claim_id")
    M["svc_state"] = M.billing_provider_state if "oos_billing" in o else M.service_facility_state
    live = (M.status == "live").values

    # ---- compensability
    det = det.sort_values(["determination_date"], kind="stable")
    last = det.groupby(["claim_id", "body_part"]).determination.last()
    if "det_any_accept" in o:
        last = det.groupby(["claim_id", "body_part"]).determination.apply(lambda s: "accepted" if (s == "accepted").any() else s.iloc[-1])
    if "det_first" in o:
        last = det.groupby(["claim_id", "body_part"]).determination.first()
    acc = {}
    for (c, p), v in last.items():
        if v == "accepted":
            acc.setdefault(c, set()).add(p)
    if "claimed_parts" in o:
        acc = {c: set(s.split(";")) for c, s in zip(C.claim_id, C.claimed_body_parts)}
    bp = dict(zip(dxm.icd10_code, dxm.body_part))
    norm = (lambda p: re.sub(r"^(right|left) ", "", p or "")) if "no_laterality" in o else (lambda p: p)
    def ok_part(c, dxs):
        a = {norm(x) for x in acc.get(c, set())}
        return any(norm(bp.get(d)) in a for d in dxs) if dxs else False
    comp = np.ones(len(M), bool)
    if "no_body_part" not in o:
        for i, r in enumerate(M.itertuples()):
            if r.form_type == "UB-04":
                dxs = [r.principal_dx]
            else:
                dd = r.diagnosis_codes.split(";")
                dxs = dd if "any_pointer" in o else dd[:1]
            comp[i] = ok_part(r.claim_id, dxs)
    if "no_preinjury" not in o:
        comp &= (M.service_date >= M.injury_date).values
    comp &= live

    # ---- bundling edits, professional lines, same claim/provider/date across bills
    ed = rd("procedure_edits.csv")
    E = {(a, b): int(m) for a, b, m in zip(ed.column1_code, ed.column2_code, ed.modifier_indicator)}
    bundled = np.zeros(len(M), bool)
    if "no_bundle" not in o:
        grp = ["bill_id", "service_date"] if "bundle_bill" in o else ["claim_id", "provider_npi", "service_date"]
        pl = M[live & (M.form_type == "CMS-1500")]
        have = pl.groupby(grp).procedure_code.apply(set).to_dict()
        for i, r in enumerate(M.itertuples()):
            if not live[i] or r.form_type != "CMS-1500":
                continue
            hs = have.get(tuple(getattr(r, g) for g in grp), set())
            mods = r.modifiers.split()
            for a in hs:
                m = E.get((a, r.procedure_code))
                if m is None:
                    continue
                if "bundle_ignore_mod" in o or not (m == 1 and ("59" in mods or "XS" in mods)):
                    bundled[i] = True
    comp &= ~bundled
    M["comp"] = comp

    # ---- schedule
    Pd = {(r.state, r.code): r for r in prof.itertuples()}
    Fd = {(r.state, r.hcpcs): r for r in fac.itertuples()}
    cft = {k: g.sort_values("effective_from")[["effective_from", "conversion_factor"]].values.tolist() for k, g in cf.groupby(["state", "schedule"])}
    def cfv(s, k, dos, recv):
        rows = cft[(s, k)]
        if "cf_latest" in o: return rows[-1][1]
        d = recv if "cf_received" in o else dos
        v = rows[0][1]
        for e, c in rows:
            if d >= e: v = c
        return v
    def cands(r):
        s, v = r.jurisdiction_state, r.svc_state
        if "oos_jurisdiction" in o or v == s or v not in STATES: return [s]
        if "oos_provider" in o: return [v]
        if s == "NM": return [v]
        if s == "SC": return [s, v]
        return [s]
    def full(r, s):
        mods = r.modifiers.split()
        if r.form_type == "UB-04":
            if "no_packaging" not in o and r.revenue_code[:3] in ("037", "071"):
                return 0.0
            if r.procedure_code == "":
                return PCT_CHARGES[s] * r.billed_usd
            f = Fd[(s, r.procedure_code)]
            if f.status_indicator == "N" and "no_packaging" not in o:
                return 0.0
            return float(f.relative_weight) * cfv(s, "facility", r.service_date, r.received_date) * r.units
        p = Pd[(s, r.procedure_code)]
        v = float(p.flat_fee_usd) * r.units if p.rvu == "" else float(p.rvu) * cfv(s, "professional", r.service_date, r.received_date) * r.units
        if "50" in mods and p.bilateral_indicator == "1":
            v *= 2.0 if "bilat200" in o else 1.5
        if "80" in mods:
            v *= 0.20 if "assist_flat" in o else (ASSIST_PCT[s] if p.assistant_surgeon == "1" else 0.0)
        return v
    M["cands"] = [cands(r) for r in M.itertuples()]
    sched = pd.Series(np.inf, index=M.index)
    for s in STATES:
        sub = M[[s in c for c in M.cands]].copy()
        sub["full"] = [full(r, s) for r in sub.itertuples()]
        sub["mult"] = 1.0
        if "no_mpr" not in o:
            pr = sub[sub.comp & (sub.form_type == "CMS-1500")]
            pr = pr[[Pd[(s, c)].mpr_indicator == "2" for c in pr.procedure_code]]
            if "mpr_mod51" in o:
                sub.loc[pr.index[pr.modifiers.str.split().apply(lambda m: "51" in m)], "mult"] = 0.5
            else:
                g_by = ["bill_id", "service_date"] if "mpr_bill" in o else ["claim_id", "provider_npi", "service_date"]
                for _, g in pr.groupby(g_by):
                    if len(g) < 2: continue
                    if "mpr_billed_order" in o:
                        idx = g.sort_values(["bill_id", "line_no"]).index
                    else:
                        idx = g.sort_values(["full", "bill_id", "line_no"], ascending=[False, True, True]).index
                    for k, ix in enumerate(idx):
                        sub.loc[ix, "mult"] = 1.0 if k == 0 else (0.5 if k == 1 or "mpr_flat" in o else MPR_THIRD[s])
        if "no_fac_mpr" not in o:
            fr = sub[sub.comp & (sub.form_type == "UB-04") & (sub.procedure_code != "")]
            fr = fr[[Fd[(s, c)].status_indicator == "T" for c in fr.procedure_code]]
            for _, g in fr.groupby("bill_id"):
                if len(g) < 2: continue
                for k, ix in enumerate(g.sort_values(["full", "line_no"], ascending=[False, True]).index):
                    sub.loc[ix, "mult"] = 1.0 if k == 0 else 0.5
        v = sub.full * sub.mult
        sched.loc[v.index] = np.minimum(sched.loc[v.index], v)
    M["sched"] = sched

    # ---- network discount
    disc = dict(zip(net.network, net.discount_pct.astype(float) / 100))
    per = {}
    for r in part.itertuples():
        per.setdefault(r.npi, []).append((r.effective_from, r.terminated_on or "9999-12-31", r.network))
    stale = dict(zip(pv.npi, pv.ppo_network))
    def network(npi, dos):
        if "ppo_stale" in o: return stale.get(npi) or None
        for a, b, n in per.get(npi, []):
            if a <= dos <= b: return n
        return None
    ppo = []
    for r in M.itertuples():
        n = None if "no_ppo" in o else network(r.provider_npi, r.service_date)
        if n is None:
            ppo.append(np.inf); continue
        base = PPO_BASE[n][r.jurisdiction_state]
        if "ppo_schedule" in o: base = "schedule"
        if "ppo_billed" in o: base = "billed"
        ppo.append((r.sched if base == "schedule" else r.billed_usd) * (1 - disc[n]))
    M["ppo"] = ppo
    cap = np.inf if "no_billed_cap" in o else M.billed_usd
    M["allowed"] = np.where(M.comp, np.minimum(np.minimum(cap, M.sched), M.ppo), 0.0).round(2)

    # ---- already paid: same service on any bill that was not voided
    M["key"] = list(zip(M.claim_id, M.provider_npi, M.service_date, M.procedure_code, M.revenue_code))
    kmap = dict(zip(zip(M.bill_id, M.line_no), M.key))
    bst = dict(zip(B.bill_id, B.status))
    paid = {}
    if "no_netting" not in o:
        P2 = pay if "keep_reversals" not in o else pay[pay.amount_usd > 0]
        for r in P2.itertuples():
            if bst[r.bill_id] in ("void", "voided") and "net_voided" not in o:
                continue
            k = (r.bill_id, r.line_no) if "net_same_line" in o else kmap[(r.bill_id, r.line_no)]
            paid[k] = paid.get(k, 0.0) + r.amount_usd
    if "net_same_line" in o:
        pp = [paid.get((b, l), 0.0) for b, l in zip(M.bill_id, M.line_no)]
    else:
        pp = [paid.get(k, 0.0) for k in M.key]
    M["payable"] = np.where(M.status == "live", np.maximum(0.0, (M.allowed - np.array(pp)).round(2)), 0.0)
    return M[["bill_id", "line_no", "allowed", "payable"]].sort_values(["bill_id", "line_no"]).reset_index(drop=True)


def write(df, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("bill_id,line_no,allowed_usd,payable_usd\n")
        for r in df.itertuples():
            f.write(f"{r.bill_id},{r.line_no},{r.allowed:.2f},{r.payable:.2f}\n")
        f.write(f"total,,{df.allowed.sum():.2f},{df.payable.sum():.2f}\n")


if __name__ == "__main__":
    data = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
    out = sys.argv[2] if len(sys.argv) > 2 else "/app/output/bill_review.csv"
    write(run(data), out)
