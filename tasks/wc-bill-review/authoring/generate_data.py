#!/usr/bin/env python3
"""Generator for wc-bill-review.

python3 authoring/generate_data.py [--seed N] [--out DIR] [--truth PATH]
Default writes environment/data and tests/truth.json for the shipped seed.
Every bill, line, payment and document is synthetic. The generator knows how each bill was created
(original, exact duplicate, corrected replacement, void, rebill after a void) and computes the amount
each line should be allowed and still paid from those facts and the state rules below.
"""
import argparse, json, shutil
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
SEED = 311
N_CLAIMS = 950
STATES = ["KY", "NM", "SC", "ID"]
NOSCHED = ["TN", "TX", "WA"]          # provider locations with no schedule in the data
SCALE = {"KY": 0.97, "NM": 1.00, "SC": 0.95, "ID": 1.06}
CF = {  # state -> schedule -> [(effective_from, cf)]
    "KY": {"professional": [("2025-01-01", 58.40), ("2026-01-01", 60.15), ("2026-04-01", 64.90)],
           "facility": [("2025-01-01", 81.00), ("2026-01-01", 84.20), ("2026-04-01", 89.50)]},
    "NM": {"professional": [("2025-01-01", 55.20), ("2026-01-01", 57.80), ("2026-04-01", 61.35)],
           "facility": [("2025-01-01", 77.50), ("2026-01-01", 80.10), ("2026-04-01", 85.30)]},
    "SC": {"professional": [("2025-01-01", 52.75), ("2026-01-01", 54.10), ("2026-04-01", 58.20)],
           "facility": [("2025-01-01", 74.20), ("2026-01-01", 76.00), ("2026-04-01", 81.60)]},
    "ID": {"professional": [("2025-01-01", 63.30), ("2026-01-01", 65.00), ("2026-04-01", 69.75)],
           "facility": [("2025-01-01", 86.40), ("2026-01-01", 88.90), ("2026-04-01", 94.00)]},
}
PROPOSED = [("ID", "professional", "2026-06-01", 72.10, "2026-04-17"), ("SC", "facility", "2026-06-01", 84.90, "2026-04-24")]
PUBLISHED = {"2025-01-01": "2024-11-15", "2026-01-01": "2025-11-14", "2026-04-01": "2026-02-20"}
# state payment rules (stated in the regulation excerpts)
ASSIST_PCT = {"KY": 0.16, "NM": 0.20, "SC": 0.16, "ID": 0.20}
MPR_THIRD = {"KY": 0.50, "NM": 0.25, "SC": 0.50, "ID": 0.25}
PCT_CHARGES = {"KY": 0.65, "NM": 0.55, "SC": 0.60, "ID": 0.70}
BILATERAL = 1.50
FAC_MULT = 0.50
PACKAGED_REV = ("037", "071")
NETWORKS = {"KHN": ("Keystone Health Network", 0.10), "SUM": ("Summit Occupational PPO", 0.12), "MER": ("Meridian Select", 0.07)}
PPO_BASE = {"KHN": {"KY": "schedule", "ID": "schedule", "NM": "billed", "SC": "billed"},
            "SUM": {"KY": "billed", "ID": "billed", "NM": "schedule", "SC": "schedule"},
            "MER": {"KY": "schedule", "ID": "schedule", "NM": "schedule", "SC": "billed"}}

REGIONS = ["lumbar", "cervical", "thoracic", "knee", "shoulder", "wrist", "head"]
SIDED = {"knee", "shoulder", "wrist"}
DX = {  # body part -> [(code, description)]
    "lumbar spine": [("S33.5XXA", "Sprain of ligaments of lumbar spine, initial"), ("M54.50", "Low back pain, unspecified"), ("M51.16", "Intervertebral disc disorder with radiculopathy, lumbar")],
    "cervical spine": [("S13.4XXA", "Sprain of ligaments of cervical spine, initial"), ("M54.2", "Cervicalgia")],
    "thoracic spine": [("S23.3XXA", "Sprain of ligaments of thoracic spine, initial"), ("M54.6", "Pain in thoracic spine")],
    "right knee": [("S83.241A", "Other tear of medial meniscus, right knee, initial"), ("S83.91XA", "Sprain of unspecified site of right knee, initial")],
    "left knee": [("S83.242A", "Other tear of medial meniscus, left knee, initial"), ("S83.92XA", "Sprain of unspecified site of left knee, initial")],
    "right shoulder": [("S43.421A", "Sprain of right rotator cuff capsule, initial"), ("M75.101", "Rotator cuff tear, right shoulder, not specified as traumatic")],
    "left shoulder": [("S43.422A", "Sprain of left rotator cuff capsule, initial"), ("M75.102", "Rotator cuff tear, left shoulder, not specified as traumatic")],
    "right wrist/hand": [("G56.01", "Carpal tunnel syndrome, right upper limb"), ("S63.501A", "Sprain of right wrist, initial")],
    "left wrist/hand": [("G56.02", "Carpal tunnel syndrome, left upper limb"), ("S63.502A", "Sprain of left wrist, initial")],
    "head": [("S06.0X0A", "Concussion without loss of consciousness, initial"), ("R51.9", "Headache, unspecified")],
}
PARTS = list(DX)
def region_of(part):
    return part.split()[-1].split("/")[0] if part.split()[0] in ("right", "left") else part.split()[0]
def mirror(part):
    a, b = part.split(" ", 1)
    return {"right": "left", "left": "right"}[a] + " " + b

