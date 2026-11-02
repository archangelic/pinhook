# Security policy

## Supported versions

| Version | Gets fixes |
| --- | --- |
| 2.x | the latest release gets every fix |
| 1.12.x | security fixes only, released from the `1.x` branch |
| older | none |

## Report a vulnerability

Report it privately, through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Don't open a public issue for it.

Say which version is affected, what someone can do with it, and how to reproduce it. The report stays private until a fix is released, and the advisory credits you unless you'd rather it didn't.

## What counts

A bot's plugins and recipe files are code and configuration its owner chose to run, so pinhook trusts them. What a plugin itself does isn't a pinhook vulnerability.

These are, and are worth reporting:

- someone in chat, or a server the bot connects to, running code on the bot's host, or reading or writing its files
- getting past access levels, bans or deny lists, or running a command as someone else
- an op doing more than the bot's own commands allow, like writing files outside `recipe_dir`
- secrets from the config showing up in chat or in the logs
- anything reachable through the health endpoint beyond `/healthz` and `/readyz`
