# scraper/scrape_transport_fc.py
import json
import os
import re
import time
from collections import deque
from urllib.parse import urlsplit, parse_qs, urljoin

import requests
from requests.adapters import HTTPAdapter            
from urllib3.util.retry import Retry 
from bs4 import BeautifulSoup as BS
from slugify import slugify

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": os.getenv(
        "CRAWLER_UA",
        "NearestStopsBot/1.0 (contact: gavnuq321@gmail.com)"
    )
}

def _build_session():                                 # NEW
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.8,       # 0.8s, 1.6s, 3.2s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

SESSION = _build_session() 
FC_SUBS = [
    "szz1", "poz2", "poz1", "ktw1", "ktw3", "ktw5",
    "wro1", "wro2", "wro3", "wro4", "wro5",
    "lcj2", "lcj3", "lcj4",
]

# WRO (wspólny rozkład dla 1..4) + WRO5
WRO_COMMON = {"wro1", "wro2", "wro3", "wro4"}
WRO_COMMON_ROZKLADY = "https://wro.transport-fc.eu/rozklady-jazdy/"
WRO5_ROZKLADY = "https://wro5.transport-fc.eu/rozklady-jazdy/"

# LCJ: семена для обхода
LCJ_SEEDS = {
    "lcj2": [
        "https://lcj2.transport-fc.eu/",
        "https://lcj2.transport-fc.eu/trasy/",
        "https://lcj2.transport-fc.eu/rozklady-jazdy/",
    ],
    "lcj3": [
        "https://lcj3.transport-fc.eu/",
        "https://lcj3.transport-fc.eu/trasy/",
        "https://lcj3.transport-fc.eu/rozklady-jazdy/",
    ],
    "lcj4": [
        "https://lcj4.transport-fc.eu/",
        "https://lcj4.transport-fc.eu/trasy/",
        "https://lcj4.transport-fc.eu/rozklady-jazdy/",
    ],
}

DATA_DIR = "data"
DATA_PATH = os.path.join(DATA_DIR, "stops.json")
CHANGES_PATH = os.path.join(DATA_DIR, "changes.json")

# Если нужно клонировать общий WRO → WRO1..WRO4 в JSON (без повторного скрапа)
DUPLICATE_WRO_BY_FC = False

REQUEST_DELAY_SEC = float(os.getenv("REQUEST_DELAY_SEC", "0.7"))  # NEW
MAX_PAGES_PER_HOST = 300
MAX_DEPTH = 2 

# ──────────────────────────────────────────────────────────────────────────────
# OSM helpers
# ──────────────────────────────────────────────────────────────────────────────

# fragment вида "#map=19/<lat>/<lon>"
OSM_MAP_FRAG = re.compile(r'(?:^|&)map=\d+/([+-]?[0-9.]+)/([+-]?[0-9.]+)(?:&|$)')

def extract_latlon(href: str):
    """Вернёт (lat, lon) из OSM-ссылки: поддерживает mlat/mlon и #map=Z/lat/lon."""
    s = href.strip()
    s = re.sub(r'\s+', '', s)
    parts = urlsplit(s)

    # 1) mlat/mlon в query
    if parts.query:
        qs = parse_qs(parts.query)
        mlat = qs.get('mlat', [None])[0]
        mlon = qs.get('mlon', [None])[0]
        if mlat and mlon:
            try:
                return float(str(mlat).replace(',', '.')), float(str(mlon).replace(',', '.'))
            except ValueError:
                pass

    # 2) #map=Z/lat/lon в fragment
    if parts.fragment:
        m = OSM_MAP_FRAG.search(parts.fragment)
        if m:
            try:
                return float(m.group(1)), float(m.group(2))
            except ValueError:
                pass
    return None

# ──────────────────────────────────────────────────────────────────────────────
# HTTP / parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

def get(url: str) -> requests.Response:               # UPDATED
    r = SESSION.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r

def _links(html: str, base_url: str, host: str, content_only: bool = False):
    soup = BS(html, "html.parser")
    scope = soup.select_one(".entry-content") if content_only else soup
    scope = scope or soup
    out = []
    for a in scope.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith("http") and urlsplit(href).netloc.endswith(host):
            out.append({"title": a.get_text(strip=True), "url": href})
    # дедуп
    return list({x["url"]: x for x in out}.values())

