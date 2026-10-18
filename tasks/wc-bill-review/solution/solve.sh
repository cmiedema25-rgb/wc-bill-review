#!/bin/bash
set -euo pipefail

# Resolves each bill's history (replacements, voids, duplicates), checks compensability against the current
# body part determinations, prices every line under the governing state's fee schedule and rules for its date
# of service, applies network agreements and the lesser-of rule, and credits payments already issued.
# Writes /app/output/bill_review.csv.
python3 /solution/solve.py /app/data /app/output/bill_review.csv
