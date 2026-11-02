#!/bin/sh
# Apply examples/deploy/kubernetes to a kind cluster with Ergo in it, changed only to
# point at Ergo and to use IMAGE, then check that the pod gets ready, which its
# readiness probe on /readyz says only once the bot is in its channel, and that a
# restart replaces it.
#
#   tests/deploy/kubernetes.sh pinhook:test
set -eu
IMAGE=${1:?usage: kubernetes.sh IMAGE}
CLUSTER=pinhook-examples
kind create cluster --name $CLUSTER --wait 120s
trap 'kind delete cluster --name $CLUSTER' EXIT
kind load docker-image "$IMAGE" --name $CLUSTER
kubectl apply -f tests/deploy/ergo.yaml
kubectl rollout status deployment/ergo --timeout=180s

kubectl create secret generic gamebot-secrets --from-literal=sasl_password=k8sbot-password
sed -e "s|ghcr.io/archangelic/pinhook:2|$IMAGE|" -e "s/'irc.libera.chat'/'ergo'/" \
    -e 's/port: 6697/port: 6667/' -e 's/ssl_required: true/ssl_required: false/' \
    examples/deploy/kubernetes/pinhook.yaml | kubectl apply -f -

show() {
    kubectl describe pods -l app=gamebot | tail -30
    kubectl logs deployment/gamebot --tail=30 || true
}
kubectl rollout status deployment/gamebot --timeout=180s || { show; exit 1; }
kubectl logs deployment/gamebot | grep -q 'joining channel #gamebot-test' \
    || { show; echo "the bot didn't log to stdout"; exit 1; }

# Recreate: the old pod stops before the new one starts, and the new one gets ready
kubectl rollout restart deployment/gamebot
kubectl rollout status deployment/gamebot --timeout=180s || { show; exit 1; }
echo "the kubernetes example ran, got ready and restarted"