# code: (description, kind, base value, mpr, bilateral, assistant allowed, regions, facility weight, status)
CODES = {
    "E2011": ("Office visit, new patient, low complexity", "em", 2.20, 0, 0, 0, "any", None, None),
    "E2012": ("Office visit, new patient, moderate complexity", "em", 3.40, 0, 0, 0, "any", None, None),
    "E2013": ("Office visit, established patient, low complexity", "em", 1.60, 0, 0, 0, "any", None, None),
    "E2014": ("Office visit, established patient, moderate complexity", "em", 2.50, 0, 0, 0, "any", None, None),
    "E2015": ("Office visit, established patient, high complexity", "em", 3.60, 0, 0, 0, "any", None, None),
    "T3101": ("Therapeutic exercise, each 15 minutes", "pt", 0.85, 0, 0, 0, "nohead", None, None),
    "T3102": ("Manual therapy, each 15 minutes", "pt", 0.80, 0, 0, 0, "nohead", None, None),
    "T3103": ("Neuromuscular reeducation, each 15 minutes", "pt", 0.90, 0, 0, 0, "nohead", None, None),
    "T3104": ("Physical therapy evaluation, moderate complexity", "pt", 2.90, 0, 0, 0, "nohead", None, None),
    "R4101": ("Radiograph, lumbar spine, 2-3 views", "rad", 1.10, 0, 0, 0, "lumbar", 0.62, "S"),
    "R4104": ("Radiograph, cervical spine, 2-3 views", "rad", 1.05, 0, 0, 0, "cervical", 0.60, "S"),
    "R4106": ("Radiograph, thoracic spine, 2 views", "rad", 0.98, 0, 0, 0, "thoracic", 0.58, "S"),
    "R4102": ("Radiograph, knee, 3 views", "rad", 0.90, 0, 0, 0, "knee", 0.55, "S"),
    "R4103": ("Radiograph, shoulder, 2 views", "rad", 0.95, 0, 0, 0, "shoulder", 0.56, "S"),
    "R4105": ("Radiograph, wrist, 3 views", "rad", 0.88, 0, 0, 0, "wrist", 0.52, "S"),
    "R4201": ("MRI lumbar spine without contrast", "rad", 6.50, 0, 0, 0, "lumbar", 3.10, "S"),
    "R4204": ("MRI cervical spine without contrast", "rad", 6.60, 0, 0, 0, "cervical", 3.15, "S"),
    "R4202": ("MRI lower extremity joint without contrast", "rad", 6.80, 0, 0, 0, "knee", 3.20, "S"),
    "R4203": ("MRI upper extremity joint without contrast", "rad", 6.90, 0, 0, 0, "shoulder wrist", 3.25, "S"),
    "R4301": ("CT head without contrast", "rad", 4.20, 0, 0, 0, "head", 2.05, "S"),
    "J5101": ("Trigger point injection, 1-2 muscles", "inj", 1.30, 2, 0, 0, "lumbar cervical thoracic shoulder", 0.90, "T"),
    "J5102": ("Arthrocentesis/injection, major joint", "inj", 1.60, 2, 1, 0, "knee shoulder", 1.05, "T"),
    "J5105": ("Arthrocentesis/injection, small joint", "inj", 1.20, 2, 1, 0, "wrist", 0.85, "T"),
    "J5103": ("Epidural steroid injection, lumbar", "inj", 5.20, 2, 0, 0, "lumbar", 6.40, "T"),
    "J5106": ("Epidural steroid injection, cervical", "inj", 5.60, 2, 0, 0, "cervical", 6.70, "T"),
    "J5104": ("Facet joint injection, single level", "inj", 4.80, 2, 1, 0, "lumbar cervical", 6.10, "T"),
    "S6101": ("Arthroscopic meniscectomy, knee", "surg", 14.50, 2, 1, 1, "knee", 28.0, "T"),
    "S6102": ("Arthroscopic debridement, knee", "surg", 12.00, 2, 1, 0, "knee", 24.5, "T"),
    "S6103": ("Arthroscopic rotator cuff repair", "surg", 22.00, 2, 0, 1, "shoulder", 41.0, "T"),
    "S6104": ("Arthroscopic subacromial decompression", "surg", 9.50, 2, 0, 1, "shoulder", 19.0, "T"),
    "S6105": ("Carpal tunnel release, open", "surg", 9.80, 2, 1, 0, "wrist", 17.5, "T"),
    "S6106": ("Trigger finger release", "surg", 7.20, 2, 0, 0, "wrist", 13.0, "T"),
    "S6107": ("Lumbar discectomy, single interspace", "surg", 28.00, 2, 0, 1, "lumbar", 52.0, "T"),
    "S6108": ("Laminotomy, lumbar, single interspace", "surg", 18.50, 2, 0, 1, "lumbar", 35.0, "T"),
    "S6109": ("Simple wound repair, up to 7.5 cm", "surg", 2.80, 2, 0, 0, "any", 4.2, "T"),
    "S6110": ("Intermediate wound repair, up to 7.5 cm", "surg", 4.50, 2, 0, 0, "any", 6.8, "T"),
    "D7101": ("Lumbar-sacral orthosis, prefabricated", "sup", 145.0, 0, 0, 0, "lumbar", 1.10, "N"),
    "D7102": ("Knee orthosis, hinged, prefabricated", "sup", 210.0, 0, 0, 0, "knee", 1.50, "N"),
    "D7103": ("Wrist-hand orthosis, prefabricated", "sup", 65.0, 0, 0, 0, "wrist", 0.50, "N"),
    "D7104": ("Cold therapy device", "sup", 180.0, 0, 0, 0, "knee shoulder", 1.30, "N"),
    "D7105": ("Cervical collar, semi-rigid", "sup", 48.0, 0, 0, 0, "cervical", 0.40, "N"),
}
EDITS = [("S6101", "S6102", 1), ("S6103", "S6104", 1), ("S6107", "S6108", 0), ("S6110", "S6109", 1),
         ("J5103", "J5101", 0), ("J5104", "J5101", 1), ("T3104", "T3101", 1), ("S6105", "S6106", 1), ("J5106", "J5104", 1)]
DECOY_EDITS = [("R4202", "R4102", 0), ("R4201", "R4101", 0), ("E2012", "E2011", 0)]  # pairs never billed together
SURG_PAIRS = {"knee": [("S6101", "S6102")], "shoulder": [("S6103", "S6104")], "wrist": [("S6105", "S6106")], "lumbar": [("S6107", "S6108")]}
REV = {"surg": "0360", "inj": "0361", "rad": "0320", "sup": "0274"}
FIRST = ["Alder", "Birch", "Cedar", "Summit", "Valley", "Ridge", "Harbor", "Pioneer", "Lakeside", "Granite", "Prairie", "Riverbend", "Canyon", "Meadow", "Bluff"]
KIND = {"clinic": ("Occupational Medicine", "CMS-1500"), "pt": ("Physical Therapy", "CMS-1500"), "img": ("Diagnostic Imaging", "CMS-1500"),
        "surgeon": ("Orthopedic Surgery", "CMS-1500"), "fac": ("Ambulatory Surgery Center", "UB-04"), "dme": ("Durable Medical Equipment", "CMS-1500")}
