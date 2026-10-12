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

## CI/CD и ветки

Прямые коммиты в `master` нежелательны: feature-ветка → CI → PR → merge только после зелёных проверок → CD.

```bash
git checkout -b feature/my-change
# правки, коммиты
git push -u origin feature/my-change
gh pr create --base master --fill
# дождаться CI, затем:
gh pr merge --merge
```

| Workflow | Когда | Что делает |
|---|---|---|
| **CI** | любой push + PR в `master`/`main` | install, `compileall`, import check, `pytest`, Bandit, pip-audit |
| **CD** | только после успешного CI на `master`/`main` | SSH на VPS → reset, `pip install`, proxy/geo/updates, restart |

Интерфейс: вкладки **Лента** / **Дашборд**, интересные сверху по умолчанию, фильтры в выпадающем списке.

Feature-ветки и открытые PR **не деплоятся** на VPS.

### Автообновления ПО

- **Python / Actions**: Dependabot (`.github/dependabot.yml`) — еженедельные PR; в прод после CI и merge
- **ОС на VPS**: `unattended-upgrades` + daily timer `sec-news-system-update.timer`
- **GeoIP**: weekly timer `sec-news-geoip.timer`

### Secrets для CD (Settings → Secrets and variables → Actions)

| Secret | Пример | Обязателен |
|---|---|---|
| `DEPLOY_HOST` | `203.0.113.10` | да |
| `DEPLOY_USER` | `deploy` | да |
| `DEPLOY_SSH_KEY` | private key (весь PEM) | да |
| `DEPLOY_PORT` | `22` | нет |
| `DEPLOY_PATH` | `/opt/sec-news-aggregator` | нет |

Без `DEPLOY_HOST` CD просто пропускается (skipped), CI продолжает работать.

Первичная установка на сервер: `deploy/bootstrap-server.sh`.

## Reverse proxy + защита

Раскатывается **через CD** после успешного CI (`deploy/setup-proxy.sh` на VPS).

Без домена:
- `https://VPS_IP/` — HTTPS с self-signed сертификатом (браузер покажет предупреждение)
- `http://VPS_IP/` — только редирект на HTTPS

Что ставится автоматически:
- **Caddy** — reverse proxy на `127.0.0.1:8000`
- **UFW** — 22/80/443
- **Geo-IP (РФ)** — на 80/443 пускаются только российские диапазоны (`deploy/setup-geo-ru.sh`, обновление раз в неделю). SSH (22) **не** режется, чтобы CD с GitHub Actions продолжал работать
- **fail2ban** — бан IP после серии `AUTH_FAIL` в логах `sec-news`
- В приложении — лимит логина: **5 попыток / 10 минут** с одного IP

Если заходите из-за рубежа (или через зарубежный VPN) — сайт будет недоступен; SSH при этом остаётся.

Когда появится домен — можно будет переключить Caddy на Let's Encrypt.

## Деплой на VPS (вручную)

1. Скопировать/клонировать проект, создать venv, установить зависимости.
2. Выставить `.env` (сильный пароль, `APP_HOST=127.0.0.1`).
3. Запуск через systemd + reverse proxy (Caddy/Nginx) с TLS.
4. Рекомендуемый профиль: **4 GB RAM**.

Пример unit-файла: `deploy/sec-news.service`.

## Брендинг

Статика в `app/static/branding/`:

| Файл | Назначение |
|---|---|
| `logo-mark.png` | знак в шапке портала |
| `logo-horizontal.png` | горизонтальный логотип |
| `favicon.ico` / `favicon-*.png` / `apple-touch-icon.png` | иконки вкладки и PWA |
| `telegram-bot-avatar.jpg` / `.png` | аватар Telegram-бота (**ровно 640×360**) |

Аватар бота API не ставит сам — в [@BotFather](https://t.me/BotFather): `/setuserpic` → выбрать бота → загрузить `app/static/branding/telegram-bot-avatar.jpg` (размер строго 640×360).

## Заметки по переводу

- Локальный LibreTranslate на 2–4 GB не рекомендуется.
- DeepL Free API сейчас по сути с разовым лимитом — не как основной вариант.
- MyMemory: укажите `MYMEMORY_EMAIL` для лимита ~50 000 символов/день.
