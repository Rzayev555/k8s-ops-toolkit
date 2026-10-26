#!/bin/bash
# k8s-logreader.sh - give a Linux user READ-ONLY access to pods and logs of one namespace.
#
#   sudo ./k8s-logreader.sh <linux-user> <namespace> [duration]     # default 24h
#   sudo ./k8s-logreader.sh --remove <linux-user> <namespace>
#
# Creates ServiceAccount + Role (pods, pods/log: get/list/watch) + RoleBinding and writes a
# kubeconfig with a short-lived token to ~user/.kube/config. No exec, no secrets, no writes.
# The token expires by itself; run again to renew.
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-/etc/kubernetes/admin.conf}

REMOVE=0
[ "${1:-}" = "--remove" ] && { REMOVE=1; shift; }
U=${1:?linux user}
NS=${2:?namespace}
DUR=${3:-24h}
SA="${U}-logreader"
H=$(getent passwd "$U" | cut -d: -f6)
[ -n "$H" ] || { echo "no such user: $U"; exit 1; }

if [ $REMOVE -eq 1 ]; then
    kubectl -n "$NS" delete rolebinding "$SA" role "$SA" serviceaccount "$SA" --ignore-not-found
    rm -f "$H/.kube/config"
    echo "removed"; exit 0
fi

kubectl -n "$NS" get serviceaccount "$SA" >/dev/null 2>&1 || kubectl -n "$NS" create serviceaccount "$SA"
kubectl -n "$NS" get role "$SA" >/dev/null 2>&1 || kubectl -n "$NS" create role "$SA" --verb=get,list,watch --resource=pods,pods/log
kubectl -n "$NS" get rolebinding "$SA" >/dev/null 2>&1 || kubectl -n "$NS" create rolebinding "$SA" --role="$SA" --serviceaccount="$NS:$SA"

TOKEN=$(kubectl -n "$NS" create token "$SA" --duration="$DUR")
SERVER=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

install -d -m 700 -o "$U" -g "$(id -gn "$U")" "$H/.kube"
umask 077
cat > "$H/.kube/config" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: k8s
  cluster:
    server: $SERVER
    certificate-authority-data: $CA
users:
- name: $SA
  user:
    token: $TOKEN
contexts:
- name: $SA
  context: {cluster: k8s, user: $SA, namespace: $NS}
current-context: $SA
EOF
chown "$U:$(id -gn "$U")" "$H/.kube/config"

echo "== checks as $U"
su - "$U" -c "kubectl get pods 2>&1 | head -3"
su - "$U" -c "kubectl auth can-i get secrets"      | sed 's/^/  read secrets? /'
su - "$U" -c "kubectl auth can-i create pods/exec" | sed 's/^/  exec?         /'
echo "OK: $U can read pods/logs in '$NS' for $DUR"