POOL = {"clinic": 26, "pt": 18, "img": 9, "surgeon": 12, "fac": 7, "dme": 5}


def fits(code, region):
    r = CODES[code][6]
    return r == "any" or (r == "nohead" and region != "head") or region in r.split()


def cf_on(state, sched, dos):
    v = None
    for d, c in CF[state][sched]:
        if dos >= d:
            v = c
    return v


def tables(rng):
    prof, fac = [], []
    for s in STATES:
        for c, (desc, kind, base, mpr, bil, asst, reg, w, st) in CODES.items():
            if kind == "sup":
                prof.append(dict(state=s, code=c, description=desc, rvu="", flat_fee_usd=round(base * SCALE[s] * rng.uniform(0.96, 1.04), 2),
                                 mpr_indicator=0, bilateral_indicator=0, assistant_surgeon=0))
            else:
                prof.append(dict(state=s, code=c, description=desc, rvu=round(base * SCALE[s] * rng.uniform(0.97, 1.03), 2), flat_fee_usd="",
                                 mpr_indicator=mpr, bilateral_indicator=bil, assistant_surgeon=asst))
            if w is not None:
                fac.append(dict(state=s, hcpcs=c, description=desc, relative_weight=round(w * SCALE[s] * rng.uniform(0.97, 1.03), 4), status_indicator=st))
    prof = pd.DataFrame(prof)
    ref = {}
    for s in STATES:
        cf = CF[s]["professional"][-1][1]
        for r in prof[prof.state == s].itertuples():
            ref[(s, r.code)] = r.flat_fee_usd if r.rvu == "" else r.rvu * cf
    prof["medicare_reference_usd"] = [round(ref[(r.state, r.code)] * rng.uniform(0.70, 0.82), 2) for r in prof.itertuples()]
    return prof, pd.DataFrame(fac)


