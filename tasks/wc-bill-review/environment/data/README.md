# Bill review files

Medical bills received on our workers' compensation claims, with the claim, provider, fee schedule and payment records we use to review them. Every person, provider, employer, claim, code and amount is synthetic.

- claims.csv: one row per claim, with the jurisdiction state, date of injury, employer, occupation and the body parts the worker claimed.
- body_part_determinations.csv: each determination made on a claimed body part, with its date.
- bills.csv: bill headers. form_type is CMS-1500 (professional) or UB-04 (facility). frequency_code and original_bill_ref follow the standard claim frequency convention. billing_provider_state is the billing office's state; service_facility_state is the location where the services were rendered. principal_dx is reported on UB-04 bills only.
- bill_lines.csv: service lines. diagnosis_codes lists the line's diagnoses in pointer order (CMS-1500 only). revenue_code is reported on UB-04 lines only. Units and billed charges are per line.
- payment_history.csv: payments and reversals issued on earlier bills, by line.
- providers.csv: provider master extract.
- provider_network_participation.csv: network participation roster by provider.
- network_contracts.csv and network_agreements/: the three PPO networks.
- professional_fee_schedule.csv, facility_fee_schedule.csv and conversion_factors.csv: the four states' fee schedules. medicare_reference_usd is shown for comparison only.
- procedure_edits.csv: the adopted procedure edit table.
- diagnosis_body_part_map.csv: the body part for each diagnosis code.
- regulations/: excerpts of the four states' fee schedule rules.
- bill_review_procedures.md: our bill review procedures.
