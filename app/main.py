from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import (
    LoginRequired,
    login_form_handler,
    login_redirect,
    logout_response,
    require_user,
)
from app.cluster import extract_cves
from app.config import get_settings
from app.db import (
    connect,
    count_articles,
    dashboard_stats,
    distinct_sources,
    get_article,
    get_articles_by_ids,
    get_ingest_run,
    list_articles,
    list_cluster_members,
    list_hot_for_digest,
    list_ingest_runs,
    update_translation,
)
from app.flash import FLASH_COOKIE, attach_flash, redirect_with_flash
from app.ingest import IngestBusy, ingest_once
from app.labels import (
    CONTENT_TYPE_LABELS,
    DIRECTION_LABELS,
    TECHNOLOGY_LABELS,
    label_content_type,
    label_direction,
    label_technology,
)
from app.notify import send_daily_digest
from app.scoring import HOT_STRONG_THRESHOLD, HOT_THRESHOLD, interest_tier
from app.security import (
    CSRF_COOKIE,
    get_or_create_csrf,
    safe_next_url,
    set_csrf_cookie,
    validate_csrf,
)
from app.translate import TranslateRateLimited, translate_article_fields
from app.user_data import (
    delete_preset,
    get_preset,
    list_bookmarked_articles,
    list_presets,
    save_preset,
    set_feedback,
    toggle_bookmark,
    toggle_read,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("sec-news")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["label_direction"] = label_direction
templates.env.filters["label_content_type"] = label_content_type
templates.env.filters["label_technology"] = label_technology
templates.env.globals["interest_tier"] = interest_tier
templates.env.globals["HOT_THRESHOLD"] = HOT_THRESHOLD
templates.env.globals["HOT_STRONG_THRESHOLD"] = HOT_STRONG_THRESHOLD
scheduler = AsyncIOScheduler()

DIRECTIONS = list(DIRECTION_LABELS.keys())
CONTENT_TYPES = list(CONTENT_TYPE_LABELS.keys())
TECHNOLOGIES = list(TECHNOLOGY_LABELS.keys())
DEFAULT_SORT = "interest"
SORT_OPTIONS = {
    "newest": "Сначала новые",
    "oldest": "Сначала старые",
    "source": "По источнику",
}
_CVE_QUERY = re.compile(r"^\s*(CVE-\d{4}-\d+)\s*$", re.I)

WEAK_SECRETS = {"", "change-me", "dev-secret-change-on-server", "secnews"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.app_secret in WEAK_SECRETS or settings.basic_auth_password in WEAK_SECRETS:
        log.warning(
            "Weak APP_SECRET / BASIC_AUTH_PASSWORD detected. "
            "Change them in .env before exposing the service."
        )
    db = await connect()
    await db.close()

    async def _job():
        try:
            await ingest_once(allow_wait=False, trigger="scheduled")
        except IngestBusy:
            log.info("Scheduled ingest skipped: already running")
        except Exception:  # noqa: BLE001
            log.exception("Scheduled ingest failed")

    async def _digest_job():
        try:
            db = await connect()
            try:
                items = await list_hot_for_digest(
                    db,
                    hours=24,
                    limit=10,
                    min_score=settings.brief_min_score,
                )
            finally:
                await db.close()
            await send_daily_digest(items)
        except Exception:  # noqa: BLE001
            log.exception("Daily digest failed")

    scheduler.add_job(
        _job,
        "interval",
        hours=settings.fetch_interval_hours,
        id="ingest",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(seconds=3),
    )
    if settings.telegram_digest_enabled and settings.telegram_bot_token:
        hour = max(0, min(23, int(settings.telegram_digest_hour_utc)))
        scheduler.add_job(
            _digest_job,
            "cron",
            hour=hour,
            minute=5,
            id="digest",
            replace_existing=True,
            max_instances=1,
        )
        log.info("Telegram digest scheduled at %02d:05 UTC", hour)
    scheduler.start()
    log.info("Scheduler started: every %s hours", settings.fetch_interval_hours)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="sec-news-aggregator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    attach_flash(request)
    csrf = get_or_create_csrf(request)
    request.state.csrf_token = csrf
    response = await call_next(request)
    if not request.cookies.get(CSRF_COOKIE):
        set_csrf_cookie(response, csrf)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "img-src 'self' data:; base-uri 'self'; form-action 'self'",
    )
    if request.cookies.get(FLASH_COOKIE) and getattr(request.state, "flash", None):
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


@app.exception_handler(LoginRequired)
async def _login_required(_: Request, exc: LoginRequired):
    return login_redirect(exc)


def _multi(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    cleaned = [v for v in values if v]
    return cleaned or None


def _csrf_or_flash(request: Request, csrf_token: str | None, fallback: str = "/"):
    if validate_csrf(request, csrf_token):
        return None
    return redirect_with_flash(fallback, "Сессия устарела, обновите страницу и повторите", "error")


def _feed_query_string(
    *,
    page: int | None = None,
    q: str = "",
    cve: str = "",
    sort: str = DEFAULT_SORT,
    translated: str = "",
    bookmarks: str = "",
    hide_read: str = "",
    directions: list[str] | None = None,
    content_types: list[str] | None = None,
    technologies: list[str] | None = None,
    sources: list[str] | None = None,
) -> str:
    pairs: list[tuple[str, str]] = []
    if page and page > 1:
        pairs.append(("page", str(page)))
    if q:
        pairs.append(("q", q))
    if cve:
        pairs.append(("cve", cve))
    if sort and sort != DEFAULT_SORT:
        pairs.append(("sort", sort))
    if translated:
        pairs.append(("translated", translated))
    if bookmarks:
        pairs.append(("bookmarks", bookmarks))
    if hide_read:
        pairs.append(("hide_read", hide_read))
    for d in directions or []:
        pairs.append(("direction", d))
    for t in content_types or []:
        pairs.append(("content_type", t))
    for t in technologies or []:
        pairs.append(("technology", t))
    for s in sources or []:
        pairs.append(("source", s))
    return urlencode(pairs)


def _article_export_payload(article: dict[str, Any], members: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": article["id"],
        "title": article.get("title_ru") or article.get("title"),
        "title_original": article.get("title"),
        "summary": article.get("summary_ru") or article.get("summary"),
        "brief_ru": article.get("brief_ru"),
        "url": article.get("url"),
        "source": article.get("source_name"),
        "published_at": article.get("published_at") or article.get("fetched_at"),
        "direction": article.get("direction"),
        "content_type": article.get("content_type"),
        "technologies": article.get("technologies") or [],
        "interest_score": article.get("interest_score"),
        "cves": extract_cves(f"{article.get('title') or ''} {article.get('summary') or ''}"),
        "cluster": [
            {
                "id": m["id"],
                "source": m.get("source_name"),
                "title": m.get("title_ru") or m.get("title"),
                "url": m.get("url"),
            }
            for m in (members or [])
            if m["id"] != article["id"]
        ],
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: Annotated[str, Query()] = "/",
):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": safe_next_url(next)},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
    csrf_token: Annotated[str | None, Form()] = None,
):
    return await login_form_handler(request, username, password, next, csrf_token)


@app.post("/logout")
async def logout(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
):
    bad = _csrf_or_flash(request, csrf_token, "/login")
    if bad:
        return bad
    return logout_response()


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    _: Annotated[str, Depends(require_user)],
    direction: Annotated[list[str] | None, Query()] = None,
    content_type: Annotated[list[str] | None, Query()] = None,
    technology: Annotated[list[str] | None, Query()] = None,
    source: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    cve: Annotated[str | None, Query()] = None,
    translated: Annotated[str | None, Query()] = None,
    bookmarks: Annotated[str | None, Query()] = None,
    hide_read: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = DEFAULT_SORT,
    page: Annotated[int, Query(ge=1)] = 1,
):
    if sort not in SORT_OPTIONS and sort != DEFAULT_SORT:
        sort = DEFAULT_SORT

    translated_only = None
    if translated == "yes":
        translated_only = True
    elif translated == "no":
        translated_only = False

    q_value = q.strip() if q else ""
    cve_value = (cve or "").strip().upper()
    m = _CVE_QUERY.match(q_value)
    if m and not cve_value:
        cve_value = m.group(1).upper()
        q_value = ""

    limit = 40
    offset = (page - 1) * limit
    selected_directions = direction or []
    selected_content_types = content_type or []
    selected_technologies = technology or []
    selected_sources = source or []
    bookmarks_only = bookmarks == "1"
    hide_read_flag = hide_read == "1"

    db = await connect()
    try:
        articles = await list_articles(
            db,
            directions=_multi(direction),
            content_types=_multi(content_type),
            technologies=_multi(technology),
            source_ids=_multi(source),
            hide_legislation=True,
            q=q_value or None,
            cve=cve_value or None,
            translated_only=translated_only,
            bookmarked_only=bookmarks_only,
            hide_read=hide_read_flag,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        total = await count_articles(db, hide_legislation=True)
        sources = await distinct_sources(db)
        presets = await list_presets(db)
    finally:
        await db.close()

    qs_kwargs = dict(
        q=q_value,
        cve=cve_value,
        sort=sort,
        translated=translated or "",
        bookmarks="1" if bookmarks_only else "",
        hide_read="1" if hide_read_flag else "",
        directions=selected_directions,
        content_types=selected_content_types,
        technologies=selected_technologies,
        sources=selected_sources,
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_nav": "bookmarks" if bookmarks_only else "feed",
            "articles": articles,
            "sources": sources,
            "presets": presets,
            "directions": DIRECTIONS,
            "content_types": CONTENT_TYPES,
            "technologies": TECHNOLOGIES,
            "sort_options": SORT_OPTIONS,
            "selected_directions": selected_directions,
            "selected_content_types": selected_content_types,
            "selected_technologies": selected_technologies,
            "selected_sources": selected_sources,
            "q": q_value,
            "cve": cve_value,
            "translated": translated or "",
            "bookmarks": bookmarks_only,
            "hide_read": hide_read_flag,
            "sort": sort,
            "page": page,
            "has_next": len(articles) == limit,
            "total": total,
            "prev_qs": _feed_query_string(page=page - 1 if page > 1 else None, **qs_kwargs),
            "next_qs": _feed_query_string(page=page + 1, **qs_kwargs),
        },
    )


