#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export MPLBACKEND=Agg

echo "Running all no-delay plotting scripts from: $(pwd)"
echo

PYTHON_CMD=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import pandas, numpy, matplotlib" >/dev/null 2>&1; then
        PYTHON_CMD="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo "Could not find a Python interpreter with pandas, numpy, and matplotlib installed."
    echo "Install the required packages with:"
    echo "  python3 -m pip install pandas numpy matplotlib"
    exit 1
fi

echo "Using: $PYTHON_CMD"
echo

run_script() {
    local script="$1"

    echo "============================================================"
    echo "Running $script"
    echo "============================================================"
    "$PYTHON_CMD" "$script"
    echo
}

run_script "overall_avg.py"
run_script "latency_avg.py"
run_script "bar_chart_avg_latency.py"

run_script "overall_95latency_avg.py"
run_script "latency_avg_95.py"
run_script "bar_chart_latency_95.py"

run_script "overall_99latency_avg.py"
run_script "latency_avg_99.py"
run_script "bar_chart_latency_99.py"

run_script "processing_reqs_by_pod_barchart.py"
run_script "processing_time_by_pod_barchart.py"

echo "Done. All scripts completed successfully."
