"""Recolector diario de noticias de reguladores financieros.

Para cada fuente de sources.json:
  1. Descarga la URL (con reintento y User-Agent de navegador).
  2. Si hay RSS/Atom (la propia URL o <link rel="alternate">), lo usa.
  3. Si no, extrae los enlaces del listado HTML con una heuristica generica.
  4. Para cada noticia NUEVA descarga el articulo, extrae el texto y pide a
     Claude un resumen de 3-5 lineas en espanol.
Guarda el resultado en site/data/ (JSON) y un informe de salud por fuente.

Uso:
  python scripts/collect.py                 # ejecucion normal
  python scripts/collect.py --no-llm        # sin API: resumen extractivo (pruebas)
  python scripts/collect.py --only 454,399  # solo esos ids de fuente
  python scripts/collect.py --sources otro.json --data-dir /ruta
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent  # archivo en la raiz del repo

# ---------------------------------------------------------------- ajustes
MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "3"))          # ignora noticias mas antiguas
MAX_NEW_PER_URL = int(os.getenv("MAX_NEW_PER_URL", "5"))    # tope por URL y dia
MAX_SUMMARIES = int(os.getenv("MAX_SUMMARIES", "400"))      # tope global por ejecucion
CANDIDATES_PER_URL = 15                                      # enlaces que se examinan por listado
KEEP_DAYS = int(os.getenv("KEEP_DAYS", "30"))                # dias de historico en la web
WORKERS = int(os.getenv("WORKERS", "12"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
TIMEOUT = 25

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en,es;q=0.8",
}

SKIP_HREF = re.compile(
    r"(^#|^javascript:|^mailto:|^tel:|login|signin|sign-in|register|contact|privacy|cookie|"
    r"terms|sitemap|accessibility|facebook\.com|twitter\.com|x\.com|linkedin\.com|youtube\.com|"
    r"instagram\.com|/tag/|/tags/|/category/|/page/\d|[?&]page=|\.(jpg|jpeg|png|gif|zip|xlsx?|docx?|pptx?|pdf)(\?|$))",
    re.I,
)
SKIP_TEXT = re.compile(
    r"^(home|news|read more|more|next|previous|back|contact|about|search|menu|login|"
    r"press releases?|all news|view all|see all|more news|archive|subscribe|rss)$",
    re.I,
)
DATE_RES = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b"),
    re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"),
]

TODAY = dt.date.today()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- red
_session = requests.Session()
_session.headers.update(HEADERS)


def http_get(url: str, retries: int = 2) -> requests.Response | None:
    """GET con reintentos; si falla el certificado, reintenta sin verificar
    (solo para leer paginas publicas de noticias)."""
    verify = True
    for i in range(retries + 1):
        try:
            r = _session.get(url, timeout=TIMEOUT, verify=verify, allow_redirects=True)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 410, 451):
                return None
        except requests.exceptions.SSLError:
            verify = False
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


# ---------------------------------------------------------------- fechas
def parse_date_text(text: str) -> dt.date | None:
    if not text:
        return None
    for rx in DATE_RES:
        m = rx.search(text)
        if not m:
            continue
        try:
            d = dateparser.parse(m.group(0), dayfirst=True, fuzzy=True).date()
            if dt.date(2000, 1, 1) <= d <= TODAY + dt.timedelta(days=1):
                return d
        except (ValueError, OverflowError):
            continue
    return None


def entry_date(e) -> dt.date | None:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return dt.date(t.tm_year, t.tm_mon, t.tm_mday)
    return parse_date_text(e.get("published", "") or e.get("updated", ""))


# ---------------------------------------------------------------- descubrimiento
class Cand(dict):
    """url, titulo, fecha (date|None), resumen_feed"""


def from_feed(parsed, base_url) -> list[Cand]:
    out = []
    for e in parsed.entries[:CANDIDATES_PER_URL]:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        out.append(Cand(url=urljoin(base_url, link), titulo=title, fecha=entry_date(e),
                        resumen_feed=re.sub(r"<[^>]+>", " ", e.get("summary", "") or "").strip()))
    return out


COMMON_FEEDS = ("feed", "rss", "rss.xml", "feed.xml", "atom.xml", "news/rss", "news/feed")


def from_html(soup: BeautifulSoup, base_url: str) -> list[Cand]:
    host = urlparse(base_url).netloc.replace("www.", "")
    for tag in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
        tag.decompose()
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    seen, out = set(), []
    for a in root.find_all("a", href=True):
        href = a["href"].strip()
        if SKIP_HREF.search(href):
            continue
        url = urljoin(base_url, href).split("#")[0]
        p = urlparse(url)
        if p.scheme not in ("http", "https") or url.rstrip("/") == base_url.rstrip("/"):
            continue
        if p.netloc.replace("www.", "") != host and not p.netloc.endswith(host.split(".", 1)[-1]):
            continue  # enlaces a otros sitios
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text:  # enlace de imagen: usa el titulo del contenedor
            h = a.find_parent(["article", "li", "div"])
            hh = h.find(["h1", "h2", "h3", "h4"]) if h else None
            text = hh.get_text(" ", strip=True) if hh else ""
        if len(text) < 25 or len(text.split()) < 4 or SKIP_TEXT.match(text):
            continue
        if url in seen:
            continue
        seen.add(url)
        # fecha cercana: <time>, o texto del contenedor
        fecha = None
        box = a.find_parent(["article", "li", "tr", "div"])
        for _ in range(2):
            if not box:
                break
            t = box.find("time")
            fecha = (parse_date_text(t.get("datetime", "")) or parse_date_text(t.get_text(" ", strip=True))) if t else None
            fecha = fecha or parse_date_text(box.get_text(" ", strip=True)[:400])
            if fecha:
                break
            box = box.find_parent(["article", "li", "tr", "div"])
        out.append(Cand(url=url, titulo=text, fecha=fecha, resumen_feed=""))
        if len(out) >= CANDIDATES_PER_URL * 2:
            break
    # los listados suelen ir de mas nuevo a mas antiguo: se respeta el orden del documento
    return out[:CANDIDATES_PER_URL]


def discover(url: str) -> tuple[list[Cand], str]:
    """Devuelve (candidatos, metodo). Lanza RuntimeError si no hay contenido."""
    r = http_get(url)
    if r is None:
        raise RuntimeError("no se pudo descargar")
    head = r.content[:600].lower()
    if b"<rss" in head or b"<feed" in head or b"<?xml" in head:
        parsed = feedparser.parse(r.content)
        if parsed.entries:
            return from_feed(parsed, r.url), "rss"
    soup = BeautifulSoup(r.content, "lxml")
    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        if (link.get("type") or "").lower() in ("application/rss+xml", "application/atom+xml") and link.get("href"):
            fr = http_get(urljoin(r.url, link["href"]), retries=1)
            if fr:
                parsed = feedparser.parse(fr.content)
                if parsed.entries:
                    return from_feed(parsed, r.url), "rss"
    cands = from_html(soup, r.url)
    if not cands:
        raise RuntimeError("listado sin enlaces de noticias (puede cargarse con JavaScript)")
    return cands, "html"


# ---------------------------------------------------------------- articulo
def fetch_article(url: str) -> tuple[str, dt.date | None]:
    r = http_get(url, retries=1)
    if r is None:
        return "", None
    text = trafilatura.extract(r.content, include_comments=False, include_tables=False,
                               favor_recall=True, url=r.url) or ""
    fecha = None
    try:
        md = trafilatura.extract_metadata(r.content, default_url=r.url)
        if md and md.date:
            fecha = dateparser.parse(md.date).date()
    except Exception:
        pass
    return text.strip(), fecha


# ---------------------------------------------------------------- resumen
_client = None


def llm_summary(inst: str, titulo: str, texto: str) -> dict | None:
    """Devuelve {'titulo_es', 'resumen'} o None si no es una noticia."""
    global _client
    import anthropic
    if _client is None:
        _client = anthropic.Anthropic()
    prompt = (
        f"Institucion: {inst}\nTitular original: {titulo}\n\nTexto de la pagina:\n{texto[:7000]}\n\n"
        "Tarea: si el texto es una noticia o comunicado de prensa real, devuelve SOLO un JSON con:\n"
        '{"titulo_es": "titular traducido al espanol (si ya esta en espanol, igual)", '
        '"resumen": "resumen en espanol de 3 a 5 lineas (50-80 palabras), factual y neutro, '
        'con las cifras y decisiones clave; no inventes nada que no este en el texto"}\n'
        'Si el texto NO es una noticia (menu, aviso de cookies, pagina de error, listado), devuelve {"skip": true}.'
    )
    for attempt in range(3):
        try:
            msg = _client.messages.create(model=MODEL, max_tokens=500,
                                          messages=[{"role": "user", "content": prompt}])
            raw = msg.content[0].text
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
            if data.get("skip"):
                return None
            if data.get("resumen"):
                return {"titulo_es": data.get("titulo_es") or titulo, "resumen": data["resumen"].strip()}
            return None
        except Exception as e:  # limite de tasa, JSON roto, etc.
            log(f"  LLM intento {attempt+1} fallo: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(3 * (attempt + 1))
    return None


def extractive_summary(texto: str) -> str:
    sents = re.split(r"(?<=[.!?])\s+", " ".join(texto.split()))
    return " ".join(sents[:3])[:600]


# ---------------------------------------------------------------- proceso
def uid(url: str) -> str:
    return hashlib.sha1(url.split("?")[0].rstrip("/").lower().encode()).hexdigest()[:16]


def process_url(src: dict, u: dict, seen: dict) -> tuple[list[dict], dict]:
    """Descubre noticias nuevas de una URL. No llama al LLM todavia."""
    health = {"fuente": src["institucion"], "url": u["url"], "metodo": None, "candidatos": 0, "nuevas": 0, "error": None}
    try:
        cands, metodo = discover(u["url"])
    except Exception as e:
        health["error"] = str(e)
        return [], health
    health["metodo"], health["candidatos"] = metodo, len(cands)
    nuevas = []
    for c in cands:
        if uid(c["url"]) in seen:
            continue
        if c["fecha"] and (TODAY - c["fecha"]).days > MAX_AGE_DAYS:
            continue
        nuevas.append(c)
        if len(nuevas) >= MAX_NEW_PER_URL:
            break
    health["nuevas"] = len(nuevas)
    return [dict(c, src=src, list_url=u["url"]) for c in nuevas], health


def build_item(c: dict, use_llm: bool) -> dict | None:
    texto, fecha_art = fetch_article(c["url"])
    fecha = c["fecha"] or fecha_art
    if fecha and (TODAY - fecha).days > MAX_AGE_DAYS:
        return "viejo"  # type: ignore[return-value]
    base = {
        "id": uid(c["url"]), "fuente_id": c["src"]["id"], "institucion": c["src"]["institucion"],
        "jurisdiccion": c["src"]["jurisdiccion"], "tipo": c["src"]["tipo"],
        "url": c["url"], "titulo": c["titulo"], "fecha": fecha.isoformat() if fecha else None,
    }
    texto = texto if len(texto) >= 200 else (c.get("resumen_feed") or texto)
    if len(texto) < 120:
        return dict(base, titulo_es=None, resumen=None, nota="Texto no accesible: abre el enlace")
    if use_llm:
        r = llm_summary(c["src"]["institucion"], c["titulo"], texto)
        if r is None:
            return None
        return dict(base, **r)
    return dict(base, titulo_es=c["titulo"], resumen=extractive_summary(texto))


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=str(ROOT / "sources.json"))
    ap.add_argument("--data-dir", default=str(ROOT / "site" / "data"))
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    use_llm = not a.no_llm
    if use_llm and not os.getenv("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY no definida: usando resumen extractivo (--no-llm)")
        use_llm = False

    data = Path(a.data_dir)
    (data / "days").mkdir(parents=True, exist_ok=True)
    seen = load_json(data / "seen.json", {})
    sources = load_json(Path(a.sources), [])
    if a.only:
        ids = set(a.only.split(","))
        sources = [s for s in sources if s["id"] in ids]

    # 1) descubrir en paralelo
    jobs = [(s, u) for s in sources for u in s["urls"] if u.get("activa")]
    log(f"{len(jobs)} URLs activas en {len(sources)} instituciones")
    nuevas, health = [], []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for items, h in ex.map(lambda j: process_url(j[0], j[1], seen), jobs):
            nuevas += items
            health.append(h)
    # dedupe entre URLs de la misma institucion
    uniq = {}
    for c in nuevas:
        uniq.setdefault(uid(c["url"]), c)
    nuevas = list(uniq.values())[:MAX_SUMMARIES]
    log(f"{len(nuevas)} noticias candidatas nuevas")

    # 2) articulo + resumen en paralelo
    items = []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for c, it in zip(nuevas, ex.map(lambda c: build_item(c, use_llm), nuevas)):
            seen[uid(c["url"])] = TODAY.isoformat()  # marcada aunque se descarte, para no reintentar
            if isinstance(it, dict):
                items.append(it)

    # 3) guardar dia
    day_file = data / "days" / f"{TODAY.isoformat()}.json"
    previos = load_json(day_file, [])
    ids_prev = {i["id"] for i in previos}
    items = previos + [i for i in items if i["id"] not in ids_prev]
    items.sort(key=lambda i: (i["jurisdiccion"], i["institucion"]))
    day_file.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    # 4) indice, limpieza y salud
    days = sorted((p.stem for p in (data / "days").glob("*.json")), reverse=True)
    for old in days[KEEP_DAYS:]:
        (data / "days" / f"{old}.json").unlink()
    days = days[:KEEP_DAYS]
    (data / "index.json").write_text(json.dumps(
        {"actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "dias": days}), encoding="utf-8")
    cutoff = (TODAY - dt.timedelta(days=90)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    (data / "seen.json").write_text(json.dumps(seen), encoding="utf-8")
    fallos = [h for h in health if h["error"]]
    (data / "health.json").write_text(json.dumps(
        {"fecha": TODAY.isoformat(), "urls": len(health), "fallos": len(fallos), "detalle": health},
        ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Hoy: {len(items)} noticias. URLs con fallo: {len(fallos)}/{len(health)}. Detalle en health.json")


if __name__ == "__main__":
    main()
