# ARES tech stack

| Layer | Technology | Used for |
|---|---|---|
| Language | Python 3.11–3.13 | Backend, ML, data pipelines |
| ML | scikit-learn 1.9 | Isolation Forest, HistGradientBoosting, isotonic calibration, logistic regression, LOF / One-Class SVM baselines |
| Explainability | SHAP (TreeExplainer) | Per-alert feature attributions |
| Data | NumPy, pandas, SciPy, PyArrow (Parquet) | Feature engineering, statistics (Mann-Whitney, effect sizes), datasets |
| Signal processing | NumPy / SciPy, wfdb | ECG R-peak detection, HRV; PhysioNet MIT-BIH validation |
| Personal baselines | Own code (Bayesian Normal-Inverse-Gamma + Kalman trend) | Each astronaut's own normal per activity context |
| API | FastAPI, Uvicorn, Pydantic, WebSockets | REST API, live push to the 3D twin |
| Storage | SQLite (hash-chained, tamper-evident log) | Offline onboard record |
| Charts | Plotly.js (served locally) | Vital-sign, AI and history charts, offline |
| Frontend + 3D hologram | React 18, TypeScript 5.6, Three.js 0.170, React Three Fiber 8, Drei 9, @react-three/postprocessing (bloom), custom GLSL hologram shader, Vite 6 | Whole interface + interactive anatomy, prebuilt so the laptop needs only Python |
| 3D asset pipeline | trimesh, fast_simplification | BodyParts3D STL to a 46-region GLB |
| Reports | Matplotlib | Evaluation figures |
| Testing | pytest, httpx, Playwright (headless Chrome) | 36 automated tests, UI screenshots |
| Packaging | Docker (optional) | One-command deployment |
| Data sources | NASA OSDR (GeneLab, ALSDA), RadLab, NASA JSC SRAG SEP list, NASA DONKI, PhysioNet, BodyParts3D | See reports/REAL_NASA_DATA.md |
