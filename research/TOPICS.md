# Open research questions

Ordered by expected value to the project. When one is finished, move it to `LOG.md` and mark the experiment ID here.

## High priority — directly affects cost or quality

1. ~~**Data-scaling law**~~ (done → E5: not saturated at 13.5k; +2–4 pt per doubling; the next meaningful step is 50–100k, which needs the supply problem solved first).
2. ~~**Label-noise measurement**~~ (done → E5/E7: flash self-consistency 90%, agreement with v4-pro 88%; cleaning training labels gains nothing, cleaning the evaluation set pays off. Remaining sub-question: ~200 human gold labels for a three-way alignment check).
3. **Rebuild the `neg` axis**: only 5% positives today and F1 0.18, i.e. unusable. Either collect negative-emotion positives on purpose, or redefine the axis / fold it into the multi-class model.
4. **Supply expansion**: legitimate ways past the ~18k corpus ceiling — long-running low-rate collection, public datasets, uploader submission feeds.
5. **Distillation gain**: how much silver labelling from the BERT teacher helps the linear student, and how the silver confidence threshold changes it. How far can API-free data expansion go?
6. **Confidence calibration and routing**: reliability diagram for the local model's probabilities; the optimal share sent to the cloud under a "local error rate ≤ x%" constraint; whether the routing threshold should be asymmetric (cost of missing a `pro` item vs cost of admitting an `ent` one).
7. **Concept drift and freshness**: how fast title style and topics drift; F1 decay of a frozen model after 1 / 4 / 12 weeks; from that, the retraining and release cadence.

## Medium priority — architecture and features

8. **Feature ablation**: marginal contribution of character n-gram range (1-3 / 1-4 / 2-4), hash dimension, the uploader-name field, and (if added) zone/tag metadata.
9. **Uploader-prior coverage and precision**: accuracy of auto-freezing rules from an uploader's label history, how coverage grows over time, and an automatic correction mechanism (LLM spot checks) when a rule goes wrong.
10. **On-device personalisation**: gain of a global model plus local incremental updates (online logistic regression) over a purely global model; the value of a small amount of explicit user feedback (manual re-labelling).
11. **Recommender ecosystem adaptation**: how the personalised feed's `pro` rate changes after sustained consumption of informative content only (E2 measured a 20.9% baseline). This determines steady-state supply cost.
12. **Multilingual transfer**: partially answered by E20 — joint cross-lingual training beat both monolingual models. Open: whether byte-level features or a dedicated English model would help further.
13. **Lite-track distillation**: use the embedding classifier to silver-label a large corpus, then distil an n-gram student; target is lifting the lite track's group-level profile fidelity from cos 0.49 to 0.7+. Alternatively, regularise the error structure (penalise the systematic skew toward large categories).
14. **Drift-detection sensitivity**: under the E14 drift criterion, fine-grained tracking is sluggish; map the trade-off between the short-term profile's half-life and its sensitivity/stability.

## Low priority — long-horizon

15. **Steady-state token economics**: how cache hit rate and uploader-rule coverage evolve with usage time; derive the asymptotic monthly cost.
16. **Aligning the definition of "negative"**: how much users disagree on the boundary; whether a configurable strictness knob is enough to express individual differences.
17. **Quantifying the privacy–quality trade-off**: the Pareto front between purely on-device and hybrid setups, in terms of both accuracy and exposed information.
18. **Supply-diversity metrics**: topic entropy and uploader concentration of the filtered feed, to test whether filtering does *not* narrow the bubble.

---

## Pending tasks (not research)

- **Publish the internationalised builds to Greasy Fork**: local is at Bilibili 2.0.4 / YouTube 2.0.2 (UI i18n, localised script metadata, event-reporting fixes); the store still has 2.0.2 / 2.0.0. Needs a signed-in browser session.
- **`LOG.md` is still in Chinese.** It is the raw experiment record and the largest document here; translating it is worthwhile for English-speaking contributors but has not been done.