def _page_has_osm(html: str) -> bool:
    return "openstreetmap.org" in html

def _bfs_collect(host_base: str, seeds: list[str]) -> list[dict]:
    """
    Ограниченный обход по своему хосту с семян: до MAX_DEPTH, с отсечением
    страниц без openstreetmap.org (по содержимому).
    """
    host = urlsplit(host_base).netloc
    seen = set()
    queue = deque([(u, 0) for u in seeds])
    kept = []

    while queue and len(seen) < MAX_PAGES_PER_HOST:
        url, depth = queue.popleft()
        u = url.rstrip("/")
        if u in seen:
            continue
        seen.add(u)
        try:
            resp = get(u)
            html = resp.text
        except Exception as e:
            print(f"[crawl] fail {u}: {e}")
            continue

        # если на странице уже есть OSM — сразу оставляем её как кандидат
        if _page_has_osm(html):
            kept.append({"title": "", "url": u})

        # продолжаем углубление
        if depth < MAX_DEPTH:
            for link in _links(html, u, host, content_only=False):
                v = link["url"].rstrip("/")
                if v in seen:
                    continue
                # Отрежем явные рубрики/архивы/пагинацию — но разрешим городские/трассы/посты
                if any(seg in v for seg in ["/category/", "/kategoria/", "/tag/", "/page/"]):
                    continue
                queue.append((v, depth + 1))

        time.sleep(0.15)

    # дедуп кандидатов
    return list({x["url"]: x for x in kept}.values())

def find_route_pages(fc_sub: str) -> list[dict]:
    """
    Возвращает страницы маршрутов (кандидаты) для данного FC.
    Для LCJ используем ограниченный обход с seeds (root, /trasy/, /rozklady-jazdy/).
    Для WRO1..4 — один общий список (rozklady).
    Для WRO5 — rozklady.
    Остальные — root (с отбором по наличию OSM).
    """
    fc = fc_sub.lower()

    # Общий WRO (1..4)
    if fc in WRO_COMMON:
        try:
            html = get(WRO_COMMON_ROZKLADY).text
            host = urlsplit(WRO_COMMON_ROZKLADY).netloc
            links = _links(html, WRO_COMMON_ROZKLADY, host, content_only=True)
            # фильтр
            filtered = []
            base = WRO_COMMON_ROZKLADY.rstrip("/")
            for x in links:
                u = x["url"].rstrip("/")
                if u == base:
                    continue
                if any(seg in u for seg in ["/category/", "/kategoria/", "/tag/", "/page/"]):
                    continue
                x["_wro_common"] = True
                filtered.append(x)
            print(f"[WRO 1/2/3/4] kept {len(filtered)}")
            return filtered
        except Exception as e:
            print(f"[WRO common] error: {e}")
            return []

    # WRO5
    if fc == "wro5":
        try:
            html = get(WRO5_ROZKLADY).text
            host = urlsplit(WRO5_ROZKLADY).netloc
            links = _links(html, WRO5_ROZKLADY, host, content_only=True)
            filtered = []
            for x in links:
                u = x["url"].rstrip("/")
                if any(seg in u for seg in ["/category/", "/kategoria/", "/tag/", "/page/"]):
                    continue
                filtered.append(x)
            print(f"[WRO5] kept {len(filtered)}")
            return filtered
        except Exception as e:
            print(f"[WRO5] error: {e}")
            return []

    # LCJ2/3/4 — BFS по своим seed-страницам
    if fc in LCJ_SEEDS:
        seeds = LCJ_SEEDS[fc]
        print(f"[{fc.upper()}] crawl seeds: {', '.join(seeds)}")
        pages = _bfs_collect(seeds[0], seeds)
        print(f"[{fc.upper()}] candidates with OSM: {len(pages)}")
        return pages

    # Остальные — корень; возьмём только те, где реально есть OSM
    root = f"https://{fc}.transport-fc.eu/"
    try:
        html = get(root).text
        host = urlsplit(root).netloc
        links = _links(html, root, host, content_only=False)
        kept = []
        for x in links:
            try:
                h2 = get(x["url"]).text
                if _page_has_osm(h2):
                    kept.append(x)
            except Exception:
                pass
            time.sleep(0.1)
        print(f"[{fc.upper()}] kept {len(kept)}")
        return kept
    except Exception as e:
        print(f"[{fc.upper()}] root error: {e}")
        return []

