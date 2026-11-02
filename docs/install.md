# Install

pinhook needs Python 3.11 or newer. Install it with pip:

```bash
pip install pinhook
```

This installs the `pinhook` command and the library. pinhook's dependencies are `irctokens`, `click`, `marshmallow` and `pyyaml`, and nothing else.

## Install the release candidate

The 2.0 release candidate is a pre-release, which pip installs only when asked:

```bash
pip install --pre pinhook
```

## Check it

```bash
pinhook --version
```

## Run it in a container

The image `ghcr.io/archangelic/pinhook` holds pinhook and nothing else. [Deployment](deployment.md) covers it.

Next: [Your first bot](your-first-bot.md).
