#!/bin/bash
# Stop MicroK8s cleanly (no Kubeshark hooks).
#
# After stop, bring the lab back with:
#   ./scripts/new-cluster-start.sh
#
set -euo pipefail

echo "[lab] Stopping MicroK8s..."
microk8s stop
echo "[lab] OK: MicroK8s stopped"
echo "[lab] To start again: ./scripts/new-cluster-start.sh"
