"""Tests de las funciones puras de extracción y detección."""

import pytest

from ai_overview_watch import (
    domain_matches,
    domain_of,
    extract_references,
    find_brand,
    flatten_text,
    name_mentioned,
    retry_after,
)

BRAND = {"names": ["SerpApi", "Serp Api"], "domains": ["serpapi.com"]}


# --------------------------------------------------------------------------
# domain_of
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url,esperado", [
    ("https://www.ejemplo.es/guia", "ejemplo.es"),
    ("https://ejemplo.es/guia", "ejemplo.es"),
    ("https://DOCS.SerpApi.com/x", "docs.serpapi.com"),
    ("", ""),
    ("no-es-una-url", ""),
])
def test_domain_of(url, esperado):
    assert domain_of(url) == esperado


# --------------------------------------------------------------------------
# flatten_text
# --------------------------------------------------------------------------

def test_flatten_text_recoge_listas_anidadas():
    overview = {"text_blocks": [
        {"type": "paragraph", "snippet": "Primero."},
        {"type": "list", "list": [
            {"snippet": "Segundo."},
            {"snippet": "Tercero.", "list": [{"snippet": "Cuarto."}]},
        ]},
    ]}
    assert flatten_text(overview) == "Primero.\nSegundo.\nTercero.\nCuarto."


def test_flatten_text_recoge_bloques_expandibles():
    """Los bloques 'expandable' anidan text_blocks dentro de text_blocks."""
    overview = {"text_blocks": [
        {"type": "paragraph", "snippet": "Visible."},
        {"type": "expandable", "title": "Cámara", "text_blocks": [
            {"type": "paragraph", "snippet": "Oculto tras el desplegable."},
        ]},
    ]}
    assert "Oculto tras el desplegable." in flatten_text(overview)


def test_flatten_text_sin_bloques():
    assert flatten_text({}) == ""
    assert flatten_text({"text_blocks": None}) == ""


# --------------------------------------------------------------------------
# extract_references
# --------------------------------------------------------------------------

def test_extract_references():
    overview = {"references": [
        {"title": "Doc", "source": "SerpApi", "link": "https://serpapi.com/search-api"},
        {"title": "Otro", "source": "Blog", "link": "https://www.ejemplo.es/x"},
    ]}
    refs = extract_references(overview)
    assert [r["domain"] for r in refs] == ["serpapi.com", "ejemplo.es"]


def test_extract_references_vacio():
    assert extract_references({}) == []


# --------------------------------------------------------------------------
# domain_matches — el bug que motivó estos tests
# --------------------------------------------------------------------------

@pytest.mark.parametrize("candidato,esperado", [
    ("serpapi.com", True),
    ("docs.serpapi.com", True),
    ("noserpapi.com", False),              # subcadena, no es la marca
    ("serpapi.com.atacante.net", False),   # sufijo falsificado
    ("serpapi.org", False),
    ("", False),
])
def test_domain_matches(candidato, esperado):
    assert domain_matches(candidato, "serpapi.com") is esperado


# --------------------------------------------------------------------------
# name_mentioned
# --------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Usamos SerpApi en producción.", True),
    ("serpapi es una opción", True),
    ("(SerpApi)", True),
    ("SerpApiClone hace lo mismo", False),  # palabra distinta
    ("", False),
])
def test_name_mentioned(texto, esperado):
    assert name_mentioned(texto, "SerpApi") is esperado


def test_name_mentioned_no_casa_dentro_de_otra_palabra():
    assert name_mentioned("me gusta la pineapple", "Apple") is False
    assert name_mentioned("compré un Apple Watch", "Apple") is True


# --------------------------------------------------------------------------
# find_brand
# --------------------------------------------------------------------------

def test_find_brand_detecta_texto_y_fuentes():
    refs = [{"domain": "serpapi.com"}, {"domain": "ejemplo.es"}]
    assert find_brand("SerpApi resuelve CAPTCHAs.", refs, BRAND) == {
        "in_text": True, "in_refs": True,
    }


def test_find_brand_citada_sin_mencion():
    """Te enlazan pero no te nombran: son estados distintos."""
    refs = [{"domain": "serpapi.com"}]
    assert find_brand("Existen varias APIs de búsqueda.", refs, BRAND) == {
        "in_text": False, "in_refs": True,
    }


def test_find_brand_ignora_dominio_falsificado():
    refs = [{"domain": "serpapi.com.atacante.net"}]
    assert find_brand("Sin menciones.", refs, BRAND)["in_refs"] is False


def test_find_brand_sin_marca_configurada():
    assert find_brand("texto", [{"domain": "x.com"}], {}) == {
        "in_text": False, "in_refs": False,
    }


# --------------------------------------------------------------------------
# retry_after
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cabecera,esperado", [
    ("30", 30),
    ("0", 1),                       # nunca menos de 1 segundo
    ("99999", 120),                 # tope
    (None, 5),                      # sin cabecera, backoff propio
    ("Wed, 21 Oct 2026 07:28:00", 5),  # formato fecha: se ignora
    ("basura", 5),
])
def test_retry_after(cabecera, esperado):
    assert retry_after(cabecera, fallback=5) == esperado
