<div align="center">
  <img src="static/logo.png" alt="Uptimium Logo" width="256">
</div>

[![Uptimium](https://img.shields.io/badge/Uptimium-v1.0.1-success)](https://git.isaweye.ink/isaweyed/uptimium)
[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg)](http://www.MIT.net/)
[![Demo](https://img.shields.io/badge/🚀-Live_Demo-9cf?style=flat-square)](https://status.isaweye.ink)

> 💡 *"Simple monitoring solution that just works"*  
> — Some random guy

Simple monitoring that does what it should. No magic, just working code. And yes, it has emojis! 🎉

## 🎯 Features

- 🚀 Monitors everything...
- 📈 Beautiful graphs (because monitoring without graphs is just logging)
- 🗂️ Organized by categories
- 🔔 Check history
- ⚡ Blazing fast!
- 🦄 Easy to set up (or not)

## 🛠️ Quick Start

1. Clone the repository:
   ```bash
   git clone https://git.isaweye.ink/isaweyed/uptimium.git
   cd uptimium
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure your monitors in `config/monitors.yml` (examples included)

4. Run:
   ```bash
   python app.py  # for development
   ```

   Or with gunicorn:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```
   
   Or with uvicorn:
   ```bash
   uvicorn asgi:app --host 0.0.0.0 --port 5000
   ```

### 🐳 Docker Setup

1. Build and run the container:
   ```bash
   docker-compose up --build
   ```

2. For background mode:
   ```bash
   docker-compose up -d
   ```

3. Stop the container:
   ```bash
   docker-compose down
   ```

4. View logs:
   ```bash
   docker-compose logs -f
   ```

Application will be available at: http://localhost:5000

## 🎮 What can you monitor?

- **http/https** — websites and APIs
- **tcp** — any TCP services (SSH, databases, etc.)
- **udp** — because why not?
- **minecraft** — just because we can

*🔌 Want to add another protocol? Feel free to submit a PR!*

## 🔌 API

- `GET /` — main dashboard with graphs
- `GET /api/status` — current status of all monitors (JSON)
- `GET /api/monitor/<monitor_id>/history` — history of a specific monitor
- `GET /api/categories` — list of categories
- `GET /api/availability` — availability of all monitors

*🤓 Example request:*
```bash
curl https://status.isaweye.ink/api/status
```

## 📜 License

This project is licensed under the MIT License - feel free to use it however you want.

## 🤝 Want to contribute?

1. Fork the repository
2. Make your changes
3. Submit a pull request
4. 🍻

---
