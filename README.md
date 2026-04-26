# 🤖 Telegram Media Agent

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)
![Jellyfin](https://img.shields.io/badge/Jellyfin-Integrated-7A5AF8)
![License](https://img.shields.io/badge/License-MIT-yellow)

Bot de Telegram multipropósito centrado en **Jellyfin**, **YouTube**, **música**, **traducción**, **búsqueda web** y **Wallapop**, construido sobre **FastAPI** y pensado para ofrecer una experiencia guiada, visual y muy práctica desde el propio chat.

Combina comandos directos, menús interactivos, callbacks y sesiones por usuario para que el bot se sienta más como una mini app que como un chat tradicional.

Además de los comandos clásicos, también puede resolver **consultas libres en lenguaje natural** cuando no encajan en un comando directo.

---

## Índice

- [Que es este proyecto](#que-es-este-proyecto)
- [Resumen rapido](#resumen-rapido)
- [Funciones principales](#funciones-principales)
- [Modo guiado](#modo-guiado)
- [Ejemplos de uso](#ejemplos-de-uso)
- [Casos de uso](#casos-de-uso)
- [Wallapop y alertas](#wallapop-y-alertas)
- [Control de acceso y administracion](#control-de-acceso-y-administracion)
- [Arquitectura y estructura](#arquitectura-y-estructura)
- [Sesiones por usuario](#sesiones-por-usuario)
- [Rendimiento y optimizaciones](#rendimiento-y-optimizaciones)
- [Variables de entorno](#variables-de-entorno)
- [Instalacion y ejecucion](#instalacion-y-ejecucion)
- [Dependencias importantes](#dependencias-importantes)
- [Proxy seguro de Jellyfin](#proxy-seguro-de-jellyfin)
- [Comandos para BotFather](#comandos-para-botfather)
- [Estado actual](#estado-actual)
- [Troubleshooting](#troubleshooting)

<a id="que-es-este-proyecto"></a>
## ✨ Qué es este proyecto

Este bot está diseñado para centralizar tareas muy comunes dentro de Telegram:

- navegar y reproducir contenido de Jellyfin
- buscar vídeos y música desde YouTube
- traducir texto y notas de voz
- consultar Wikipedia, imágenes y tiempo
- buscar artículos en Wallapop con filtros, fichas y alertas
- mantener playlists y favoritos por usuario

El objetivo no es solo “responder comandos”, sino ofrecer una experiencia fluida:

- comandos directos para usuarios avanzados
- modo guiado para usuarios nuevos
- menús con botones para reducir errores
- sesiones separadas por usuario para no mezclar estados

<a id="resumen-rapido"></a>
## ⚡ Resumen rápido

| Área | Qué hace |
| --- | --- |
| 🎬 Jellyfin | Biblioteca, películas, series, temporadas, episodios y selección de audio |
| 📺 YouTube | Búsqueda, envío de vídeo y optimizaciones con caché |
| 🎵 Música | Audio, favoritos, recomendaciones y playlists locales |
| 🌍 Traducción | Texto, nota de voz, TTS y flujo guiado |
| 🛒 Wallapop | Búsqueda avanzada, fichas, gangas, paginación y alertas |
| 🍳 Recetas | Búsqueda, predicción de éxito e historial culinario |
| 🧰 Utilidades | Wiki, imágenes, tiempo, onboarding y ayuda |
| 🔐 Control | Whitelist de usuarios, solicitudes de acceso y panel admin |
| 🧠 IA general | Consultas libres sin slash cuando no hay un flujo específico |

<a id="funciones-principales"></a>
## 🚀 Funciones principales

### 🎬 Jellyfin

- `/library`
- `/menu`
- `/catalog`
- `/video <pelicula>`

Qué incluye:

- navegación por biblioteca con botones
- soporte para `Películas` y `Series`
- paginación en listados largos
- flujo `serie -> temporadas -> episodios`
- selección de audio/idioma cuando está disponible
- ficha única reutilizable para no acumular tarjetas en el chat
- envío de carátulas como binario a Telegram para mejorar velocidad y fiabilidad
- proxy seguro opcional para no exponer Jellyfin directamente

### 📺 YouTube

- `/youtube <busqueda>`
- `/youtube`

Qué incluye:

- búsqueda y selección del mejor resultado
- envío como vídeo de Telegram
- caché de búsquedas
- caché de descargas por `video_id`
- reutilización de archivos ya descargados
- limpieza de temporales

### 🎵 Música

- `/music <cancion>`
- `/music`
- `/music buscar <consulta>`
- `/music fav <consulta>`
- `/music favs`
- `/music recomendar`

Qué incluye:

- ranking específico para audio
- favoritos por usuario
- historial local
- recomendaciones básicas
- reutilización de resultados y descargas

### 📚 Playlists locales

- `/playlist`
- `/playlist crear <nombre>`
- `/playlist listas`
- `/playlist add <nombre> | <cancion>`
- `/playlist ver <nombre>`
- `/playlist play <nombre>`
- `/playlist remove <nombre> | <posicion>`
- `/playlist borrar <nombre>`

Qué incluye:

- gestión interactiva por botones
- modo guiado para añadir canciones
- vista, reproducción y borrado
- separación por usuario

### 🌍 Traducción

- `/translate <destino> | <texto>`
- `/translate <origen> | <destino> | <texto>`
- `/translate`

Qué incluye:

- traducción directa o guiada
- selector de idiomas frecuentes
- soporte de nota de voz en el flujo
- transcripción local con `faster-whisper`
- pronunciación del texto traducido
- audio TTS generado localmente

### 🍳 Recetas Culinarias

- `/receta <plato>` o `/recipe <dish>` → Búsqueda directa en Cookpad
- `/receta` (vacío) → Modo guiado paso a paso
- `/mis_recetas` - Ver historial de recetas guardadas con botones
- `/clear_recipes` - Limpiar historial

Qué incluye:

- búsqueda de recetas desde Cookpad (scraping web)
- **historial privado por usuario** (`chat_id`) con fecha de guardado
- **modo guiado**: `/receta` → pregunta "¿Qué receta?" → esperas tu respuesta
- menús interactivos con botones para cada resultado encontrado
- visualización detallada de ingredientes y pasos (todos los listados)
- guardado automático al seleccionar una receta

**Flujo guiado:**
1. `/receta` → Bot pregunta: "🍳 ¿Qué receta quieres buscar?"
2. Escribes: "pasta carbonara"
3. Bot busca en Cookpad y muestra menú con resultados encontrados (botones)
4. Al hacer clic en una receta, se muestran detalles completos:
   - Título de la receta
   - Ingredientes (todos los listados)
   - Pasos de elaboración (todos los pasos)
5. La receta se guarda automáticamente en el historial

**Flujo de búsqueda:**
1. `/receta` → Muestra menú principal con opciones
2. Botón "🔍 Buscar Receta" → Pregunta por la receta
3. Escribes nombre del plato (ej: "paella")
4. Bot busca en Cookpad y muestra lista de recetas encontradas con botones
5. Al hacer clic en una receta, se muestran detalles completos

**Historial de recetas:**
- `/mis_recetas` → Muestra todas las recetas guardadas con fecha
- Cada receta tiene un botón "🍽️" para ver sus detalles completos
- Botón "↩️ Volver" para regresar al menú principal
- `/clear_recipes` → Borra todo el historial

**Flujo de historial:**
1. `/mis_recetas` o botón "📚 Mi Historial" en menú principal
2. Muestra lista de recetas con fecha de guardado
3. Haz clic en una receta para ver detalles completos (ingredientes + pasos)
4. Botón "↩️ Volver" regresa al menú del historial

**Comandos directos:**
- `/receta paella` → Busca y muestra resultados directamente
- `/mis_recetas` → Muestra historial completo con botones
- `/clear_recipes` → Limpia todas las recetas guardadas

### 🛒 Wallapop

- `/wallapop`
- `/wallapop <producto>`
- `/mis_alertas`

Qué incluye:

- búsqueda guiada por producto (flujo paso a paso)
- filtros de estado, precio, ubicación, radio y orden
- soporte de ubicación compartida desde Telegram móvil
- listado paginado
- fichas detalladas
- detección de anuncios reservados
- indicador de ganga / razonable / caro
- alertas guardadas con comprobación periódica

**Flujo guiado:**
1. `/wallapop` → pregunta producto
2. Escribes "Rtx 4090" → guarda query y pide estado
3. Seleccionas condición (nuevo, usado...) → pide precio
4. Indicas rango o skip → pide ubicación
5. Escribe ciudad o skip → pide radio
6. Elige radio o skip → pide orden
7. Seleccionas orden → ejecuta búsqueda

**Comando directo:** `/wallapop Rtx 4090` → salta al paso de condición directamente.

### 🧰 Utilidades

- `/wiki <tema>`
- `/img <tema>`
- `/image <tema>`
- `/weather <ciudad>`
- `/tiempo <ciudad>`
- `/start`
- `/helper`
- `/help`
- `/control` solo para administración

### 🧠 Consultas libres

El bot también puede responder mensajes sin slash cuando no estás dentro de un flujo guiado específico.

Ejemplos:

- `cuantos goles lleva cristiano ronaldo`
- `quien invento internet`
- `explicame que es docker`

Esto convive con los comandos directos, así que:

- si usas un comando, el flujo es determinista
- si escribes texto libre, el bot intenta resolverlo con su capa de IA

### 🛠️ Administración

- `/control`

Qué incluye:

- control de acceso por whitelist
- panel visual de usuarios
- estados `pendiente`, `aprobado` y `bloqueado`
- vista de detalle por usuario
- historial reciente de entradas
- acciones rápidas de aprobar o bloquear
- persistencia de accesos fuera del contenedor

<a id="modo-guiado"></a>
## 🧭 Modo guiado

Muchos comandos se pueden usar vacíos para que el bot te vaya pidiendo lo necesario paso a paso:

- `/video`
- `/wiki`
- `/img`
- `/image`
- `/weather`
- `/tiempo`
- `/youtube`
- `/music`
- `/translate`
- `/playlist`
- `/wallapop`

Ejemplos:

- `/video` → pregunta qué película quieres ver
- `/translate` → pide texto o nota de voz y luego idioma
- `/music` → pregunta qué canción quieres buscar
- `/wallapop` → pide producto, filtros y luego muestra resultados
- sin slash → el bot puede intentar responder como consulta general si no hay un flujo activo

<a id="ejemplos-de-uso"></a>
## 🧪 Ejemplos de uso

```text
/library
/video interstellar
/wiki chuck norris
/img cascadas
/weather madrid
/youtube waka waka shakira
/music Danza Kuduro
/music fav Hall of Fame
/playlist crear motivacion
/playlist add motivacion | believer imagine dragons
/translate en | hola mundo
/wallapop steam deck
/mis_alertas
/control
cuantos goles lleva cristiano ronaldo
```

<a id="casos-de-uso"></a>
## 💡 Casos de uso

### 1. Explorar la biblioteca de Jellyfin

```text
/library
```

Ideal para navegar por contenido sin recordar el nombre exacto.

Resultado esperado:

- menú inicial con `Películas` y `Series`
- navegación por botones
- menos ruido en el chat gracias a edición de mensajes

### 2. Reproducir una película concreta

```text
/video interstellar
```

O en modo guiado:

```text
/video
```

Resultado esperado:

- búsqueda directa o guiada
- apertura de la película si existe
- selección de audio si aplica

### 3. Buscar y enviar música

```text
/music Danza Kuduro
```

Resultado esperado:

- localiza la mejor pista
- prioriza audio frente a vídeo
- lo envía como audio reproducible dentro de Telegram

### 4. Gestionar playlists propias

```text
/playlist
```

O directo:

```text
/playlist crear motivacion
/playlist add motivacion | believer imagine dragons
```

Resultado esperado:

- playlists aisladas por usuario
- añadir, ver, reproducir o borrar con botones

### 5. Traducir una nota de voz

```text
/translate
```

Después:

- envías la nota de voz
- el bot la transcribe
- eliges idioma
- devuelve traducción y pronunciación

### 7. Buscar una receta y predecir éxito

```text
/receta pasta carbonara
→ Bot busca receta en API externa
→ Analiza complejidad e ingredientes
→ Muestra probabilidad de éxito + factores/riesgos
```

**Resultado esperado:**
- Probabilidad calibrada (5%-95%)
- Factores positivos y riesgos identificados
- Opción de guardar en historial

### 8. Consultar historial de recetas

```text
/mis_recetas
→ Muestra todas tus recetas guardadas
```

### 7. Buscar un producto en Wallapop (flujo guiado)

```text
/wallapop
→ ¿Qué producto quieres buscar?
Rtx 4090
→ ¿Qué estado quieres filtrar?
[Seleccionas: Nuevo]
→ Indica un rango de precio...
skip
→ Indica una localidad...
skip
→ ¿Cómo quieres ordenar los resultados?
[Seleccionas: Recientes]
```

**Resultado esperado:** listado paginado con filtros aplicados.

### 7. Buscar un producto en Wallapop (comando directo)

```text
/wallapop steam deck
→ ¿Qué estado quieres filtrar?
```

Salta directamente al filtro de condición.

### 8. Crear una alerta desde la búsqueda

Desde el menú de resultados:
- `🔔 Crear alerta` → pide precio máximo
- Alerta guardada con comprobación periódica

Gestión: `/mis_alertas` → ver, probar, borrar alertas.

### 7. Hacer una consulta libre al bot

```text
cuantos goles lleva cristiano ronaldo
quien invento internet
explicame que es docker
```

Resultado esperado:

- si no estás dentro de un flujo guiado pendiente
- y no estás usando un comando
- el bot intenta resolver la consulta como pregunta general con RAG + LLM

**Nota:** Los comandos slash (`/video`, `/wiki`, etc.) tienen prioridad sobre consultas libres.

<a id="wallapop-y-alertas"></a>
## 🔔 Wallapop y alertas

Wallapop ya funciona como una mini app dentro del bot con **dos modos de uso**:

1. **Flujo guiado**: `/wallapop` → paso a paso (producto → estado → precio → ubicación → orden)
2. **Comando directo**: `/wallapop Rtx 4090` → salta directamente a filtros

### Búsqueda guiada

Permite filtrar por:

- producto
- estado
- rango de precio
- ubicación escrita o compartida desde móvil
- radio de búsqueda
- orden (relevancia, recientes, precio, cercanos, gangas)

Órdenes disponibles:

- `⭐ Relevancia`
- `🕒 Recientes`
- `💸 Precio asc`
- `💰 Precio desc`
- `📍 Cercanos`
- `🔥 Gangas`

Estados disponibles:

- `🆕 Nuevo`
- `✨ Como nuevo`
- `📦 En su caja`
- `♻️ Buen estado`
- `⏭ Sin filtrar`

### Listado y ficha

El listado de resultados prioriza:

- precio
- señales visuales rápidas
- título
- ubicación solo cuando aporta valor

La ficha puede incluir:

- precio
- ubicación
- estado
- fecha de publicación
- última edición
- envío
- reservado
- garantía
- visualizaciones si existen
- valoración de precio frente a comparables

### Indicadores visuales

- `⛔` reservado
- `🟢` ganga
- `🟡` precio razonable
- `🔴` caro
- `🆕` nuevo
- `✨` como nuevo
- `📦` en su caja
- `♻️` buen estado / usado
- `🚚` con envío
- `🚫` sin envío

### Alertas guardadas

Desde un resultado de Wallapop puedes pulsar `🔔 Crear alerta`.

Flujo:

1. eliges si quieres reutilizar filtros o solo el nombre del producto
2. indicas el precio máximo
3. el bot guarda la alerta
4. solo avisará de anuncios nuevos desde ese momento

Gestión:

- `/mis_alertas`

Desde ese menú puedes:

- ver la alerta activa
- ver próxima revisión
- ver última revisión
- probarla manualmente con `🧪 Probar ahora`
- borrarla

La prueba manual:

- ejecuta una comprobación real en ese momento
- usa la misma lógica que el worker
- si encuentra anuncios nuevos, envía el aviso normal
- si no los encuentra, actualiza el menú con un resumen del resultado

### Worker de alertas

El sistema de alertas no crea un proceso por usuario.

Diseño actual:

- worker global único
- comprobación por lotes
- intervalo configurable
- `jitter` para evitar patrones exactos
- límite de carga controlable

Esto ayuda a reducir:

- uso innecesario de CPU
- peticiones agresivas
- ruido en el sistema
- riesgo de bloqueo por uso demasiado rígido

### Zona horaria de las alertas

Telegram no expone directamente la zona horaria real del dispositivo al bot.

Por eso el sistema usa esta estrategia:

1. si hay ubicación compartida, intenta inferir una zona horaria razonable
2. si no puede, usa `APP_TIMEZONE` como referencia

El menú de `/mis_alertas` muestra la zona horaria usada para que no haya ambigüedad.

<a id="control-de-acceso-y-administracion"></a>
## 🔐 Control de acceso y administración

El bot puede quedar cerrado por defecto aunque cualquiera pueda encontrar su `username` en Telegram.

### Modelo de acceso

- usuarios administradores cargados desde `TELEGRAM_ADMIN_CHAT_IDS`
- alta automática de admins como aprobados
- usuarios nuevos en estado `pendiente`
- aprobación o bloqueo manual desde el panel `/control`

### Persistencia

El estado de acceso se guarda en:

- `data/access/users.json`

Esto permite conservar:

- usuarios aprobados
- usuarios bloqueados
- solicitudes pendientes
- perfiles básicos
- última actividad e histórico reciente

### Panel `/control`

Desde el panel de administración puedes:

- listar usuarios por estado
- abrir la ficha de un usuario
- aprobar o bloquear
- volver automáticamente a la lista después de actuar
- revisar:
  - fecha de primera vez visto
  - fecha de solicitud
  - fecha de aprobación o bloqueo
  - último uso
  - contador de actividad
  - entradas recientes

### Recomendación de despliegue

Si quieres que el control de acceso sobreviva a recreaciones del contenedor, mantén montado el directorio:

- `./data:/app/data`

<a id="arquitectura-y-estructura"></a>
## 🏗️ Arquitectura y estructura

El proyecto ha ido separando responsabilidades para evitar que `router.py` concentre demasiada lógica.

Capas principales:

- `app/router.py`
  - webhook principal
  - orquestación
  - callbacks y flujo general
- `app/main.py`
  - arranque de FastAPI
  - inicio y parada del worker global de alertas
- `app/core/`
  - estado temporal
  - flujos de comandos
  - intents
  - workers
- `app/tools/`
  - integración con servicios externos y lógica de negocio
- `app/utils/`
  - textos, menús, formato y helpers de interfaz
- `app/services/`
  - cliente de Telegram
  - agente/LLM
  - servicios auxiliares

Estructura actual:

```text
Agent/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── BOTFATHER_COMMANDS.txt
└── app/
    ├── main.py
    ├── router.py
    ├── config.py
    ├── core/
    │   ├── access_control.py
    │   ├── callback_handler.py
    │   ├── chat_state.py
    │   ├── command_flow.py
    │   ├── direct_intents.py
    │   ├── playlist_flow.py
    │   ├── router_intent.py
    │   ├── translate_flow.py
    │   └── wallapop_alert_worker.py
    ├── services/
    │   ├── agent.py
    │   ├── llm_client.py
    │   ├── llm_client_cloud.py
    │   ├── llm_provider.py
    │   └── telegram_client.py
    ├── tools/
    │   ├── images.py
    │   ├── jellyfin.py
    │   ├── music_local.py
    │   ├── transcription.py
    │   ├── translate.py
    │   ├── wallapop.py
    │   ├── wallapop_alerts.py
    │   ├── weather.py
    │   ├── web.py
    │   ├── wiki.py
    │   └── youtube.py
    └── utils/
        ├── access_ui.py
        ├── bot_ui.py
        ├── jellyfin_ui.py
        ├── playlist_ui.py
        ├── response_flow.py
        └── wallapop_ui.py
```

<a id="sesiones-por-usuario"></a>
## 👤 Sesiones por usuario

El bot separa el estado por `chat_id`.

Cada usuario mantiene su propio:

- historial musical
- favoritos
- playlists
- sesión guiada activa
- traducción pendiente
- búsqueda temporal de Wallapop
- ficha abierta de Wallapop
- ficha abierta de Jellyfin
- alerta de Wallapop activa

<a id="rendimiento-y-optimizaciones"></a>
## ⚡ Rendimiento y optimizaciones

### YouTube y música

- caché de búsquedas por consulta
- caché de descargas por `video_id`
- reutilización de temporales
- selección distinta para vídeo y audio
- limpieza automática de archivos

Esto acelera especialmente:

- `/youtube`
- `/music`
- `/playlist add`

### Wallapop

- filtrado por similitud para evitar resultados irrelevantes
- exclusión de anuncios con `0€`
- paginación incremental
- reutilización de la ficha abierta para no ensuciar el chat
- valoración de precio con comparables similares

### Jellyfin

- soporte de proxy firmado opcional
- evita exponer `api_key`
- evita filtrar rutas internas del servidor multimedia
- carátulas subidas directamente por el bot para evitar problemas de descarga remota de Telegram
- menos llamadas repetidas a Jellyfin al construir la ficha y los botones de audio

<a id="variables-de-entorno"></a>
## ⚙️ Variables de entorno

Ejemplo base:

```env
# Telegram
TELEGRAM_TOKEN=tu_token
TELEGRAM_ADMIN_CHAT_IDS=123456789,987654321

# Jellyfin
JELLYFIN_URL=https://tu-jellyfin
JELLYFIN_API_KEY=tu_api_key
JELLYFIN_USER_ID=tu_user_id
APP_BASE_URL=https://tu-dominio-del-bot
MEDIA_PROXY_SECRET=una_clave_larga_y_aleatoria
APP_TIMEZONE=Europe/Madrid

# LLM local
LM_STUDIO_URL=http://localhost:1234/v1/chat/completions
MODEL_NAME_LLM=meta-llama-3.1-8b-instruct

# LLM cloud
OPENROUTER_API_KEY=tu_api_key
OPENROUTER_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_MODEL=openrouter/free

# YouTube
YOUTUBE_MAX_HEIGHT=720
YOUTUBE_SEND_AS_DOCUMENT=false

# Whisper local
WHISPER_MODEL_SIZE=base

# Wallapop alerts
WALLAPOP_ALERT_INTERVAL_HOURS=8
WALLAPOP_ALERT_INTERVAL_MINUTES=0
WALLAPOP_ALERT_JITTER_MINUTES=90
WALLAPOP_ALERT_BATCH_SIZE=3

# Recipe tool (Spoonacular API)
SPOONACULAR_API_KEY=tu_api_key_spoonacular
```

Valores recomendados para `WHISPER_MODEL_SIZE`:

- `tiny` si priorizas velocidad
- `base` como equilibrio general
- `small` si quieres algo más fino y tu máquina aguanta

Notas para alertas de Wallapop:

- `WALLAPOP_ALERT_INTERVAL_MINUTES` tiene prioridad si es mayor que `0`
- para pruebas puedes poner, por ejemplo, `3`
- en producción lo normal es usar minutos a `0`
- el horario de referencia sale de `APP_TIMEZONE` si no se puede inferir uno mejor
- si compartes ubicación en Wallapop, el sistema intenta usar esa pista para ajustar mejor la zona horaria de la alerta

Notas para administración:

- `TELEGRAM_ADMIN_CHAT_IDS` acepta uno o varios IDs separados por comas
- esos admins quedan aprobados automáticamente
- el control de acceso persistido vive en `data/access/users.json`

<a id="instalacion-y-ejecucion"></a>
## 🛠️ Instalación y ejecución

### Local

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker compose up -d --build
```

El `docker-compose.yml` actual está orientado a desarrollo iterativo y usa recarga automática en `app/`.

<a id="dependencias-importantes"></a>
## 📦 Dependencias importantes

- `ffmpeg`
- `yt-dlp`
- `deep-translator`
- `gTTS`
- `faster-whisper`

`ffmpeg` es especialmente importante para:

- audio en `/music`
- conversión de medios
- notas de voz
- temporales de vídeo y audio

<a id="proxy-seguro-de-jellyfin"></a>
## 🔒 Proxy seguro de Jellyfin

Si no quieres exponer:

- el dominio real de Jellyfin
- la `api_key`
- rutas internas del servidor

puedes activar el proxy seguro del backend.

Qué hace:

- genera URLs firmadas con expiración
- sirve imágenes y streams desde tu backend
- reescribe playlists HLS

Variables necesarias:

```env
APP_BASE_URL=https://tu-dominio-del-bot
MEDIA_PROXY_SECRET=una_clave_larga_y_aleatoria
```

Recomendaciones:

- usa una clave larga y aleatoria
- apunta `APP_BASE_URL` al dominio público real del bot
- reconstruye el contenedor después de activarlo

<a id="comandos-para-botfather"></a>
## 🤖 Comandos para BotFather

El archivo [BOTFATHER_COMMANDS.txt](\\192.168.1.46\Library\PYTHON\Agent\BOTFATHER_COMMANDS.txt) contiene la lista actualizada para copiarla directamente en BotFather.

<a id="estado-actual"></a>
## ✅ Estado actual

El bot soporta actualmente:

- comandos directos y modo guiado paso a paso
- callbacks y menús interactivos
- sesiones por usuario (multi-chat)
- control de acceso por whitelist
- reproducción de vídeo y audio desde Jellyfin
- traducción de texto y voz con TTS
- búsquedas guiadas de Wallapop con dos modos:
  - `/wallapop` → flujo guiado completo
  - `/wallapop <producto>` → directo a filtros
- fichas detalladas y paginación de artículos
- alertas de Wallapop con worker en segundo plano
- predicciones deportivas con análisis estadístico

<a id="troubleshooting"></a>
## 🧯 Troubleshooting

### El bot parece seguir usando código antiguo en Docker

Reconstruye el contenedor:

```bash
docker compose up -d --build
```

### El worker de alertas no parece dispararse

Para pruebas rápidas puedes usar:

```env
WALLAPOP_ALERT_INTERVAL_MINUTES=3
WALLAPOP_ALERT_JITTER_MINUTES=0
WALLAPOP_ALERT_BATCH_SIZE=1
```

Y después volver a un intervalo más conservador para producción.

También puedes usar:

- `/mis_alertas`
- `🧪 Probar ahora`

para forzar una comprobación manual sin esperar al siguiente ciclo.

### El panel `/control` no muestra usuarios o no te deja administrar

Comprueba:

- que `TELEGRAM_ADMIN_CHAT_IDS` esté configurado
- que el contenedor se haya reiniciado después del cambio
- que `./data` siga montado para conservar `data/access/users.json`

Si quieres resetear pruebas de acceso, puedes borrar:

- `data/access/users.json`

y reiniciar el servicio para que el archivo se regenere con los admins actuales.

### La hora de la alerta no coincide exactamente con mi dispositivo

Telegram no expone directamente la zona horaria del dispositivo al bot.

El sistema usa este orden:

1. intenta inferir una zona mejor desde ubicación compartida si existe
2. si no puede, usa `APP_TIMEZONE`

### Wallapop no me avisa aunque la alerta se ejecuta

Las alertas notifican solo de anuncios nuevos respecto a los ya vistos al crearla o en revisiones anteriores.

Puedes usar `🧪 Probar ahora` en `/mis_alertas` para comprobar el estado actual de forma manual.
