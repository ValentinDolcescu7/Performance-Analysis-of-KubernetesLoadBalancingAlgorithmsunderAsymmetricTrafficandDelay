#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Average latency ==="
python doverall_avg.py
python dlatency_avg.py
python dbar_chart_avg_latency.py

echo "=== P95 latency ==="
python doverall_95latency_avg.py
python dlatency_avg_95.py
python dbar_chart_latency_95.py

echo "=== P99 latency ==="
python doverall_99latency_avg.py
python dlatency_avg_99.py
python dbar_chart_latency_99.py

echo "=== Requests by pod ==="
python dprocessing_reqs_by_pod_barchart.py

echo "=== Processing time by pod ==="
python dprocessing_time_by_pod_barchart.py

echo
echo "Done. Toate graficele si CSV-urile au fost generate."