def generate(seed=SEED):
    rng = np.random.default_rng(seed)
    prof, fac = tables(rng)
    P = {(r.state, r.code): r for r in prof.itertuples()}
    F = {(r.state, r.hcpcs): r for r in fac.itertuples()}

    # providers
    provs, npi_used = [], set()
    def new_npi():
        while True:
            n = "1" + "".join(str(x) for x in rng.integers(0, 10, 9))
            if n not in npi_used:
                npi_used.add(n); return n
    for s in STATES + NOSCHED:
        for kind, n in POOL.items():
            n = n if s in STATES else max(1, n // 5)
            for _ in range(n):
                nm = f"{rng.choice(FIRST)} {KIND[kind][0]}" + (" Center" if kind in ("img", "fac") else rng.choice([" Associates", " Group", " Clinic", " PLLC", ""]))
                remit = s if rng.random() < 0.80 else str(rng.choice([x for x in STATES if x != s] + ["TX", "GA"]))
                bill_ratio = rng.uniform(0.88, 1.30) if rng.random() < 0.42 else rng.uniform(1.5, 2.8)
                provs.append(dict(npi=new_npi(), name=nm, kind=kind, state=s, remit_state=remit, ratio=bill_ratio,
                                  tax_id=f"{rng.integers(10, 99)}-{rng.integers(1000000, 9999999)}"))
    pv = pd.DataFrame(provs)
    part_rows = []
    for p in provs:
        if p["state"] not in STATES and rng.random() < 0.6:
            continue
        if rng.random() < 0.58:
            net = str(rng.choice(list(NETWORKS), p=[0.4, 0.35, 0.25]))
            start = pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(rng.integers(0, 900)))
            end = ""
            if rng.random() < 0.22:
                end = (pd.Timestamp("2025-12-15") + pd.Timedelta(days=int(rng.integers(0, 200)))).strftime("%Y-%m-%d")
            part_rows.append(dict(npi=p["npi"], network=net, effective_from=start.strftime("%Y-%m-%d"), terminated_on=end))
            if end and rng.random() < 0.3:
                net2 = str(rng.choice([n for n in NETWORKS if n != net]))
                st2 = (pd.Timestamp(end) + pd.Timedelta(days=int(rng.integers(20, 90)))).strftime("%Y-%m-%d")
                part_rows.append(dict(npi=p["npi"], network=net2, effective_from=st2, terminated_on=""))
    part = pd.DataFrame(part_rows)
    stale = part.groupby("npi").network.first().to_dict()  # the provider master shows the first listed network
    pv["ppo_network"] = pv.npi.map(stale).fillna("")
    by = {(s, k): pv[(pv.state == s) & (pv.kind == k)].npi.tolist() for s in STATES + NOSCHED for k in POOL}
    PROV = {r.npi: r for r in pv.itertuples()}

    def pick(state, kind):
        u = rng.random()
        if u < 0.07:
            s2 = str(rng.choice([x for x in STATES if x != state]))
        elif u < 0.10:
            s2 = str(rng.choice(NOSCHED))
        else:
            s2 = state
        return str(rng.choice(by[(s2, kind)]))

    # claims
    claims, dets = [], []
    d0, d1 = pd.Timestamp("2025-06-01"), pd.Timestamp("2026-06-01")
    for i in range(N_CLAIMS):
        st = STATES[i % 4] if rng.random() < 0.9 else str(rng.choice(STATES))
        inj = d0 + pd.Timedelta(days=int(rng.integers(0, (d1 - d0).days)))
        main = str(rng.choice(PARTS, p=np.array([18, 8, 3, 9, 9, 9, 9, 7, 7, 4], float) / 83))
        claimed = [main]
        for _ in range(int(rng.choice([0, 1, 2], p=[0.45, 0.4, 0.15]))):
            o = str(rng.choice(PARTS))
            if o not in claimed:
                claimed.append(o)
        status = {main: "accepted"}
        for o in claimed[1:]:
            status[o] = str(rng.choice(["accepted", "denied", "pending"], p=[0.45, 0.35, 0.2]))
        cid = f"WC{26000000 + i * 7 + int(rng.integers(0, 7))}"
        claims.append(dict(claim_id=cid, jurisdiction_state=st, injury_date=inj.strftime("%Y-%m-%d"),
                           employer=f"{rng.choice(FIRST)} {rng.choice(['Logistics', 'Foods', 'Builders', 'Manufacturing', 'Health', 'Retail', 'Transit'])}",
                           occupation=str(rng.choice(["warehouse associate", "nurse aide", "carpenter", "driver", "line operator", "cashier", "electrician", "custodian"])),
                           claimed_body_parts=";".join(claimed), status=status, main=main))
        for o in claimed:
            dd = inj + pd.Timedelta(days=int(rng.integers(5, 60)))
            dets.append(dict(claim_id=cid, body_part=o, determination=status[o], determination_date=dd.strftime("%Y-%m-%d")))
    # a few disputed parts later reversed: the most recent determination controls
    det = pd.DataFrame(dets)
    flip = det[det.determination != "accepted"].sample(frac=0.45, random_state=seed)
    extra = flip.copy()
    extra["determination"] = "accepted"
    extra["determination_date"] = (pd.to_datetime(flip.determination_date) + pd.to_timedelta(rng.integers(30, 120, len(flip)), unit="D")).dt.strftime("%Y-%m-%d")
    acc2 = det[(det.determination == "accepted") & det.duplicated("claim_id")].sample(frac=0.50, random_state=seed + 1)
    extra2 = acc2.copy()
    extra2["determination"] = "denied"
    extra2["determination_date"] = (pd.to_datetime(acc2.determination_date) + pd.to_timedelta(rng.integers(20, 90, len(acc2)), unit="D")).dt.strftime("%Y-%m-%d")
    for idx in acc2.index:
        next(c for c in claims if c["claim_id"] == acc2.loc[idx, "claim_id"])["status"][acc2.loc[idx, "body_part"]] = "denied"
    extra = pd.concat([extra, extra2])
    det = pd.concat([det, extra]).sort_values(["claim_id", "determination_date", "body_part"]).reset_index(drop=True)
    for c in claims:
        for idx in flip[flip.claim_id == c["claim_id"]].index:
            c["status"][flip.loc[idx, "body_part"]] = "accepted"

    bills, lines = [], []
    seen_service = set()
    bseq = [0]
    def new_bill(c, npi, form, dx_main, received, freq=1, orig=""):
        bseq[0] += 1
        bid = f"B{bseq[0] * 13 + 100000:07d}"
        p = PROV[npi]
        b = dict(bill_id=bid, claim_id=c["claim_id"], provider_npi=npi, form_type=form, frequency_code=freq, original_bill_ref=orig,
                 received_date=received.strftime("%Y-%m-%d"), billing_provider_state=p.remit_state, service_facility_state=p.state,
                 principal_dx=dx_main if form == "UB-04" else "", gen="live", _c=c)
        bills.append(b)
        return b
    def ref_amount(c, code, units, mods, form, rev, billed_hint=None):
        s = c["jurisdiction_state"]
        if form == "UB-04":
            if code == "":
                return billed_hint
            return F[(s, code)].relative_weight * CF[s]["facility"][-1][1] * units
        r = P[(s, code)]
        v = (r.flat_fee_usd if r.rvu == "" else r.rvu * CF[s]["professional"][-1][1]) * units
        if "50" in mods: v *= 1.5
        if "80" in mods: v *= 0.2
        return v
    def add_line(b, dos, code, units=1, mods=(), dx=(), rev="", raw=None):
        c = b["_c"]
        key = (c["claim_id"], b["provider_npi"], dos.strftime("%Y-%m-%d"), code, rev)
        if code and key in seen_service:
            return False
        seen_service.add(key)
        if raw is None:
            ratio = PROV[b["provider_npi"]].ratio
            raw = ref_amount(c, code, units, mods, b["form_type"], rev) * ratio * rng.uniform(0.95, 1.05)
        billed = float(max(5, round(raw)))
        lines.append(dict(bill_id=b["bill_id"], line_no=0,
                          service_date=dos.strftime("%Y-%m-%d"), revenue_code=rev, procedure_code=code, modifiers=" ".join(mods),
                          units=units, diagnosis_codes=";".join(dx), billed_usd=billed))
        return True

    def dxs(part, n=1):
        opts = DX[part]
        k = rng.permutation(len(opts))[:n]
        return [opts[j][0] for j in k]

    for c in claims:
        st, inj = c["jurisdiction_state"], pd.Timestamp(c["injury_date"])
        acc = [p for p, v in c["status"].items() if v == "accepted"]
        others = [p for p in c["status"] if c["status"][p] != "accepted"]
        main = c["main"]
        reg = region_of(main)
        t0 = max(inj, pd.Timestamp("2025-10-01"))
        endd = pd.Timestamp("2026-07-01")
        if t0 >= endd: t0 = endd - pd.Timedelta(days=30)
        def day(a, b):
            x = t0 + pd.Timedelta(days=int(rng.integers(a, b)))
            return min(x, endd)
        def recv(dos):
            return dos + pd.Timedelta(days=int(rng.integers(6, 40)))
        def maindx(n=1):
            out = dxs(main, n)
            if rng.random() < 0.25 and len(acc) > 1:
                out += dxs(str(rng.choice([a for a in acc if a != main])))
            return out
        # clinic visits
        cl = pick(st, "clinic")
        nvis = int(rng.integers(1, 6))
        vd = sorted(set(day(0, 200) for _ in range(nvis)))
        for k, dos in enumerate(vd):
            b = new_bill(c, cl, "CMS-1500", "", recv(dos))
            dx = maindx()
            em = ("E2011" if rng.random() < 0.5 else "E2012") if k == 0 else str(rng.choice(["E2013", "E2014", "E2015"], p=[0.3, 0.5, 0.2]))
            pre = rng.random() < 0.06 and k == 0
            dd = inj - pd.Timedelta(days=int(rng.integers(1, 25))) if pre else dos
            add_line(b, dd, em, 1, ("25",) if rng.random() < 0.3 else (), dx)
            if k == 0 and rng.random() < 0.6:
                xr = [x for x in ("R4101", "R4104", "R4106", "R4102", "R4103", "R4105", "R4301") if fits(x, reg)]
                if xr: add_line(b, dd, xr[0], 1, (), dx)
            inj_codes = [x for x in ("J5101", "J5102", "J5105", "J5103", "J5106", "J5104") if fits(x, reg)]
            if inj_codes and rng.random() < 0.3:
                j = str(rng.choice(inj_codes))
                mods = ("50",) if CODES[j][4] and rng.random() < 0.2 else ()
                add_line(b, dd, j, 1, mods, dx)
                if j in ("J5103", "J5104") and rng.random() < 0.45:
                    add_line(b, dd, "J5101", 1, ("59",) if rng.random() < 0.5 else ("51",), dx)
                elif rng.random() < 0.4:
                    others_inj = [x for x in inj_codes if x != j]
                    if others_inj:
                        j2 = str(rng.choice(others_inj))
                        add_line(b, dd, j2, 1, ("51",) if rng.random() < 0.6 else (), dx)
                        rest = [x for x in others_inj if x != j2]
                        if rest and rng.random() < 0.5:
                            add_line(b, dd, str(rng.choice(rest)), 1, ("51",) if rng.random() < 0.5 else (), dx)
            sups = [x for x in ("D7101", "D7102", "D7103", "D7104", "D7105") if fits(x, reg)]
            if k == 0 and sups and rng.random() < 0.3:
                add_line(b, dd, str(rng.choice(sups)), 1, (), dx)
            # a line aimed at a non-accepted or opposite-side part
            if rng.random() < 0.12:
                if others and rng.random() < 0.6:
                    o = str(rng.choice(others))
                elif region_of(main) in SIDED:
                    o = mirror(main)
                else:
                    o = None
                if o and o not in acc:
                    xr = [x for x in ("R4101", "R4104", "R4106", "R4102", "R4103", "R4105", "R4301") if fits(x, region_of(o))]
                    if xr:
                        add_line(b, dd, xr[0], 1, (), dxs(o) + (dx[:1] if rng.random() < 0.6 else []))
        # separate visit for a disputed part
        if others and rng.random() < 0.35:
            o = str(rng.choice(others))
            dos = day(5, 150)
            b = new_bill(c, cl if rng.random() < 0.7 else pick(st, "clinic"), "CMS-1500", "", recv(dos))
            add_line(b, dos, str(rng.choice(["E2013", "E2014"])), 1, (), dxs(o) + (dxs(main) if rng.random() < 0.5 else []))
            xr = [x for x in ("R4101", "R4104", "R4106", "R4102", "R4103", "R4105", "R4301") if fits(x, region_of(o))]
            if xr and rng.random() < 0.5:
                add_line(b, dos, xr[0], 1, (), dxs(o))
        # imaging
        if rng.random() < 0.45:
            mri = [x for x in ("R4201", "R4204", "R4202", "R4203", "R4301") if fits(x, reg)]
            if mri:
                im = pick(st, "img"); dos = day(10, 120)
                b = new_bill(c, im, "CMS-1500", "", recv(dos))
                add_line(b, dos, mri[0], 1, (), maindx())
        # physical therapy
        if reg != "head" and rng.random() < 0.7:
            pt = pick(st, "pt")
            nv = int(rng.integers(3, 16))
            ds = sorted(set(day(15, 260) for _ in range(nv)))
            chunks = [ds[i:i + int(rng.integers(1, 5))] for i in range(0, len(ds), 4)]
            first = True
            for ch in chunks:
                b = new_bill(c, pt, "CMS-1500", "", recv(ch[-1]))
                dx = maindx()
                for dos in ch:
                    if first:
                        add_line(b, dos, "T3104", 1, ("GP",), dx)
                        if rng.random() < 0.5:
                            add_line(b, dos, "T3101", int(rng.integers(1, 3)), ("GP", "59") if rng.random() < 0.5 else ("GP",), dx)
                        first = False
                        continue
                    for code in rng.permutation(["T3101", "T3102", "T3103"])[:int(rng.integers(1, 4))]:
                        add_line(b, dos, str(code), int(rng.integers(1, 5)), ("GP",), dx)
        # surgery
        if reg in SURG_PAIRS and rng.random() < 0.3 or (rng.random() < 0.04):
            dos = day(40, 230)
            sg = pick(st, "surgeon")
            dx = maindx(2 if len(DX[main]) > 1 else 1)
            if reg in SURG_PAIRS:
                a, bcode = SURG_PAIRS[reg][0]
            else:
                a, bcode = "S6110", "S6109"
            procs = [(a, ())]
            u = rng.random()
            if u < 0.7:
                ed = any(e[0] == a and e[1] == bcode for e in EDITS)
                if ed:
                    m = str(rng.choice(["59", "XS", "51", ""], p=[0.45, 0.15, 0.25, 0.15]))
                    procs.append((bcode, (m,) if m else ()))
                else:
                    procs.append((bcode, ("51",) if rng.random() < 0.7 else ()))
            if rng.random() < 0.75:
                extra_code = {"knee": "J5102", "shoulder": "J5101", "wrist": "J5105", "lumbar": "J5104"}.get(reg, "S6109")
                if extra_code not in [p[0] for p in procs]:
                    procs.append((extra_code, ("51",) if rng.random() < 0.5 else ()))
            if a != "S6110" and rng.random() < 0.5:
                procs.append(("S6109", ("51",) if rng.random() < 0.5 else ()))
            # modifier 51 sometimes placed on the primary instead
            if len(procs) > 1 and rng.random() < 0.4:
                procs = [(procs[0][0], ("51",))] + [(p, tuple(m for m in mm if m != "51")) for p, mm in procs[1:]]
            if CODES[a][4] and rng.random() < 0.18:
                procs[0] = (a, procs[0][1] + ("50",))
            if len(procs) > 1 and rng.random() < 0.4:
                procs = [procs[j] for j in rng.permutation(len(procs))]
            split = len(procs) > 1 and rng.random() < 0.45
            b1 = new_bill(c, sg, "CMS-1500", "", recv(dos))
            b2 = new_bill(c, sg, "CMS-1500", "", recv(dos) + pd.Timedelta(days=int(rng.integers(3, 30)))) if split else b1
            for k, (code, mods) in enumerate(procs):
                add_line(b1 if (k == 0 or not split) else b2, dos, code, 1, mods, dx)
            if rng.random() < 0.6:
                asg = pick(st, "surgeon")
                if asg != sg:
                    b3 = new_bill(c, asg, "CMS-1500", "", recv(dos))
                    add_line(b3, dos, a, 1, ("80",), dx)
            # facility
            fc = pick(st, "fac")
            bf = new_bill(c, fc, "UB-04", dx[0], recv(dos) + pd.Timedelta(days=int(rng.integers(0, 20))))
            for code, mods in procs:
                add_line(bf, dos, code, 1, tuple(m for m in mods if m in ("50", "59", "XS")), (), REV[CODES[code][1]])
            add_line(bf, dos, "", 1, (), (), "0250", raw=rng.uniform(120, 900))
            add_line(bf, dos, "", 1, (), (), "0270", raw=rng.uniform(80, 700))
            add_line(bf, dos, "", 1, (), (), "0370", raw=rng.uniform(600, 2500))
            add_line(bf, dos, "", 1, (), (), "0710", raw=rng.uniform(300, 1400))
            if rng.random() < 0.4:
                s2 = [x for x in ("D7101", "D7102", "D7103", "D7104", "D7105") if fits(x, reg)]
                if s2: add_line(bf, dos, s2[0], 1, (), (), "0274")
            if rng.random() < 0.3:
                xr = [x for x in ("R4101", "R4104", "R4106", "R4102", "R4103", "R4105") if fits(x, reg)]
                if xr: add_line(bf, dos, xr[0], 1, (), (), "0320")
            if rng.random() < 0.5:
                dm = pick(st, "dme")
                s2 = [x for x in ("D7101", "D7102", "D7103", "D7104", "D7105") if fits(x, reg)]
                if s2:
                    b4 = new_bill(c, dm, "CMS-1500", "", recv(dos))
                    for x in s2[:2]: add_line(b4, dos, x, 1, (), dx[:1])

    B = pd.DataFrame(bills)
    L = pd.DataFrame(lines)
    L = L[L.bill_id.isin(B.bill_id)]
    B = B[B.bill_id.isin(L.bill_id)].reset_index(drop=True)
    L["line_no"] = L.groupby("bill_id").cumcount() + 1
    L = L.reset_index(drop=True)

    # duplicates, replacements, voids, rebills after a void
    orig = B.bill_id.tolist()
    rng.shuffle(orig)
    n = len(orig)
    n_dup, n_rep, n_void = int(0.050 * n), int(0.062 * n), int(0.034 * n)
    dup_src, rep_src, void_src = orig[:n_dup], orig[n_dup:n_dup + n_rep], orig[n_dup + n_rep:n_dup + n_rep + n_void]
    BR = {r["bill_id"]: dict(r) for r in B.to_dict("records")}
    LB = {k: g.copy() for k, g in L.groupby("bill_id")}
    newB, newL = [], []
    gen = {b: "live" for b in B.bill_id}
    def clone(src, freq, ref, lag, mutate=False):
        r = BR[src]
        bseq[0] += 1
        bid = f"B{bseq[0] * 13 + 100000:07d}"
        nb = dict(r); nb.update(bill_id=bid, frequency_code=freq, original_bill_ref=ref,
                               received_date=(pd.Timestamp(r["received_date"]) + pd.Timedelta(days=lag)).strftime("%Y-%m-%d"))
        ls = LB[src].copy().reset_index(drop=True)
        ls["bill_id"] = bid
        if mutate:
            k = int(rng.integers(0, len(ls)))
            what = rng.random()
            row = ls.loc[k]
            if what < 0.3:
                ls.loc[k, "billed_usd"] = float(round(row.billed_usd * rng.uniform(0.6, 0.95)))
            elif what < 0.5 and row.procedure_code and row.revenue_code == "":
                m = row.modifiers.split()
                m = [x for x in m if x != "59"] if "59" in m else m + ["59"]
                ls.loc[k, "modifiers"] = " ".join(m)
            elif what < 0.65 and row.revenue_code == "" and row.procedure_code.startswith("T"):
                u = int(row.units)
                ls.loc[k, "units"] = u + 1
                ls.loc[k, "billed_usd"] = float(round(row.billed_usd * (u + 1) / u))
            elif what < 0.8 and len(ls) > 1:
                ls = ls.drop(k).reset_index(drop=True)
            elif row.diagnosis_codes:
                c = r["_c"]; acc = [p for p, v in c["status"].items() if v == "accepted"]
                ls.loc[k, "diagnosis_codes"] = ";".join(dxs(str(rng.choice(acc))))
            else:
                ls.loc[k, "billed_usd"] = float(round(row.billed_usd * rng.uniform(1.05, 1.3)))
            ls["line_no"] = range(1, len(ls) + 1)
        BR[bid] = nb; LB[bid] = ls
        newB.append(nb); newL.append(ls)
        return bid
    for s in dup_src:
        b = clone(s, 1, "", int(rng.integers(10, 40))); gen[b] = "duplicate"
    for s in rep_src:
        b = clone(s, 7, s, int(rng.integers(12, 45)), mutate=True); gen[s] = "replaced"; gen[b] = "live"
        if rng.random() < 0.15:
            b2 = clone(b, 7, b, int(rng.integers(8, 25)), mutate=True); gen[b] = "replaced"; gen[b2] = "live"
    for s in void_src:
        b = clone(s, 8, s, int(rng.integers(10, 35))); gen[s] = "voided"; gen[b] = "void"
        if rng.random() < 0.7:
            b2 = clone(s, 1, "", int(rng.integers(40, 60)), mutate=rng.random() < 0.5); gen[b2] = "live"
    B = pd.concat([B, pd.DataFrame(newB)], ignore_index=True)
    L = pd.concat([L] + newL, ignore_index=True)
    B["gen"] = B.bill_id.map(gen)
    C = pd.DataFrame(claims)
    T = truth_lines(B, L, C, prof, fac, part, det)

    # payments: issued by the prior bill review on many bills before they were replaced, duplicated or voided
    pays = []
    pid = [0]
    Bx = B.set_index("bill_id")
    tl = T.set_index(["bill_id", "line_no"])
    def pay(bid, ln, amt, date, typ="payment"):
        pid[0] += 1
        pays.append(dict(payment_id=f"P{700000 + pid[0] * 3}", bill_id=bid, line_no=int(ln), amount_usd=round(amt, 2), transaction_date=date, transaction_type=typ))
    svc_true = {}  # service key -> correct allowed on the live line
    for r in T.itertuples():
        if r.status == "live":
            svc_true[r.key] = r.allowed
    LG = {k: g for k, g in L.groupby("bill_id")}
    for r in B.itertuples():
        if r.frequency_code != 1 and r.gen != "replaced":
            continue
        g = r.gen
        p_bill = {"live": 0.42, "replaced": 0.7, "voided": 0.6, "duplicate": 0.10}.get(g, 0)
        if rng.random() >= p_bill:
            continue
        d = (pd.Timestamp(r.received_date) + pd.Timedelta(days=int(rng.integers(6, 12)))).strftime("%Y-%m-%d")
        if d > "2026-10-09":
            continue
        for x in LG[r.bill_id].itertuples():
            base = svc_true.get(tl.loc[(r.bill_id, x.line_no)].key, 0.0)
            if base <= 0:
                base = x.billed_usd * rng.uniform(0.3, 0.6)
            u = rng.random()
            amt = base * (rng.uniform(1.0, 1.25) if u < 0.25 else rng.uniform(0.45, 0.98))
            if rng.random() < 0.08:
                continue
            pay(r.bill_id, x.line_no, amt, d)
            if rng.random() < 0.06:
                d2 = (pd.Timestamp(d) + pd.Timedelta(days=int(rng.integers(4, 20)))).strftime("%Y-%m-%d")
                if d2 <= "2026-10-09":
                    pay(r.bill_id, x.line_no, -round(amt, 2), d2, "reversal")
    PAY = pd.DataFrame(pays)
    T = net_payments(T, PAY, B)
    return dict(B=B, L=L, C=C, prof=prof, fac=fac, part=part, det=det, pv=pv, PAY=PAY), T