@app.get("/article/{article_id}", response_class=HTMLResponse)
async def article_page(
    request: Request,
    article_id: int,
    _: Annotated[str, Depends(require_user)],
):
    db = await connect()
    try:
        article = await get_article(db, article_id)
        members = []
        if article and article.get("cluster_id"):
            members = await list_cluster_members(db, article["cluster_id"])
        from app.user_data import attach_states

        if article:
            await attach_states(db, [article])
    finally:
        await db.close()
    if not article:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "article.html",
        {
            "active_nav": "feed",
            "article": article,
            "cluster_members": [m for m in members if m["id"] != article_id],
            "cves": extract_cves(f"{article.get('title') or ''} {article.get('summary') or ''}"),
        },
    )


@app.get("/article/{article_id}/export.json")
async def export_article_json(
    article_id: int,
    _: Annotated[str, Depends(require_user)],
):
    db = await connect()
    try:
        article = await get_article(db, article_id)
        members = await list_cluster_members(db, article["cluster_id"]) if article and article.get("cluster_id") else []
    finally:
        await db.close()
    if not article:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(_article_export_payload(article, members))


@app.get("/article/{article_id}/export.md")
async def export_article_md(
    article_id: int,
    _: Annotated[str, Depends(require_user)],
):
    db = await connect()
    try:
        article = await get_article(db, article_id)
        members = await list_cluster_members(db, article["cluster_id"]) if article and article.get("cluster_id") else []
    finally:
        await db.close()
    if not article:
        return PlainTextResponse("Not found", status_code=404)
    payload = _article_export_payload(article, members)
    lines = [
        f"# {payload['title']}",
        "",
        f"- Источник: {payload['source']}",
        f"- Дата: {payload['published_at']}",
        f"- Score: {payload['interest_score']}",
        f"- URL: {payload['url']}",
    ]
    if payload["cves"]:
        lines.append(f"- CVE: {', '.join(payload['cves'])}")
    if payload.get("brief_ru"):
        lines.extend(["", "## Brief", "", payload["brief_ru"]])
    if payload.get("summary"):
        lines.extend(["", "## Summary", "", payload["summary"] or ""])
    if payload["cluster"]:
        lines.extend(["", "## Другие источники", ""])
        for m in payload["cluster"]:
            lines.append(f"- {m['source']}: [{m['title']}]({m['url']})")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/markdown; charset=utf-8")