def parse_route_page_with_flag(url: str, fc_sub: str, is_wro_common: bool = False) -> dict | None:
    html = get(url).text
    soup = BS(html, "html.parser")
    stop_rows = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "openstreetmap.org" not in href:
            continue
        latlon = extract_latlon(href)
        if not latlon:
            continue
        lat, lon = latlon
        name = a.get_text(strip=True)
        # Времена HH:MM рядом
        times = []
        parent = a.find_parent(["tr", "li", "p", "div"]) or soup
        for t in re.findall(r"\b\d{1,2}:\d{2}\b", parent.get_text(" ")):
            times.append(t)
        stop_rows.append({
            "stop_name": name,
            "lat": lat,
            "lon": lon,
            "url": href,
            "context_times": sorted(set(times)),
        })

    if not stop_rows:
        print(f"  [warn] no OSM stops on: {url}")
        return None

    title = soup.find(["h1", "h2"]) or url
    route_title = title.get_text(strip=True) if hasattr(title, "get_text") else str(title)
    fc_label = "WRO" if is_wro_common else fc_sub.upper()
    slug_prefix = "wro" if is_wro_common else fc_sub
    print(f"  [+] {fc_label}: {route_title} → {len(stop_rows)} stops")
    return {
        "fc": fc_label,
        "route": route_title,
        "route_slug": slugify(f"{slug_prefix}-{route_title}"),
        "source": url,
        "stops": stop_rows,
    }

def scrape_all() -> list[dict]:
    routes = []
    seen_wro_common = False

    for sub in FC_SUBS:
        # если общий WRO уже собран — пропускаем дубликаты wro1..wro4
        if seen_wro_common and sub.lower() in WRO_COMMON:
            print(f"[skip] duplicate WRO alias: {sub}")
            continue

        pages = find_route_pages(sub)
        for p in pages:
            try:
                data = parse_route_page_with_flag(p["url"], sub, is_wro_common=p.get("_wro_common", False))
                if data:
                    routes.append(data)
                    if p.get("_wro_common"):
                        seen_wro_common = True
            except Exception as e:
                print("! Error on", p["url"], e)
            time.sleep(REQUEST_DELAY_SEC)

    print(f"[done] routes collected: {len(routes)}")
    return routes

# ──────────────────────────────────────────────────────────────────────────────
# Diff & export
# ──────────────────────────────────────────────────────────────────────────────

