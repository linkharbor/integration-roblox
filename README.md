# LinkHarbor for Roblox

A single-file Python agent that polls the public Roblox API for one
experience and pushes the live numbers to your
[LinkHarbor](https://linkharbor.com) bio page: a game-server card with the
current player count ("1,204 / 48"), visits and favourites, a "Play on
Roblox" button, plus events for push notifications to your followers when
the player count changes or a visits milestone is reached.

It reads the same public endpoints the experience page uses, so there is
nothing to install in the experience and no API key. Roblox does not
expose player names, so there are no join/leave events. Standard library
only, Python 3.10 or newer.

Part of the [LinkHarbor integrations](https://github.com/linkharbor/integrations)
family, one repo per game or tool.

## Setup

```bash
git clone https://github.com/linkharbor/integration-roblox
cd integration-roblox

export LH_INGEST_URL="https://dock.at-harbor.com/v1/ingest/123"   # dashboard: Integrations, Custom (API)
export LH_INGEST_SECRET="…"

python3 agent.py --place-id 920587237 --name "My Experience" \
  --url "https://discord.gg/xyz" --interval 120
```

The place id is the number in the experience URL
(`roblox.com/games/<placeId>/…`). The agent resolves it to the universe id
on start; `--universe-id` skips that step. Without `--url` the button opens
the experience page itself.

Start with `--once -v`. Run it as a service with `integration-roblox.service`
(systemd; secrets go into `/etc/integration-roblox.env`, `chmod 600`).

## Events sent

| Event | When | Template variables |
|---|---|---|
| `experience.online` | first successful poll | `{name}`, `{players_online}`, `{players_max}` |
| `players.changed` | the player count changed since the last poll | `{players_online}`, `{delta}` + the above |
| `milestone.visits` | visits crossed a multiple of `--visits-step` | `{visits}`, `{milestone}` + the above |

The state is sent with every event and every `--heartbeat` minutes (default
10). When the Roblox API does not answer, the agent logs it and tries again
next interval; the card keeps its last state.

Suggested push rule (dashboard, Integrations, Push rules, Custom (API), event `players.changed`): title "🎮 {players_online} playing", body
"{name} has {players_online} players right now", minimum pause 30 min.

## Options

```
--place-id ID          place id from the experience URL
--universe-id ID       universe id (instead of --place-id)
--name NAME            card title (default: the experience's name)
--address TEXT         text shown in the card's address box (optional)
--url URL              link behind the card's button (default: the experience page)
--cta TEXT             button label (default "Play on Roblox")
--image-url URL        banner image (large layout)
--visits-step N        send milestone.visits every N visits (default 0 = off)
--interval SECONDS     polling interval (default 120, minimum 5)
--heartbeat MINUTES    state-only update interval (default 10, 0 = only on change)
--once                 poll once, send, exit
-v                     verbose logging
```

## License

[MIT](LICENSE). © 2026 EMI Solutions OÜ.
