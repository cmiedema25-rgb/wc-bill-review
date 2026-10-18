# Authoring notes: wc-bill-review

Reproduce (numpy 2.2.6, pandas 2.2.3):

    python3 authoring/generate_data.py                                # seed 311: environment/data + tests/truth.json, byte for byte
    authoring/methods/sweep.sh /tmp/sw "$(seq -s ' ' 301 332)"        # every method on seeds 301-332 (resumable)
    python3 authoring/methods/sweep.py /tmp/sw                        # pass counts and ranges at the task bands

authoring/static/ holds the regulation excerpts, network agreements and bill review procedures copied into the data. The generator computes the truth from how it created each bill (original, duplicate, replacement, void, rebill after a void) and from the rule tables at the top of generate_data.py. solution/solve.py works only from the shipped files; each shortcut in authoring/methods/methods.py is solve.py with one or two steps switched off or done the obvious wrong way. authoring/methods/independent.py is a separately written line-by-line engine that rounds at each pricing step. Scoring is authoring/methods/score.py, the same bands as tests/test_outputs.py.

Bands: at least 99% of lines within 0.5% / $0.50 for allowed_usd and separately payable_usd, at least 99.7% of bills with total payable_usd within 0.5% / $1.00, total allowed and total payable within 0.25%.

Sweep at the shipped bands, seeds 301-332 (shipped seed 311 is one of them); shares are the fraction of lines or bills within band, totals are relative errors:

    32 seeds
    reference                        pass 32/32  lines(allowed) 1.000-1.000  lines(payable) 1.000-1.000  bills 1.000-1.000  total allowed -0.0000 to +0.0000  total payable -0.0000 to +0.0000
    independent                      pass 32/32  lines(allowed) 1.000-1.000  lines(payable) 1.000-1.000  bills 1.000-1.000  total allowed -0.0000 to +0.0000  total payable -0.0000 to +0.0000
    billed_as_allowed                pass  0/32  lines(allowed) 0.017-0.047  lines(payable) 0.010-0.031  bills 0.008-0.030  total allowed +1.5937 to +1.9328  total payable +2.7263 to +3.1684
    cf_latest                        pass  0/32  lines(allowed) 0.633-0.676  lines(payable) 0.659-0.699  bills 0.577-0.629  total allowed +0.0289 to +0.0351  total payable +0.0373 to +0.0462
    cf_by_received_date              pass  0/32  lines(allowed) 0.837-0.858  lines(payable) 0.849-0.871  bills 0.827-0.850  total allowed +0.0090 to +0.0115  total payable +0.0118 to +0.0149
    cf_include_proposed              pass  0/32  lines(allowed) 0.954-0.971  lines(payable) 0.959-0.974  bills 0.944-0.965  total allowed +0.0018 to +0.0027  total payable +0.0023 to +0.0035
    ppo_schedule_base_everywhere     pass  0/32  lines(allowed) 0.778-0.871  lines(payable) 0.801-0.882  bills 0.772-0.863  total allowed -0.0275 to -0.0111  total payable -0.0345 to -0.0139
    ppo_billed_base_everywhere       pass  0/32  lines(allowed) 0.734-0.826  lines(payable) 0.752-0.838  bills 0.729-0.813  total allowed +0.0160 to +0.0304  total payable +0.0211 to +0.0397
    no_ppo                           pass  0/32  lines(allowed) 0.712-0.794  lines(payable) 0.729-0.807  bills 0.690-0.778  total allowed +0.0231 to +0.0365  total payable +0.0298 to +0.0484
    ppo_provider_master_network      pass  0/32  lines(allowed) 0.948-0.978  lines(payable) 0.953-0.981  bills 0.948-0.979  total allowed -0.0053 to -0.0014  total payable -0.0070 to -0.0020
    no_billed_cap                    pass  0/32  lines(allowed) 0.958-0.986  lines(payable) 0.961-0.987  bills 0.943-0.976  total allowed +0.0014 to +0.0050  total payable +0.0019 to +0.0068
    no_multiple_procedure            pass  0/32  lines(allowed) 0.966-0.972  lines(payable) 0.966-0.972  bills 0.937-0.948  total allowed +0.0168 to +0.0207  total payable +0.0243 to +0.0296
    mpr_by_modifier_51               pass  0/32  lines(allowed) 0.963-0.971  lines(payable) 0.964-0.972  bills 0.941-0.953  total allowed -0.0075 to -0.0021  total payable -0.0056 to +0.0029
    mpr_per_bill                     pass  0/32  lines(allowed) 0.991-0.994  lines(payable) 0.991-0.994  bills 0.980-0.987  total allowed +0.0043 to +0.0062  total payable +0.0061 to +0.0087
    mpr_billed_order                 pass  0/32  lines(allowed) 0.981-0.988  lines(payable) 0.982-0.989  bills 0.971-0.982  total allowed -0.0140 to -0.0074  total payable -0.0146 to -0.0066
    mpr_flat_50                      pass  0/32  lines(allowed) 0.994-0.996  lines(payable) 0.994-0.996  bills 0.987-0.992  total allowed +0.0006 to +0.0011  total payable +0.0009 to +0.0015
    no_bundling                      pass  0/32  lines(allowed) 0.972-0.978  lines(payable) 0.977-0.981  bills 0.946-0.958  total allowed +0.0163 to +0.0209  total payable +0.0158 to +0.0216
    bundling_ignores_modifiers       pass  0/32  lines(allowed) 0.980-0.983  lines(payable) 0.982-0.985  bills 0.957-0.965  total allowed -0.0131 to -0.0105  total payable -0.0139 to -0.0100
    bundling_per_bill                pass  0/32  lines(allowed) 0.995-0.998  lines(payable) 0.996-0.998  bills 0.992-0.997  total allowed +0.0031 to +0.0072  total payable +0.0028 to +0.0077
    ignore_frequency_codes           pass  0/32  lines(allowed) 0.869-0.891  lines(payable) 0.894-0.914  bills 0.875-0.886  total allowed +0.0965 to +0.1405  total payable +0.0509 to +0.0880
    no_duplicate_check               pass  0/32  lines(allowed) 0.959-0.966  lines(payable) 0.965-0.972  bills 0.959-0.964  total allowed +0.0358 to +0.0596  total payable +0.0287 to +0.0552
    duplicates_of_inactive_bills     pass  0/32  lines(allowed) 0.985-0.991  lines(payable) 0.986-0.992  bills 0.985-0.989  total allowed -0.0230 to -0.0091  total payable -0.0272 to -0.0088
    no_body_part_check               pass  0/32  lines(allowed) 0.979-0.983  lines(payable) 0.981-0.984  bills 0.958-0.966  total allowed +0.0072 to +0.0098  total payable +0.0078 to +0.0108
    any_diagnosis_pointer            pass  0/32  lines(allowed) 0.990-0.993  lines(payable) 0.991-0.993  bills 0.977-0.982  total allowed +0.0032 to +0.0047  total payable +0.0033 to +0.0050
    claimed_body_parts               pass  0/32  lines(allowed) 0.986-0.990  lines(payable) 0.987-0.990  bills 0.974-0.981  total allowed +0.0052 to +0.0078  total payable +0.0056 to +0.0086
    ignore_laterality                pass  0/32  lines(allowed) 0.991-0.994  lines(payable) 0.991-0.994  bills 0.978-0.985  total allowed +0.0020 to +0.0029  total payable +0.0022 to +0.0034
    first_determination              pass  0/32  lines(allowed) 0.993-0.996  lines(payable) 0.993-0.996  bills 0.986-0.992  total allowed +0.0015 to +0.0030  total payable +0.0017 to +0.0037
    any_acceptance                   pass  0/32  lines(allowed) 0.994-0.997  lines(payable) 0.994-0.997  bills 0.988-0.993  total allowed +0.0022 to +0.0034  total payable +0.0022 to +0.0042
    no_preinjury_check               pass  0/32  lines(allowed) 0.989-0.995  lines(payable) 0.990-0.995  bills 0.988-0.993  total allowed +0.0041 to +0.0084  total payable +0.0042 to +0.0087
    jurisdiction_schedule_always     pass  0/32  lines(allowed) 0.983-0.993  lines(payable) 0.984-0.994  bills 0.982-0.992  total allowed -0.0011 to +0.0001  total payable -0.0014 to +0.0002
    provider_state_schedule_always   pass  0/32  lines(allowed) 0.956-0.972  lines(payable) 0.959-0.974  bills 0.954-0.971  total allowed -0.0022 to +0.0012  total payable -0.0026 to +0.0021
    billing_office_state             pass  0/32  lines(allowed) 0.958-0.995  lines(payable) 0.960-0.995  bills 0.953-0.993  total allowed -0.0015 to +0.0064  total payable -0.0020 to +0.0088
    no_payment_netting               pass  0/32  lines(allowed) 1.000-1.000  lines(payable) 0.696-0.729  bills 0.653-0.684  total allowed -0.0000 to +0.0000  total payable +0.3955 to +0.5019
    netting_same_line_only           pass  0/32  lines(allowed) 1.000-1.000  lines(payable) 0.964-0.974  bills 0.958-0.965  total allowed -0.0000 to +0.0000  total payable +0.0334 to +0.0592
    netting_includes_voided          pass  0/32  lines(allowed) 1.000-1.000  lines(payable) 0.990-0.994  bills 0.987-0.991  total allowed -0.0000 to +0.0000  total payable -0.0180 to -0.0056
    ignore_reversals                 pass  0/32  lines(allowed) 1.000-1.000  lines(payable) 0.979-0.984  bills 0.949-0.962  total allowed -0.0000 to +0.0000  total payable -0.0343 to -0.0200
    facility_no_packaging            pass  0/32  lines(allowed) 0.956-0.965  lines(payable) 0.958-0.966  bills 0.953-0.962  total allowed +0.1265 to +0.1479  total payable +0.1378 to +0.1668
    facility_no_multiple_procedure   pass  0/32  lines(allowed) 0.966-0.973  lines(payable) 0.966-0.973  bills 0.955-0.964  total allowed +0.0638 to +0.0793  total payable +0.0905 to +0.1141
    assistant_flat_20                pass  0/32  lines(allowed) 0.993-0.996  lines(payable) 0.993-0.996  bills 0.982-0.989  total allowed +0.0018 to +0.0028  total payable +0.0021 to +0.0034
    bilateral_200                    pass  0/32  lines(allowed) 0.992-0.995  lines(payable) 0.992-0.995  bills 0.980-0.988  total allowed +0.0023 to +0.0047  total payable +0.0030 to +0.0065
    pair_cf_received_no_reversals    pass  0/32  lines(allowed) 0.837-0.858  lines(payable) 0.833-0.855  bills 0.792-0.816  total allowed +0.0090 to +0.0115  total payable -0.0207 to -0.0079
    pair_mpr51_bundle_bill           pass  0/32  lines(allowed) 0.960-0.969  lines(payable) 0.962-0.970  bills 0.938-0.950  total allowed +0.0010 to +0.0072  total payable +0.0042 to +0.0132