def truth_lines(B, L, C, prof, fac, part, det):
    """Correct allowed amount per line from the generator's knowledge of each bill's history."""
    P = {(r.state, r.code): r for r in prof.itertuples()}
    F = {(r.state, r.hcpcs): r for r in fac.itertuples()}
    cl = C.set_index("claim_id")
    acc = {c: {p for p, v in s.items() if v == "accepted"} for c, s in zip(C.claim_id, C.status)}
    dxp = {code: part for part, lst in DX.items() for code, _ in lst}
    parts = {}
    for r in part.itertuples():
        parts.setdefault(r.npi, []).append((r.effective_from, r.terminated_on or "9999-12-31", r.network))
    M = L.merge(B[["bill_id", "claim_id", "provider_npi", "form_type", "service_facility_state", "principal_dx", "gen"]], on="bill_id")
    M["state"] = M.claim_id.map(cl.jurisdiction_state)
    M["injury"] = M.claim_id.map(cl.injury_date)
    M["key"] = list(zip(M.claim_id, M.provider_npi, M.service_date, M.procedure_code, M.revenue_code))
    live = M.gen == "live"
    pdx = np.where(M.form_type == "UB-04", M.principal_dx, M.diagnosis_codes.str.split(";").str[0])
    comp = live & (M.service_date >= M.injury) & np.array([dxp.get(d) in acc[c] for d, c in zip(pdx, M.claim_id)])
    # bundling edits on professional lines of the same provider and date
    E = {(a, b): m for a, b, m in EDITS}
    prof_live = M[live & (M.form_type == "CMS-1500")]
    codes_by = prof_live.groupby(["claim_id", "provider_npi", "service_date"]).procedure_code.apply(set).to_dict()
    bundled = np.zeros(len(M), bool)
    for i, r in enumerate(M.itertuples()):
        if not live.iloc[i] or r.form_type != "CMS-1500":
            continue
        have = codes_by.get((r.claim_id, r.provider_npi, r.service_date), set())
        mods = r.modifiers.split()
        for a in have:
            m = E.get((a, r.procedure_code))
            if m is not None and not (m == 1 and ("59" in mods or "XS" in mods)):
                bundled[i] = True
    M["comp"] = comp & ~bundled

    def sched_states(r):
        s, v = r.state, r.service_facility_state
        if v == s or v not in STATES:
            return [s]
        if s == "NM": return [v]
        if s == "SC": return [s, v]
        return [s]
    M["cands"] = [sched_states(r) for r in M.itertuples()]

    def full(r, s):
        mods = r.modifiers.split()
        if r.form_type == "UB-04":
            if r.revenue_code.startswith(PACKAGED_REV):
                return 0.0
            if r.procedure_code == "":
                return PCT_CHARGES[s] * r.billed_usd
            f = F[(s, r.procedure_code)]
            if f.status_indicator == "N":
                return 0.0
            return f.relative_weight * cf_on(s, "facility", r.service_date) * r.units
        p = P[(s, r.procedure_code)]
        v = p.flat_fee_usd * r.units if p.rvu == "" else p.rvu * cf_on(s, "professional", r.service_date) * r.units
        if "50" in mods and p.bilateral_indicator == 1: v *= BILATERAL
        if "80" in mods: v = v * ASSIST_PCT[s] if p.assistant_surgeon == 1 else 0.0
        return v
    sched = {}
    for s in STATES:
        idx = [i for i, c in enumerate(M.cands) if s in c]
        sub = M.iloc[idx].copy()
        sub["full"] = [full(r, s) for r in sub.itertuples()]
        sub["mult"] = 1.0
        # professional multiple procedure reduction, same provider and date, across bills
        pr = sub[sub.comp & (sub.form_type == "CMS-1500")]
        pr = pr[[P[(s, c)].mpr_indicator == 2 for c in pr.procedure_code]]
        for _, g in pr.groupby(["claim_id", "provider_npi", "service_date"]):
            if len(g) < 2: continue
            o = g.sort_values(["full", "bill_id", "line_no"], ascending=[False, True, True]).index
            for k, ix in enumerate(o):
                sub.loc[ix, "mult"] = 1.0 if k == 0 else (0.5 if k == 1 else MPR_THIRD[s])
        fr = sub[sub.comp & (sub.form_type == "UB-04") & (sub.procedure_code != "")]
        fr = fr[[F[(s, c)].status_indicator == "T" for c in fr.procedure_code]]
        for _, g in fr.groupby("bill_id"):
            if len(g) < 2: continue
            o = g.sort_values(["full", "line_no"], ascending=[False, True]).index
            for k, ix in enumerate(o):
                sub.loc[ix, "mult"] = 1.0 if k == 0 else FAC_MULT
        for ix, v in zip(sub.index, sub.full * sub.mult):
            sched[ix] = min(sched.get(ix, np.inf), v)
    M["sched"] = pd.Series(sched)
    def network(npi, dos):
        for a, b, n in parts.get(npi, []):
            if a <= dos <= b: return n
        return None
    ppo = []
    for r in M.itertuples():
        n = network(r.provider_npi, r.service_date)
        if n is None:
            ppo.append(np.inf); continue
        d = NETWORKS[n][1]
        ppo.append((r.sched if PPO_BASE[n][r.state] == "schedule" else r.billed_usd) * (1 - d))
    M["ppo"] = ppo
    M["allowed"] = np.where(M.comp, np.minimum(np.minimum(M.billed_usd, M.sched), M.ppo), 0.0).round(2)
    M["status"] = M.gen
    return M[["bill_id", "line_no", "key", "status", "allowed", "billed_usd"]].copy()


