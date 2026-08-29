# Local service API

The daemon in `daemon/app.py` binds `127.0.0.1` only. This document is the contract for other local programs that read from it.

## Stability promise

- Responses carry `api_version` (currently `1`).
- **Additive changes only** within a version: new fields may appear at any time; existing field names and their meaning will not change.
- A rename or a semantic change bumps `api_version` and will be announced in `../research/LOG.md` before shipping.

## Authentication

| Surface | Requirement |
|---|---|
| Read endpoints (`GET`) | None, but **no CORS headers are sent**, so only same-origin (the dashboard) and native local programs can read the response. Web pages cannot. |
| Write endpoints (`POST /events`, `POST /prefs`) | Header `X-IM-Token` must equal the token in `~/.interest-model/token`. |
| `POST /pair/new` | Same token. Intended for local programs that can read the token file. |
| `POST /pair/exchange` | No token, but `Origin` must be in the allowlist (`https://www.bilibili.com`, `https://www.youtube.com`) **and** the pairing code must be valid. |
| `GET /pair` | None (the daemon binds 127.0.0.1 only). A human-facing launcher: it lists site links, and `GET /pair?site=bilibili\|youtube` mints a code and 302-redirects to that site with `#im-pair=<nonce>`, where the script completes the exchange. Local programs should keep using `POST /pair/new`. |

## Pairing (how a browser script gets the token without the user copying it)

The token stays the only credential; pairing is just a delivery path for it.

```
local app                     daemon                       userscript
    |  POST /pair/new           |                                |
    |  (X-IM-Token)             |                                |
    |------------------------->|                                |
    |  {nonce, expires_in:120}  |                                |
    |<-------------------------|                                |
    |                                                            |
    |  open https://www.bilibili.com/#im-pair=<nonce>            |
    |----------------------------------------------------------->|
    |                           |   POST /pair/exchange {nonce}  |
    |                           |   (Origin set by the browser)  |
    |                           |<-------------------------------|
    |                           |   {token}                      |
    |                           |------------------------------->|
```

The userscript strips the fragment from the URL before exchanging, so the code does not linger in the address bar or history. It listens for both page load and `hashchange`, so it also works when the site is already open and the fragment is appended to the current tab.

Properties: the code is single-use, expires in 120 seconds, is only issued to a caller that can already read the token file, and can only be redeemed from an allowlisted origin. The token itself is never displayed or copied.

## Read endpoints

All return JSON. `days` defaults are per-endpoint; values are clamped to 1–3650.

| Endpoint | Query | Returns |
|---|---|---|
| `GET /profile` | — | `api_version`, `topics` / `topics_en` (48 leaf names), `groups` / `groups_en`, `short` / `long` / `expose` (normalised 48-vectors), `prefs`, `drivers`, `n_events`, `classifier`, `emotion_on` |
| `GET /emotion_series` | `days`, `cat` ∈ `all|pro|ent|gent` | `emotions` / `emotions_en`, `valences`, and `expose` / `engage`: arrays of `{day, valence, n, mix[]}` |
| `GET /wordcloud` | `days`, `source` ∈ `engage|expose` | `{days, source, words: [{w, n, valence}]}` |
| `GET /new_interests` | — | `{interests: [{topic, topic_en, share, before, items[]}]}` |
| `GET /pro_content` | `days` | `{days, finished[], unfinished[]}`; items carry `ts, id, title, up, topic, topic_en, group, group_en, pic, dwell, dur, site` |
| `GET /export` | — | Full profile snapshot |

Note on `cat=gent` in `/emotion_series`: it is approximated as "non-informative topics with valence ≥ 0.5". Because the filter is defined by valence, its curve is **not** independent evidence about emotional quality — do not present it as such. For a real measurement see `../research/LOG.md` E22.

## Write endpoints

`POST /events` — body is one event object or an array (max 1000):

```json
{"t": "title", "u": "author", "type": "expose|click|watch",
 "dwell": 0, "dur": 0, "id": "video id", "pic": "cover url",
 "site": "bilibili|youtube", "ts": 1756200000.0}
```

Events are classified on arrival (topic + emotion, routed by `site`) and appended to `~/.interest-model/events.db`.

`POST /prefs` — body `{"<topic name>": -2..2}` — declared preference per topic.

## Failure behaviour expected of clients

The service may not be running. Clients should treat connection failure as "not connected" and retry rather than discard data; the userscripts queue up to 1000 events and retry with exponential backoff (5s → 60s). A `403` means the token is wrong and retrying will not help — surface it to the user instead of retrying.
