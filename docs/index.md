---
template: home.html
title: drop a line in any channel
hide:
  - navigation
  - toc
---

## Quick start

```bash
pip install pinhook
pinhook new bot gamebot
```

Edit `gamebot/config.yaml` with your server and channel, then run the bot:

```bash
pinhook run gamebot/config.yaml
```

Say `!hello` in the channel and the bot answers.

## Where to next

* [Your first bot](your-first-bot.md): a dice command, its test, and running it
* [The context](the-context.md): everything a plugin gets with `ctx`
* [Writing recipes](writing-recipes.md): commands written as YAML
* [Access levels](access-levels.md): who runs what
* [Deployment](deployment.md): the image, and compose, systemd and Kubernetes examples
* Coming from 1.x? [Migrating from 1.x](migrating-from-1x.md) lists what changed

pinhook is made with love on [tilde.town](https://tilde.town). Bots using it include [pinhook-tilde](https://github.com/archangelic/pinhook-tilde) and [adminbot](https://github.com/tildetown/adminbot).
