#!/bin/bash
# node-pressure.sh - per node: allocatable memory, sum of memory requests, real usage, pod count.
# Shows at a glance whether the scheduler's view (requests) matches reality (usage).
#   ./node-pressure.sh
set -euo pipefail

to_mi() {  # 1234Ki / 512Mi / 2Gi -> Mi
    awk -v q="$1" 'BEGIN{
        n=q; sub(/[A-Za-z]+$/,"",n); u=q; sub(/^[0-9.]+/,"",u)
        f=(u=="Ki")?1/1024:(u=="Mi")?1:(u=="Gi")?1024:(u=="")?1/1048576:1
        printf "%d", n*f }'
}

declare -A ALLOC USED PODS REQ
while read -r node alloc; do ALLOC[$node]=$(to_mi "$alloc"); done < <(
    kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name} {.status.allocatable.memory}{"\n"}{end}')
while read -r node _cpu _cpup mem _memp; do USED[$node]=$(to_mi "$mem"); done < <(kubectl top nodes --no-headers)
while read -r node reqs; do
    [ -n "$node" ] || continue
    PODS[$node]=$(( ${PODS[$node]:-0} + 1 ))
    for r in ${reqs//,/ }; do
        [ "$r" = "<none>" ] && continue
        REQ[$node]=$(( ${REQ[$node]:-0} + $(to_mi "$r") ))
    done
done < <(kubectl get pods -A --field-selector=status.phase=Running \
          -o custom-columns='N:.spec.nodeName,R:.spec.containers[*].resources.requests.memory' --no-headers)

printf '%-22s %10s %16s %16s %6s\n' NODE ALLOC_Mi REQUESTED USED PODS
for n in $(printf '%s\n' "${!ALLOC[@]}" | sort); do
    a=${ALLOC[$n]}; r=${REQ[$n]:-0}; u=${USED[$n]:-0}
    printf '%-22s %10d %9d (%3d%%) %9d (%3d%%) %6d\n' "$n" "$a" "$r" $((r * 100 / a)) "$u" $((u * 100 / a)) "${PODS[$n]:-0}"
done
echo
echo "USED >> REQUESTED  -> pods have no/low requests; the scheduler is flying blind"
echo "REQUESTED > 90%    -> new pods will go Pending on this node"
