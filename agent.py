#!/usr/bin/env python3
"""LinkHarbor agent for Roblox experiences.

Polls the public Roblox API for one experience (no server, no API key —
the numbers are the same ones the experience page shows) and pushes the
state to a LinkHarbor "Custom (API)" integration: a game-server card on
your bio page with the live player count, visits and favourites, a "Play"
button, and events for push notifications.

    export LH_INGEST_URL="https://dock.at-harbor.com/v1/ingest/123"
    export LH_INGEST_SECRET="…"
    python3 agent.py --place-id 920587237 --url "https://discord.gg/xyz"

The place id is the number in the experience URL
(roblox.com/games/<placeId>/…); it is resolved to the universe id on start.
No third-party packages needed (Python 3.10+, standard library only).

Events sent (each can drive a push rule in the dashboard):
    experience.online   first successful poll
    players.changed     data.players_online, data.delta
    milestone.visits    data.visits, data.milestone (every --visits-step visits)

Roblox does not expose player names, so there are no join/leave events.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

log = logging.getLogger("linkharbor")

UA = "LinkHarbor-Roblox/1.0"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--place-id", type=int, default=0, help="place id from the experience URL (roblox.com/games/<placeId>/…)")
    p.add_argument("--universe-id", type=int, default=0, help="universe id (instead of --place-id)")
    p.add_argument("--name", default="", help="card title (default: the experience's name)")
    p.add_argument("--address", default="", help="text shown in the card's address box (optional)")
    p.add_argument("--url", default="", help="link behind the card's button (default: the experience page)")
    p.add_argument("--cta", default="Play on Roblox", help="button label")
    p.add_argument("--image-url", default="", help="banner image for the large layout")
    p.add_argument("--visits-step", type=int, default=0, help="send milestone.visits every N visits (0 = off)")
    p.add_argument("--interval", type=int, default=120, help="seconds between polls (default 120)")
    p.add_argument("--heartbeat", type=int, default=10, help="minutes between state-only updates (0 = only on change)")
    p.add_argument("--ingest-url", default=os.environ.get("LH_INGEST_URL", ""))
    p.add_argument("--ingest-secret", default=os.environ.get("LH_INGEST_SECRET", ""))
    p.add_argument("--once", action="store_true", help="poll once, send, exit")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    if not a.place_id and not a.universe_id:
        p.error("give --place-id or --universe-id")
    if not a.ingest_url or not a.ingest_secret:
        p.error("set LH_INGEST_URL and LH_INGEST_SECRET (or --ingest-url / --ingest-secret)")
    return a


class Ingest:
    def __init__(self, url: str, secret: str) -> None:
        self.url, self.secret = url, secret

    def send(self, event: str | None, data: dict | None, state: dict) -> bool:
        body: dict = {"state": state}
        if event:
            body["event"] = event
            body["event_id"] = f"{event}-{uuid.uuid4()}"
        if data:
            body["data"] = data
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json",
                     "User-Agent": UA},
        )
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    log.debug("← %s %s", res.status, res.read(200).decode(errors="replace"))
                    return True
            except urllib.error.HTTPError as e:
                text = e.read(300).decode(errors="replace")
                if e.code == 401:
                    log.error("401 from LinkHarbor — wrong secret or integration disconnected")
                    return False
                if e.code < 500:
                    log.error("%s from LinkHarbor: %s", e.code, text)
                    return False
                log.warning("%s from LinkHarbor (attempt %d)", e.code, attempt)
            except Exception as e:  # network
                log.warning("request failed (attempt %d): %s", attempt, e)
            time.sleep(2)
        return False


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read(512_000).decode(errors="replace"))


def fetch_universe_id(place_id: int) -> int | None:
    """Resolves a place id to its universe id; None when the API did not answer."""
    try:
        data = fetch_json(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe")
        return int(data.get("universeId") or 0) or None
    except Exception as e:
        log.debug("universe lookup failed: %s", e)
        return None


def fetch_game(universe_id: int) -> dict | None:
    """Returns the experience's numbers, or None when the API did not answer."""
    try:
        data = fetch_json("https://games.roblox.com/v1/games?" + urllib.parse.urlencode({"universeIds": universe_id}))
        row = (data.get("data") or [None])[0]
    except Exception as e:
        log.debug("games lookup failed: %s", e)
        return None
    if not isinstance(row, dict):
        log.debug("no experience for universe %s", universe_id)
        return None
    return {
        "name": str(row.get("name") or "").strip(),
        "playing": int(row.get("playing") or 0),
        "visits": int(row.get("visits") or 0),
        "favorites": int(row.get("favoritedCount") or 0),
        "max_players": int(row.get("maxPlayers") or 0),
        "creator": str((row.get("creator") or {}).get("name") or ""),
        "updated": str(row.get("updated") or ""),
        "root_place_id": int(row.get("rootPlaceId") or 0),
    }


def build_state(a: argparse.Namespace, info: dict, place_id: int) -> dict:
    s: dict = {
        "type": "game_server",
        "name": a.name or info["name"] or "Roblox experience",
        "online": True,
        "players_online": info["playing"],
        "players_max": info["max_players"],
        "game": "Roblox",
        "description": f"{info['visits']:,} visits · {info['favorites']:,} favorites"[:200],
        "url": a.url or f"https://www.roblox.com/games/{place_id}",
        "cta": a.cta,
    }
    if a.address:
        s["address"] = a.address
    if a.image_url:
        s["image_url"] = a.image_url
    return s


def main() -> int:
    a = parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ingest = Ingest(a.ingest_url, a.ingest_secret)

    universe_id = a.universe_id
    place_id = a.place_id
    first = True
    last_playing = 0
    last_visits = -1
    last_sent = 0.0
    heartbeat_s = a.heartbeat * 60

    while True:
        if not universe_id:
            universe_id = fetch_universe_id(place_id) or 0
            if universe_id:
                log.info("place %s → universe %s", place_id, universe_id)
            else:
                log.warning("could not resolve place %s, retrying in %ss", place_id, a.interval)
        info = fetch_game(universe_id) if universe_id else None
        if info is None:
            if universe_id:
                log.warning("Roblox API did not answer, retrying in %ss", a.interval)
            if a.once:
                return 1
            time.sleep(max(5, a.interval))
            continue
        if not place_id:
            place_id = info["root_place_id"]
        state = build_state(a, info, place_id)

        events: list[tuple[str, dict | None]] = []
        if first:
            events.append(("experience.online", None))
        elif info["playing"] != last_playing:
            events.append(("players.changed", {"players_online": info["playing"], "delta": info["playing"] - last_playing}))
        if a.visits_step > 0 and last_visits >= 0 and info["visits"] // a.visits_step > last_visits // a.visits_step:
            milestone = (info["visits"] // a.visits_step) * a.visits_step
            events.append(("milestone.visits", {"visits": info["visits"], "milestone": milestone}))

        if events:
            for ev, data in events:
                log.info("%s %s", ev, json.dumps(data) if data else "")
                ingest.send(ev, data, state)
            last_sent = time.time()
        elif heartbeat_s and time.time() - last_sent >= heartbeat_s:
            log.info("heartbeat: %s playing, %s visits", info["playing"], info["visits"])
            ingest.send(None, None, state)
            last_sent = time.time()

        first = False
        last_playing = info["playing"]
        last_visits = info["visits"]
        if a.once:
            return 0
        time.sleep(max(5, a.interval))


if __name__ == "__main__":
    sys.exit(main())
