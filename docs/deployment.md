# Deployment

A bot is one long-running process holding one connection. Run it as exactly one instance: a container, a systemd service, or `pinhook run`.

## Run one copy

Two copies of a bot fight over its nick and answer every command twice. Every example here runs one copy, and replaces it by stopping the old one first: `strategy: Recreate` on Kubernetes, never a rolling update. Restarts are safe: the bot reconnects, and its state is on disk.

## Keep state on a volume

`data_dir` holds plugin stores, grants and denies, bans, `!enable` and `!disable`, and STS policies. `recipes/` holds recipes added from chat. Put both on a persistent volume with one writer. A backup is a copy of the two folders.

The config is read only. Check it in CI before it's deployed:

```bash
pinhook check --strict config.yaml
```

## Pass secrets

Write `${NAME}` for an environment variable and `${file:PATH}` for a file, which is how Docker and Kubernetes secrets arrive:

```yaml
sasl_password: '${file:/run/secrets/sasl_password}'
```

`secrets.env` beside the config is for a plain install. A variable already in the environment wins. Secrets show as `***` in the log.

## Logs

```yaml
log_file: '-'
log_format: json
```

`log_file: '-'` writes to stdout. `log_format: json` writes one JSON object per line, with `time`, `level`, `bot` and `message`, and `error` with the traceback:

```json
{"time": "2026-11-02T10:15:00.123+00:00", "level": "info", "bot": "gamebot", "message": "mal (account mal) ran !ban troll: banned troll (account trollacct)", "audit": true}
```

Changes to who can do what are audit lines, logged with who made them and carrying `"audit": true`: `!op`, `!deop`, `!ban`, `!unban`, `!allow`, `!deny`, `!revoke`, `!enable`, `!disable` and `!recipe`.

## Health checks

```yaml
health_port: 8080
```

`/healthz` answers 200 while the process runs. `/readyz` answers 200 once the bot is connected and in every channel in its config, and 503 with the reason before then, like `not in #games`. It listens on `health_host`, `127.0.0.1` by default.

## Shut down cleanly

SIGTERM lets running commands finish and sends what's waiting, for up to 5 seconds, then quits. Give the bot longer than that to stop: the examples give it 30 seconds.

## Network

A bot makes outbound connections only: IRC on 6697, or Twitch's chat servers. It needs no inbound ports apart from the health endpoint.

## The image

`ghcr.io/archangelic/pinhook` is pinhook on Python 3.15's slim image, for amd64 and arm64, tagged with each version and its minor and major, like `2.0.0`, `2.0` and `2`. It runs as user 10001, with `/bot` as its folder:

| Path | Holds |
| --- | --- |
| `/bot/config.yaml` | the config, mounted read only |
| `/bot/plugins` | plugins, mounted or built in |
| `/bot/recipes` | recipes, writable for `!recipe add` |
| `/bot/data` | the volume |

It runs `pinhook run /bot/config.yaml`, logs to stdout, and serves the health endpoint on 8080. A bot with plugin dependencies builds its own image on it:

```dockerfile
FROM ghcr.io/archangelic/pinhook:2
COPY plugins /bot/plugins
RUN pip install --no-cache-dir requests
```

Each image is signed with cosign. Check one:

```bash
cosign verify ghcr.io/archangelic/pinhook:2 \
  --certificate-identity-regexp '^https://github.com/archangelic/pinhook/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Docker Compose

Save these beside `config.yaml`, `plugins/` and `recipes/`, with the bot account's password in `sasl_password.txt`, then run `docker compose up -d`.

`compose.yaml`:

```yaml
--8<-- "examples/deploy/compose/compose.yaml"
```

`config.yaml`:

```yaml
--8<-- "examples/deploy/compose/config.yaml"
```

## systemd

For a plain `pip install` on a server. Save this as `/etc/systemd/system/pinhook.service`, after the steps at its top:

```ini
--8<-- "examples/deploy/systemd/pinhook.service"
```

`/srv/pinhook/config.yaml`:

```yaml
--8<-- "examples/deploy/systemd/config.yaml"
```

## Kubernetes

A ConfigMap for the config, a PersistentVolumeClaim for `data/` and `recipes/`, and a Deployment with one replica, `strategy: Recreate` and probes on the health endpoint:

```yaml
--8<-- "examples/deploy/kubernetes/pinhook.yaml"
```

Each example is started against a real IRC server in pinhook's CI, so these files work as shown.
