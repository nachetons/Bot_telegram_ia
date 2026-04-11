# 🤖 Jellyfin AI Agent - Telegram Bot

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

Turn your **Jellyfin server** into an intelligent, AI-powered Telegram assistant.

This project combines a **FastAPI backend**, an **LLM-based agent**, and **Jellyfin integration** to provide a seamless media browsing and streaming experience directly inside Telegram.

---

## 🚀 Features

### 🧠 AI-Powered Agent
- Natural language understanding
- Intent classification (movies, weather, wiki, etc.)
- Context-aware responses

### 🎬 Jellyfin Integration
- Browse full library (movies & series)
- Interactive menus using inline buttons
- Callback-based navigation (no message spam)

### 📚 Scalable Library System
- Handles large libraries without breaking Telegram limits
- Pagination via callbacks
- Clean and responsive UX

### 🎧 Multi-Audio Streaming
- Detects available audio tracks automatically
- Language-based playback selection
- Supports multiple audio streams per media

### ⚡ Optimized Streaming
- HLS streaming (`master.m3u8`)
- Video stream copy (low CPU usage)
- Fast playback start
- Seek support inside Telegram player

### 🧰 Integrated Tools
- Image search
- Weather information
- Wikipedia queries
- Web scraping
- YouTube video search

---

## 📁 Project Structure

```bash
Agent/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    ├── router.py
    ├── config.py
    │
    ├── core/
    │   ├── callback_handler.py
    │   ├── router_intent.py
    │   ├── refiner.py
    │   ├── context_builder.py
    │   └── prompt.py
    │
    ├── services/
    │   ├── agent.py
    │   ├── llm_client.py
    │   ├── llm_client_cloud.py
    │   ├── llm_provider.py
    │   └── telegram_client.py
    │
    └── tools/
        ├── jellyfin.py
        ├── images.py
        ├── weather.py
        ├── wiki.py
        ├── web.py
        └── scraper.py

```
---

## ⚙️ Installation

### 1. Clone the repository

```bash
git clone https://github.com/youruser/jellyfin-ai-agent.git
cd jellyfin-ai-agent
```

2. Configuration
Create a .env file or configure app/config.py:
## 🔐 Environment Variables
```env
# === LLM Providers ===
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_URL=your_openrouter_url
OPENROUTER_MODEL=your_model_name

# === Local LLM (Optional) ===
LM_STUDIO_URL=http://localhost:1234
MODEL_NAME_LLM=your_local_model

# === GitHub (Optional) ===
GITHUB_TOKEN=your_github_token

# === Telegram ===
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# === Jellyfin ===
JELLYFIN_URL=http://your-server-ip:8096
JELLYFIN_API_KEY=your_jellyfin_api_key
JELLYFIN_USER_ID=your_user_id

# === YouTube (optional tuning) ===
YOUTUBE_MAX_HEIGHT=720

```
## 🐳 Docker Setup

This project includes Docker support for easy deployment.

### 📦 Dockerfile

```dockerfile
FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 📦 Docker-compose

```yaml
version: "3.9"

services:
  jellyfin-agent:
    build: .
    container_name: jellyfin-ai-agent
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
```

3. Run with Docker
docker-compose up -d --build

🤖 Usage
| Command           | Description             |
| ----------------- | ----------------------- |
| `/menu`           | Open main menu          |
| `/library`        | Browse full library     |
| `/video <name>`   | Search and play a movie |
| `/img <query>`    | Search images           |
| `/wiki <query>`   | Wikipedia search        |
| `/weather <city>` | Get weather information |
| `/youtube <query>` | Busca el mejor resultado de YouTube y lo envía a Telegram |
| `/music <query>` | Busca música y la envía como audio directamente a Telegram |
| `/music buscar <query>` | Muestra varias opciones musicales |
| `/music fav <query>` | Guarda una canción en favoritos |
| `/music favs` | Lista tus favoritos musicales |
| `/music recomendar` | Sugiere música según tu historial y favoritos |
| `/playlist crear <nombre>` | Crea una playlist local |
| `/playlist add <nombre> \| <canción>` | Añade una canción a una playlist |
| `/playlist listas` | Lista las playlists creadas |
| `/playlist remove <nombre> \| <posición>` | Elimina una canción de una playlist |
| `/playlist borrar <nombre>` | Elimina una playlist completa |
| `/playlist ver <nombre>` | Muestra una playlist |
| `/playlist play <nombre>` | Reproduce el primer tema de una playlist |


Natural Language Examples

```bash
Ponme una película de terror
I want to watch Interstellar
¿Qué tiempo hace en Madrid?
/youtube Waka Waka Shakira
```

`/youtube <query>` ahora intenta:
- buscar el resultado más probable
- priorizar vídeos con más visualizaciones y señales de oficialidad
- descargarlo temporalmente
- enviarlo como vídeo nativo de Telegram

La capa `/music` reutiliza esa lógica para construir una biblioteca musical local por usuario con:
- historial
- favoritos
- playlists en JSON
- recomendaciones básicas según uso

En `/music`, el bot prioriza audio y envía pistas reproducibles en Telegram usando `sendAudio`.

The agent automatically:

Detects intent
Selects the appropriate tool
Returns interactive results
🧠 Architecture Overview
User → Telegram → FastAPI Webhook
                    ↓
                 Router
                    ↓
                  Agent
                    ↓
          Intent Router (LLM)
                    ↓
                  Tools
                    ↓
           Telegram Client

---
🎬 Streaming Details

To ensure compatibility with Telegram's internal player:

📡 Protocol
- Uses HLS (master.m3u8) for proper duration detection
🎧 Audio Handling
- Uses AudioStreamIndex to select language
- Forces AAC for compatibility
⚡ Performance
- AllowVideoStreamCopy=true to avoid transcoding
🛡️ Stability
- Includes MediaSourceId to prevent playback errors

---
⚠️ Telegram Limitations
- Maximum ~4096 characters per message
- Limit on inline buttons per message

Handled via:
- Pagination using callbacks
- Structured menus

---
🛠️ Roadmap
- Advanced filtering (genre, year, rating)
- AI-based recommendations
- Continue watching feature
- Multi-user support
- Authentication system

🧑‍💻 Author
- Ignacio Pinto Rodriguez