@app.get("/export/bookmarks.json")
async def export_bookmarks_json(_: Annotated[str, Depends(require_user)]):
    db = await connect()
    try:
        ids = await list_bookmarked_articles(db)
        articles = await get_articles_by_ids(db, ids)
    finally:
        await db.close()
    return JSONResponse([_article_export_payload(a) for a in articles])


@app.post("/article/{article_id}/translate")
async def translate_one(
    request: Request,
    article_id: int,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
):
    bad = _csrf_or_flash(request, csrf_token, f"/article/{article_id}")
    if bad:
        return bad

    db = await connect()
    try:
        article = await get_article(db, article_id)
    finally:
        await db.close()

    if not article:
        return redirect_with_flash("/", "Статья не найдена", "error")

    try:
        title_ru, summary_ru = await translate_article_fields(
            article["title"],
            article.get("summary"),
        )
    except TranslateRateLimited:
        return redirect_with_flash(
            f"/article/{article_id}",
            "Перевод временно недоступен (лимит API). Попробуйте позже.",
            "error",
        )

    if title_ru or summary_ru:
        db = await connect()
        try:
            await update_translation(db, article_id, title_ru, summary_ru)
        finally:
            await db.close()
        return redirect_with_flash(f"/article/{article_id}", "Перевод выполнен", "ok")
    return redirect_with_flash(f"/article/{article_id}", "Не удалось получить перевод", "error")


