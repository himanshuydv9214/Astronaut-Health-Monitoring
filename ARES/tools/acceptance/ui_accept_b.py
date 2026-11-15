"""Acceptance phase B (NO network): reopen ARES on the same data, check history, run another test, organ popups."""
import json, os, random, socket, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[2])
DATA = sys.argv[1]
PORT = 8812
SHOTS = os.environ.get("ARES_SHOTS", "acceptance_screenshots")
OUT = {}
os.makedirs(SHOTS, exist_ok=True)


def start_backend():
    env = os.environ | {"ARES_DATA_DIR": DATA, "ARES_SHUTDOWN_TOKEN": "t", "OMP_NUM_THREADS": "1"}
    p = subprocess.Popen([sys.executable, "-m", "ares.desktop_backend", "--port", str(PORT)], cwd=ROOT, env=env,
                         stdout=open(f"{DATA}/backend_stdout.log", "a"), stderr=subprocess.STDOUT)
    for _ in range(240):
        try:
            if json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/system/health", timeout=2).read())["ready"]:
                return p
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("backend not ready")


def get(path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=20).read())


def post(path, body):
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())


def respond_loop(page, n, rng):
    for _ in range(n):
        page.wait_for_selector(".pvt-stage.go", timeout=15000)
        time.sleep(rng.uniform(0.21, 0.31))
        page.keyboard.press("Space")
        page.wait_for_function("!document.querySelector('.pvt-stage').classList.contains('go')", timeout=5000)


def scan_click(page, want, box):
    """Hover over the hologram until the HUD names the wanted structure, then click it (a real 3D mesh pick)."""
    x0, y0, x1, y1 = box
    want = [w.lower() for w in want]
    for step in (22, 11):
        for y in range(y0, y1, step):
            for x in range(x0, x1, step):
                page.mouse.move(x, y)
                page.wait_for_timeout(8)
                el = page.query_selector(".holo-tr .hud-box")
                if el:
                    t = el.inner_text()
                    if t.split(" · ")[0].strip().lower() in want:
                        page.mouse.click(x, y)
                        return {"x": x, "y": y, "hover": t}
    return None


def dump():
    open(os.path.join(SHOTS, "results_b.json"), "w").write(json.dumps(OUT, indent=1))


