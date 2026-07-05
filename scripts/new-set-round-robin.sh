#!/bin/bash
# iptables round robin — no Kubeshark.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/lab-lite.sh
source "${SCRIPT_DIR}/lib/lab-lite.sh"

echo "Switching to iptables (Round Robin)..."

sudo sed -i 's|--proxy-mode=.*|--proxy-mode=iptables|' "${KUBE_PROXY_CONFIG}"
sudo sed -i '/--ipvs-scheduler/d' "${KUBE_PROXY_CONFIG}"

lab_apply_kube_proxy_change "iptables" ""
lab_post_scheduler_change

echo "Round Robin (iptables) active"
