#!/usr/bin/env python3
"""
Rastrea qué dice el AI Overview de Google sobre una marca.

Para cada consulta configurada:
  1. Llama a la Google Search API de SerpApi (engine=google).
  2. Si hay AI Overview parcial, hace la segunda llamada con page_token
     (engine=google_ai_overview). La documentación de SerpApi da dos cifras
     para su caducidad (1 y 4 minutos); asumimos la más estricta. Ver FUENTES.md.
  3. Guarda el texto, las fuentes citadas y el top orgánico en SQLite.
  4. Detecta si tu marca aparece en el texto o entre las fuentes.

Uso:
    export SERPAPI_API_KEY="tu_clave"
    python ai_overview_watch.py run --config queries.json
    python ai_overview_watch.py report --config queries.json

Autor: Carlos Barboza 
https://www.carlosbarboza.org
Licencia: MIT
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

ENDPOINT = "https://serpapi.com/search"
DB_PATH = os.environ.get("AIW_DB", "ai_overview_watch.db")
TIMEOUT = 60
MAX_RETRIES = 3

log = logging.getLogger("aiw")


# --------------------------------------------------------------------------
# Cliente HTTP
# --------------------------------------------------------------------------

def retry_after(header_value, fallback: int, cap: int = 120) -> int:
    """Respeta la cabecera Retry-After cuando el servidor la envía.

    Solo se admite el formato en segundos; el formato con fecha HTTP se ignora
    a propósito, porque interpretarlo mal es peor que usar nuestro backoff.
    """
    if not header_value:
        return fallback
    try:
        return max(1, min(int(str(header_value).strip()), cap))
    except (TypeError, ValueError):
        return fallback


def call_serpapi(params: dict, api_key: str) -> dict:
    """GET a SerpApi con reintentos y backoff exponencial.

    Reintentamos ante 429 (límite de peticiones) y 5xx. Un 401 o un 400 no se
    reintentan: son errores nuestros y repetirlos solo gasta cuota.
    """
    payload = {**params, "api_key": api_key}
    delay = 2

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(ENDPOINT, params=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            log.warning("Error de red (%s). Reintento %d/%d en %ds",
                        exc, attempt, MAX_RETRIES, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            return r.json()

        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            wait = retry_after(r.headers.get("Retry-After"), delay)
            log.warning("HTTP %s. Reintento %d/%d en %ds",
                        r.status_code, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            delay *= 2
            continue

        raise RuntimeError(f"SerpApi devolvió HTTP {r.status_code}: {r.text[:300]}")

    raise RuntimeError("Reintentos agotados")


def fetch_ai_overview(query: str, gl: str, hl: str, api_key: str) -> dict:
    """Devuelve el AI Overview completo (si existe) y el top orgánico."""
    search = call_serpapi(
        {"engine": "google", "q": query, "gl": gl, "hl": hl, "no_cache": "true"},
        api_key,
    )

    organic = [
        {"pos": item.get("position"),
         "domain": domain_of(item.get("link", "")),
         "title": item.get("title")}
        for item in (search.get("organic_results") or [])[:10]
    ]

    overview = search.get("ai_overview")

    # Caso 1: no hay AI Overview para esta consulta. Es un dato en sí mismo.
    if not overview:
        return {"ai_overview": None, "error": None, "organic": organic}

    # Caso 2: el bloque existe pero Google no pudo generarlo
    # ("Can't generate an AI overview right now"). NO es lo mismo que
    # "no hay resumen para esta consulta": aquí Google lo intentó y falló.
    if overview.get("error") and not overview.get("text_blocks"):
        return {"ai_overview": None, "error": overview["error"], "organic": organic}

    # Caso 3: viene incompleto y hay que pedirlo con el token.
    # Se usa inmediatamente, no se guarda (ver README sobre su caducidad).
    token = overview.get("page_token")
    if token:
        try:
            expanded = call_serpapi(
                {"engine": "google_ai_overview", "page_token": token}, api_key
            )
            overview = expanded.get("ai_overview") or overview
        except RuntimeError as exc:
            log.warning("No se pudo expandir el AI Overview de '%s': %s", query, exc)

    return {"ai_overview": overview, "error": None, "organic": organic}


# --------------------------------------------------------------------------
# Extracción
# --------------------------------------------------------------------------

def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def flatten_text(overview: dict) -> str:
    """Los text_blocks pueden anidar listas dentro de párrafos. Los aplanamos."""
    parts = []

    def walk(blocks):
        for block in blocks or []:
            if block.get("snippet"):
                parts.append(block["snippet"])
            walk(block.get("list"))
            walk(block.get("text_blocks"))

    walk(overview.get("text_blocks"))
    return "\n".join(parts).strip()


def extract_references(overview: dict) -> list:
    refs = []
    for ref in overview.get("references") or []:
        link = ref.get("link", "")
        refs.append({
            "title": ref.get("title"),
            "source": ref.get("source"),
            "domain": domain_of(link),
            "link": link,
        })
    return refs


def domain_matches(candidate: str, brand_domain: str) -> bool:
    """El dominio coincide exactamente o es un subdominio suyo.

    Comparar por subcadena sería un error: 'serpapi.com' aparece dentro de
    'noserpapi.com.ejemplo.net', que no tiene nada que ver con la marca.
    """
    candidate = (candidate or "").lower().strip(".")
    brand_domain = (brand_domain or "").lower().strip(".")
    if not candidate or not brand_domain:
        return False
    return candidate == brand_domain or candidate.endswith("." + brand_domain)


def name_mentioned(text: str, name: str) -> bool:
    """Busca el nombre como palabra completa, no como subcadena.

    Sin límites de palabra, una marca como 'Apple' casaría dentro de
    'pineapple' y el conteo de menciones quedaría inflado.
    """
    if not name:
        return False
    pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
    return re.search(pattern, text or "", re.IGNORECASE | re.UNICODE) is not None


def find_brand(text: str, refs: list, brand: dict) -> dict:
    """¿Aparece la marca en el texto, entre las fuentes, o en ninguno?"""
    names = brand.get("names", [])
    domains = brand.get("domains", [])
    ref_domains = [r.get("domain", "") for r in refs]

    return {
        "in_text": any(name_mentioned(text, n) for n in names),
        "in_refs": any(domain_matches(rd, d) for d in domains for rd in ref_domains),
    }


# --------------------------------------------------------------------------
# Almacenamiento
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at   TEXT NOT NULL,
    query         TEXT NOT NULL,
    gl            TEXT NOT NULL,
    hl            TEXT NOT NULL,
    has_overview  INTEGER NOT NULL,
    error         TEXT,
    overview_text TEXT,
    references_json TEXT,
    organic_json  TEXT,
    brand_in_text INTEGER,
    brand_in_refs INTEGER,
    is_control    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_query_time ON snapshots(query, gl, captured_at);
"""


