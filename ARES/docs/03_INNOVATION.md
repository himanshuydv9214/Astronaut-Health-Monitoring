# D. Technical contribution — what is actually new here

Each item solves a stated problem; nothing is included just to look advanced.

1. **Personal, context-conditioned Bayesian baselines.**
   *Problem:* population ranges miss abnormal-for-you values and flag normal-for-you ones
   (a fit astronaut sleeps at HR 42). *Solution:* a Normal-Inverse-Gamma model per astronaut ×
   signal × activity context (sleep / rest / exercise / recovery). The Student-t predictive gives a
   deviation score **with its own uncertainty**; exponential forgetting (7-day half-life) follows slow
   adaptation; z-gating stops acute events from being learned as "normal".

2. **Corroboration rule between population safety limits and personal deviation.**
   *Problem:* ignoring population limits is unsafe; obeying them blindly causes false alarms.
   *Solution:* a limit breach counts as a medical deviation only if it is also unusual for this
   person (|z| ≥ 2); otherwise it is an **observation**, never silently ignored. Critical limits still
   escalate (to L2 without corroboration, L3 with it).

3. **Measurement-aware persistence.** Spot-check channels (BP cuff) count *measurements*, not minutes,
   and ask for a repeat reading before escalating — standard clinical practice that naive monitors
   violate by treating one held cuff value as "sustained for 15 minutes".

4. **Crew-wide environmental attribution.** When ≥ half the crew deviate the same way at the same time
   while ppCO₂ is elevated, ARES opens **one cabin incident** and tags individual reports
   "environmental cause likely", instead of four separate medical incidents.

5. **Mission-aware escalation.** Reports state the one-way light time, earliest possible ground reply
   and link state; in blackout they say so explicitly. Earth messages are prioritised P1–P4,
   store-and-forward, never dropped.

6. **Uncertainty-aware, explainable decisions.** Every alert carries: values vs personal band, how
   long, trend, systems involved, sensor quality, missing data, detection confidence, and SHAP
   attributions from the forecaster (SHAP is computed on the *same* booster that predicts; isotonic
   calibration is monotone).

7. **ML in its proper place.** Isolation Forest (trained on nominal minutes only) and a calibrated
   30-min risk forecaster can raise *observation*; only transparent rules declare L2/L3. ML outputs
   are labelled "simulation-trained, not a medical probability". **Runtime model monitoring** compares
   the live anomaly-flag rate to its expected 0.5 % and tracks out-of-range features — this caught a
   real train/serve mismatch during development (documented in `docs/LIMITATIONS.md`).

8. **Behavioral channel with privacy by design.** Real PVT-B in the browser, scored exactly as on ISS;
   results go to the astronaut and CMO only; Earth receives the readiness category, not scores.

9. **Tamper-evident onboard record.** SHA-256 hash chain over stored vitals/events/behavioral rows;
   `GET /api/system` verifies it. Records synchronised to Earth hours later can be trusted.

10. **Honest evaluation.** Astronaut-level split, conventional baselines (static limits, NEWS2),
    calibration, horizon analysis, leave-one-scenario-out, sensor- and comm-failure tests, and
    real-data validation of the signal chain with its weaknesses reported.
