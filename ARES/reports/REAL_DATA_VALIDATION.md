# Real-data validation of the ECG chain

Real human recordings from PhysioNet (not astronauts - see Limitations).

## MIT-BIH Arrhythmia Database, record 100 (30.1 min, 360 Hz)

| Metric | Value |
|---|---|
| Reference beats (cardiologist-annotated) | 2,273 |
| Beat-detection sensitivity (150 ms tolerance) | 99.60% |
| Positive predictive value | 100.00% |
| HR mean absolute error per 10 s window | 0.09 bpm (bias -0.0) |
| HR 95th-percentile absolute error | 0.29 bpm |
| RMSSD MAE per 10 s window | 3.13 ms (reference median 26.9 ms) |
| Median signal-quality index | 1.0 |

### Noise robustness (record 100 + added in-band 5-30 Hz noise, overlapping QRS energy)

| SNR (dB) | Median SQI | Windows trusted (SQI >= 0.6) | HR error > 10 bpm, all windows | ... among trusted windows |
|---|---|---|---|---|
| 20 | 1.0 | 100.0% | 0.0% | 0.0% |
| 12 | 1.0 | 100.0% | 0.0% | 0.0% |
| 9 | 1.0 | 100.0% | 0.0% | 0.0% |
| 6 | 0.99 | 100.0% | 0.0% | 0.0% |
| 3 | 0.933 | 100.0% | 0.0% | 0.0% |
| 0 | 0.823 | 96.7% | 10.0% | 10.3% |
| -3 | 0.575 | 26.7% | 56.7% | 25.0% |

Reading this honestly: down to ~3 dB the detector is unaffected. Below that the SQI falls, but not fast enough on its own - at 0 dB some windows it still trusts carry HR errors > 10 bpm. ARES therefore does not rely on the SQI alone: (1) ECG HR is cross-checked against the oximeter pulse rate (> 15 bpm disagreement lowers trust and triggers fallback), and (2) escalation requires the deviation to persist for minutes, which isolated wrong windows do not. Improving the SQI (e.g., multi-lead agreement, template matching against the personal beat) is listed as future work.

## drivedb drivedb/drive02 (83.9 min of real-driving ambulatory ECG)

- Windows compared: 503; trusted by SQI: 99.8%
- ARES HR vs recording device HR: MAE 2.71 bpm (all), 2.7 bpm (trusted); within 5 bpm: 90.0% of trusted windows
- Device HR is itself an estimate (not a gold standard); agreement, not accuracy, is measured.

## Limitations

- One annotated record is a demonstration, not a validation study; the full 48-record MIT-BIH evaluation is the next step (PhysioNet was not reachable from the build environment).
- Neither dataset is from spaceflight; microgravity changes ECG amplitude/axis (fluid shift) and electrode contact behaves differently in weightlessness.
