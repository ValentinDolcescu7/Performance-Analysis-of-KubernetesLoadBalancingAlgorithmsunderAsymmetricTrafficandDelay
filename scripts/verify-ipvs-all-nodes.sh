#!/bin/bash
# Verify MicroK8s IPVS scheduler on all cluster nodes (read-only).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${SCRIPT_DIR}/k8s/ipvs-scheduler-verify.yaml"
NAMESPACE="lb-podinfo"
NODEPORT="${1:-30198}"

echo "[verify-ipvs] NodePort check: ${NODEPORT}"
echo "[verify-ipvs] Local node (if you are on a cluster node):"
grep -E 'proxy-mode|ipvs-scheduler' /var/snap/microk8s/current/args/kube-proxy 2>/dev/null || \
  echo "  (cannot read local kube-proxy args from this host)"

microk8s kubectl -n "${NAMESPACE}" delete daemonset ipvs-scheduler-verify --ignore-not-found=true
sleep 2

TMP="$(mktemp)"
sed "s/value: \"30198\"/value: \"${NODEPORT}\"/" "${MANIFEST}" > "${TMP}"
microk8s kubectl apply -f "${TMP}"
rm -f "${TMP}"

echo "[verify-ipvs] Waiting for verify pods..."
microk8s kubectl -n "${NAMESPACE}" wait --for=condition=ready pod \
  -l app=ipvs-scheduler-verify --timeout=120s

echo
for pod in $(microk8s kubectl -n "${NAMESPACE}" get pods -l app=ipvs-scheduler-verify -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort); do
  node="$(microk8s kubectl -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.spec.nodeName}')"
  echo "==================== ${node} (${pod}) ===================="
  microk8s kubectl -n "${NAMESPACE}" logs "${pod}" 2>/dev/null | head -20
  echo
done

echo "[verify-ipvs] NodePort HTTP smoke:"
for ip in 192.168.100.81 192.168.100.82 192.168.100.83; do
  code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://${ip}:${NODEPORT}/" || echo "000")"
  echo "  http://${ip}:${NODEPORT}/ -> HTTP ${code}"
done

echo
echo "[verify-ipvs] Cleanup: microk8s kubectl -n ${NAMESPACE} delete daemonset ipvs-scheduler-verify"
