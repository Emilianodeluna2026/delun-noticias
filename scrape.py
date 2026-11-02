"""Lee las páginas de noticias de sources.json y guarda los titulares en news.json.
Orden de intentos por fuente: 1) feed RSS/Atom  2) enlaces del HTML  3) navegador real (Playwright)."""
import json, re, datetime, sys, concurrent.futures as cf
from urllib.parse import urljoin, urlparse
import requests, feedparser, urllib3
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect

urllib3.disable_warnings()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
PER_SITE = 5
SKIP = re.compile(r"^(read more|more|view all|see all|home|news|contact|login|search|privacy|cookie|leer más|ver más|skip to)", re.I)

def site(u): return ".".join(urlparse(u).netloc.split(".")[-2:])

def get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except requests.exceptions.SSLError:
        r = requests.get(url, headers=HEADERS, timeout=25, verify=False)
    r.raise_for_status()
    return r

def from_feed(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for l in soup.find_all("link", href=True):
        if "alternate" in (l.get("rel") or []) and any(k in (l.get("type") or "") for k in ("rss", "atom")):
            try:
                f = feedparser.parse(get(urljoin(url, l["href"])).content)
            except Exception:
                continue
            items = [{"title": " ".join(e.title.split()), "url": e.link} for e in f.entries
                     if getattr(e, "title", "") and getattr(e, "link", "")]
            if items: return items[:PER_SITE]
    return []

def from_html(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["nav", "footer", "script", "style"]):
        t.decompose()
    cands = [a for h in soup.find_all(["h1", "h2", "h3", "h4", "h5"]) for a in ([h] if h.name == "a" else h.find_all("a"))]
    cands += soup.find_all("a", href=True)
    seen, out = set(), []
    for a in cands:
        href, text = a.get("href"), " ".join(a.get_text(" ").split())
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")): continue
        if not 20 <= len(text) <= 250 or SKIP.match(text) or text in seen: continue
        link = urljoin(url, href)
        if site(link) != site(url) or link.rstrip("/") == url.rstrip("/"): continue
        seen.add(text); out.append({"title": text, "url": link})
        if len(out) >= PER_SITE: break
    return out

def extract(html, url):
    return from_feed(html, url) or from_html(html, url)

def stage1(src):
    err = ""
    for url in src["urls"]:
        try:
            items = extract(get(url).text, url)
            if items: return src, url, items, ""
            err = "sin titulares en el HTML"
        except Exception as e:
            err = type(e).__name__ + " " + str(e)[:80]
    return src, src["urls"][0], [], err

def browser_fallback(failed):
    """Segundo intento con un Chrome real para las webs que cargan con JavaScript o bloquean bots."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {}
    got = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=HEADERS["User-Agent"], ignore_https_errors=True)
        for src in failed:
            for url in src["urls"]:
                try:
                    pg = ctx.new_page()
                    pg.goto(url, wait_until="domcontentloaded", timeout=40000)
                    pg.wait_for_timeout(4000)
                    items = extract(pg.content(), url)
                    pg.close()
                    if items:
                        got[src["institution"] + url] = (url, items); break
                except Exception:
                    try: pg.close()
                    except Exception: pass
        b.close()
    return got

def tr(text, lang, target):
    if lang == target: return text
    try: return GoogleTranslator(source="auto", target=target).translate(text)
    except Exception: return text

def translate(item):
    try: lang = detect(item["title"])
    except Exception: lang = "en"
    item.update(lang=lang, en=tr(item["title"], lang, "en"), es=tr(item["title"], lang, "es"))

if __name__ == "__main__":
    sources = json.load(open("sources.json", encoding="utf-8"))
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(stage1, sources))
    failed = [r[0] for r in res if not r[2]]
    print(f"Paso 1: {len(res) - len(failed)}/{len(sources)} fuentes", flush=True)
    got = browser_fallback(failed) if failed else {}
    final = []
    for src, url, items, err in res:
        if not items:
            for u in src["urls"]:
                if src["institution"] + u in got: url, items = got[src["institution"] + u]; err = ""; break
        final.append({"institution": src["institution"], "jurisdiction": src["jurisdiction"],
                      "source": url, "items": items, "error": err})
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(translate, [i for f in final for i in f["items"]]))
    json.dump({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(), "sources": final},
              open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(1 for f in final if f["items"])
    print(f"{ok}/{len(sources)} fuentes con titulares")
    for f in final:
        if not f["items"]: print("FALLA:", f["institution"], "|", f["source"], "|", f["error"])
