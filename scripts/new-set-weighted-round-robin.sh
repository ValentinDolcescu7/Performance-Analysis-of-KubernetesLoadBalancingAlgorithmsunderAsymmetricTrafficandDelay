#!/bin/bash
# IPVS weighted round robin (wrr) — no Kubeshark.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/lab-lite.sh
source "${SCRIPT_DIR}/lib/lab-lite.sh"

echo "Setting Weighted Round Robin (IPVS wrr)..."

sudo sed -i 's|--proxy-mode=.*|--proxy-mode=ipvs|' "${KUBE_PROXY_CONFIG}"
sudo sed -i '/--ipvs-scheduler/d' "${KUBE_PROXY_CONFIG}"
echo "--ipvs-scheduler=wrr" | sudo tee -a "${KUBE_PROXY_CONFIG}" > /dev/null

lab_apply_kube_proxy_change "ipvs" "wrr"
lab_post_scheduler_change

echo "Weighted Round Robin (wrr) active"
