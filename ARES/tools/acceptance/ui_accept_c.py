"""Acceptance phase C (NO network): organ popups from real 3D clicks, multiple events, no mixing; PVT timing check."""
import json, os, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[2])
DATA = sys.argv[1]
PORT = 8813
SHOTS = os.environ.get("ARES_SHOTS", "acceptance_screenshots")
OUT = {}
os.makedirs(SHOTS, exist_ok=True)


def dump():
    open(os.path.join(SHOTS, "results_c.json"), "w").write(json.dumps(OUT, indent=1))


def start_backend():
    env = os.environ | {"ARES_DATA_DIR": DATA, "ARES_SHUTDOWN_TOKEN": "t", "OMP_NUM_THREADS": "1"}
    p = subprocess.Popen([sys.executable, "-m", "ares.desktop_backend", "--port", str(PORT), "--parent-pid", str(os.getpid())],
                         cwd=ROOT, env=env, stdout=open(f"{DATA}/backend_stdout.log", "a"), stderr=subprocess.STDOUT)
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


def scan_click(page, want, box, step=9):
    want = [w.lower() for w in want]
    x0, y0, x1, y1 = box
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            page.mouse.move(x, y)
            page.wait_for_timeout(6)
            el = page.query_selector(".holo-tr .hud-box")
            if el and el.inner_text().split(" · ")[0].strip().lower() in want:
                t = el.inner_text()
                page.mouse.click(x, y)
                return {"x": x, "y": y, "hover": t}
    return None


def panel(page, name):
    page.wait_for_selector(f".organ-head h2:has-text('{name}')", timeout=15000)
    page.wait_for_timeout(2500)
    return {"title": page.inner_text(".organ-head h2"), "status": page.inner_text(".organ-status").replace("\n", " | "),
            "nodata": page.inner_text(".nodata") if page.query_selector(".nodata") else None,
            "tabs": page.eval_on_selector_all(".ev-tab", "t => t.map(x => x.innerText.replace(/\\n/g,' | '))"),
            "rows": page.eval_on_selector_all(".osec.A .mc-label", "t => t.map(x => x.innerText)"),
            "protocols": page.eval_on_selector_all(".osec.C .proto b", "t => t.map(x => x.innerText)"),
            "has_history_chart": bool(page.query_selector(".osec.F .js-plotly-plot, .osec.F .plot"))}


