#!/bin/bash
# Podinfo LB metrics for a single time window (avoid mixing runs in [15m]).
#
# Usage:
#   ./prometheus-podinfo-snapshot.sh           # last 5 minutes
#   ./prometheus-podinfo-snapshot.sh 3m        # last 3 minutes (one client run)
#
set -uo pipefail

PROM="${PROM_URL:-http://192.168.100.81:30109}"
WINDOW="${1:-5m}"

query() {
  curl -s "${PROM}/api/v1/query" --data-urlencode "query=$1" | python3 -m json.tool
}

echo "=== Podinfo per pod (window=${WINDOW}) ==="
echo ""
echo "--- Request count (figure B) ---"
query "sum by(pod)(increase(http_request_duration_seconds_count{namespace=\"lb-podinfo\"}[${WINDOW}]))"

echo ""
echo "--- Processing time sum in seconds (figure C) ---"
query "sum by(pod)(increase(http_request_duration_seconds_sum{namespace=\"lb-podinfo\"}[${WINDOW}]))"

echo ""
echo "Set Grafana time picker to the same window as your client run."
echo "If counts are ~equal here but client showed spread, [15m] included other traffic."
