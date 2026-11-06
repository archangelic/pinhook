#!/bin/sh
set -eu
IMAGE=${1:?usage: image.sh IMAGE}
WORK=$(mktemp -d)
NAME=pinhook-image-test
trap 'docker rm -f $NAME >/dev/null 2>&1; docker volume rm -f $NAME-data >/dev/null 2>&1; rm -rf "$WORK"' EXIT

if [ "$(uname)" = Darwin ]; then
    SERVER=host.docker.internal NETWORK="-p 18080:8080" HEALTH=http://127.0.0.1:18080
else
    SERVER=127.0.0.1 NETWORK="--network host" HEALTH=http://127.0.0.1:8080
fi

mkdir "$WORK/plugins"
cat > "$WORK/config.yaml" <<CONFIG
nickname: 'imagebot'
server: '$SERVER'
port: 6667
channels:
  - '#imagetest'
CONFIG
chmod 644 "$WORK/config.yaml"
chmod 755 "$WORK" "$WORK/plugins"

docker run -d --name $NAME $NETWORK \
    -v "$WORK/config.yaml:/bot/config.yaml:ro" -v "$WORK/plugins:/bot/plugins:ro" \
    -v $NAME-data:/bot/data "$IMAGE" > /dev/null

ready=
for _ in $(seq 1 30); do
    if [ "$(curl -s $HEALTH/readyz)" = ready ]; then ready=yes; break; fi
    sleep 1
done
docker logs $NAME 2>&1 | tail -20
[ -n "$ready" ] || { echo "the bot never got ready"; exit 1; }
[ "$(curl -s $HEALTH/healthz)" = ok ] || { echo "/healthz isn't ok"; exit 1; }
[ "$(docker exec $NAME id -u)" != 0 ] || { echo "the image runs as root"; exit 1; }
docker logs $NAME 2>&1 | grep -q 'joining channel #imagetest' \
    || { echo "nothing was logged to stdout"; exit 1; }
docker stop $NAME > /dev/null
[ "$(docker inspect $NAME --format '{{.State.ExitCode}}')" = 0 ] \
    || { echo "the bot didn't stop cleanly"; exit 1; }
echo "the image ran, got ready and stopped cleanly"
