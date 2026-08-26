<div align="center">

# Feed Mode

**One-click filter for your Bilibili / YouTube home feed: Informative · Feel-good · Entertainment**

[中文](README.md) | English

[![Bilibili](https://img.shields.io/greasyfork/v/592929?label=Bilibili&color=00aeec)](https://greasyfork.org/scripts/592929)
[![YouTube](https://img.shields.io/greasyfork/v/592932?label=YouTube&color=ff0000)](https://greasyfork.org/scripts/592932)
[![Installs](https://img.shields.io/greasyfork/dt/592929?label=installs)](https://greasyfork.org/scripts/592929)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

<img src="docs/switchbar.png" width="620" alt="mode switch">

<img src="docs/preview.png" width="840" alt="Bilibili homepage with the mode switch (logged-out screenshot)">

</div>

## ✨ Features

- **Four modes**: All / Entertainment / Feel-good (healing, comedy, talent, pets — filters rage-bait, shock content and anxiety-mongering) / Informative (science, tech, finance, documentaries with a calm tone — clickbait "analysis" doesn't count)
- **Built-in local model**: works offline out of the box, no configuration
- **Optional cloud review**: add a DeepSeek API key for higher accuracy; usage and cost shown in real time, with a tolerance slider to control cloud usage
- **Hands off business**: no ad blocking, no link rewriting — creator revenue is untouched

## 📦 Install

1. Install [Violentmonkey](https://violentmonkey.github.io/) or [Tampermonkey](https://www.tampermonkey.net/)
2. Install the script: [Bilibili](https://greasyfork.org/scripts/592929) · [YouTube](https://greasyfork.org/scripts/592932)
3. Open the site's homepage — the mode switch appears at the bottom left

## 🔑 API Key (optional)

Works fine without one. With a key, classification is reviewed by a cloud model and fine-grained calls like "Feel-good" get noticeably better.

Get a key at [platform.deepseek.com](https://platform.deepseek.com), click ⚙ on the switch bar to enter it. Set it separately per site.

> This project is completely free and never handles any money. API costs are settled directly between you and DeepSeek; without a key there is zero cost.

## 🛡️ Privacy

- Only with a key set: video title, author name and tags are sent to DeepSeek for classification — never your account, cookies or watch history
- The key and all classification data stay in your local browser; nothing is uploaded
- The Bilibili script prefetches content via the site's own recommendation API, equivalent to refreshing the homepage; the YouTube script does no prefetching

## ⚠️ Disclaimer

- Third-party personal tool, not affiliated with Bilibili, YouTube/Google or their subsidiaries
- Modifying page display may not comply with parts of the platforms' terms of service; assess the risk yourself
- Classification is AI-generated and not guaranteed to be accurate

## 📄 License

[GPL-3.0](LICENSE) — free and open source forever. If you like it, leave a ⭐

