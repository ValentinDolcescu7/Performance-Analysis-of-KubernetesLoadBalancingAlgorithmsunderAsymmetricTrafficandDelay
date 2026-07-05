#!/bin/bash
# Set the same MicroK8s IPVS scheduler on all cluster nodes via a privileged DaemonSet.
# Usage: ./scripts/set-ipvs-all-nodes.sh [scheduler]
# Schedulers: rr | lc | wrr | sed | nq
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHED="${1:-lc}"
MANIFEST="${SCRIPT_DIR}/k8s/ipvs-scheduler-setup.yaml"
NAMESPACE="lb-podinfo"

case "${SCHED}" in
  rr|lc|wrr|sed|nq) ;;
  *)
    echo "Invalid scheduler: ${SCHED}"
    echo "Use one of: rr lc wrr sh sed nq"
    exit 1
    ;;
esac

if [[ ! -f "${MANIFEST}" ]]; then
  echo "Missing manifest: ${MANIFEST}"
  exit 1
fi

echo "[set-ipvs] Applying scheduler=${SCHED} on all nodes..."
microk8s kubectl -n "${NAMESPACE}" delete daemonset ipvs-scheduler-setup --ignore-not-found=true
sleep 3

TMP="$(mktemp)"
sed "s/value: \"lc\"/value: \"${SCHED}\"/" "${MANIFEST}" > "${TMP}"
microk8s kubectl apply -f "${TMP}"
rm -f "${TMP}"

echo "[set-ipvs] Waiting for setup pods..."
microk8s kubectl -n "${NAMESPACE}" wait --for=condition=ready pod \
  -l app=ipvs-scheduler-setup --timeout=300s || true

echo "[set-ipvs] Logs per node:"
for pod in $(microk8s kubectl -n "${NAMESPACE}" get pods -l app=ipvs-scheduler-setup -o name); do
  echo "---------- ${pod} ----------"
  microk8s kubectl -n "${NAMESPACE}" logs "${pod}" --tail=40 || true
done

echo "[set-ipvs] Cluster nodes:"
microk8s kubectl get nodes -o wide

echo "[set-ipvs] Podinfo:"
microk8s kubectl -n lb-podinfo get pods -o wide

for ip in 192.168.100.81 192.168.100.82 192.168.100.83; do
  code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://${ip}:30198/" || echo "000")"
  echo "[set-ipvs] NodePort ${ip}:30198 -> HTTP ${code}"
done

echo "[set-ipvs] Scheduler ${SCHED} applied. DaemonSet left running for log inspection."
echo "Remove when done: microk8s kubectl -n ${NAMESPACE} delete daemonset ipvs-scheduler-setup"
