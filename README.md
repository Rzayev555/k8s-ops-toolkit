<div align="center">

# ☸️ k8s-ops-toolkit

**Small, sharp scripts for day-2 Kubernetes operations on self-hosted (kubeadm) clusters.**

[![ci](https://github.com/Rzayev555/k8s-ops-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Rzayev555/k8s-ops-toolkit/actions/workflows/ci.yml)
![Kubernetes](https://img.shields.io/badge/kubernetes-1.27+-326ce5?logo=kubernetes&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

| script | problem it solves |
|---|---|
| [`node-pressure.sh`](scripts/node-pressure.sh) | *"Why is one worker at 97% RAM while another is idle?"* Compares what the scheduler believes (requests) with what is really used, per node. |
| [`requests-from-usage.py`](scripts/requests-from-usage.py) | Sets memory requests from observed usage (×1.2, rounded), dry run by default, backup before patching. **Never touches limits.** |
| [`k8s-logreader.sh`](scripts/k8s-logreader.sh) | Gives a colleague or vendor read-only access to pods + logs of one namespace with a token that **expires by itself**. No exec, no secrets. |

## node-pressure.sh

Illustrative output:
```console
$ ./node-pressure.sh
NODE                     ALLOC_Mi        REQUESTED             USED   PODS
worker1                     11520      512 (  4%)    11198 ( 97%)     41
worker2                     11520        0 (  0%)      812 (  7%)      3
worker3                     11520      384 (  3%)     6610 ( 57%)     22
```
Usage is far above requests, so the scheduler is flying blind. That is what you get when a cluster
reboots and the first node back up takes every pod.

## requests-from-usage.py

```console
$ ./requests-from-usage.py -n app-dev
namespace          deployment                       container             used  req now  req new
app-dev            billing-api                      app                   742M       0M     896M
app-dev            notification-worker              app                   201M       0M     256M
...
53 containers, requests change by +18240 Mi in total
dry run - add --apply to patch
```

On a real 3-worker cluster, after `--apply` and a rolling restart, the busiest worker went from
**97% RAM to 57%**, and the three nodes settled at **57 / 67 / 66%**.

Why no limits? A memory limit on a JVM that doesn't set `-XX:MaxRAMPercentage` turns a slow
memory leak into an OOMKill loop. Add limits only together with the runtime flags.

## k8s-logreader.sh

```bash
sudo ./k8s-logreader.sh alice payments 8h      # alice can now: kubectl logs -f deploy/api
sudo ./k8s-logreader.sh --remove alice payments
```
It verifies itself at the end: `can-i get secrets → no`, `can-i create pods/exec → no`.

## Requirements

`kubectl` with cluster-admin (for the first and the last script), `metrics-server` for usage, Python 3.8+.

## License

MIT
