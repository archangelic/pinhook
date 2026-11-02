#!/bin/sh
# Start examples/deploy/compose against the Ergo server from tests/integration/ergo.sh,
# changed only to point at it and to use IMAGE, and check that it gets ready and stops
# cleanly.
#
#   tests/deploy/compose.sh pinhook:test
set -eu
IMAGE=${1:?usage: compose.sh IMAGE}
WORK=$(mktemp -d)
PROJECT=pinhookcompose
cp examples/deploy/compose/* "$WORK"
cd "$WORK"
trap 'docker compose -p $PROJECT down -v >/dev/null 2>&1; cd /; rm -rf "$WORK"' EXIT

if [ "$(uname)" = Darwin ]; then
    SERVER=host.docker.internal HEALTH=http://127.0.0.1:18080
    printf 'services:\n  bot:\n    ports: ["18080:8080"]\n' > compose.override.yaml
else
    SERVER=127.0.0.1 HEALTH=http://127.0.0.1:8080
    printf 'services:\n  bot:\n    network_mode: host\n' > compose.override.yaml
fi
sed -e "s/'irc.libera.chat'/'$SERVER'/" -e 's/^port: 6697/port: 6667/' \
    -e 's/^ssl_required: true/ssl_required: false/' -e 's/gamebot/composebot/g' \
    -i.orig config.yaml
sed -e "s|ghcr.io/archangelic/pinhook:2|$IMAGE|" -i.orig compose.yaml
mkdir plugins recipes
# the bot's uid, 10001, writes recipes added from chat
chmod 777 recipes
echo 'composebot-password' > sasl_password.txt
chmod 644 config.yaml sasl_password.txt

docker compose -p $PROJECT up -d --quiet-pull
ready=
for _ in $(seq 1 30); do
    if [ "$(curl -s $HEALTH/readyz)" = ready ]; then ready=yes; break; fi
    sleep 1
done
docker compose -p $PROJECT logs 2>&1 | tail -20
[ -n "$ready" ] || { echo "the bot never got ready"; exit 1; }
docker compose -p $PROJECT stop
CONTAINER=$(docker compose -p $PROJECT ps -aq bot)
[ "$(docker inspect "$CONTAINER" --format '{{.State.ExitCode}}')" = 0 ] \
    || { echo "the bot didn't stop cleanly"; exit 1; }
echo "the compose example ran, got ready and stopped cleanly"
