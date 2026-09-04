"""Tests del flujo de captura (con la API simulada) y del almacenamiento."""

import json

import pytest

import ai_overview_watch as aiw

BRAND_HIT = {"in_text": False, "in_refs": False}


@pytest.fixture()
def conn(tmp_path):
    c = aiw.db_connect(str(tmp_path / "test.db"))
    yield c
    c.close()


def fake_api(respuestas):
    """Sustituye call_serpapi devolviendo respuestas en orden."""
    llamadas = []

    def _fake(params, api_key):
        llamadas.append(params)
        return respuestas[len(llamadas) - 1]

    _fake.llamadas = llamadas
    return _fake


# --------------------------------------------------------------------------
# fetch_ai_overview: los tres estados
# --------------------------------------------------------------------------

def test_overview_embebido_no_hace_segunda_llamada(monkeypatch):
    respuesta = {
        "ai_overview": {
            "text_blocks": [{"type": "paragraph", "snippet": "Texto."}],
            "references": [{"title": "T", "link": "https://serpapi.com/x", "source": "S"}],
        },
        "organic_results": [{"position": 1, "link": "https://ejemplo.es", "title": "E"}],
    }
    api = fake_api([respuesta])
    monkeypatch.setattr(aiw, "call_serpapi", api)

    res = aiw.fetch_ai_overview("q", "es", "es", "k")

    assert len(api.llamadas) == 1
    assert res["error"] is None
    assert res["organic"][0]["domain"] == "ejemplo.es"


def test_page_token_dispara_segunda_llamada(monkeypatch):
    primera = {"ai_overview": {"page_token": "TOKEN123"}, "organic_results": []}
    segunda = {"ai_overview": {"text_blocks": [{"snippet": "Expandido."}]}}
    api = fake_api([primera, segunda])
    monkeypatch.setattr(aiw, "call_serpapi", api)

    res = aiw.fetch_ai_overview("q", "es", "es", "k")

    assert len(api.llamadas) == 2
    assert api.llamadas[1]["engine"] == "google_ai_overview"
    assert api.llamadas[1]["page_token"] == "TOKEN123"
    assert aiw.flatten_text(res["ai_overview"]) == "Expandido."


def test_sin_overview(monkeypatch):
    monkeypatch.setattr(aiw, "call_serpapi", fake_api([{"organic_results": []}]))
    res = aiw.fetch_ai_overview("q", "mx", "es", "k")
    assert res["ai_overview"] is None
    assert res["error"] is None


def test_error_de_google_no_es_ausencia(monkeypatch):
    """El estado de error debe distinguirse de 'no hay resumen'."""
    respuesta = {
        "ai_overview": {"error": "Can't generate an AI overview right now. Try again later."},
        "organic_results": [],
    }
    monkeypatch.setattr(aiw, "call_serpapi", fake_api([respuesta]))

    res = aiw.fetch_ai_overview("q", "ar", "es", "k")

    assert res["ai_overview"] is None
    assert "Can't generate" in res["error"]


def test_fallo_al_expandir_conserva_el_bloque_parcial(monkeypatch):
    def _fake(params, api_key):
        if params["engine"] == "google":
            return {"ai_overview": {"page_token": "T", "text_blocks": [{"snippet": "Parcial."}]},
                    "organic_results": []}
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(aiw, "call_serpapi", _fake)
    res = aiw.fetch_ai_overview("q", "es", "es", "k")
    assert aiw.flatten_text(res["ai_overview"]) == "Parcial."


# --------------------------------------------------------------------------
# Almacenamiento
# --------------------------------------------------------------------------

def test_guarda_referencias_y_organico(conn):
    result = {
        "ai_overview": {
            "text_blocks": [{"snippet": "Hola."}],
            "references": [{"title": "T", "link": "https://serpapi.com/a", "source": "S"}],
        },
        "error": None,
        "organic": [{"pos": 1, "domain": "ejemplo.es", "title": "E"}],
    }
    assert aiw.save_snapshot(conn, "q", "es", "es", result, BRAND_HIT) == 1

    fila = conn.execute("SELECT * FROM snapshots").fetchone()
    assert fila["has_overview"] == 1
    assert fila["is_control"] == 0
    assert json.loads(fila["references_json"])[0]["domain"] == "serpapi.com"


def test_error_y_ausencia_se_guardan_distinto(conn):
    err = {"ai_overview": None, "error": "Can't generate", "organic": []}
    nada = {"ai_overview": None, "error": None, "organic": []}
    aiw.save_snapshot(conn, "con error", "es", "es", err, BRAND_HIT)
    aiw.save_snapshot(conn, "sin resumen", "es", "es", nada, BRAND_HIT)

    filas = {f["query"]: f for f in conn.execute("SELECT * FROM snapshots")}
    assert filas["con error"]["has_overview"] == 0
    assert filas["con error"]["error"] == "Can't generate"
    assert filas["sin resumen"]["error"] is None


def test_el_control_se_marca_en_la_base_de_datos(conn):
    """El estado del control es dato, no solo una línea de log."""
    result = {"ai_overview": {"text_blocks": [{"snippet": "ok"}]}, "error": None, "organic": []}
    aiw.save_snapshot(conn, "what is dropshipping", "us", "en", result, BRAND_HIT, is_control=1)

    fila = conn.execute("SELECT * FROM snapshots WHERE is_control=1").fetchone()
    assert fila["gl"] == "us"
    assert fila["has_overview"] == 1
