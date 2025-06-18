<div align="center">
  <img src="static/logo.png" alt="Uptimium Logo" width="256">
</div>

[![Uptimium](https://img.shields.io/badge/Uptimium-v1.0.0-success)](https://git.isaweye.ink/isaweyed/uptimium)
[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg)](http://www.MIT.net/)
[![Demo](https://img.shields.io/badge/🚀-Live_Demo-9cf?style=flat-square)](https://status.isaweye.ink)

> 💡 *"Простая рандомная хрень, которая взбрела в голову, но почему-то работает"*  
> — Какой-то мужик

Просто мониторинг, который делает то, что должен. Без лишней магии, но с костылями, которые работают. И да, тут есть смайлики! 🎉

## 🎯 Что умеет?

- 🚀 Мониторит всё подряд...
- 📈 Графики! Потому что без графиков — это не мониторинг
- 🗂️ Раскладывает всё по полочкам
- 🔔 Хранит историю проверок
- ⚡ Быстрый, как понос!
- 🦄 Прост в настройке (или нет)

## 🛠️ Как запустить?

1. Клонируем репозиторий (или качаем ZIP, мы не осуждаем):
   ```bash
   git clone https://git.isaweye.ink/isaweyed/uptimium.git
   cd uptimium
   ```

2. Ставим зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Настраиваем мониторинг в `monitors.yml` (там куча примеров)

4. Вперде:
   ```bash
   python app.py  # для разработки
   ```

   Или с gunicorn:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```
   
   Или с uvicorn:
   ```bash
   uvicorn asgi:app --host 0.0.0.0 --port 5000
   ```

### 🐳 Запуск через Docker

1. Соберите и запустите контейнер:
   ```bash
   docker-compose up --build
   ```

2. Для запуска в фоновом режиме:
   ```bash
   docker-compose up -d
   ```

3. Остановка контейнера:
   ```bash
   docker-compose down
   ```

4. Просмотр логов:
   ```bash
   docker-compose logs -f
   ```

Приложение будет доступно по адресу: http://localhost:5000

Данные мониторинга сохраняются в Docker volume `uptimium_data`.

## 🎮 Что можно мониторить?

- **http/https** — веб-сайты и API
- **tcp** — любые TCP-сервисы (SSH, базы данных, и т.д.)
- **udp** — ну да.
- **minecraft** — потому что почему бы и нет?

*🔌 Хотите добавить свой протокол? Дерзайте, пулл-реквесты приветствуются!*

## 🔌 API

- `GET /` — главная страничка с графиками
- `GET /api/status` — текущий статус всех мониторов (JSON)
- `GET /api/monitor/<monitor_id>/history` — история конкретного монитора
- `GET /api/categories` — список категорий

*🤓 Пример запроса:*
```bash
curl https://status.isaweye.ink/api/status
```

## 📜 Лицензия

Этот проект лицензирован по лицензии MIT — делайте что хотите.

## 🤝 Хотите "испачкаться"?

1. Форкните репозиторий
2. Сделайте изменения
3. Отправьте пулл-реквест
4. 🍻
