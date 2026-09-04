# Fuentes y referencias

Documentación y fuentes utilizadas para el proyecto **AI Overview Watch** y para el artículo
[¿Qué está diciendo la IA de Google sobre tu marca?](https://carlosbarboza.org/post/ai-overview-google-marca).

**Consultado el 30 de Agosto de 2026.** La documentación de APIs cambia con frecuencia. Si
lees esto mucho después, verifica antes de fiarte de las cifras citadas aquí.

---

## Documentación de SerpApi (fuente primaria)

### [Google AI Overview API](https://serpapi.com/google-ai-overview-api)

Endpoint `https://serpapi.com/search?engine=google_ai_overview`.

De aquí sale:

- El parámetro `page_token` y su origen (`ai_overview.page_token` de la Google Search API).
- **Caducidad declarada del token: 1 minuto** desde la búsqueda, con indicación de usarlo
  de inmediato. Ver contradicción más abajo.
- Comportamiento del caché: `no_cache` sirve para forzar resultados frescos; el caché
  **expira tras 1 hora** y solo se sirve si la consulta y todos los parámetros coinciden
  exactamente. Las búsquedas cacheadas son gratuitas y no consumen cuota mensual.
- `no_cache` y `async` no deben usarse a la vez.
- Estructura de la respuesta JSON: `text_blocks`, `thumbnail` y `references`; estado de la
  búsqueda en `search_metadata.status` (`Processing` → `Success` | `Error`).

### [Google AI Overview Results](https://serpapi.com/ai-overview)

Documentación del bloque `ai_overview` embebido en la Google Search API.

De aquí sale:

- **La limitación de idioma**: la página declara que, actualmente, el bloque de AI Overview
  solo se ve en búsquedas en inglés (`hl=en`) y con un rango limitado de países (`gl`).
  Este es el punto que motiva la consulta de control del proyecto.
- **La contradicción sobre la caducidad**: aquí se afirma que `page_token` y `serpapi_link`
  expiran a los **4 minutos**, frente al **1 minuto** de la página anterior. Mismo campo,
  dos cifras.
- El estado de error: `ai_overview` puede contener únicamente
  `"error": "Can't generate an AI overview right now. Try again later."`, distinto de la
  ausencia del bloque. El HTML renderizado muestra ese mismo mensaje y es comportamiento
  esperado.
- La estructura completa de `text_blocks`: tipos `heading`, `paragraph`, `list`,
  `expandable`, `comparison`, `table` y `top_stories`; listas anidadas dentro de listas;
  `reference_indexes` que enlazan cada bloque con las fuentes citadas.
- Campos adicionales no cubiertos por el script: `products`, `header_images`,
  `snippet_links`, `snippet_latex`, `thumbnail`.

### [Google Search API](https://serpapi.com/search-api)

Endpoint base `engine=google` del que cuelga el bloque `ai_overview`, junto a
`organic_results`, que el proyecto captura para comparar citas de la IA contra posiciones
orgánicas.

### [serpapi/google-AI-overview-scraper](https://github.com/serpapi/google-AI-overview-scraper)

Repositorio oficial de SerpApi con la implementación de referencia del flujo de dos
llamadas (búsqueda → token → expansión).

### [Fetching AI Overviews with Node.js](https://serpapi.com/blog/fetching-ai-overviews-with-node-js)

Artículo del blog de SerpApi sobre el mismo flujo en JavaScript, con los parámetros de
búsqueda habituales y advertencias de implementación.

---

## Disponibilidad de AI Overviews en español (fuentes secundarias)

**Advertencia:** no está verificado contra una publicación de Google directamente. Procede de
cobertura especializada y debe tratarse como tal. Sustituir por el anuncio oficial de Google
en cuanto se localice.

- [Así son las AI Overviews o "vistas creadas con IA" de Google](https://useo.es/google-ai-overviews-espana/)
  — useo.es. Anuncio de la llegada a España y otros ocho países europeos; señala que las
  respuestas aparecen tanto en búsquedas en español como en inglés.
- [Google lanza (por fin) las AI Overviews en España](https://marketing4ecommerce.net/ai-overviews-de-google-espana/)
  — Marketing4eCommerce. Detalle de los países e idiomas incluidos en la expansión europea.
- [Google lanza AI Overview en español](https://hipertextual.com/internet/google-ai-overviews-ia-gemini-buscador/)
  — Hipertextual, agosto de 2024. Despliegue en México con resúmenes en español, junto a
  Brasil, Reino Unido, Japón, India e Indonesia, cada uno en su idioma local.

---

## La discrepancia

SerpApi documenta que el bloque solo se extrae con `hl=en` y países limitados. Google anuncia
AI Overviews en español en España, México y Argentina. Ambas cosas no pueden ser ciertas a la
vez para quien quiera monitorizar el mercado hispanohablante vía API.

Resolver esa discrepancia con datos es el objetivo del proyecto. La consulta de control en
inglés/EE.UU. existe para que un resultado vacío en español sea interpretable.

---

**Carlos Barboza** — [carlosbarboza.org](https://carlosbarboza.org)
