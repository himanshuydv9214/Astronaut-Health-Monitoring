"""Offline check: open every ARES page with ALL non-local network requests blocked (Playwright + Chrome).

    python -m ares.api.server            # in one terminal
    python scripts/offline_check.py      # in another; needs: pip install playwright && playwright install chromium
"""
import asyncio, json, urllib.request
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"])
        ctx = await b.new_context(viewport={"width":1500,"height":900})
        external, failed = [], []
        async def guard(route):
            u = route.request.url
            if u.startswith("http://127.0.0.1:8000") or u.startswith("ws://127.0.0.1:8000") or u.startswith("data:") or u.startswith("blob:"):
                await route.continue_()
            else:
                external.append(u); await route.abort()
        await ctx.route("**/*", guard)
        pg = await ctx.new_page()
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("requestfailed", lambda r: failed.append(r.url) if "127.0.0.1" in r.url else None)
        checks = {}
        for name, sel in [("overview",".crew-card"),("crew",".tbl"),("body","canvas"),("insights",".js-plotly-plot"),("emergency",".panel"),("alertness",".pvt-stage"),("sim",".scen"),("system",".tbl")]:
            await pg.goto(f"http://127.0.0.1:8000/#/{name}"); await pg.wait_for_timeout(4500)
            checks[name] = await pg.locator(sel).count() > 0
        # backend functions offline: ML inference + KB retrieval + DB
        st = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/system/status").read())
        kb = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/medical-guidance/search?q=oxygen").read())
        print("pages rendered:", checks)
        print("external requests attempted:", external)
        print("local failures:", failed[:5])
        print("ML local:", st["local_inference"]["anomaly_model"], st["local_inference"]["risk_forecaster"], "| KB hits:", len(kb["protocols"]), "| DB:", list(st["storage"]["integrity"].keys()) if isinstance(st["storage"]["integrity"], dict) else st["storage"])
        print("page errors:", errs)
        await b.close()
asyncio.run(main())
