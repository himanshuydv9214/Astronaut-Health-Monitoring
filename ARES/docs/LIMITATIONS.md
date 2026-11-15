# Limitations (read this before presenting results)

1. **Not a medical device.** No clinical validation. Protocol entries are **UNAPPROVED DEMO** structures;
   real flight procedures are controlled documents.
2. **Simulated crew.** All crew physiology, dosimeters, cabin sensors and behavioral results in the demo
   are simulated. The fictional crew are not real people.
3. **Evaluation measures internal consistency.** Ground truth is the scenario designer's labelling.
   High recall on simulated scenarios shows the logic works as designed, not that it detects real
   illness. Leave-one-scenario-out results show how much performance drops on event types the
   forecaster never saw.
4. **Domain shift Earth → spaceflight.** Real-data validation uses hospital (MIT-BIH, 1975–79) and
   driving (drivedb) ECG. Microgravity changes fluid distribution, ECG amplitude/axis, and electrode
   contact; none of that is represented.
5. **Small real-data sample.** One annotated MIT-BIH record and one drivedb record were reachable from
   the build environment. Results are a demonstration of the method.
6. **ECG quality index weakness.** At ≤ 0 dB in-band noise the SQI still trusts some windows with HR error
   > 10 bpm. ARES mitigates with ECG–oximeter cross-checking and persistence requirements, but the SQI
   itself needs improvement (multi-lead agreement, personal beat template).
7. **Train/serve consistency is engineered, not measured on hardware.** A mismatch between the fast
   simulation path and the live ECG path inflated the live anomaly-flag rate (~14 % vs 0.5 % expected)
   until the fast path was given the ECG pipeline's measured error model. The runtime model monitor
   detected it; the same monitor is the guard against spaceflight adaptation drift.
8. **Radiation biology is not modelled.** Measured and modelled dose only; individual cancer,
   cardiovascular or cataract risk is deliberately not computed.
9. **Cabin model is single-volume and well-mixed.** Real microgravity CO₂ pockets are not modelled.
10. **Behavioral readiness is not a mental-health diagnosis.** Thresholds are engineering choices;
    PVT practice effects are only partly handled (first test treated as familiarisation).
11. **Security.** The local API has no authentication and the SQLite store is not encrypted at rest
    (SQLCipher or equivalent and role-based access are deployment requirements).
12. **Trajectory** is a Hohmann transfer on circular coplanar orbits — correct magnitude of distance and
    light time, not a mission design.

## Real NASA data models (added Nov 14)
* **Model D (RadLab):** one DOSTEL-1 detector in Columbus, in LEO. Most SEPs are not visible at ISS (3/10 strong 2024 events
  detected). The SAA split uses a fixed dose cut because this export has no orbit position. Labels (SRAG) are GOES >10 MeV
  at geostationary orbit. A threshold calibrated on 2022–23 does not transfer to 2024 (solar maximum). Deep-space validation
  needs MSL/RAD data.
* **Model E (Inspiration4):** n = 4, 3-day mission, civilian crew, three pre-flight samples each. Cytokine analysis is
  exploratory (71 analytes, no multiplicity correction).
* **Model C / bone (rodents):** relative western-blot intensities, small groups, uncorrected comparisons. Shown only as
  research evidence on muscles and bones, never as an astronaut's state.
* **GeneLab runsheets (OSD-104, OSD-770):** sample metadata only. Transcriptomic modelling needs the normalised-counts tables.