def db_connect(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_snapshot(conn, query, gl, hl, result, brand_hit, is_control=0):
    overview = result["ai_overview"]
    text = flatten_text(overview) if overview else ""
    refs = extract_references(overview) if overview else []

    conn.execute(
        """INSERT INTO snapshots
           (captured_at, query, gl, hl, has_overview, error, overview_text,
            references_json, organic_json, brand_in_text, brand_in_refs, is_control)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         query, gl, hl, 1 if overview else 0, result.get("error"), text,
         json.dumps(refs, ensure_ascii=False),
         json.dumps(result["organic"], ensure_ascii=False),
         int(brand_hit["in_text"]), int(brand_hit["in_refs"]), int(is_control)),
    )
    conn.commit()
    return len(refs)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def cmd_run(cfg: dict, api_key: str):
    conn = db_connect()
    brand = cfg.get("brand", {"names": [], "domains": []})
    pause = cfg.get("pause_seconds", 2)

    # Consulta de control: la documentación de SerpApi afirma que el bloque
    # de AI Overview solo se ve con hl=en y un conjunto limitado de países.
    # Un control en inglés/EE.UU. permite distinguir "este mercado no devuelve
    # resumen" de "la herramienta o la cuenta están fallando".
    control = cfg.get("control")
    if control:
        c_gl, c_hl = control.get("gl", "us"), control.get("hl", "en")
        try:
            res = fetch_ai_overview(control["query"], c_gl, c_hl, api_key)
            # Se guarda en la base de datos, no solo en el log: el estado del
            # control es parte del dato. Sin él no se puede saber, semanas
            # después, si un vacío en español era real o un fallo del sistema.
            save_snapshot(conn, control["query"], c_gl, c_hl, res,
                          {"in_text": False, "in_refs": False}, is_control=1)
            if res["ai_overview"]:
                log.info("Control OK: la consulta de referencia devuelve AI Overview")
            else:
                log.warning("Control SIN resumen (%s). Los negativos de abajo "
                            "no son concluyentes.", res.get("error") or "sin error")
        except Exception as exc:
            log.error("Control falló: %s", exc)

    for market in cfg["markets"]:
        gl, hl = market["gl"], market.get("hl", "es")
        for query in cfg["queries"]:
            try:
                result = fetch_ai_overview(query, gl, hl, api_key)
            except Exception as exc:
                log.error("Falló '%s' [%s]: %s", query, gl, exc)
                continue

            overview = result["ai_overview"]
            text = flatten_text(overview) if overview else ""
            refs = extract_references(overview) if overview else []
            hit = find_brand(text, refs, brand)
            n = save_snapshot(conn, query, gl, hl, result, hit)

            if overview:
                estado = f"{n} fuentes"
            elif result.get("error"):
                estado = "ERROR de Google"
            else:
                estado = "SIN AI Overview"
            marca = "marca citada" if (hit["in_text"] or hit["in_refs"]) else "marca ausente"
            log.info("[%s] %-45s %-18s %s", gl, query[:45], estado, marca)
            time.sleep(pause)

    conn.close()


def cmd_report(cfg: dict, _api_key: str):
    """Compara la última captura con la anterior de cada consulta y mercado."""
    conn = db_connect()
    print(f"\n# Informe AI Overview — {datetime.now().strftime('%Y-%m-%d')}\n")

    ctl = conn.execute(
        "SELECT * FROM snapshots WHERE is_control=1 ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    if ctl is None:
        print("> Sin consulta de control. Los resultados vacíos no son interpretables.\n")
    elif ctl["has_overview"]:
        print(f"> Control ({ctl['gl']}/{ctl['hl']}) OK el {ctl['captured_at'][:10]}: "
              "la extracción funciona, los vacíos de abajo son reales.\n")
    else:
        print(f"> Control ({ctl['gl']}/{ctl['hl']}) SIN resumen el "
              f"{ctl['captured_at'][:10]}. Los vacíos de abajo NO son concluyentes.\n")

    for market in cfg["markets"]:
        gl = market["gl"]
        print(f"\n## {market.get('label', gl.upper())}\n")

        for query in cfg["queries"]:
            rows = conn.execute(
                """SELECT * FROM snapshots WHERE query=? AND gl=? AND is_control=0
                   ORDER BY captured_at DESC LIMIT 2""", (query, gl)
            ).fetchall()
            if not rows:
                continue

            now = rows[0]
            before = rows[1] if len(rows) > 1 else None

            print(f"### {query}")
            if not now["has_overview"]:
                if now["error"]:
                    print(f"- Google no pudo generar el resumen: {now['error']}\n")
                else:
                    print("- Google no genera AI Overview para esta consulta.\n")
                continue

            refs_now = {r["domain"] for r in json.loads(now["references_json"])}
            organic = {o["domain"] for o in json.loads(now["organic_json"])}

            print(f"- Fuentes citadas: {len(refs_now)}")
            print(f"- Marca en el texto: {'sí' if now['brand_in_text'] else 'no'} · "
                  f"entre las fuentes: {'sí' if now['brand_in_refs'] else 'no'}")

            solo_ia = refs_now - organic
            if solo_ia:
                print(f"- Citados por la IA pero fuera del top 10 orgánico: "
                      f"{', '.join(sorted(solo_ia))}")

            if before and before["has_overview"]:
                refs_before = {r["domain"] for r in json.loads(before["references_json"])}
                entran = refs_now - refs_before
                salen = refs_before - refs_now
                if entran:
                    print(f"- Nuevos: {', '.join(sorted(entran))}")
                if salen:
                    print(f"- Ya no aparecen: {', '.join(sorted(salen))}")
            print()

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Rastreador de AI Overviews de Google")
    parser.add_argument("command", choices=["run", "report"])
    parser.add_argument("--config", default="queries.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        sys.exit("Falta la variable de entorno SERPAPI_API_KEY")

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    {"run": cmd_run, "report": cmd_report}[args.command](cfg, api_key)


if __name__ == "__main__":
    main()
