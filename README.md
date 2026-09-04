# AI Overview Watch

Rastrea qué responde el **AI Overview de Google** sobre una marca o un tema, en varios
mercados hispanohablantes, y detecta qué fuentes cita y cómo cambian con el tiempo.

Usa la [Google Search API](https://serpapi.com/search-api) y la
[Google AI Overview API](https://serpapi.com/google-ai-overview-api) de SerpApi.

## Por qué

El SEO clásico medía posiciones en una lista de diez enlaces azules. Cuando Google responde
directamente con un resumen generado, la pregunta ya no es "en qué puesto salgo", sino
**"me menciona la IA, y de dónde saca lo que dice"**. Este script mide exactamente eso.

## Instalación

```bash
git clone <tu-repo> && cd ai-overview-watch
python3 -m venv .venv && source .venv/bin/activate
pip install requests
export SERPAPI_API_KEY="tu_clave"     # https://serpapi.com/manage-api-key
cp queries.example.json queries.json  # edita marca, mercados y consultas
```

## Uso

```bash
python ai_overview_watch.py run      # captura y guarda en SQLite
python ai_overview_watch.py report   # compara con la captura anterior
```

Salida típica de `run`:

```
09:14:02 INFO    [es] mejor API para scraping de buscadores   7 fuentes   marca citada
09:14:05 INFO    [mx] mejor API para scraping de buscadores   SIN AI Overview
```

## Cómo funciona

1. Llamada a `engine=google` con `q`, `gl` (país) y `hl` (idioma).
2. Si la respuesta trae `ai_overview.page_token`, el resumen viene incompleto: se hace una
   segunda llamada a `engine=google_ai_overview` con ese token. La documentación de SerpApi
   da dos cifras para su caducidad de 1 minuto en la página del AI Overview API, 4 minutos en
   la de AI Overview Results. El código asume la más estricta: el token se usa al vuelo y
   nunca se guarda en base de datos ni en una cola de trabajos.
3. Se aplanan los `text_blocks` (los párrafos pueden anidar listas) y se extraen las
   `references` con su dominio.
4. Todo se guarda en SQLite con marca de tiempo, junto al top 10 orgánico de la misma
   consulta, para poder comparar qué cita la IA frente a lo que rankea.

## Detalles operativos

- **`no_cache=true`**: el caché de SerpApi dura 1 hora, así que con capturas semanales es
  irrelevante. Se activa por el desarrollo (decenas de consultas seguidas sí caen dentro de
  esa ventana) y para tener una sola ruta de código. Las cacheadas son gratis y no cuentan
  cuota; las frescas sí. Con frecuencia diaria o semanal, `no_cache=false` es defendible.
- **Reintentos**: backoff exponencial ante 429 y 5xx. Un 401 o un 400 no se reintentan,
  son errores de configuración y repetirlos solo quema cuota.
- **Tres estados, no dos**: hay resumen, no hay resumen (`has_overview = 0`), y Google no
  pudo generarlo (`error` con el mensaje "Can't generate an AI overview right now"). El
  tercero se guarda aparte: confundirlo con la ausencia contamina la serie temporal.
- **Cobertura en español sin confirmar**: la documentación de SerpApi indica que el bloque
  solo se ve con `hl=en` y un rango limitado de países, mientras que Google anuncia AI
  Overviews en español. Por eso la configuración incluye una **consulta de control** en
  inglés/EE.UU. que se ejecuta primero: si el control no devuelve resumen, los vacíos en
  español no son concluyentes.
- **Cuota**: cada consulta con AI Overview puede costar dos llamadas. Con 5 consultas × 3
  mercados × 1 ejecución semanal son ~120 llamadas al mes.

## Ejecución semanal (systemd)

`/etc/systemd/system/aiw.service`:

```ini
[Unit]
Description=AI Overview Watch
After=network-online.target

[Service]
Type=oneshot
User=aiw
WorkingDirectory=/opt/ai-overview-watch
EnvironmentFile=/etc/aiw.env
ExecStart=/opt/ai-overview-watch/.venv/bin/python ai_overview_watch.py run
```

`/etc/systemd/system/aiw.timer`:

```ini
[Unit]
Description=Ejecuta AI Overview Watch cada lunes

[Timer]
OnCalendar=Mon *-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now aiw.timer
systemctl list-timers aiw.timer
```

`Persistent=true` importa: si el servidor estaba apagado el lunes, la captura se ejecuta al
arrancar en lugar de perderse. La clave va en `/etc/aiw.env` con permisos `600`, nunca en el
repositorio.

## Licencia

MIT

---
## Fuentes
 
Toda la documentación consultada, con la fecha de consulta y el detalle de qué dato sale de
cada página: [Fuentes y referencias](https://github.com/carlosbrbz/serpapi-lab/edit/main/FUENTES.md).

**Artículo completo:** [¿Qué está diciendo la IA de Google sobre tu marca?](https://carlosbarboza.org/post/ai-overview-google-marca)

**Carlos Barboza** — Sistemas, infraestructura y datos de búsqueda
[carlosbarboza.org](https://carlosbarboza.org)