def net_payments(T, PAY, B):
    """Credit every payment issued for the same service on a bill that was not voided."""
    voided = set(B.bill_id[B.gen.isin(["voided", "void"])])
    k = T.set_index(["bill_id", "line_no"]).key
    paid = {}
    for r in PAY.itertuples():
        if r.bill_id in voided: continue
        kk = k.loc[(r.bill_id, r.line_no)]
        paid[kk] = paid.get(kk, 0.0) + r.amount_usd
    T = T.copy()
    T["prior_paid"] = [paid.get(x, 0.0) if s == "live" else 0.0 for x, s in zip(T.key, T.status)]
    T["payable"] = np.maximum(0.0, (T.allowed - T.prior_paid).round(2))
    T.loc[T.status != "live", "payable"] = 0.0
    return T


def write(d, T, out, truth_path):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for p in out.iterdir():
        if p.name == "README.md": continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    C = d["C"]
    C[["claim_id", "jurisdiction_state", "injury_date", "employer", "occupation", "claimed_body_parts"]].to_csv(out / "claims.csv", index=False)
    d["det"].to_csv(out / "body_part_determinations.csv", index=False)
    pv = d["pv"].rename(columns={"state": "practice_state", "remit_state": "billing_office_state"})
    pv["specialty"] = pv.kind.map(lambda k: KIND[k][0])
    pv[["npi", "name", "tax_id", "specialty", "practice_state", "billing_office_state", "ppo_network"]].to_csv(out / "providers.csv", index=False)
    d["part"].to_csv(out / "provider_network_participation.csv", index=False)
    pd.DataFrame([dict(network=k, network_name=v[0], discount_pct=round(v[1] * 100, 1), agreement=f"network_agreements/{k}_agreement.md") for k, v in NETWORKS.items()]).to_csv(out / "network_contracts.csv", index=False)
    B = d["B"].sort_values("bill_id")
    B[["bill_id", "claim_id", "provider_npi", "form_type", "frequency_code", "original_bill_ref", "received_date", "billing_provider_state", "service_facility_state", "principal_dx"]].to_csv(out / "bills.csv", index=False)
    L = d["L"].sort_values(["bill_id", "line_no"])
    L[["bill_id", "line_no", "service_date", "revenue_code", "procedure_code", "modifiers", "units", "diagnosis_codes", "billed_usd"]].to_csv(out / "bill_lines.csv", index=False)
    d["PAY"].sort_values("payment_id").to_csv(out / "payment_history.csv", index=False)
    d["prof"].to_csv(out / "professional_fee_schedule.csv", index=False)
    d["fac"].to_csv(out / "facility_fee_schedule.csv", index=False)
    rows = [dict(state=s, schedule=k, effective_from=e, conversion_factor=c, status="adopted", published_on=PUBLISHED[e]) for s in STATES for k in ("professional", "facility") for e, c in CF[s][k]]
    rows += [dict(state=s, schedule=k, effective_from=e, conversion_factor=c, status="proposed", published_on=p) for s, k, e, c, p in PROPOSED]
    pd.DataFrame(rows).sort_values(["state", "schedule", "effective_from"]).to_csv(out / "conversion_factors.csv", index=False)
    pd.DataFrame([dict(column1_code=a, column2_code=b, modifier_indicator=m) for a, b, m in sorted(EDITS + DECOY_EDITS)]).to_csv(out / "procedure_edits.csv", index=False)
    pd.DataFrame([dict(icd10_code=c, description=t, body_part=p) for p, lst in DX.items() for c, t in lst]).sort_values("icd10_code").to_csv(out / "diagnosis_body_part_map.csv", index=False)
    shutil.copytree(HERE / "static", out, dirs_exist_ok=True)
    T = T.sort_values(["bill_id", "line_no"])
    truth = dict(lines={f"{b}|{l}": [float(a), float(p)] for b, l, a, p in zip(T.bill_id, T.line_no, T.allowed, T.payable)},
                 total_allowed_usd=round(float(T.allowed.sum()), 2), total_payable_usd=round(float(T.payable.sum()), 2))
    Path(truth_path).write_text(json.dumps(truth, separators=(",", ":"), sort_keys=True) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(TASK / "environment" / "data"))
    ap.add_argument("--truth", default=str(TASK / "tests" / "truth.json"))
    a = ap.parse_args()
    d, T = generate(a.seed)
    write(d, T, a.out, a.truth)
    print(f"bills {len(d['B'])} lines {len(d['L'])} payments {len(d['PAY'])} allowed {T.allowed.sum():,.2f} payable {T.payable.sum():,.2f}")
    print(d["B"].gen.value_counts().to_dict())