def load_prev_stops(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            j = json.load(f)
            return j.get("stops") if isinstance(j, dict) else None
    except Exception:
        return None

def make_stop_key(s: dict) -> tuple:
    return (
        s.get("fc"),
        s.get("route_slug"),
        s.get("stop_name"),
        round(float(s.get("lat", 0.0)), 6),
        round(float(s.get("lon", 0.0)), 6),
    )

def make_route_key(r: dict) -> tuple:
    return (r.get("fc"), r.get("route_slug"))

def dedupe_stops(stops_list: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for s in stops_list:
        key = make_stop_key(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out

def duplicate_wro_if_needed(stops_list: list[dict]) -> list[dict]:
    if not DUPLICATE_WRO_BY_FC:
        return stops_list
    cloned = []
    for s in stops_list:
        if s.get("fc") == "WRO":
            for fc in ("WRO1", "WRO2", "WRO3", "WRO4"):
                ss = dict(s)
                ss["fc"] = fc
                ss["route_slug"] = slugify(f"{fc.lower()}-{s['route']}")
                cloned.append(ss)
        else:
            cloned.append(s)
    return cloned

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)

    prev_wrapper = None
    if os.path.exists(DATA_PATH):                      # NEW: сохраним «как было», на случай фейла
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                prev_wrapper = json.load(f)
        except Exception:
            prev_wrapper = None

    prev = None
    if prev_wrapper and isinstance(prev_wrapper, dict):
        prev = prev_wrapper.get("stops")

    try:
        routes = scrape_all()
    except Exception as e:                             # NEW: не валим пайплайн
        print("[fatal] scrape_all failed:", e)
        routes = []

    all_stops = []
    for r in routes:
        for s in r["stops"]:
            all_stops.append({
                "fc": r["fc"],
                "route": r["route"],
                "route_slug": r["route_slug"],
                "source": r["source"],
                **s,
            })

    # дедуп
    all_stops = dedupe_stops(all_stops)
    all_stops = duplicate_wro_if_needed(all_stops)

    # ── Детерминированная сортировка для красивых Git-диффов ─────────────── NEW
    def _sort_key(s):
        return (
            s.get("fc", ""),
            s.get("route_slug", ""),
            s.get("stop_name", ""),
            round(float(s.get("lat", 0.0)), 6),
            round(float(s.get("lon", 0.0)), 6),
        )
    all_stops.sort(key=_sort_key)

    # Если мы ничего не собрали (сайт лёг/бан), НЕ перезаписываем прошлую версию
    if not all_stops:
        print("[warn] no stops collected; keep previous data.json as-is")
        if prev_wrapper:
            # обновим только changes.json, чтобы workflow не падал
            with open(CHANGES_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "generated": time.time(),
                    "routes_total_new": len({make_route_key({"fc": s["fc"], "route_slug": s["route_slug"]}) for s in prev}) if prev else 0,
                    "stops_total_new": len(prev) if prev else 0,
                    "new_routes": [], "removed_routes": [], "new_stops": [], "removed_stops": []
                }, f, ensure_ascii=False, indent=2)
            print(f"Diff report saved to {CHANGES_PATH}")
        raise SystemExit(0)

    # Пишем новую версию
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"generated": time.time(), "stops": all_stops}, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_stops)} stops to {DATA_PATH}")

    changes = {
        "generated": time.time(),
        "routes_total_new": len({make_route_key({"fc": s["fc"], "route_slug": s["route_slug"]}) for s in all_stops}),
        "stops_total_new": len(all_stops),
        "new_routes": [], "removed_routes": [], "new_stops": [], "removed_stops": [],
    }

    if prev is not None:
        prev_stop_keys = {make_stop_key(s) for s in prev}
        new_stop_keys  = {make_stop_key(s) for s in all_stops}

        added_stop_keys   = new_stop_keys - prev_stop_keys
        removed_stop_keys = prev_stop_keys - new_stop_keys

        prev_route_keys = {make_route_key({"fc": s["fc"], "route_slug": s["route_slug"]}) for s in prev}
        new_route_keys  = {make_route_key({"fc": s["fc"], "route_slug": s["route_slug"]}) for s in all_stops}

        added_route_keys   = new_route_keys - prev_route_keys
        removed_route_keys = prev_route_keys - new_route_keys

        def find_by_stop_key(pool, key):
            for s in pool:
                if make_stop_key(s) == key:
                    return {
                        "fc": s["fc"],
                        "route": s["route"],
                        "route_slug": s["route_slug"],
                        "stop_name": s["stop_name"],
                        "lat": s["lat"],
                        "lon": s["lon"],
                        "source": s.get("source"),
                        "url": s.get("url"),
                    }
            return None

        def label_route_key(key):
            fc, route_slug = key
            return {"fc": fc, "route_slug": route_slug}

        changes["new_routes"]     = [label_route_key(k) for k in sorted(added_route_keys)]
        changes["removed_routes"] = [label_route_key(k) for k in sorted(removed_route_keys)]
        changes["new_stops"]      = [find_by_stop_key(all_stops, k) for k in sorted(added_stop_keys)]
        changes["removed_stops"]  = [find_by_stop_key(prev, k) for k in sorted(removed_stop_keys)]

        print("\n=== DIFF vs previous stops.json ===")
        print(f"+ new routes: {len(changes['new_routes'])}")
        print(f"- removed routes: {len(changes['removed_routes'])}")
        print(f"+ new stops: {len(changes['new_stops'])}")
        print(f"- removed stops: {len(changes['removed_stops'])}")

    with open(CHANGES_PATH, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)
    print(f"Diff report saved to {CHANGES_PATH}")