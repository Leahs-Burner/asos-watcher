#!/usr/bin/env python3
"""ASOS Sample Sale watcher (GitHub Actions version).

Checks asossamplesale.com and, when there are new items, restocks or price
drops, writes alert.md. The workflow then opens a GitHub issue from it, and
GitHub emails the issue to you.
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state", "state.json")
ALERT_PATH = os.path.join(HERE, "alert.md")
TITLE_PATH = os.path.join(HERE, "alert_title.txt")
BASE = "https://www.asossamplesale.com"
UA = "Mozilla/5.0 (personal stock watcher)"
MAX_BODY = 60000  # GitHub issue limit is 65,536 characters


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC] {msg}", flush=True)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2:
                raise
            log(f"retrying {url}: {e}")
            time.sleep(5 * (attempt + 1))


def fetch_catalog(section):
    path = "/products.json" if section in ("", "all") else f"/collections/{section}/products.json"
    products, page = [], 1
    while True:
        batch = fetch_page(f"{BASE}{path}?limit=250&page={page}").get("products", [])
        if not batch:
            break
        products.extend(batch)
        if len(batch) < 250 or page >= 200:
            break
        page += 1
        time.sleep(1)
    return products


def size_matcher(sizes):
    pats = [re.compile(r"(?<![\w])" + re.escape(s.strip()) + r"(?![\w])", re.I) for s in sizes if s.strip()]
    return (lambda t: True) if not pats else (lambda t: any(p.search(t or "") for p in pats))


def keyword_ok(title, keywords, exclude):
    t = (title or "").lower()
    if exclude and any(k.lower() in t for k in exclude):
        return False
    return not keywords or any(k.lower() in t for k in keywords)


def money(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def snapshot(products):
    return {
        str(p["id"]): {
            "title": p.get("title", ""),
            "handle": p.get("handle", ""),
            "image": (p.get("images") or [{}])[0].get("src", "") if p.get("images") else "",
            "variants": {
                str(v["id"]): {"title": v.get("title", ""), "price": money(v.get("price")),
                               "available": bool(v.get("available"))}
                for v in p.get("variants", [])
            },
        }
        for p in products
    }


def slim(snap):
    """What we keep between runs: just stock and price per size."""
    return {pid: {vid: [v["price"], v["available"]] for vid, v in p["variants"].items()}
            for pid, p in snap.items()}


def diff(old, new, cfg):
    match_size = size_matcher(cfg.get("sizes", []))
    kws, excl = cfg.get("keywords", []), cfg.get("exclude_keywords", [])
    notify = cfg.get("notify", {})
    seen_ever = set(old.get("seen_ever", []))
    old_products = old.get("products", {})
    changes = {"new": [], "restock": [], "price": []}

    for pid, p in new.items():
        if not keyword_ok(p["title"], kws, excl):
            continue
        avail = [v["title"] for v in p["variants"].values() if v["available"] and match_size(v["title"])]
        prev = old_products.get(pid)
        if prev is None:
            if not avail:
                continue
            if pid not in seen_ever:
                if notify.get("new_items", True):
                    changes["new"].append((p, avail, "New"))
            elif notify.get("restocks", True):
                changes["restock"].append((p, avail, "Back on the site"))
            continue

        restocked, drops = [], {}
        for vid, v in p["variants"].items():
            if not match_size(v["title"]):
                continue
            pv = prev.get(vid)  # [price, available]
            if v["available"] and (pv is None or not pv[1]):
                restocked.append(v["title"])
            if pv and v["price"] is not None and pv[0] is not None and v["price"] < pv[0] - 0.001:
                drops.setdefault(f"£{pv[0]:.2f} → £{v['price']:.2f}", []).append(v["title"])
        if restocked and notify.get("restocks", True):
            changes["restock"].append((p, restocked, "Back in stock"))
        if notify.get("price_drops", True):
            for note, sizes in drops.items():
                changes["price"].append((p, sizes, note))
    return changes


def item_md(p, sizes, note):
    url = f"{BASE}/products/{p['handle']}"
    price = next((v["price"] for v in p["variants"].values() if v["price"] is not None), None)
    price_txt = f" · £{price:.2f}" if price is not None and "→" not in note else ""
    img = f'<img src="{p["image"]}" width="80" align="left"> ' if p.get("image") else ""
    size_txt = ", ".join(s.split(" / ")[0] for s in sizes[:15])
    return (f'{img}**[{p["title"]}]({url})**<br>{note}{price_txt}<br>Sizes: {size_txt}'
            f'<br clear="left">\n\n')


def build_alert(changes):
    sections = [("new", "New items"), ("restock", "Back in stock"), ("price", "Price drops")]
    counts = [f"{len(changes[k])} {label.lower()}" for k, label in sections if changes[k]]
    title = "ASOS Sample Sale: " + ", ".join(counts)
    body, more = "", 0
    for key, label in sections:
        if not changes[key]:
            continue
        body += f"### {label} ({len(changes[key])})\n\n"
        for c in changes[key]:
            chunk = item_md(*c)
            if len(body) + len(chunk) > MAX_BODY - 500:
                more += 1
                continue
            body += chunk
    if more:
        body += f"\n…and {more} more. [Open the shop]({BASE}/collections/all)\n"
    return title, body


def main():
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})
    products = fetch_catalog(cfg.get("section", "all"))
    prev_count = len(state.get("products", {}))
    if not products or (prev_count > 100 and len(products) < prev_count * 0.5):
        log(f"suspicious fetch ({len(products)} items vs {prev_count} before), skipping this run")
        return

    snap = snapshot(products)
    seen_ever = sorted(set(state.get("seen_ever", [])) | set(snap))
    first_run = not state.get("products")

    if first_run:
        title = "ASOS watcher is running"
        body = (f"Set up successfully. It found **{len(snap)} items** on the site and saved them as the "
                f"starting point.\n\nFrom now on you'll get an email like this whenever there are new items, "
                f"restocks or price drops. [Open the shop]({BASE}/collections/all)")
        log(f"first run: recorded {len(snap)} items")
    else:
        changes = diff(state, snap, cfg)
        if sum(len(v) for v in changes.values()):
            title, body = build_alert(changes)
            log(title)
        else:
            title = body = None
            log(f"checked {len(snap)} items, no changes")

    # At most one email per day (UK time): later changes that day are not emailed
    today = datetime.now(ZoneInfo("Europe/London")).strftime("%Y-%m-%d")
    last_alert_date = state.get("last_alert_date", "")
    if title and not first_run and last_alert_date == today:
        log(f"already emailed today, skipping: {title}")
        title = body = None
    if title and not first_run:
        last_alert_date = today

    if title:
        with open(ALERT_PATH, "w") as f:
            f.write(body)
        with open(TITLE_PATH, "w") as f:
            f.write(title)

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump({"products": slim(snap), "seen_ever": seen_ever, "last_alert_date": last_alert_date},
                  f, separators=(",", ":"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"error: {e}")
        sys.exit(1)
