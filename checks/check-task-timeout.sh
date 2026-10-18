#!/bin/bash

# Fails unless task.toml gives the agent exactly eight hours, the standard
# budget for every task in this format. The verifier
# remains optional, but keeps its existing five-hour ceiling when configured.

set -e

EXPECTED_AGENT_TIMEOUT_SEC=28800
MAX_VERIFIER_TIMEOUT_SEC=18000

# Arguments: task directories (e.g., tasks/my-task) or no args to check all
if [ $# -eq 0 ]; then
    FILES_TO_CHECK=$(find tasks -type f -name "task.toml")
else
    FILES_TO_CHECK=""
    for task_dir in "$@"; do
        if [ -d "$task_dir" ] && [ -f "$task_dir/task.toml" ]; then
            FILES_TO_CHECK="$FILES_TO_CHECK $task_dir/task.toml"
        fi
    done
fi

if [ -z "$FILES_TO_CHECK" ]; then
    echo "No task.toml files to check"
    exit 0
fi

FAILED=0
for file in $FILES_TO_CHECK; do
    if [ ! -f "$file" ]; then
        echo "File $file does not exist, skipping"
        continue
    fi

    echo "Checking $file..."

    RESULT=$(python3 - "$file" "$EXPECTED_AGENT_TIMEOUT_SEC" "$MAX_VERIFIER_TIMEOUT_SEC" <<'PYEOF'
import sys

path = sys.argv[1]
expected_sec = int(sys.argv[2])
max_verifier_sec = int(sys.argv[3])

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

violations = []
try:
    with open(path, "rb") as f:
        data = tomllib.load(f)
except (OSError, tomllib.TOMLDecodeError) as exc:
    print(f"could not read task.toml: {exc}")
    sys.exit(1)

value = data.get("agent", {}).get("timeout_sec")
if value is None:
    violations.append(
        f"agent.timeout_sec is required and must equal {expected_sec} (8h)"
    )
elif isinstance(value, bool) or not isinstance(value, (int, float)):
    violations.append(f"agent.timeout_sec must be numeric, found {value!r}")
elif value != expected_sec:
    violations.append(
        f"agent.timeout_sec={value:g}; expected exactly {expected_sec} seconds (8h)"
    )

verifier_value = data.get("verifier", {}).get("timeout_sec")
if verifier_value is not None:
    if isinstance(verifier_value, bool) or not isinstance(
        verifier_value, (int, float)
    ):
        violations.append(
            f"verifier.timeout_sec must be numeric, found {verifier_value!r}"
        )
    elif verifier_value > max_verifier_sec:
        violations.append(
            "verifier.timeout_sec="
            f"{verifier_value:g} exceeds {max_verifier_sec} seconds (5h)"
        )

if violations:
    for v in violations:
        print(v)
    sys.exit(1)
PYEOF
    ) || {
        echo "$RESULT" | while IFS= read -r line; do
            [ -n "$line" ] && echo "FAIL $file: $line"
        done
        FAILED=1
        continue
    }
done

if [ $FAILED -eq 1 ]; then
    echo ""
    echo "Some task.toml files do not set agent.timeout_sec to"
    echo "${EXPECTED_AGENT_TIMEOUT_SEC} seconds (8h), as required,"
    echo "or set verifier.timeout_sec above ${MAX_VERIFIER_TIMEOUT_SEC} seconds (5h)."
    exit 1
fi

echo "All task.toml files use the required 8h agent timeout and valid verifier timeout"
