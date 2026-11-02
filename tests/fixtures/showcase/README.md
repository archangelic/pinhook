# The showcase bot

A bot that uses every plugin feature pinhook 2.0 has, for trying 2.0 out on a real network
and for the tests in `tests/test_showcase.py`.

- `plugins/legacy_tour.py` uses every 1.x feature 2.0 runs through its compatibility layer
- `plugins/modern_tour.py` uses every 2.0 feature: a class plugin, typed commands, aliases,
  access levels, everything on `ctx`, an `@on` handler for each event, and a timer
- `recipes/` has a recipe for each step type

Run it against a network:

```bash
cp -r tests/fixtures/showcase /tmp/showcase
# edit /tmp/showcase/config.yaml: server, channels and ops
pinhook check --strict /tmp/showcase/config.yaml
pinhook run /tmp/showcase/config.yaml
```

Then say `!help` in the channel, and try each command it lists.
