"""Browser check: real rendering of every AUTOSHORT AI page against the live API."""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8787"
ROUTES = [
    "/",
    "/onboarding",
    "/dashboard",
    "/ideas",
    "/scripts",
    "/video",
    "/queue",
    "/calendar",
    "/publishing",
    "/automation",
    "/voice",
    "/ai",
    "/analytics",
    "/published",
    "/resources",
    "/logs",
    "/settings",
]

failures = []
console_errors = []


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on(
            "console",
            lambda m: console_errors.append(f"{m.type}: {m.text}") if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        page.goto(BASE, wait_until="networkidle", timeout=60000)
        title = page.title()
        print(f"landing title: {title!r}")

        # Local sign-in, as a user would click it.
        btn = page.get_by_role("button", name="Continue on this PC")
        if btn.count() == 0:
            btn = page.get_by_text("Continue on this PC")
        if btn.count() == 0:
            failures.append("local sign-in button not found on landing")
        else:
            btn.first.click()
            page.wait_for_timeout(3000)
            print(f"after login url: {page.url}")
            if page.url.rstrip("/") == BASE:
                failures.append("local sign-in did not leave the landing page")

        # Nothing else is meaningful unless we are actually authenticated.
        page.goto(f"{BASE}/dashboard", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        if page.url.rstrip("/") == BASE:
            failures.append("not authenticated: /dashboard redirected back to landing")
            print(page.inner_text("body")[:300])


        # Every page must be its own screen, not the router fallback. Compare the
        # main content only: the sidebar is shared by every authenticated page.
        # Routes that intentionally redirect (e.g. / and /onboarding -> /dashboard
        # once setup is done) are compared by their final URL instead.
        seen: dict[int, str] = {}
        for route in ROUTES:
            page.goto(f"{BASE}{route}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(700)
            body = page.inner_text("body")
            main = page.inner_text("main") if page.query_selector("main") else body
            root_html = page.eval_on_selector("#root", "el => el.innerHTML.length") if page.query_selector("#root") else 0
            has_content = len(body.strip()) > 40 and root_html > 200
            status = "ok" if has_content else "EMPTY"
            final = page.url.replace(BASE, "").split("?")[0] or "/"
            print(f"[{status}] {route} -> {final} :: {len(body)} chars :: {main.strip()[:60]!r}")
            if not has_content:
                failures.append(f"{route} rendered empty")
                continue
            # A redirect landing on a screen another route owns is fine; two
            # routes rendering different content on their own paths is not.
            if final != route:
                continue
            key = hash(main.strip()[:400])
            if key in seen and route not in ("/", "/onboarding"):
                failures.append(f"{route} renders identical content to {seen[key]}")
            seen[key] = route

        # Verify a couple of live-data screens show real API numbers. A fresh
        # install still needs a niche, so activate one first the way the
        # onboarding wizard does, then confirm the dashboard really renders.
        page.evaluate(
            """async () => {
                const r = await fetch('/api/ai/niches', {credentials: 'include'});
                const niches = (await r.json()).niches || [];
                if (!niches.length) return null;
                await fetch('/api/ai/niches/activate', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({niche_id: niches[0].id}),
                });
                return niches[0].name;
            }"""
        )

        page.goto(f"{BASE}/dashboard", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        dash = page.inner_text("main") if page.query_selector("main") else page.inner_text("body")
        for needle in ("Queue", "Ready"):
            if needle.lower() not in dash.lower():
                failures.append(f"dashboard missing {needle!r}")
        if "/onboarding" in page.url:
            failures.append("dashboard still redirects to onboarding after activating a niche")

        page.goto(f"{BASE}/logs", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        logs_text = page.inner_text("body")
        if len(logs_text.strip()) < 50:
            failures.append("logs page rendered nothing")

        page.screenshot(path="data/tmp/browser_dashboard.png", full_page=False)
        browser.close()

    print("\nconsole errors:", len(console_errors))
    for err in console_errors[:12]:
        print("  ", err)

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nAll browser checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
