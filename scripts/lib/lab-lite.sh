#!/bin/bash
# Lightweight lab helpers (no Kubeshark). Used by new-*.sh scripts.
# shellcheck disable=SC2034

LAB_NODEPORT_HOST="${LAB_NODEPORT_HOST:-192.168.100.81}"
LAB_NODEPORT="${LAB_NODEPORT:-30198}"
LAB_NAMESPACE="${LAB_NAMESPACE:-lb-podinfo}"
KUBE_PROXY_CONFIG="/var/snap/microk8s/current/args/kube-proxy"
LAB_WAIT_NODES_SECONDS="${LAB_WAIT_NODES_SECONDS:-600}"
LAB_WAIT_PODINFO_TIMEOUT="${LAB_WAIT_PODINFO_TIMEOUT:-600s}"

lab_log()  { echo "[lab] $*"; }
lab_ok()   { echo "[lab] OK: $*"; }
lab_warn() { echo "[lab] WARN: $*" >&2; }
lab_err()  { echo "[lab] ERROR: $*" >&2; }

lab_kubectl() {
  microk8s kubectl "$@"
}

lab_wait_microk8s_ready() {
  lab_log "Waiting for MicroK8s to be ready..."
  microk8s status --wait-ready
  lab_ok "MicroK8s is ready"
}

lab_wait_nodes_ready() {
  lab_log "Waiting for all nodes to be Ready (up to ${LAB_WAIT_NODES_SECONDS}s)..."
  local deadline=$((SECONDS + LAB_WAIT_NODES_SECONDS))
  while (( SECONDS < deadline )); do
    local not_ready
    not_ready="$(lab_kubectl get nodes --no-headers 2>/dev/null | grep -v ' Ready ' | wc -l || true)"
    if [[ "${not_ready// /}" == "0" ]]; then
      lab_kubectl get nodes -o wide
      lab_ok "All nodes are Ready"
      return 0
    fi
    sleep 5
  done
  lab_warn "Nodes not all Ready within ${LAB_WAIT_NODES_SECONDS}s — continuing anyway"
  lab_kubectl get nodes -o wide || true
  return 0
}

lab_wait_lb_podinfo_ready() {
  lab_log "Waiting for Podinfo pods in namespace ${LAB_NAMESPACE}..."
  if ! lab_kubectl get namespace "${LAB_NAMESPACE}" &>/dev/null; then
    lab_warn "Namespace ${LAB_NAMESPACE} not found — skip Podinfo wait"
    return 0
  fi
  if ! lab_kubectl wait --namespace="${LAB_NAMESPACE}" \
    --for=condition=ready pod --all --timeout="${LAB_WAIT_PODINFO_TIMEOUT}"; then
    lab_warn "Podinfo wait timed out (${LAB_WAIT_PODINFO_TIMEOUT}) — continuing anyway"
  fi
  lab_kubectl get pods -n "${LAB_NAMESPACE}" -o wide
  local ready count
  ready="$(lab_kubectl get pods -n "${LAB_NAMESPACE}" --no-headers 2>/dev/null | grep -c ' Running ' || true)"
  count="$(lab_kubectl get pods -n "${LAB_NAMESPACE}" --no-headers 2>/dev/null | wc -l || true)"
  if [[ "${ready}" -lt 1 ]]; then
    lab_warn "No Running Podinfo pods — check: microk8s kubectl -n ${LAB_NAMESPACE} get pods"
    return 0
  fi
  lab_ok "Podinfo ready (${ready}/${count} pods Running)"
  return 0
}

lab_curl_nodeport_smoke() {
  lab_log "Smoke test: GET http://${LAB_NODEPORT_HOST}:${LAB_NODEPORT}/"
  local code
  code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://${LAB_NODEPORT_HOST}:${LAB_NODEPORT}/" || echo "000")"
  if [[ "${code}" == "200" ]]; then
    lab_ok "NodePort responds HTTP 200"
    return 0
  fi
  lab_warn "NodePort returned HTTP ${code} (cluster may still be starting)"
  return 0
}

lab_show_kube_proxy_config() {
  lab_log "kube-proxy args:"
  grep -E 'proxy-mode|ipvs-scheduler' "${KUBE_PROXY_CONFIG}" 2>/dev/null || lab_warn "Cannot read ${KUBE_PROXY_CONFIG}"
}

lab_reload_kube_proxy() {
  lab_log "Reloading kube-proxy via kubelite..."
  if ! sudo systemctl restart snap.microk8s.daemon-kubelite; then
    lab_err "systemctl restart snap.microk8s.daemon-kubelite failed"
    return 1
  fi
  sleep 25
  lab_wait_microk8s_ready
  lab_ok "kubelite restarted"
  return 0
}

lab_full_microk8s_restart() {
  lab_log "Full MicroK8s restart (stop → start)..."
  microk8s stop
  sleep 5
  microk8s start
  lab_wait_microk8s_ready
  lab_wait_nodes_ready
  lab_wait_lb_podinfo_ready
}

lab_apply_kube_proxy_change() {
  local expect_mode="${1:-}"
  local expect_scheduler="${2:-}"

  if lab_reload_kube_proxy; then
    if [[ -n "${expect_mode}" ]] && ! grep -q -- "--proxy-mode=${expect_mode}" "${KUBE_PROXY_CONFIG}" 2>/dev/null; then
      lab_warn "proxy-mode not ${expect_mode} in config file"
    fi
    if [[ -n "${expect_scheduler}" ]] && ! grep -q -- "--ipvs-scheduler=${expect_scheduler}" "${KUBE_PROXY_CONFIG}" 2>/dev/null; then
      lab_warn "scheduler not ${expect_scheduler} — falling back to full MicroK8s restart"
      lab_full_microk8s_restart
    else
      lab_ok "kube-proxy config applied (kubelite reload)"
      lab_show_kube_proxy_config
      return 0
    fi
  else
    lab_warn "kubelite reload failed — falling back to full MicroK8s restart"
    lab_full_microk8s_restart
  fi

  lab_show_kube_proxy_config
}

lab_post_scheduler_change() {
  lab_wait_lb_podinfo_ready
  lab_curl_nodeport_smoke
  lab_log "Done. Run load test, then check Grafana."
}
