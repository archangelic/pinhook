# Writing recipes

A recipe is a command written as YAML, not Python. It runs existing commands, replies, saves data, loops and checks conditions, so a bot owner who doesn't program can make their own commands.

## Write one

Save this as `recipes/gamenight.yaml`:

```yaml
version: 1
name: gamenight
help: pick tonight's game and who goes first
steps:
  - command: 'quote random games'
    save: game
  - reply: 'Tonight: {game}. {members|random} goes first'
```

`!gamenight` runs the steps in order. The bot loads every `.yaml` file in `recipes/` when it starts and on `!reload`. `pinhook new recipe gamenight` makes a starter file.

## Run commands as the person who asked

A `command` step runs a command, written without its prefix, as the person who started the recipe, with their access. A recipe can never do more than its user could. With `save: name`, what the command said goes in that variable, as a list of lines. Without it, it's said in the channel.

A step that can't run stops the recipe, and it says why:

```
<ana> !gamenight
<gamebot> gamenight stopped: ana doesn't have access to !quote
```

## The steps

| Step | What it does |
| --- | --- |
| `command: 'roll 2 20'` | runs a command, and `save: name` keeps what it said |
| `reply: 'text'` | says a [template](templates-and-filters.md) |
| `store: games` with `set:`, `add:`, `remove:` or `clear: true` | changes the recipes' store, kept between restarts |
| `for_each: members` with `steps:` | runs its steps once per item, as `{item}` |

Every step can carry `when`, which skips it unless the condition holds:

```yaml
version: 1
name: addgame
help: add a game to the list, like addgame azul
steps:
  - store: games
    add: '{arg}'
    when: arg is not ''
  - reply: 'games: {store.games|sorted|join}'
```

`when` compares a variable with a value: `x is y` or `x is not y`.

## Variables

| Variable | Holds |
| --- | --- |
| `{nick}` | who started the recipe |
| `{channel}` | where |
| `{arg}` | everything after the recipe's name |
| `{members}` | the nicks in the channel |
| `{store.key}` | a key in the recipes' store |
| `{item}` | the current item, inside `for_each` |
| anything a step saved | like `{game}` above |

Every recipe shares one store, so `!addgame` adds what `!games` lists. A recipe that reads a store key no recipe sets gets a warning when it loads, naming the closest key that is set.

## Check recipes

The bot checks every recipe when it loads: the version, each step's fields, every variable and filter. A recipe with a mistake is left out and logged, and the rest still load. `pinhook check config.yaml` shows the same errors without starting the bot.

## Add a recipe from chat

Ops add one-line reply recipes from chat, and remove any recipe:

```
!recipe add hug {nick} hugs {arg|default:everyone}
!recipe del hug
```

`!recipe add` checks the template, then saves it as `recipes/hug.yaml`.

## Set who runs it

`access: restricted` or `access: ops` in the file sets the recipe's level. [Access levels](access-levels.md) covers grants, and `access.recipes` in the config.

## Limits

A run takes at most 100 steps, loops included. A recipe that calls itself, directly or through another recipe, stops with the chain it took:

```
gamenight stopped: it calls itself: gamenight -> pick -> gamenight
```
