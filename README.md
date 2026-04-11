# 🤖 Telegram Media Agent

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)
![Jellyfin](https://img.shields.io/badge/Jellyfin-Integrated-7A5AF8)
![License](https://img.shields.io/badge/License-MIT-yellow)

Bot de Telegram centrado en Jellyfin, búsqueda web, YouTube, música, traducción y utilidades rápidas, montado sobre FastAPI.

---

## ✨ Qué hace

- Navega la biblioteca de Jellyfin con menús y callbacks.
- Busca y reproduce películas desde Telegram.
- Busca vídeos de YouTube y los envía al chat.
- Busca música y la envía como audio reproducible.
- Mantiene favoritos, historial y playlists locales por usuario.
- Traduce texto y notas de voz, con pronunciación del resultado.
- Busca en Wikipedia, imágenes y tiempo.
- Usa modos guiados cuando lanzas ciertos comandos vacíos.

## 🚀 Funciones principales

### 🎬 Jellyfin

- `/library`
- `/menu`
- `/catalog`
- `/video <pelicula>`
- Navegación por callbacks para evitar llenar el chat de mensajes.
- Selección de idioma/audio cuando el contenido lo permite.

### 📺 YouTube

- `/youtube <busqueda>`
- Busca el mejor resultado y lo envía como vídeo nativo de Telegram.
- Usa caché de búsquedas y caché de descargas para reducir latencia.
- Limpia archivos temporales automáticamente.

### 🎵 Música

- `/music <cancion>`
- `/music buscar <consulta>`
- `/music fav <consulta>`
- `/music favs`
- `/music recomendar`

Características:

- Prioriza audio frente a vídeo.
- Guarda historial y favoritos por `chat_id`.
- Usa almacenamiento local en JSON.
- Reutiliza resultados y descargas de YouTube para mejorar rendimiento.

### 📚 Playlists locales

- `/playlist`
- `/playlist crear <nombre>`
- `/playlist listas`
- `/playlist add <nombre> | <cancion>`
- `/playlist ver <nombre>`
- `/playlist play <nombre>`
- `/playlist remove <nombre> | <posicion>`
- `/playlist borrar <nombre>`

Características:

- Gestor interactivo por botones.
- Añadir canciones en modo guiado.
- Eliminar canciones por posición o desde botones.
- Cada usuario mantiene sus propias playlists.

### 🌍 Traducción

- `/translate <destino> | <texto>`
- `/translate <origen> | <destino> | <texto>`
- `/translate`

Características:

- Traducción directa o guiada.
- Selector de idiomas frecuentes.
- Soporte para nota de voz dentro del flujo de traducción.
- Botón para escuchar la pronunciación del texto traducido.
- Generación local de audio de pronunciación.
- Transcripción local con `faster-whisper`.

### 🧰 Otras utilidades

- `/wiki <tema>`
- `/img <tema>`
- `/image <tema>`
- `/weather <ciudad>`
- `/tiempo <ciudad>`
- `/start`
- `/helper`

## 🧭 Modo guiado

Algunos comandos se pueden usar sin parámetros y el bot te va guiando:

- `/video`
- `/wiki`
- `/img`
- `/image`
- `/weather`
- `/tiempo`
- `/youtube`
- `/translate`
- `/playlist`

Ejemplos:

- `/translate` -> te pide el texto y luego el idioma destino.
- `/video` -> te pregunta qué película quieres ver.
- `/playlist` -> te deja elegir playlist y acción.

## 🧪 Ejemplos de uso

```text
/library
/video interestellar
/wiki chuck norris
/img cascadas
/weather madrid
/youtube waka waka shakira
/music Danza Kuduro
/music fav Hall of Fame
/playlist crear motivacion
/playlist add motivacion | believer imagine dragons
/translate en | hola mundo
```

## 💡 Casos de uso

### 1. Explorar la biblioteca de Jellyfin

Caso ideal para usuarios que quieren navegar sin recordar nombres exactos.

Flujo:

```text
/library
```

Resultado esperado:

- el bot abre un menú con `Películas` y `Series`
- la navegación se hace con botones
- no se genera spam de mensajes al paginar

Valor técnico:

- usa callbacks inline
- evita desbordar límites de Telegram
- mantiene una experiencia más cercana a una interfaz real que a un chat simple

### 2. Reproducir una película concreta

Caso ideal para búsqueda directa.

Flujo:

```text
/video interstellar
```

O en modo guiado:

```text
/video
```

Resultado esperado:

- si se pasa el nombre, busca directamente la película
- si no se pasa nada, el bot pregunta cuál quieres ver
- cuando encuentra el contenido, devuelve reproducción y opciones de audio si están disponibles

Valor técnico:

- combina enrutado directo y fallback inteligente
- aprovecha Jellyfin como fuente principal

### 3. Buscar y enviar un vídeo de YouTube

Caso ideal para compartir clips, canciones o vídeos concretos.

Flujo:

```text
/youtube waka waka shakira
```

O en modo guiado:

```text
/youtube
```

Resultado esperado:

- el bot busca el mejor resultado
- prioriza vídeos oficiales o más representativos
- lo descarga y lo envía como vídeo nativo de Telegram

Valor técnico:

- usa caché de búsqueda y descarga
- limpia temporales automáticamente
- reduce tiempo de respuesta en repeticiones

### 4. Reproducir música como audio

Caso ideal para usar Telegram como reproductor rápido.

Flujo:

```text
/music Danza Kuduro
```

Resultado esperado:

- el bot localiza la mejor pista musical
- prioriza audio frente a vídeo
- la envía como audio reproducible dentro de Telegram

Valor técnico:

- usa ranking específico para música
- evita descargar vídeo si solo hace falta audio
- aprovecha temporales reutilizables

### 5. Guardar favoritos musicales

Caso ideal para empezar a construir perfil musical por usuario.

Flujo:

```text
/music fav Hall of Fame
/music favs
/music recomendar
```

Resultado esperado:

- se guarda la canción en favoritos
- el usuario puede listar sus favoritos
- el bot puede recomendar música básica según historial y canales más repetidos

Valor técnico:

- guarda datos locales por `chat_id`
- no depende de Spotify ni de cuentas externas

### 6. Crear y gestionar playlists

Caso ideal para usuarios que quieren una pequeña biblioteca musical propia dentro del bot.

Flujo directo:

```text
/playlist crear motivacion
/playlist add motivacion | believer imagine dragons
/playlist ver motivacion
```

Flujo guiado:

```text
/playlist
```

Resultado esperado:

- el bot permite crear playlists
- se pueden añadir canciones por texto o por flujo guiado
- se puede ver, reproducir, quitar canciones o borrar la playlist

Valor técnico:

- cada usuario mantiene sus playlists por separado
- el bot usa menús y callbacks para que el flujo sea más natural

### 7. Traducir texto

Caso ideal para traducción rápida en chat.

Flujo directo:

```text
/translate en | hola mundo
/translate es | en | good morning
```

Flujo guiado:

```text
/translate
```

Resultado esperado:

- el bot traduce el texto
- si usas el modo guiado, primero te pide el contenido y luego el idioma destino
- tras traducir, ofrece un botón para escuchar la pronunciación

Valor técnico:

- combina traducción directa, selector de idiomas y TTS local

### 8. Traducir una nota de voz

Caso ideal para usar el bot como traductor hablado.

Flujo:

```text
/translate
```

Después:

- envías una nota de voz
- el bot transcribe el audio
- te muestra el texto detectado
- eliges idioma
- devuelve la traducción y la pronunciación

Valor técnico:

- transcripción local con `faster-whisper`
- no depende de tokens externos para STT
- reutiliza el mismo flujo guiado que la traducción por texto

### 9. Buscar información rápida

Casos típicos:

```text
/wiki chuck norris
/img cascadas
/weather madrid
```

Resultado esperado:

- `/wiki` devuelve información estructurada
- `/img` devuelve imágenes relevantes
- `/weather` devuelve el tiempo de la ciudad indicada

Valor técnico:

- cada tool está separada
- el router decide si usar flujo directo o guiado

### 10. Onboarding de un usuario nuevo

Caso ideal para alguien que entra por primera vez al bot.

Flujo:

```text
/start
/helper
```

Resultado esperado:

- `/start` resume el bot sin saturar
- `/helper` documenta todos los comandos, alias, subcomandos y modos guiados

Valor técnico:

- mejora la descubribilidad
- reduce dudas y errores de uso

## 👤 Sesiones por usuario

El bot separa el estado por `chat_id`.

Cada usuario mantiene su propio:

- historial musical
- favoritos
- playlists
- sesión guiada actual
- traducción pendiente

## ⚡ Rendimiento y optimizaciones

YouTube y música incluyen varias optimizaciones:

- caché de búsquedas por consulta
- caché de descargas por `video_id`
- reutilización de archivos temporales existentes
- selección distinta para modo vídeo y modo música
- limpieza automática de temporales

Esto acelera bastante:

- `/youtube`
- `/music`
- `/playlist add`

## 📁 Estructura del proyecto

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
    │   ├── callback_handler.py
    │   ├── context_builder.py
    │   ├── prompt.py
    │   ├── refiner.py
    │   └── router_intent.py
    ├── services/
    │   ├── agent.py
    │   ├── llm_client.py
    │   ├── llm_client_cloud.py
    │   ├── llm_provider.py
    │   └── telegram_client.py
    └── tools/
        ├── images.py
        ├── jellyfin.py
        ├── music_local.py
        ├── scraper.py
        ├── transcription.py
        ├── translate.py
        ├── weather.py
        ├── web.py
        ├── wiki.py
        └── youtube.py
```

## ⚙️ Variables de entorno

Ejemplo base:

```env
# Telegram
TELEGRAM_TOKEN=tu_token

# Jellyfin
JELLYFIN_URL=https://tu-jellyfin
JELLYFIN_API_KEY=tu_api_key
JELLYFIN_USER_ID=tu_user_id

# LLM local
LM_STUDIO_URL=http://localhost:1234/v1/chat/completions
MODEL_NAME_LLM=meta-llama-3.1-8b-instruct

# LLM cloud
OPENROUTER_API_KEY=tu_api_key
OPENROUTER_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_MODEL=openrouter/free

# YouTube
YOUTUBE_MAX_HEIGHT=720

# Whisper local
WHISPER_MODEL_SIZE=base
```

Valores recomendados para `WHISPER_MODEL_SIZE`:

- `tiny` si priorizas velocidad
- `base` como equilibrio general
- `small` si quieres algo más fino y tu máquina aguanta

## 🛠️ Instalación

### Local

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

El proyecto ya incluye `Dockerfile` y `docker-compose.yml`.

```bash
docker compose up -d --build
```

El `docker-compose.yml` actual usa recarga automática de `uvicorn` sobre `app/`, lo que facilita iterar en desarrollo.

## 📦 Dependencias importantes

- `ffmpeg`
- `yt-dlp`
- `deep-translator`
- `gTTS`
- `faster-whisper`

`ffmpeg` es importante para:

- mejorar audio en `/music`
- facilitar ciertos flujos de medios
- trabajar mejor con notas de voz y temporales

## 🤖 Comandos para BotFather

El archivo [BOTFATHER_COMMANDS.txt](\\192.168.1.46\Library\PYTHON\Agent\BOTFATHER_COMMANDS.txt) contiene la lista actualizada para copiarla directamente en BotFather.

## ✅ Estado actual

El bot soporta actualmente:

- comandos directos
- callbacks
- menús interactivos
- sesiones guiadas
- multiusuario por chat
- reproducción de vídeo y audio
- traducción de texto y voz

## 📝 Notas

- Si cambias dependencias, reconstruye el contenedor.
- Si añades nuevos comandos, actualiza también `BOTFATHER_COMMANDS.txt`.
- Si el bot parece seguir usando código viejo en Docker, recrea con:

```bash
docker compose up -d --build
```
