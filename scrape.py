"""Lee las páginas de noticias de sources.json y guarda los titulares en news.json."""
import json, re, datetime, concurrent.futures as cf
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DelunNewsBot/1.0)"}
PER_SITE = 5
SKIP = re.compile(r"^(read more|more|view all|see all|home|news|contact|login|search|privacy|cookie|leer más|ver más)", re.I)

def headlines(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["nav", "footer", "header", "script", "style", "aside"]):
        t.decompose()
    seen, out = set(), []
    # primero titulares dentro de h1-h4, luego cualquier enlace "largo"
    cands = [a for h in soup.find_all(["h1", "h2", "h3", "h4"]) for a in ([h] if h.name == "a" else h.find_all("a"))]
    cands += soup.find_all("a", href=True)
    for a in cands:
        href, text = a.get("href"), " ".join(a.get_text(" ").split())
        if not href or href.startswith(("#", "mailto:", "javascript:")): continue
        if not 25 <= len(text) <= 250 or SKIP.match(text) or text in seen: continue
        link = urljoin(url, href)
        if urlparse(link).netloc.split(".")[-2:] != urlparse(url).netloc.split(".")[-2:]: continue
        seen.add(text); out.append({"title": text, "url": link})
        if len(out) >= PER_SITE: break
    return out

def tr(text, lang, target):
    if lang == target: return text
    try: return GoogleTranslator(source="auto", target=target).translate(text)
    except Exception: return text

def process(src):
    for url in src["urls"]:
        try:
            items = headlines(url)
        except Exception:
            continue
        if items:
            for it in items:
                try: lang = detect(it["title"])
                except Exception: lang = "en"
                it.update(lang=lang, en=tr(it["title"], lang, "en"), es=tr(it["title"], lang, "es"))
            return {"institution": src["institution"], "jurisdiction": src["jurisdiction"], "source": url, "items": items}
    return {"institution": src["institution"], "jurisdiction": src["jurisdiction"], "source": src["urls"][0], "items": []}

if __name__ == "__main__":
    sources = json.load(open("sources.json", encoding="utf-8"))
    with cf.ThreadPoolExecutor(8) as ex:
        res = [r for r in ex.map(process, sources) if r]
    json.dump({"updated": datetime.datetime.utcnow().isoformat() + "Z", "sources": res},
              open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{sum(1 for r in res if r['items'])}/{len(sources)} fuentes con titulares")
