#!/usr/bin/env python3
"""Set memory requests from real usage so the scheduler stops stacking pods on one node.

Story: after all workers rebooted, the first node to come back got every pod. No pod had
resource requests, so the scheduler thought each node was empty, and one worker sat at 97% RAM
while another was idle. With requests based on real usage, the next rollout spread the pods
evenly (57/67/66%).

  requests-from-usage.py                       # dry run, all namespaces
  requests-from-usage.py -n app-dev -n app-test
  requests-from-usage.py --apply               # patch Deployments (backup written first)

Rule: request = observed usage x FACTOR, rounded up to STEP Mi, at least MIN Mi.
CPU request is set to a small floor only if missing. LIMITS ARE NOT TOUCHED on purpose:
a memory limit on a JVM without -XX:MaxRAMPercentage is an OOMKill waiting to happen.
"""
import argparse
import json
import math
import subprocess
import sys
import time

SKIP_NS = {"kube-system", "kube-public", "kube-node-lease"}


def kubectl(*args, stdin=None):
    r = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"kubectl {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def mi(q):
    """'123Mi' / '1Gi' / '512000Ki' -> MiB"""
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024, "K": 1000 / 1048576,
             "M": 1e6 / 1048576, "G": 1e9 / 1048576}
    for u in sorted(units, key=len, reverse=True):
        if q.endswith(u):
            return float(q[: -len(u)]) * units[u]
    return float(q) / 1048576


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--namespace", action="append", help="limit to namespace (repeatable)")
    ap.add_argument("--factor", type=float, default=1.2)
    ap.add_argument("--step", type=int, default=64, help="round up to this many Mi")
    ap.add_argument("--min", type=int, default=128, help="minimum request in Mi")
    ap.add_argument("--cpu", default="50m", help="cpu request to add where none exists")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    # current usage per container: "ns pod container cpu mem"
    usage = {}
    for line in kubectl("top", "pods", "-A", "--containers", "--no-headers").splitlines():
        ns, pod, cont, _cpu, mem = line.split()[:5]
        usage.setdefault((ns, pod), {})[cont] = mi(mem)

    pods = json.loads(kubectl("get", "pods", "-A", "-o", "json"))["items"]
    deps = json.loads(kubectl("get", "deployments", "-A", "-o", "json"))["items"]
    rs_owner = {}
    for rs in json.loads(kubectl("get", "replicasets", "-A", "-o", "json"))["items"]:
        for o in rs["metadata"].get("ownerReferences", []):
            if o["kind"] == "Deployment":
                rs_owner[(rs["metadata"]["namespace"], rs["metadata"]["name"])] = o["name"]

    # peak usage per (ns, deployment, container) across its pods
    peak = {}
    for p in pods:
        ns, name = p["metadata"]["namespace"], p["metadata"]["name"]
        for o in p["metadata"].get("ownerReferences", []):
            dep = rs_owner.get((ns, o["name"])) if o["kind"] == "ReplicaSet" else None
            if dep:
                for c, m in usage.get((ns, name), {}).items():
                    k = (ns, dep, c)
                    peak[k] = max(peak.get(k, 0), m)

    plan, backup = [], []
    for d in deps:
        ns, dep = d["metadata"]["namespace"], d["metadata"]["name"]
        if ns in SKIP_NS or (a.namespace and ns not in a.namespace):
            continue
        for c in d["spec"]["template"]["spec"]["containers"]:
            used = peak.get((ns, dep, c["name"]))
            if used is None:
                continue
            req = c.get("resources", {}).get("requests", {})
            want = max(a.min, math.ceil(used * a.factor / a.step) * a.step)
            have = mi(req["memory"]) if "memory" in req else 0
            if abs(have - want) < a.step:
                continue
            plan.append((ns, dep, c["name"], used, have, want, "cpu" not in req))
        backup.append(d)

    if not plan:
        print("nothing to change")
        return
    print(f"{'namespace':18} {'deployment':32} {'container':20} {'used':>7} {'req now':>8} {'req new':>8}")
    for ns, dep, c, used, have, want, _ in plan:
        print(f"{ns:18} {dep:32} {c:20} {used:6.0f}M {have:7.0f}M {want:7d}M")
    total = sum(w - h for *_, h, w, _ in plan)
    print(f"\n{len(plan)} containers, requests change by {total:+.0f} Mi in total")

    if not a.apply:
        print("dry run - add --apply to patch")
        return
    bk = f"deploy-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    json.dump({"items": backup}, open(bk, "w"))
    print(f"backup: {bk}")
    for ns, dep, c, _used, _have, want, add_cpu in plan:
        res = {"requests": {"memory": f"{want}Mi"}}
        if add_cpu:
            res["requests"]["cpu"] = a.cpu
        patch = {"spec": {"template": {"spec": {"containers": [{"name": c, "resources": res}]}}}}
        kubectl("-n", ns, "patch", "deployment", dep, "--type=strategic", "-p", json.dumps(patch))
        print(f"patched {ns}/{dep}/{c} -> {want}Mi")


if __name__ == "__main__":
    main()
