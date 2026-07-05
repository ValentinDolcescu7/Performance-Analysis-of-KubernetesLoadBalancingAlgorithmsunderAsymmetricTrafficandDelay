#!/bin/bash
# Start MicroK8s (optional), wait for workload — no Kubeshark.
#
# Usage:
#   ./scripts/new-cluster-start.sh              # microk8s start + wait
#   ./scripts/new-cluster-start.sh --no-microk8s   # cluster already running
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/lab-lite.sh
source "${SCRIPT_DIR}/lib/lab-lite.sh"

DO_MICROK8S_START=1

for arg in "$@"; do
  case "${arg}" in
    --no-microk8s) DO_MICROK8S_START=0 ;;
    -h|--help)
      echo "Usage: $0 [--no-microk8s]"
      exit 0
      ;;
    *)
      lab_err "Unknown argument: ${arg}"
      exit 1
      ;;
  esac
done

lab_log "=== new-cluster-start.sh ==="

if [[ "${DO_MICROK8S_START}" -eq 1 ]]; then
  lab_log "Starting MicroK8s..."
  microk8s start
else
  lab_log "Skipping microk8s start (--no-microk8s)"
fi

lab_wait_microk8s_ready
lab_wait_nodes_ready
lab_wait_lb_podinfo_ready
lab_curl_nodeport_smoke
lab_show_kube_proxy_config

lab_ok "Cluster start complete"
lab_log "Next: cd ~/lb-podinfo-experiment/client && source .venv/bin/activate && python client.py"