@app.post("/article/{article_id}/bookmark")
async def bookmark_toggle(
    request: Request,
    article_id: int,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
    next: Annotated[str, Form()] = "/",
):
    bad = _csrf_or_flash(request, csrf_token, safe_next_url(next))
    if bad:
        return bad
    db = await connect()
    try:
        on = await toggle_bookmark(db, article_id)
    finally:
        await db.close()
    return redirect_with_flash(
        safe_next_url(next),
        "В закладках" if on else "Убрано из закладок",
        "ok",
    )


@app.post("/article/{article_id}/read")
async def read_toggle(
    request: Request,
    article_id: int,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
    next: Annotated[str, Form()] = "/",
):
    bad = _csrf_or_flash(request, csrf_token, safe_next_url(next))
    if bad:
        return bad
    db = await connect()
    try:
        on = await toggle_read(db, article_id)
    finally:
        await db.close()
    return redirect_with_flash(
        safe_next_url(next),
        "Отмечено прочитанным" if on else "Снова непрочитанное",
        "ok",
    )


@app.post("/article/{article_id}/feedback")
async def feedback_set(
    request: Request,
    article_id: int,
    _: Annotated[str, Depends(require_user)],
    value: Annotated[int, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    next: Annotated[str, Form()] = "/",
):
    bad = _csrf_or_flash(request, csrf_token, safe_next_url(next))
    if bad:
        return bad
    db = await connect()
    try:
        new_val = await set_feedback(db, article_id, value)
    finally:
        await db.close()
    msg = {1: "Полезное — поднято в ранжировании", -1: "Мимо — опущено", 0: "Оценка сброшена"}[new_val]
    return redirect_with_flash(safe_next_url(next), msg, "ok")


@app.post("/presets/save")
async def presets_save(
    request: Request,
    _: Annotated[str, Depends(require_user)],
    name: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    params_json: Annotated[str, Form()] = "{}",
):
    bad = _csrf_or_flash(request, csrf_token, "/")
    if bad:
        return bad
    try:
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            raise ValueError("params must be object")
    except (json.JSONDecodeError, ValueError):
        return redirect_with_flash("/", "Некорректные параметры пресета", "error")
    db = await connect()
    try:
        await save_preset(db, name, params)
    except ValueError:
        return redirect_with_flash("/", "Укажите имя пресета", "error")
    finally:
        await db.close()
    return redirect_with_flash("/", f"Пресет «{name.strip()}» сохранён", "ok")


@app.post("/presets/{preset_id}/delete")
async def presets_delete(
    request: Request,
    preset_id: int,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
):
    bad = _csrf_or_flash(request, csrf_token, "/")
    if bad:
        return bad
    db = await connect()
    try:
        await delete_preset(db, preset_id)
    finally:
        await db.close()
    return redirect_with_flash("/", "Пресет удалён", "ok")


@app.get("/presets/{preset_id}/apply")
async def presets_apply(
    preset_id: int,
    _: Annotated[str, Depends(require_user)],
    scope: Annotated[str | None, Query()] = None,
):
    db = await connect()
    try:
        preset = await get_preset(db, preset_id)
    finally:
        await db.close()
    if not preset:
        return redirect_with_flash("/", "Пресет не найден", "error")
    params = preset["params"]
    use_bookmarks = scope == "bookmarks"
    qs = _feed_query_string(
        q=params.get("q") or "",
        cve=params.get("cve") or "",
        sort=params.get("sort") or DEFAULT_SORT,
        translated=params.get("translated") or "",
        bookmarks="1" if use_bookmarks else "",
        hide_read=params.get("hide_read") or "",
        directions=params.get("direction") or [],
        content_types=params.get("content_type") or [],
        technologies=params.get("technology") or [],
        sources=params.get("source") or [],
    )
    if not qs and use_bookmarks:
        return RedirectResponse(url="/?bookmarks=1", status_code=303)
    return RedirectResponse(url=f"/?{qs}" if qs else "/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    _: Annotated[str, Depends(require_user)],
    run: Annotated[int | None, Query()] = None,
):
    db = await connect()
    try:
        stats = await dashboard_stats(db)
        runs = await list_ingest_runs(db, limit=50)
        selected = None
        if run:
            selected = await get_ingest_run(db, run)
        if selected is None and runs:
            selected = runs[0]
    finally:
        await db.close()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_nav": "dashboard",
            "stats": stats,
            "runs": runs,
            "selected": selected,
            "highlight": run,
        },
    )


