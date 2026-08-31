# Personal Interest Model

> Status: incubating. Shares its foundations (classifiers, feature pipeline, research assets) with the feed-classification userscripts in this repository; it may be split into its own repo once its boundaries settle.

## In one line

Make "your browsing interests" an object **you own**: it lives on your machine, you can read it, edit it and export it — instead of being scattered across platform recommenders as parameters you never see.

## Quick start

Requires one of the feed-mode userscripts installed.

1. **Windows**: download [interest-model-windows.zip](https://github.com/Kali-Leo/feed-mode/releases/latest/download/interest-model-windows.zip), unzip, double-click `interest-model.exe`.
   **Linux / macOS**: install [Python 3.10+](https://www.python.org/downloads/) if you don't have it, download the [source zip](https://github.com/Kali-Leo/feed-mode/archive/refs/heads/main.zip), unpack, and run `./start.sh` in the `interest-model` folder (the first run installs dependencies once)
2. A browser page opens and turns into the dashboard once the first-run model download (~600 MB) finishes
3. The dashboard shows two connect links — click your site, done

The first run also registers the daemon to start at login, so the dashboard stays available after a reboot; launching the program while it is already running just opens the dashboard. Remove the login entry with `--autostart off`.

From then on, just browse as usual and the dashboard fills in: emotion curves of what you're fed vs what you open, word clouds, emerging interests, unfinished informative videos. You can also connect or open the dashboard any time from the 🔗 button on the userscript's switch bar. Data lives in `~/.interest-model/`, and never leaves your machine.

## Why this exists

Survey as of 2026-08 (details in `../research/LOG.md`, E17):

| Prior work | What it does | How this differs |
|---|---|---|
| Google Topics API | Chrome classifies browsing history locally into ~469 topics, for **advertisers** to read | Opposite direction: it computes your interests so others can use them; this computes them for you alone. It is coarse, effectively invisible and not editable, and was rejected by Brave/Mozilla/Apple on privacy grounds. |
| Ad-transparency extensions (MyAdChoices etc.) | Show or clear the labels **a platform** attached to you | Read-only, and about someone else's model; this builds a model you own. |
| Self-hosted recommenders (gorse etc.) | Recommendation service for site operators | Server-side perspective, unrelated to personal ownership. |
| Research on interest drift / time decay / long–short profiles | Modelling methodology | **Reused directly**: long/short dual profiles, exponential time decay, exposure and engagement counted separately. |

Core conceptual difference: existing systems model **revealed preference** (what you clicked). This one also carries **declared preference** (what you want to be interested in), and lets the latter override the former. The Learn mode in the companion userscripts is the first instance of that idea.

## Design principles

1. **Local ownership.** All data and models live on the user's device. Nothing is reported anywhere.
2. **Understandable.** The profile is shown in plain language (topic distribution, trends, what drove it), and every judgement can be traced to concrete features. Shallow, interpretable models are used on purpose — that is the product, not a compromise.
3. **Controllable.** Every topic can be adjusted directly (more / less / block). Declared preference is a first-class citizen.
4. **Portable.** One-click export/import, so users can take their interest model with them.
5. **No sensitive categories.** The taxonomy describes content subject matter only — no political stance, religion, ethnicity, sexual orientation or other personal attributes (following the Topics API category-screening convention).

## Two tracks

Both tracks share one event protocol (exposure / click / dwell + content metadata):

- **Lite (in-browser)** — `lite/`. Zero install: topic classifier plus dual-decay counters run inside the page, stored in localStorage/IndexedDB. Limited, but available to everyone.
- **Full (local host)** — `daemon/`. A resident local service (binds 127.0.0.1, token auth, origin allowlist). The userscript posts events to your own machine, which runs semantic embeddings, stronger classifiers, and a local web dashboard. The userscript upgrades automatically when it detects the daemon, and falls back to the lite track when it does not.

## Taxonomy

`taxonomy.json`: two levels, 13 groups / 48 leaf topics, aimed at video content, with English names alongside Chinese. Quality evaluation in `../research/LOG.md` (E13).
`emotions.json`: 9 emotions with valence from +2 to −2 (E18).

## Evaluation method

Interests have no off-the-shelf ground truth, so evaluation uses **synthetic-user replay**: build virtual users with a known interest mix from labelled corpora (e.g. "40% programming + 30% history + 30% pets"), generate an event stream with realistic engagement bias, replay it through both tracks, and measure profile recovery (distance to the true mix, top-K topic hit rate), convergence speed (how many events until the profile stabilises) and drift response (lag after the interests change mid-stream). Records: `../research/LOG.md` E13–E17.

## Measured results (2026-08-26)

- **Full track is usable**: at group granularity the profile reaches cos = 0.80 and 92% top-3 hit rate, approaching convergence after roughly 50 events; after an interest switch the short-term profile partially catches up within about 200 events. Integration tests pass end to end (auth / event ingest / profile / dashboard / declared preference).
- **The lite track's "mirror" is not good enough yet** (an honest negative result): the pure in-browser n-gram classifier's errors skew systematically toward large categories, so the aggregated profile distorts (cos only 0.49 at group granularity). The lite track's role is therefore narrowed to event collection, declared preference and state export; the mirror itself is served by the full track. Improvement path: distil from the embedding model's silver labels (see `../research/TOPICS.md`).
- **Methodological finding**: profile fidelity depends on the *structure* of classification errors, not the error rate — single-item accuracy is a misleading proxy for profile quality (E14/E15).

## Running the daemon by hand

`start.sh` / `start.bat` wrap `python3 daemon/app.py` (defaults to `127.0.0.1:21456`; `--no-browser` skips opening the dashboard; `--autostart on|off` registers or removes the login entry and exits). Pairing without the dashboard: open `http://127.0.0.1:21456/pair` and pick the site — a one-time code completes the handshake, nothing to copy.
