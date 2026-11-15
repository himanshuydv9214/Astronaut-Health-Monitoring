"""Acceptance phase A (run with NO network): perform reaction tests through the real UI, then crash the backend."""
import json, os, random, signal, socket, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[2])
DATA = sys.argv[1]
PORT = 8811
SHOTS = os.environ.get("ARES_SHOTS", "acceptance_screenshots")
os.makedirs(SHOTS, exist_ok=True)
OUT = {}


def internet():
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return True
    except OSError:
        return False


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
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10).read())


def respond_loop(page, n, rng):
    done = 0
    while done < n:
        page.wait_for_selector(".pvt-stage.go", timeout=15000)
        time.sleep(rng.uniform(0.21, 0.31))
        page.keyboard.press("Space")
        done += 1
        page.wait_for_function("!document.querySelector('.pvt-stage').classList.contains('go')", timeout=5000)


def main():
    OUT["internet_reachable"] = internet()
    os.makedirs(DATA, exist_ok=True)
    be = start_backend()
    rng = random.Random(7)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        ctx.add_init_script("Math.random = () => 0;")            # shortest PVT-B interval (2 s) to keep the test quick
        page = ctx.new_page()
        ext = []
        page.on("request", lambda r: ext.append(r.url) if not r.url.startswith(f"http://127.0.0.1:{PORT}") and not r.url.startswith("data:") and not r.url.startswith("blob:") else None)
        page.goto(f"http://127.0.0.1:{PORT}/#/alertness")
        page.wait_for_selector("text=Reaction Time and Alertness Test")
        page.select_option("select >> nth=1", "")  if False else None
        # astronaut selector in the top bar -> AST-1
        page.select_option("header select", "AST-1")
        # --- test 1: completed (20-trial limit)
        page.select_option("label.field:has-text('Trial limit') select", "20")
        page.click("text=Start test")
        respond_loop(page, 20, rng)
        page.wait_for_selector(".save-line.saved", timeout=20000)
        OUT["test1_saveline"] = page.inner_text(".save-line")
        page.screenshot(path=f"{SHOTS}/pvt_completed.png")
        # --- test 2: stopped early after 6 responses
        page.click("text=Start test")
        respond_loop(page, 6, rng)
        page.click("text=Stop & score")
        page.wait_for_selector(".save-line.saved", timeout=20000)
        OUT["test2_saveline"] = page.inner_text(".save-line")
        # --- test 3: terminated with the button after 4 responses
        page.click("text=Start test")
        respond_loop(page, 4, rng)
        page.click("button:has-text('Terminate')")
        page.wait_for_selector(".save-line.saved", timeout=20000)
        OUT["test3_saveline"] = page.inner_text(".save-line")
        page.screenshot(path=f"{SHOTS}/pvt_terminated.png")
        # --- test 4: running when ARES crashes (5 responses, then the backend is killed)
        page.click("text=Start test")
        respond_loop(page, 5, rng)
        time.sleep(1.5)                                          # incremental trial upload
        tests = get("/api/tests?astronaut=AST-1&test_type=pvt")["tests"]
        OUT["before_crash"] = [(t["status"], t["trials"], t["summary"]) for t in tests]
        OUT["external_requests"] = sorted(set(ext))
        be.send_signal(signal.SIGKILL)
        be.wait()
        OUT["backend_killed"] = True
        b.close()
    print(json.dumps(OUT, indent=1))


main()
