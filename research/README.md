# research/

Experiment records and research assets for the feed-classification project. The goal is that every engineering decision here is traceable to data.

## Files

| Path | What it is |
|---|---|
| `LOG.md` | Experiment log. One section per experiment: motivation / setup / data / result / conclusion / cost. Append-only — when a conclusion is overturned, add a new experiment referencing the old ID instead of editing it. |
| `TOPICS.md` | Open research questions worth doing but not done yet. |
| `pipeline/` | Collection, labelling, training, export and parity-check scripts. |
| `data/` | Corpora and label sets (gzipped JSONL) plus the frozen split. |
| `results/` | Machine-readable artefacts (JSON/JSONL) matching the tables in `LOG.md`. |

## Method rules

1. **Frozen test set.** Model comparisons always run on the same held-out set, split by uploader/channel so the same creator never appears on both sides — otherwise phrasing style leaks and inflates the numbers.
2. **Repeats and variance.** Anything with randomness (sampling, initialisation) runs at least 3 seeds; report mean ± sd.
3. **One variable at a time.** Data-scaling experiments freeze the model config and vary only the amount of data; hyper-parameter searches freeze the data.
4. **Cost accounting.** Every experiment records LLM token spend (taken from the API's own `usage` field, never estimated) and the number of platform requests.
5. **Honest records.** Negative results and mistakes — such as an uncontrolled variable — are written down, with a note on how much they weaken the conclusion.

## Labelling policy (set by E7)

- **Training labels always use v4-flash** (thinking disabled, ~¥0.06 per 1k items). E7 showed that cleaning training labels brings no measurable gain: the linear model absorbs random label noise, so paying a stronger model to produce training labels is waste.
- **Evaluation labels use v4-pro, once.** The evaluation set defines the standard, so it must not be graded by the same model that taught the student — otherwise "learned the teacher's quirks" scores as ability. The v4-pro evaluation set already exists and is frozen; it is a fixed asset, not a recurring cost.
- **No more arbitration** — E7 showed the return on it is poor.
- Open item: ~200 human-labelled items to verify the currently unproven assumption that v4-pro is in fact closer to ground truth than flash.

## Label axes

Three independent axes, all produced by v4-flash with fixed prompts (prompt versions recorded in `LOG.md`):

- `pro` — informative content: dense, you actually learn something, and the tone stays calm. Emotionally charged "analysis" clickbait does not qualify.
- `neg` — negative content: anxiety-mongering, panic, rage-baiting, shock/lurid content, drama, anger-driven news, course-selling marketing.
- `topic` — one of 48 leaf topics in `../interest-model/taxonomy.json`.
- `emotion` — one of 9 emotions in `../interest-model/emotions.json`, each with a valence from +2 to −2.
