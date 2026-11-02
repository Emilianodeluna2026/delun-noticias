"""Convierte sources/fuentes.xlsx en sources.json (una fuente por institucion).

Uso: python scripts/build_sources.py
Se puede volver a ejecutar si editas el Excel.
"""
import json, re, sys
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "sources" / "fuentes.xlsx"
OUT = ROOT / "sources.json"

# Columnas con URLs de noticias: G, H, I (indices 6, 7, 8)
NEWS_COLS = {"G": 6, "H": 7, "I": 8}


def parse_notes(note):
    """'G: No funciona - ...; H: sin probar' -> {'G': '...', 'H': '...'}"""
    out = {}
    if not note:
        return out
    for part in re.split(r";\s*(?=[GHI]:)", note):
        m = re.match(r"([GHI]):\s*(.*)", part.strip(), re.S)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def classify(note):
    if not note:
        return "ok", None
    n = note.lower()
    if n.startswith("no funciona"):
        return "roto", note
    if n.startswith("bloqueado"):
        return "bloqueado", note
    if n.startswith("abre pero no muestra") or n.startswith("funciona en parte"):
        return "dudoso", note
    if n.startswith("sin probar"):
        return "sin_probar", note
    return "dudoso", note


def main():
    ws = openpyxl.load_workbook(XLSX).worksheets[0]
    sources, skipped = [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        org_id, mtype, juris, inst = row[0], row[1], row[2], row[3]
        notes = parse_notes(row[10])
        urls = []
        for col, idx in NEWS_COLS.items():
            u = row[idx]
            if not u or not str(u).strip().startswith("http"):
                continue
            status, why = classify(notes.get(col))
            urls.append({"url": str(u).strip(), "status": status, "nota": why})
        if not urls:
            skipped.append(inst)
            continue
        # activa si al menos una URL no esta rota ni bloqueada
        for u in urls:
            u["activa"] = u["status"] in ("ok", "dudoso", "sin_probar")
        sources.append({
            "id": f"{org_id}",
            "institucion": (inst or "").strip(),
            "jurisdiccion": (juris or "").strip(),
            "tipo": (mtype or "").strip() or "Otro",
            "web": row[5],
            "urls": urls,
        })
    OUT.write_text(json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")
    act = sum(1 for s in sources if any(u["activa"] for u in s["urls"]))
    print(f"{len(sources)} instituciones, {act} con alguna URL activa, "
          f"{sum(len(s['urls']) for s in sources)} URLs en total")
    if skipped:
        print("Sin URL de noticias:", skipped)


if __name__ == "__main__":
    sys.exit(main())
