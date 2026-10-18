# wc-bill-review

Category: Operations
Sub-Category: Claims

## Task

A workers' compensation insurer's medical bill review team audits the provider bills received on its claims. For every one of 15,473 bill lines the agent determines the amount that should be allowed and the amount still payable after earlier payments, and writes /app/output/bill_review.csv with bill_id, line_no, allowed_usd and payable_usd plus a total row.

## Shipped data (/app/data, generator seed 311)

- claims.csv: 950 claims (KY 224, NM 241, SC 242, ID 243), injuries June 2, 2025 to May 31, 2026; body_part_determinations.csv: 1,798 determinations.
- bills.csv: 6,121 bills (5,801 CMS-1500, 320 UB-04) received October 7, 2025 to October 2, 2026; bill_lines.csv: 15,473 lines dated May 24, 2025 to July 1, 2026, billed $8,134,736.00 in total.
- payment_history.csv: 5,785 transactions (5,462 payments, 323 reversals).
- providers.csv: 347 providers practicing in KY, NM, SC and ID (77 each) and in TN, TX and WA (13 each); provider_network_participation.csv: 190 roster rows on 181 providers; network_contracts.csv and network_agreements/ for three PPO networks.
- professional_fee_schedule.csv (164 rows), facility_fee_schedule.csv (128 rows), conversion_factors.csv (26 rows), procedure_edits.csv (12 pairs), diagnosis_body_part_map.csv (21 codes).
- regulations/ (four state fee schedule excerpts) and bill_review_procedures.md.

The correct totals are $2,914,945.38 allowed and $2,048,516.68 still payable.

Codes, fee schedules, networks, providers and regulation text are synthetic, modeled on real workers' compensation medical fee schedules and bill review practice.

Reproducibility: `python3 authoring/generate_data.py` (numpy 2.2.6, pandas 2.2.3) rewrites environment/data and tests/truth.json byte for byte; the default seed is 311. Calibration of the bands is described in authoring/NOTES.md.
