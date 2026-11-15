# UI acceptance tests (optional)

Browser-driven checks of the v0.5 features against the real backend, used to verify this release. They need Playwright
(`pip install playwright && python -m playwright install chromium`), which is NOT an ARES dependency.

Run in order on one data folder (`DATA`), ideally with the network off:

    python tools/acceptance/ui_accept_a.py DATA   # PVT through the UI: completed, stopped, terminated, then a crash mid-test
    python tools/acceptance/ui_accept_b.py DATA   # reopen: history, details, filters, a 2nd test (1st unchanged)
    python tools/acceptance/ui_accept_c.py DATA   # organ popups by real 3D clicks, multiple events, no mixing, PVT timing

On Linux, `unshare -n python3 tools/netns_offline.py python3 tools/acceptance/ui_accept_c.py DATA` enforces "no network
except loopback". Screenshots and JSON results go to `acceptance_screenshots/` (or `$ARES_SHOTS`).
Note: script A presses keys from Python, so its reaction times include automation lag; script C measures timing with an
in-page responder (exactly 250 ms after each stimulus) - ARES recorded 233-249 ms.
