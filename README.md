<div align="center">

# Feed Mode

**One-click filter for your Bilibili / YouTube home feed: Learn · Feel-good · Fun**

English | [中文](README.zh-CN.md)

[![Bilibili](https://img.shields.io/greasyfork/v/592929?label=Bilibili&color=00aeec)](https://greasyfork.org/scripts/592929)
[![YouTube](https://img.shields.io/greasyfork/v/592932?label=YouTube&color=ff0000)](https://greasyfork.org/scripts/592932)
[![Installs](https://img.shields.io/greasyfork/dt/592929?label=installs)](https://greasyfork.org/scripts/592929)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

<img src="docs/switchbar_en.png" width="560" alt="mode switch on YouTube">

</div>

## ✨ Features

- **Four modes**: All / Fun / Feel-good / Learn. Feel-good keeps healing, comedy, talent and pet content and filters out rage-bait, shock content and anxiety-mongering; Learn covers science, tech, finance and documentaries with a calm tone, so clickbait "analysis" doesn't count.
- **Built-in local model**: works offline out of the box.
- **Optional cloud review**: add a DeepSeek API key for higher accuracy. Usage and cost are shown live; the tolerance slider controls how much goes to the cloud, and at the far end everything runs offline.
- Only reorders the homepage cards; ads, links and creator revenue stay as they are.

## 📊 Results

Measured on 2,368 videos: each was classified with the exact prompt the script uses in production, then scored by a separately trained emotion model.

| Mode | Videos | Mean emotional valence | Share of negative content |
|---|---|---|---|
| **Feel-good** | 1,061 | **+1.09** | **11.9%** |
| Fun | 862 | +0.70 | 24.8% |

Switching from Fun to Feel-good brings the share of negative content from 24.8% down to 11.9%. Method and raw data: [`research/LOG.md`](research/LOG.md), entry E22.

The same gap shows up in the companion dashboard. Orange is the mean emotion of the recommended feed, blue is the videos you actually open:

<img src="docs/emo_fun_en.png" width="880" alt="emotion curve in Fun mode">
<img src="docs/emo_feelgood_en.png" width="880" alt="emotion curve in Feel-good mode">

## 🧭 Companion: your own interest model

[`interest-model/`](interest-model/README.md) is an optional local program that turns your browsing into a dashboard: emotion curves of the feed vs the videos you open, word clouds over a chosen time window, newly emerging interests, and Learn videos you started but never finished. All data stays on your machine; the userscripts connect with one click.

To install: on Windows, download [interest-model-windows.zip](https://github.com/Kali-Leo/feed-mode/releases/latest/download/interest-model-windows.zip), unzip and double-click `interest-model.exe`; on Linux/macOS, run `interest-model/start.sh`. The dashboard opens in your browser; the first run registers autostart, so it stays available after a reboot. Details in its [README](interest-model/README.md).

## 📦 Install

1. Install [Violentmonkey](https://violentmonkey.github.io/) or [Tampermonkey](https://www.tampermonkey.net/)
2. Install the script: [Bilibili](https://greasyfork.org/scripts/592929) · [YouTube](https://greasyfork.org/scripts/592932)
3. Open the site's homepage — the mode switch appears at the bottom left

The interface follows your browser language (English or Chinese).

## 🔑 API Key (optional)

Get a key at [platform.deepseek.com](https://platform.deepseek.com), click ⚙ on the switch bar to enter it, and set it separately per site. With a key, fine-grained calls like "Feel-good" get noticeably more accurate.

The script itself is free; API usage is billed by DeepSeek at their rates, and the running total is shown on the switch bar.

## 🛡️ Privacy

- With a key set, what goes to DeepSeek is the video title, author name and tags; your account, cookies and watch history are never sent
- The key and all classification data stay in your local browser
- The Bilibili script prefetches content through the site's own recommendation API, which amounts to refreshing the homepage a few extra times; the YouTube script does no prefetching

## 🗂️ Repository layout

| Path | What it is |
|---|---|
| `bilibili-feed-mode.user.js` | Bilibili userscript, with the local classifier embedded |
| `youtube-feed-mode.user.js` | YouTube userscript, with the local classifier embedded |
| `interest-model/` | Optional companion: the personal interest dashboard, see its [README](interest-model/README.md) |
| `research/` | Experiment log, training pipeline and labelled datasets, see its [README](research/README.md) |

## ⚠️ Disclaimer

- Third-party personal tool, not affiliated with Bilibili, YouTube/Google or their subsidiaries
- Modifying page display may not comply with parts of the platforms' terms of service; assess the risk yourself
- Classification is AI-generated and not guaranteed to be accurate

## 📄 License

[GPL-3.0](LICENSE). If you like it, leave a ⭐
