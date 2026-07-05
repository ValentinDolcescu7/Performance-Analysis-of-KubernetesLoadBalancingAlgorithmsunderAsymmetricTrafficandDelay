#!/bin/bash
# Enable IPVS kernel modules and kube-proxy mode — no Kubeshark.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/lab-lite.sh
source "${SCRIPT_DIR}/lib/lab-lite.sh"

echo "Enabling IPVS kernel modules..."

sudo modprobe ip_vs
sudo modprobe ip_vs_wrr
sudo modprobe ip_vs_lc
sudo modprobe ip_vs_sed
sudo modprobe ip_vs_nq

echo "Configuring kube-proxy..."

if grep -q -- '--proxy-mode' "${KUBE_PROXY_CONFIG}"; then
  sudo sed -i 's|--proxy-mode=.*|--proxy-mode=ipvs|' "${KUBE_PROXY_CONFIG}"
else
  echo "--proxy-mode=ipvs" | sudo tee -a "${KUBE_PROXY_CONFIG}" > /dev/null
fi

# First-time IPVS usually needs a full cluster cycle on MicroK8s.
lab_full_microk8s_restart
lab_show_kube_proxy_config

echo "IPVS mode enabled"
