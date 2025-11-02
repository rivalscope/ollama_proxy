# Ollama Proxy

Secure proxy for Ollama with token-based authentication and multi-backend support.

## Features

- 🔐 Token authentication
- 🎯 Multiple Ollama backends
- 🔄 Full API support (streaming included)
- 🐳 Docker ready

## Quick Start

**1. Install dependencies:**

```bash
pip install -r requirements.txt
```

**2. Configure environment:**

```bash
cp .env.example .env
# Edit .env and configure:
# - API_TOKEN: Authentication token (required for security)
# - OLLAMA_INSTANCES: Backend instances (format: name:host:port)
# - HOST: Server bind address (0.0.0.0 = all interfaces)
# - PORT: Server port
# - CONTAINER_MAPPING: Docker port mapping (host:container)
# - DEBUG: Enable debug logging and auto-reload
```

**3. Run:**

```bash
# Python
python main.py

# Docker
docker compose up -d
```

## Usage

All requests require `Authorization: Bearer <token>` header.

**List models:**

```bash
curl -H "Authorization: Bearer your-token" \
  http://localhost:8000/api/tags
```

**Generate (default backend):**

```bash
curl -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma3:1b", "prompt": "Hello!", "stream": false}' \
  http://localhost:8000/api/generate
```

**Use specific backend:**

```bash
# If you have: OLLAMA_INSTANCES=ollama1:host1:11434,ollama2:host2:11434
curl -H "Authorization: Bearer your-token" \
  http://localhost:8000/ollama2/api/generate
```

## Configuration

| Variable           | Default                   | Description                      |
| ------------------ | ------------------------- | -------------------------------- |
| `API_TOKEN`        | None (⚠️ required)        | Authentication token             |
| `OLLAMA_INSTANCES` | `default:localhost:11434` | `name:host:port,name2:host:port` |
| `HOST`             | `0.0.0.0`                 | Server host                      |
| `PORT`             | `8000`                    | Server port                      |
| `DEBUG`            | `false`                   | Enable debug mode                |

**Instance examples:**

- `default:localhost:11434` - Local
- `remote:192.168.1.100:11434` - Remote LAN
- `cloud:llm.flowfoundry.ai:443` - Cloudflare Tunnel

All Ollama API endpoints are supported: `/api/tags`, `/api/generate`, `/api/chat`, `/api/embeddings`, etc.

## Python Example

```python
import requests

headers = {"Authorization": "Bearer your-token"}
response = requests.post(
    "http://localhost:8000/api/generate",
    headers=headers,
    json={"model": "gemma3:1b", "prompt": "Hello!", "stream": False}
)
print(response.json())
```

## JavaScript Example

```javascript
fetch("http://localhost:8000/api/generate", {
  method: "POST",
  headers: {
    Authorization: "Bearer your-token",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "gemma3:1b",
    prompt: "Hello!",
    stream: false,
  }),
})
  .then((r) => r.json())
  .then(console.log);
```

## Troubleshooting

**Connection refused:** Check Ollama is running on configured host:port

**Authentication error:** Verify `Authorization` header matches `API_TOKEN` in `.env`

**Port in use:** Change `PORT` in `.env` or kill process: `lsof -ti:8000 | xargs kill -9`

## License

MIT