def main():
    be = start_backend()
    post("/api/scenario", {"key": "spo2_drop", "astronaut_id": "AST-1"})
    OUT["labs_post"] = post("/api/clinical/AST-1/labs", {"creatinine": 1.9, "bun": 14})["persisted"]
    post("/api/speed", {"minutes_per_second": 30})
    for _ in range(120):
        o = {x["group"]: x["state"] for x in get("/api/organs?astronaut=AST-1")["organs"]}
        if o.get("lungs") == "critical":
            break
        time.sleep(1)
    post("/api/speed", {"minutes_per_second": 1})
    OUT["organ_states"] = {k: v for k, v in o.items() if v not in ("not_monitored",)} | {"kidneys": o.get("kidneys")}
    an = get("/api/anatomy?astronaut=AST-1")["regions"]
    OUT["hologram_region_states"] = {r: an[r]["state"] for r in ("lung_left", "lung_right", "heart", "kidney_left", "kidney_right")}
    dump()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        ctx.add_init_script("try { localStorage.setItem('ares.glow','off'); localStorage.setItem('ares.aid','AST-1'); } catch(e) {}")
        page = ctx.new_page()
        ext, errors = [], []
        page.on("request", lambda r: ext.append(r.url) if not r.url.startswith(f"http://127.0.0.1:{PORT}") and not r.url.startswith(("data:", "blob:")) else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(f"http://127.0.0.1:{PORT}/#/body")
        page.wait_for_selector("canvas")
        page.wait_for_timeout(9000)
        page.click("button:has-text('Internal organs')")
        page.click("button:has-text('Front')")
        page.wait_for_timeout(2500)
        page.screenshot(path=f"{SHOTS}/c_body_organs.png")
        OUT["lung_click"] = scan_click(page, ["left lung", "right lung"], (560, 440, 800, 640), 10)
        dump()
        OUT["lungs"] = panel(page, "Lungs")
        page.screenshot(path=f"{SHOTS}/c_organ_lungs.png")
        dump()
        page.click("button[aria-label='Close']")
        page.wait_for_selector("text=Select an organ")
        page.wait_for_timeout(2500)
        OUT["heart_click"] = scan_click(page, ["heart"], (640, 470, 770, 610), 6)
        dump()
        OUT["heart"] = panel(page, "Heart")
        page.screenshot(path=f"{SHOTS}/c_organ_heart.png")
        dump()
        page.click("button[aria-label='Close']")
        page.wait_for_selector("text=Select an organ")
        OUT["findings_list"] = page.eval_on_selector_all(".finding", "t => t.map(x => x.innerText.replace(/\\s+/g,' '))")
        page.click(".finding:has-text('Kidneys')")
        OUT["kidneys"] = panel(page, "Kidneys")
        page.screenshot(path=f"{SHOTS}/c_organ_kidneys.png")
        dump()
        page.click("button[aria-label='Close']")
        page.wait_for_timeout(2500)
        OUT["brain_click"] = scan_click(page, ["brain"], (640, 280, 760, 420), 8)
        dump()
        if OUT["brain_click"]:
            OUT["brain"] = panel(page, "Brain")
            OUT["brain"]["saved_test_rows"] = len(page.query_selector_all(".osec.F table.tbl tbody tr"))
            page.click(".osec.F summary") if not page.query_selector(".osec.F[open]") else None
            page.wait_for_timeout(1500)
            OUT["brain"]["saved_test_rows"] = len(page.query_selector_all(".osec.F table.tbl tbody tr"))
            page.screenshot(path=f"{SHOTS}/c_organ_brain.png", full_page=True)
            page.click("button[aria-label='Close']")
            page.wait_for_timeout(1500)
        OUT["gut_click"] = scan_click(page, ["stomach", "small intestine", "large intestine", "spleen"], (620, 600, 800, 760), 10)
        if OUT["gut_click"]:
            page.wait_for_selector(".organ-head h2", timeout=15000)
            page.wait_for_timeout(1500)
            OUT["unmonitored"] = {"title": page.inner_text(".organ-head h2"), "nodata": page.inner_text(".nodata") if page.query_selector(".nodata") else None}
            page.screenshot(path=f"{SHOTS}/c_organ_unmonitored.png")
        dump()
        # --- PVT timing accuracy: an in-page responder presses exactly 250 ms after the stimulus class appears
        page.goto(f"http://127.0.0.1:{PORT}/#/alertness")
        page.wait_for_selector("text=Start test")
        page.evaluate("""() => { const st = document.querySelector('.pvt-stage');
          new MutationObserver(() => { if (st.classList.contains('go') && !st.__armed) { st.__armed = true;
            setTimeout(() => { window.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', key: ' ', bubbles: true })); st.__armed = false; }, 250); } })
          .observe(st, { attributes: true, attributeFilter: ['class'] }); }""")
        page.select_option("label.field:has-text('Trial limit') select", "20")
        page.click("text=Start test")
        page.wait_for_selector(".save-line.saved", timeout=150000)
        OUT["timing_test"] = page.inner_text(".save-line")
        tid = page.get_attribute(".save-line a", "href").split("id=")[1]
        d = get(f"/api/tests/{tid}")
        rts = [t["rt_ms"] for t in d["trials"] if t["rt_ms"] is not None]
        OUT["timing_rts"] = {"n": len(rts), "mean": round(sum(rts) / len(rts), 1), "min": min(rts), "max": max(rts), "scored": d["result"]["scored"]}
        OUT["external_requests"] = sorted(set(ext))
        OUT["page_errors"] = errors
        dump()
        b.close()
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/api/system/shutdown", data=b"{}", method="POST",
                                                  headers={"x-ares-shutdown": "t"}), timeout=20)
    be.wait(30)
    OUT["backend_exit"] = be.returncode
    dump()


main()
