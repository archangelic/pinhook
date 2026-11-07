# Templates & filters

A recipe's text is a template: `{name}` is a variable, and `|` passes it through a filter.

```yaml
- reply: '{nick} hugs {arg|default:everyone}'
- reply: 'games: {store.games|sorted|join:, }'
```

`{{` and `}}` are a literal brace.

## Filters

| Filter | Gives | Example |
| --- | --- | --- |
| `join` | a list's items, joined with `, `, or the text after `:` | <code>{members&#124;join: and }</code> |
| `sorted` | a list, sorted without regard to case | <code>{store.games&#124;sorted}</code> |
| `count` | how many items | <code>{members&#124;count} here</code> |
| `first`, `last` | the first or last item | <code>{rolled&#124;first}</code> |
| `random` | one item at random | <code>{members&#124;random}</code> |
| `upper`, `lower` | the text in upper or lower case | <code>{nick&#124;upper}</code> |
| `default` | the text after `:` when the value is empty | <code>{arg&#124;default:everyone}</code> |

Filters run left to right: `{store.games|sorted|first}` is the first game alphabetically.

## Read saved values

`{store.games}` reads the key `games` from the recipes' store. `{saved.key}` reads a key from a dict a step saved. A missing key is empty.

## Add a filter from a plugin

A plugin adds filters for every recipe to use:

```python
from pinhook import recipes


@recipes.template_filter('shout')
def shout(value, arg):
    return str(value).upper() + '!'
```

`value` is the variable, and `arg` is the text after `:`, or `None`.

## Add a step from a plugin

A plugin adds step types the same way. Each declares its fields, so recipe files using it are checked when they load:

```python
from pinhook import recipes


@recipes.step('weather', {'weather': 'template', 'save': 'name'}, saves='save')
async def weather(run, fields):
    forecast = await fetch_forecast(run.render(fields['weather']))
    run.save(fields.get('save'), forecast)
```

A field's kind is one of `template`, `text`, `name`, `path`, `steps`, `flag` or `any`.
