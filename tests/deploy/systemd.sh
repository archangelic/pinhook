#!/bin/sh
# Install examples/deploy/systemd the way its comments say, from a built wheel, pointed
# at the Ergo server from tests/integration/ergo.sh, and check that the service gets
# ready, logs to the journal and stops cleanly. Needs Linux with systemd, and sudo.
#
#   tests/deploy/systemd.sh dist/pinhook-2.0.0-py3-none-any.whl
set -eu
WHEEL=$(realpath "${1:?usage: systemd.sh WHEEL}")
EXAMPLE=examples/deploy/systemd

sudo useradd --system --home-dir /srv/pinhook --shell /usr/sbin/nologin pinhook
sudo python3 -m venv /srv/pinhook/venv
sudo /srv/pinhook/venv/bin/pip install --quiet "$WHEEL"
sudo mkdir -p /srv/pinhook/data /srv/pinhook/recipes /srv/pinhook/plugins
sed -e "s/'irc.libera.chat'/'127.0.0.1'/" -e 's/^port: 6697/port: 6667/' \
    -e 's/^ssl_required: true/ssl_required: false/' -e 's/gamebot/systemdbot/g' \
    $EXAMPLE/config.yaml | sudo tee /srv/pinhook/config.yaml > /dev/null
echo 'SASL_PASSWORD=systemdbot-password' | sudo tee /srv/pinhook/secrets.env > /dev/null
sudo chmod 600 /srv/pinhook/secrets.env
sudo chown -R pinhook: /srv/pinhook
sudo cp $EXAMPLE/pinhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start pinhook

ready=
for _ in $(seq 1 30); do
    if [ "$(curl -s http://127.0.0.1:8080/readyz)" = ready ]; then ready=yes; break; fi
    sleep 1
done
sudo journalctl -u pinhook --no-pager | tail -20
[ -n "$ready" ] || { echo "the bot never got ready"; exit 1; }
sudo journalctl -u pinhook --no-pager | grep -q 'joining channel #systemdbot-test' \
    || { echo "nothing was logged to the journal"; exit 1; }
sudo journalctl -u pinhook --no-pager | grep -q 'other users can read' \
    && { echo "secrets.env was warned about"; exit 1; }
sudo systemctl stop pinhook
[ "$(systemctl show pinhook -p Result --value)" = success ] \
    || { echo "the bot didn't stop cleanly"; exit 1; }
echo "the systemd example ran, got ready and stopped cleanly"
