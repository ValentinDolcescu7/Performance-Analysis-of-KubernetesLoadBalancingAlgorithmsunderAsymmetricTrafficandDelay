#!/usr/bin/env bash
# Install podinfo from the vendored Helm chart (no SSH; chart is local after git clone).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="${ROOT}/vendor/podinfo/charts/podinfo"
# Opțional: primul argument = fișier values (cale relativă la ROOT sau absolută). Implicit 2 noduri.
if [[ -n "${1:-}" ]]; then
  if [[ "$1" == /* ]]; then
    VALUES="$1"
  else
    VALUES="${ROOT}/${1#./}"
  fi
else
  VALUES="${ROOT}/k8s/helm-values-2nodes.yaml"
fi
NS=lb-podinfo

if [[ ! -d "$CHART" ]]; then
  echo "Missing Helm chart at $CHART — run: git clone https://github.com/stefanprodan/podinfo.git vendor/podinfo"
  exit 1
fi

echo "[1/2] Helm upgrade --install podinfo (namespace=$NS) values=$VALUES"
microk8s helm3 upgrade --install podinfo "$CHART" \
  --namespace "$NS" \
  --create-namespace \
  --wait --timeout 15m \
  -f "$VALUES"

echo "[2/2] Status"
microk8s kubectl -n "$NS" get pods,svc

NODE_IP="${NODE_IP:-}"
if [[ -z "$NODE_IP" ]]; then
  NODE_IP="$(hostname -I | awk '{print $1}')"
fi
echo ""
echo "HTTP NodePort (set LB_PODINFO_URL for the client):"
echo "  http://${NODE_IP}:30198"
