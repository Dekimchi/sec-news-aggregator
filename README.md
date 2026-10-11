# sec-news-aggregator

Self-hosted агрегатор практических новостей по ИБ (offensive / defensive) с мультифильтрами и опциональным переводом на русский через бесплатный MyMemory API.

Оптимизирован под VPS **1 vCPU / 4 GB RAM / 30 GB**: один процесс Python, SQLite, без Docker/Redis/локальных LLM.

## Стек

- Python 3.10+, FastAPI, Jinja2, APScheduler
- SQLite (WAL)
- HTTP Basic Auth
- Перевод: MyMemory (бесплатно; до ~50k символов/день с email в `MYMEMORY_EMAIL`)

## Быстрый старт (Windows / Linux)

```bash
cd sec-news-aggregator
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # или cp .env.example .env
```

Перед запуском обязательно смените в `.env`:
- `APP_SECRET` — длинная случайная строка
- `BASIC_AUTH_PASSWORD` — сильный пароль
- желательно `MYMEMORY_EMAIL` для лимита перевода

```bash
python run.py
```

Откройте http://127.0.0.1:8000 — логин/пароль из `.env`.
Не коммитьте `.env` и файлы `data/*.db`.

При старте и далее каждые `FETCH_INTERVAL_HOURS` часов сервис тянет RSS из `app/sources.yaml`, классифицирует, отфильтровывает legislation и переводит до 20 новых карточек за цикл (квота). Остальное можно перевести кнопкой на странице статьи.

## Фильтры

Одновременно: направление, тип контента (включая `incident_report`), технологии, источник, поиск, наличие RU-перевода, показ/скрытие законодательства.

Хранение: только последние `RETENTION_DAYS` дней (по умолчанию 7) — старые записи удаляются при каждом сборе.

## Деплой на VPS (кратко)

1. Скопировать проект, создать venv, установить зависимости.
2. Выставить `.env` (сильный пароль, `APP_HOST=127.0.0.1`).
3. Запуск через systemd + reverse proxy (Caddy/Nginx) с TLS и basic auth на proxy *или* встроенный basic auth приложения.
4. Рекомендуемый профиль: **4 GB RAM**.

Пример unit-файла: `deploy/sec-news.service`.

## Заметки по переводу

- Локальный LibreTranslate на 2–4 GB не рекомендуется.
- DeepL Free API сейчас по сути с разовым лимитом — не как основной вариант.
- MyMemory: укажите `MYMEMORY_EMAIL` для лимита ~50 000 символов/день.
