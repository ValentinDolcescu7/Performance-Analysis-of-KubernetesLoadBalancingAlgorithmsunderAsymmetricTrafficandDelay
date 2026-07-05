#!/bin/bash
microk8s kubectl port-forward -n observability svc/kube-prom-stack-grafana 3000:80
