# Performance Analysis of Kubernetes Load Balancing Algorithms under Asymmetric Traffic and Delay

This repository contains the implementation and results of an experimental study
on Kubernetes Layer-4 load balancing behavior under deterministic traffic and
controlled backend delay.

The project compares the default Kubernetes `kube-proxy` Round Robin behavior
against several Linux IPVS schedulers, using the same backend service, the same
traffic generator, and the same measurement pipeline for every run. The goal is
to isolate the load balancing policy as the main variable and observe how each
algorithm behaves when backend traffic is asymmetric and one pod can be made
artificially slower.

## Algorithms Compared

The experiment evaluates five configurations:

- **RR**: Round Robin baseline through `kube-proxy` in `iptables` mode.
- **LC**: Least Connections through `kube-proxy` in `ipvs` mode.
- **WRR**: Weighted Round Robin through IPVS. In this project no custom backend
weights are configured, so the scheduler is effectively tested with equal
weights.
- **SED**: Shortest Expected Delay through IPVS.
- **NQ**: Never Queue through IPVS.



## Experimental Setup

The platform is built around a three-node MicroK8s cluster running inside
VirtualBox virtual machines. The backend service is
[Podinfo](https://github.com/stefanprodan/podinfo), deployed with three replicas
in the `lb-podinfo` namespace and exposed through a fixed NodePort.

Main properties of the setup:

- 3 Kubernetes nodes on the `192.168.100.0/24` network.
- 3 Podinfo replicas, placed one per node using pod anti-affinity.
- Podinfo exposed on NodePort `30198`.
- Prometheus exposed on NodePort `30109`.
- Metrics scraped through a `ServiceMonitor` at a 15-second interval.
- A deterministic Python traffic generator based on `aiohttp`.
- Exported results for both normal and delayed-backend scenarios.

The default client target is:

```bash
http://192.168.100.81:30198
```

The default Prometheus endpoint is:

```bash
http://192.168.100.81:30109
```



## Workload

The official workload is implemented in `client/client.py` as the
`traffic_logic` scenario. It builds the full request plan before sending traffic,
which makes each run reproducible.

The workload mixes:

- light `GET /` requests;
- heavier `POST /store` requests with payloads from 2 KiB to 32 KiB.

Default workload parameters:

- 15,000 cycles;
- 23 requests per cycle;
- 345,000 planned requests in total;
- 0.005 seconds between planned requests;
- approximately 200 requests per second;
- concurrency limit of 300;
- request timeout of 180 seconds.

The client opens a new TCP connection per request by default so that load
balancing decisions remain visible at request level instead of being hidden by
connection reuse.

## Repository Structure

```text
.
|-- client/                 # Deterministic Python load generator
|-- scripts/                # Cluster setup, kube-proxy, IPVS, and verification scripts
|-- k8s/                    # Kubernetes and Grafana configuration files
|-- no_delay/               # Exported no-delay results and generated charts
`-- delay_results/          # Exported delay-scenario results and generated charts
```



## Requirements

The scripts are designed for a Linux/MicroK8s environment. A typical setup
requires:

- MicroK8s with `kubectl` and `helm3`;
- a three-node Kubernetes cluster;
- Python 3.10+;
- `aiohttp` and `requests`;
- Prometheus Operator / kube-prometheus-stack;
- Linux IPVS kernel modules;
- `ipvsadm`, `ipset`, and the standard Linux networking tools used by MicroK8s.

Install the Python client dependencies with:

```bash
cd client
python3 -m pip install -r requirements.txt
```

Before running the cluster deployment, make sure the Podinfo Helm chart required
by `scripts/install-podinfo.sh` is available locally. If it is missing, the
script prints the expected chart location and the setup step that must be run.

## Running the Experiment

Deploy Podinfo with three replicas:

```bash
./scripts/install-podinfo.sh k8s/helm-values-3nodes.yaml
```

Enable IPVS support:

```bash
./scripts/new-enable-ipvs.sh
```

Select the scheduler to test:

```bash
./scripts/new-set-round-robin.sh        # RR baseline, iptables mode
./scripts/set-ipvs-all-nodes.sh lc      # Least Connections
./scripts/set-ipvs-all-nodes.sh wrr     # Weighted Round Robin
./scripts/set-ipvs-all-nodes.sh sed     # Shortest Expected Delay
./scripts/set-ipvs-all-nodes.sh nq      # Never Queue
```

Verify the active configuration on all nodes:

```bash
./scripts/verify-ipvs-all-nodes.sh
```

Run the deterministic workload from the client directory:

```bash
cd client
python3 client.py --algorithm rr
python3 client.py --algorithm lc
python3 client.py --algorithm wrr
python3 client.py --algorithm sed
python3 client.py --algorithm nq
```

The `--algorithm` argument labels the run only. It does not change the cluster
configuration; the scheduler must be selected separately through the shell
scripts above.

## Delay Scenario Results

The repository includes exported data and charts for a delayed-backend scenario
under `delay_results/`. In that recorded experiment, one Podinfo replica was
made slower so the schedulers could be compared under asymmetric backend
conditions.

## Output Files

Each client run writes a self-describing set of artifacts:

- `<run_id>_plan.csv`: the full planned workload;
- `<run_id>_requests.csv`: one row per completed request;
- `<run_id>_summary.json`: aggregate latency, throughput, error, and Prometheus
delta metrics.

The repository also includes exported Grafana/Prometheus data and generated
charts for both scenarios:

- `no_delay/`: results without artificial delay;
- `delay_results/`: results with deterministic delay applied to one pod.



## Results Summary

The main observations from the recorded experiment are:

- In the no-delay scenario, the connection-aware IPVS schedulers produced lower
latency than the stateless RR and equal-weight WRR configurations.
- LC achieved the best no-delay latency across average, P95, and P99 metrics.
- Under injected delay, SED and NQ shifted load away from the impaired pod and
achieved the best or near-best latency results.
- RR and WRR remained largely indifferent to the slower backend because they do
not react to active connection state in this setup.
- Tail latency was more sensitive to the scheduler choice than average latency.

These observations are specific to this three-node virtualized environment, this
workload, and this delay model. They should not be interpreted as universal
performance guarantees for all Kubernetes deployments.

## Limitations

This experiment was intentionally controlled and reproducible, but it has a
limited scope:

- the cluster has only three nodes;
- the environment is virtualized;
- the workload is deterministic and does not represent every production traffic
pattern;
- only one pod is impaired in the delay scenario;
- results depend on Prometheus/Grafana export resolution and VM scheduling noise.

The repository is therefore best read as a reproducible academic experiment and
not as a general benchmark of all Kubernetes load balancing behavior.