def main():
    be = start_backend()
    h = get("/api/system/health")
    OUT["restart_health"] = {"previous_session_unclean": h["previous_session_unclean"], "tests": h["tests"]}
    dump()
    first = [t for t in get("/api/tests?astronaut=AST-1&test_type=pvt&status=completed")["tests"]][-1]
    first_detail = get(f"/api/tests/{first['test_id']}")
    rng = random.Random(11)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        ctx.add_init_script("Math.random = () => 0; try { localStorage.setItem('ares.glow','off'); localStorage.setItem('ares.aid','AST-1'); } catch(e) {}")
        page = ctx.new_page()
        ext = []
        page.on("request", lambda r: ext.append(r.url) if not r.url.startswith(f"http://127.0.0.1:{PORT}") and not r.url.startswith(("data:", "blob:")) else None)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        # ---- Test History after reopening
        page.goto(f"http://127.0.0.1:{PORT}/#/tests")
        page.wait_for_selector("text=Test History")
        page.wait_for_selector("table.tbl tbody tr td >> nth=1")
        page.wait_for_timeout(1500)
        OUT["history_rows"] = page.eval_on_selector_all("table.tbl tbody tr", "rs => rs.map(r => r.innerText.replace(/\\s+/g,' ').slice(0,140))")
        dump()
        page.screenshot(path=f"{SHOTS}/history_after_restart.png")
        page.goto(f"http://127.0.0.1:{PORT}/#/tests?id={first['test_id']}")
        page.wait_for_selector("text=Individual trials")
        page.wait_for_timeout(1500)
        OUT["detail_trials_heading"] = page.inner_text("h4:has-text('Individual trials')")
        dump()
        page.screenshot(path=f"{SHOTS}/history_detail.png", full_page=True)
        # filters
        page.select_option("label.field:has-text('Status') select", "interrupted")
        page.wait_for_timeout(5000)
        OUT["filter_interrupted_rows"] = page.eval_on_selector_all("table.tbl tbody tr", "rs => rs.map(r => r.innerText.replace(/\\s+/g,' ').slice(0,100))")
        dump()
        # ---- another completed test (glow off)
        page.goto(f"http://127.0.0.1:{PORT}/#/alertness")
        page.wait_for_selector("text=Start test")
        page.select_option("label.field:has-text('Trial limit') select", "20")
        page.click("text=Start test")
        respond_loop(page, 20, rng)
        page.wait_for_selector(".save-line.saved", timeout=20000)
        OUT["second_test_saveline"] = page.inner_text(".save-line")
        dump()
        page.wait_for_timeout(1200)
        page.screenshot(path=f"{SHOTS}/pvt_second.png", full_page=True)
        after = get(f"/api/tests/{first['test_id']}")
        OUT["first_test_unchanged"] = (after["trials"] == first_detail["trials"] and after["result"]["metrics"] == first_detail["result"]["metrics"])
        dump()
        pv = get("/api/tests?astronaut=AST-1&test_type=pvt")["tests"]
        OUT["pvt_tests_now"] = [(t["status"], t["trials"], t["summary"]) for t in pv]
        dump()
        OUT["duplicates"] = len(pv) != len({t["test_id"] for t in pv})
        dump()
        # ---- health events: respiratory (AST-1) + kidney lab marker (AST-1)
        post("/api/scenario", {"key": "spo2_drop", "astronaut_id": "AST-1"})
        post("/api/speed", {"minutes_per_second": 30})
        post("/api/clinical/AST-1/labs", {"creatinine": 1.9, "bun": 14})
        for _ in range(120):
            o = {x["group"]: x["state"] for x in get("/api/organs?astronaut=AST-1")["organs"]}
            if o.get("lungs") == "critical":
                break
            time.sleep(1)
        post("/api/speed", {"minutes_per_second": 1})
        OUT["organ_states"] = o
        dump()
        page.goto(f"http://127.0.0.1:{PORT}/#/body")
        page.wait_for_selector("canvas")
        page.wait_for_timeout(9000)
        page.click("button:has-text('Front')")
        page.wait_for_timeout(2500)
        page.screenshot(path=f"{SHOTS}/body_alerts.png")
        cv = page.query_selector(".holo-stage canvas").bounding_box()
        box = (int(cv["x"] + cv["width"] * 0.30), int(cv["y"] + cv["height"] * 0.12),
               int(cv["x"] + cv["width"] * 0.70), int(cv["y"] + cv["height"] * 0.62))
        OUT["lung_click"] = scan_click(page, ["left lung", "right lung"], box)
        dump()
        page.wait_for_selector(".organ-head h2", timeout=15000)
        page.wait_for_timeout(2500)
        OUT["lung_panel"] = {"title": page.inner_text(".organ-head h2"), "status": page.inner_text(".organ-status"),
                             "tabs": page.eval_on_selector_all(".ev-tab", "t => t.map(x => x.innerText)"),
                             "table": page.eval_on_selector_all(".osec.A .mtable tbody tr", "t => t.map(x => x.innerText.replace(/\\s+/g,' '))")}
        page.screenshot(path=f"{SHOTS}/organ_lungs.png")
        api_lungs = get("/api/organs/lung_left?astronaut=AST-1")
        OUT["lung_api_events"] = [(e["event_id"], e["title"], e["severity"]) for e in api_lungs["events"]]
        dump()
        page.click("button[aria-label='Close']")
        page.wait_for_selector("text=Select an organ")
        page.wait_for_timeout(2500)
        OUT["heart_click"] = scan_click(page, ["heart"], box)
        dump()
        page.wait_for_selector(".organ-head h2:has-text('Heart')", timeout=15000)
        page.wait_for_timeout(2500)
        OUT["heart_panel"] = {"title": page.inner_text(".organ-head h2"), "status": page.inner_text(".organ-status"),
                              "tabs": page.eval_on_selector_all(".ev-tab", "t => t.map(x => x.innerText)"),
                              "table": page.eval_on_selector_all(".osec.A .mtable tbody tr", "t => t.map(x => x.innerText.replace(/\\s+/g,' '))")}
        page.screenshot(path=f"{SHOTS}/organ_heart.png")
        page.click("button[aria-label='Close']")
        page.wait_for_selector("text=Select an organ")
        OUT["findings_list"] = page.eval_on_selector_all(".finding", "t => t.map(x => x.innerText.replace(/\\s+/g,' '))")
        dump()
        page.click(".finding:has-text('Kidneys')")
        page.wait_for_selector(".organ-head h2:has-text('Kidneys')", timeout=15000)
        page.wait_for_timeout(2000)
        OUT["kidney_panel"] = {"tabs": page.eval_on_selector_all(".ev-tab", "t => t.map(x => x.innerText)"),
                               "table": page.eval_on_selector_all(".osec.A .mtable tbody tr", "t => t.map(x => x.innerText.replace(/\\s+/g,' '))")}
        page.click("button[aria-label='Close']")
        page.wait_for_timeout(1500)
        OUT["brain_click"] = scan_click(page, ["brain"], (box[0], int(cv["y"] + 4), box[2], int(cv["y"] + cv["height"] * 0.25)))
        dump()
        page.wait_for_selector(".organ-head h2:has-text('Brain')", timeout=15000)
        page.wait_for_timeout(3000)
        page.screenshot(path=f"{SHOTS}/organ_brain.png")
        OUT["brain_tests_rows"] = len(page.query_selector_all(".organ table.tbl tbody tr"))
        dump()
        page.click("button[aria-label='Close']")
        page.wait_for_timeout(800)
        OUT["stomach_click"] = scan_click(page, ["stomach", "small intestine", "large intestine", "spleen"], box)
        dump()
        if OUT["stomach_click"]:
            page.wait_for_selector(".organ-head h2", timeout=15000)
            page.wait_for_timeout(1500)
            OUT["unmonitored_panel"] = {"title": page.inner_text(".organ-head h2"),
                                        "nodata": (page.query_selector(".nodata").inner_text() if page.query_selector(".nodata") else None)}
            page.screenshot(path=f"{SHOTS}/organ_unmonitored.png")
        OUT["external_requests"] = sorted(set(ext))
        dump()
        OUT["page_errors"] = errors
        dump()
        b.close()
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/api/system/shutdown", data=b"{}", method="POST",
                                                  headers={"x-ares-shutdown": "t"}), timeout=20)
    be.wait(30)
    OUT["backend_exit"] = be.returncode
    dump()
    print(json.dumps(OUT, indent=1))


main()