@app.get("/updates", response_class=HTMLResponse)
async def updates_redirect():
    return RedirectResponse(url="/dashboard", status_code=301)


@app.get("/updates/{run_id}", response_class=HTMLResponse)
async def update_detail_redirect(run_id: int):
    return RedirectResponse(url=f"/dashboard?run={run_id}", status_code=301)


@app.post("/admin/refresh")
async def refresh(
    request: Request,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
):
    bad = _csrf_or_flash(request, csrf_token, "/dashboard")
    if bad:
        return bad
    try:
        stats = await ingest_once(allow_wait=True, trigger="manual")
    except IngestBusy:
        return redirect_with_flash(
            "/dashboard",
            "Сбор новостей уже выполняется — откройте дашборд чуть позже",
            "info",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Manual refresh failed")
        return redirect_with_flash("/dashboard", f"Ошибка обновления: {exc}", "error")
    run_id = stats.get("run_id")
    failed = stats.get("failed_sources") or []
    msg = (
        f"Обновление завершено: новых {stats['inserted']}, "
        f"переведено {stats['translated']}"
    )
    if failed:
        msg += f". Недоступны: {', '.join(failed)}"
        level = "info"
    else:
        level = "ok"
    target = f"/dashboard?run={run_id}" if run_id else "/dashboard"
    return redirect_with_flash(target, msg, level)


@app.post("/admin/digest-now")
async def digest_now(
    request: Request,
    _: Annotated[str, Depends(require_user)],
    csrf_token: Annotated[str | None, Form()] = None,
):
    bad = _csrf_or_flash(request, csrf_token, "/dashboard")
    if bad:
        return bad
    settings = get_settings()
    db = await connect()
    try:
        items = await list_hot_for_digest(
            db,
            hours=24,
            limit=10,
            min_score=settings.brief_min_score,
        )
    finally:
        await db.close()
    ok = await send_daily_digest(items)
    if ok:
        return redirect_with_flash("/dashboard", f"Дайджест отправлен ({len(items)} шт.)", "ok")
    return redirect_with_flash(
        "/dashboard",
        "Не удалось отправить дайджест — проверьте TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID",
        "error",
    )


@app.get("/health")
async def health():
    return {"ok": True}
