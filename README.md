# Workers' compensation medical bill review task

A single Harbor-format task, `tasks/wc-bill-review`, built as a portfolio sample of a hard, realistic claims operations benchmark task. An agent works in a container with a synthetic set of provider bills, claim files, state fee schedules, network agreements and payment history, and must produce the correct allowed and still-payable amount for every bill line.

## Layout

```
tasks/wc-bill-review/
  instruction.md            what the agent is asked to do
  task.toml                 metadata, timeouts and resources
  README.md                 data summary and how to reproduce it
  environment/              agent image (Dockerfile + /app/data)
  solution/                 reference solution (solve.sh -> solve.py)
  tests/                    verifier image, test.sh, test_outputs.py, truth.json
  authoring/                data generator, static documents, calibration methods
checks/                     deterministic static checks
docs/                       task template and category taxonomy
```

## Checks

From the repository root:

```bash
bash checks/static-report.sh tasks/wc-bill-review
```

## Running the task locally without Docker

```bash
cd tasks/wc-bill-review
python3 authoring/generate_data.py                        # rewrites environment/data and tests/truth.json (seed 311)
python3 solution/solve.py environment/data /tmp/out/bill_review.csv
```

The verifier reads `/app/output/bill_review.csv` and `/tests/truth.json`; to run it outside the containers, copy those two files to those paths (or edit the two path constants at the top of `tests/test_outputs.py`) and run `pytest tests/test_outputs.py`.

With Docker and the [Harbor](https://harborframework.com) CLI installed, `harbor run -p tasks/wc-bill-review -a oracle` builds both images and runs the reference solution through the verifier.

All data is synthetic. State names are used for realism; the regulation excerpts, fee schedules, codes, networks and providers are invented.
