from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, httpx, asyncio, time as time_module, traceback
from datetime import datetime, timezone
from urllib.parse import quote

app = FastAPI()

APP_VERSION = "0.13"
SERVER_START_DT = datetime.now(timezone.utc)
SERVER_START_DATE = SERVER_START_DT.strftime("%d.%m.%y")
CONTACT_EMAILS = ["sldshr.confirmation@gmail.com", "sldshr.confirm@yandex.ru"]
BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

deleted_records, pinned_records, pending_records = set(), {}, {}
MAX_B64_LEN = 900000
PER_PAGE = 5
_RATE_BUCKETS, _LOGIN_FAILS = {}, {}

def _rate_ok(key, limit=60, window=60):
    now = time_module.time()
    lst = _RATE_BUCKETS.setdefault(key, [])
    lst[:] = [t for t in lst if now - t < window]
    if len(lst) >= limit: return False
    lst.append(now); return True

def _login_fails(ip):
    now = time_module.time()
    return len([t for t in _LOGIN_FAILS.get(ip, []) if now - t < 300])

def _login_fail(ip):
    now = time_module.time()
    lst = _LOGIN_FAILS.setdefault(ip, [])
    lst[:] = [t for t in lst if now - t < 300]
    lst.append(now)

def _login_clear(ip): _LOGIN_FAILS.pop(ip, None)

@app.middleware("http")
async def security_mw(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else "0.0.0.0"
    if path in ("/login", "/register", "/rpc"):
        if not _rate_ok(f"auth:{ip}", 60, 60):
            return Response("Too Many Requests", status_code=429)
    if path == "/login" and request.method == "POST":
        if _login_fails(ip) >= 10:
            return Response("Too many login attempts.", status_code=429, media_type="text/plain")
    try:
        response = await call_next(request)
    except Exception:
        traceback.print_exc()
        return Response("Internal Server Error", status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return HTMLResponse("<div style='text-align:center;padding:40px;font-family:sans-serif'><h2>Ошибка сервера</h2><a href='/home'>OK</a></div>", status_code=500)

# --- SVG ICON FACTORY ---
def svg(name, size=22, cls=""):
    I = {
        "home": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
        "user": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        "chart": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
        "message": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
        "bell": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
        "edit": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
        "logout": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
        "plus": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
        "x": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
        "link": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
        "pin": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
        "unpin": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/><line x1="3" y1="3" x2="21" y2="21"/></svg>',
        "trash": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
        "eye": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
        "eye_off": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
        "chev_l": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
        "chev_r": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
        "lock": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
        "check": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        "email": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>',
        "image": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
        "search": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
        "logo": f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    }
    return I.get(name, "")

def esc(v): return html.escape(str(v)) if v is not None else ""

def linkify(t):
    if not t: return ""
    return re.sub(r'(https?://[^\s]+)', r'<a href="#" class="ext-link" data-url="\1" onclick="showLinkWarning(event, this)">\1</a>', html.escape(t)).replace('\n', '<br>')

def valid_b64(s):
    if not s: return ""
    s = str(s)
    if len(s) > MAX_B64_LEN or not s.startswith("data:image/"): return ""
    return s

def _uptime(lang="ru"):
    d = datetime.now(timezone.utc) - SERVER_START_DT
    sec = int(d.total_seconds())
    d, rem = divmod(sec, 86400); h, rem = divmod(rem, 3600); m, s = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}{'д' if lang=='ru' else 'd'}")
    parts.append(f"{h:02d}:{m:02d}:{s:02d}")
    return " ".join(parts)

async def _fetch_user(nick):
    for sel in ('username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
                'username,description,sugges_rules,avatar_data,sugges_enabled',
                'username,description,sugges_rules,avatar_data',
                'username,description,sugges_rules',
                'username,description'):
        try:
            r = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nick).execute())
            if r.data: return r.data[0]
        except Exception: pass
    return None

async def _fetch_posts(nick):
    for sel in ('*', 'id,user_nickname,content,image_data,created_at,suggested_by,is_pinned'):
        try:
            r = await asyncio.to_thread(lambda: sb.table('posts').select(sel).eq('user_nickname', nick).execute())
            return r.data or []
        except Exception: pass
    return []

async def _fetch_suggestions(nick):
    try:
        r = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('author_nickname', nick).eq('status', 'pending').order('created_at', desc=True).execute())
        return r.data or []
    except Exception: return []

async def _fetch_home_posts(page=1, per_page=PER_PAGE, q="", author=""):
    offset = max(0, (page-1)*per_page); end = offset + per_page - 1
    sq = q.strip()[:100] if q else ""
    for vis in (True, False):
        for img in (True, False):
            try:
                cols = 'id,user_nickname,content,created_at,suggested_by'
                if img: cols += ',image_data'
                if vis: cols += ',visibility'
                qo = sb.table('posts').select(cols, count='exact')
                if vis: qo = qo.eq('visibility', 'public')
                if sq: qo = qo.ilike('content', f'%{sq}%')
                if author.strip(): qo = qo.eq('user_nickname', author.strip())
                qo = qo.order('created_at', desc=True).range(offset, end)
                r = await asyncio.to_thread(lambda: qo.execute())
                return r.data or [], (getattr(r, 'count', None) or len(r.data or []))
            except Exception: continue
    return [], 0

async def _stats_data():
    uc, pc, sc, lu = 0, 0, 0, None
    for tbl, field in [('users','nickname'), ('posts','id'), ('suggestions','id')]:
        try:
            r = await asyncio.to_thread(lambda: sb.table(tbl).select(field, count='exact').execute())
            c = getattr(r, 'count', None) or len(r.data or [])
            if tbl == 'users': uc = c
            elif tbl == 'posts': pc = c
            else: sc = c
        except Exception: pass
    try:
        r = await asyncio.to_thread(lambda: sb.table('posts').select('created_at').order('created_at', desc=True).limit(1).execute())
        if r.data: lu = r.data[0].get('created_at')
    except Exception: pass
    return uc, pc, sc, lu

def _sugg_enabled(u): return bool(u) and u.get('sugges_enabled') is not False
def _sugg_photo_enabled(u): return bool(u) and u.get('sugges_photo_enabled') is not False

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws):
        await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg):
        for c in self.active_connections:
            try: await c.send_json(msg)
            except: pass

manager = ConnectionManager()

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

@app.get("/manifest.json")
async def manifest():
    return JSONResponse({"name":"Solid Link","short_name":"SolidLink","start_url":"/home","display":"standalone","background_color":"#ffffff","theme_color":"#1d9bf0","icons":[{"src":"data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFkOWJmMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xMCAxM2E1IDUgMCAwIDAgNy41NC41NGwzLTNhNSA1IDAgMCAwLTcuMDctNy4wN2wtMS43MiAxLjcxIi8+PHBhdGggZD0iTTE0IDExYTUgNSAwIDAgMC03LjU0LS41NGwtMyAzYTUgNSAwIDAgMCA3LjA3IDcuMDdsMS43MS0xLjcxIi8+PC9zdmc+","sizes":"192x192","type":"image/svg+xml"}]}, headers={"Cache-Control":"public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = "self.addEventListener('install',(e)=>{e.waitUntil(caches.open('solid-v1').then(c=>c.addAll(['/home'])))});self.addEventListener('fetch',(e)=>{if(e.request.method!=='GET')return;e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)))})"
    return Response(content=js, media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})

@app.get("/api/og")
async def get_og(url: str):
    if not url.startswith("http"): return {"title":"","description":"","image":""}
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(url, timeout=5.0, follow_redirects=True)
            hc = r.text
            def gm(p):
                m = re.search(fr'<meta[^>]+(?:property|name)=["\']og:{p}["\'][^>]+content=["\']([^"\']*)["\']', hc, re.I)
                if not m: m = re.search(fr'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']og:{p}["\']', hc, re.I)
                return m.group(1) if m else ""
            t = gm("title")
            if not t:
                tm = re.search(r'<title>([^<]*)</title>', hc, re.I)
                if tm: t = tm.group(1)
            return {"title": t, "description": gm("description"), "image": gm("image")}
    except Exception: return {"title":"","description":"","image":""}

def hash_password(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
def verify_password(p, h):
    try:
        if len(h) == 64 and hashlib.sha256(p.encode()).hexdigest() == h: return True
        return bcrypt.checkpw(p.encode(), h.encode())
    except: return False

def get_csrf_token(r): return r.cookies.get("csrf_token") or secrets.token_hex(32)
def check_csrf(r, ft=None):
    ct = r.cookies.get("csrf_token")
    if not ct: return False
    ht = r.headers.get("X-CSRF-Token")
    return ct == ft or ct == ht

def set_csrf_cookie(res, t, r):
    secure = r.url.scheme == "https"
    res.set_cookie("csrf_token", t, httponly=True, samesite="lax", secure=secure, max_age=86400*365)

@app.exception_handler(RequestValidationError)
async def val_handler(req, exc):
    lang = req.cookies.get("lang", "ru")
    em = "Заполните все поля" if lang == "ru" else "Fill all fields"
    tok = get_csrf_token(req)
    r = HTMLResponse(auth_html(lang, em, tok), status_code=422)
    set_csrf_cookie(r, tok, req); return r

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

# --- LOCALES ---
LOCALES = {
    "ru": {
        "login": "Войти", "reg": "Регистрация", "username": "Имя пользователя", "nickname": "Никнейм",
        "password": "Пароль", "re_pass": "Повторите пароль", "captcha": "Я не робот",
        "register_btn": "Создать аккаунт", "login_btn": "Войти", "logout": "Выйти",
        "profile": "Профиль", "cabinet": "Личный кабинет", "home": "Главная", "stats": "Статистика",
        "suggestions": "Предложки", "edit_profile": "Редактировать", "bugreport": "Баг-репорт",
        "total_posts": "записей", "description": "Описание", "desc_placeholder": "Расскажите о себе...",
        "create_post": "Создать", "post_placeholder": "Что нового?", "my_posts": "Мои записи",
        "no_posts": "Записей пока нет...", "pin": "Закрепить", "unpin": "Открепить", "delete": "Удалить",
        "copy_link": "Ссылка", "confirm_delete": "Удалить запись?",
        "home_title": "Главная", "home_empty": "Постов нет...",
        "prev": "Назад", "next": "Вперёд", "page": "Стр.", "of": "из", "found": "всего",
        "search_q": "Поиск по тексту...", "search_author": "Автор",
        "post_visibility": "Видимость", "vis_public": "В ленту", "vis_private": "Только в профиль",
        "private_label": "Личное", "suggested_by": "Предложено:",
        "sugges_empty": "Предложек нет", "sugges_approve": "Принять", "sugges_reject": "Отклонить",
        "sugges_title": "Предложить пост для", "sugges_name": "Ваше имя",
        "sugges_content": "Текст поста", "sugges_send": "Отправить",
        "sugges_disabled": "Предложка отключена", "sugges_own": "Нельзя предложить себе",
        "sugges_enable": "Разрешить предложку", "sugges_photo_enable": "Разрешить фото",
        "rules": "Правила предложки", "rules_ph": "Напишите правила...",
        "attach_photo": "Прикрепить фото", "attach_avatar": "Сменить аватар",
        "save": "Сохранить", "cancel": "Отмена",
        "bugreport_title": "Баг-репорт", "bugreport_name": "Ваше имя", "bugreport_desc": "Опишите проблему",
        "bugreport_send": "Отправить", "bugreport_my": "Мои заявки",
        "privacy_title": "Политика конфиденциальности",
        "privacy_text": "1. Сбор данных. Мы собираем только ваш юзернейм, никнейм и хеш пароля.<br><br>2. Использование. Данные нужны для работы сайта и аутентификации.<br><br>3. Контент. Ваши записи хранятся на серверах Supabase.<br><br>4. Cookies. Для сессии и языка.<br><br>5. Права. Вы можете изменить или удалить данные в любое время.",
        "privacy_agree": "Принимаю", "privacy_link": "политику",
        "stats_title": "Статистика", "stats_users": "Пользователей", "stats_posts": "Записей",
        "stats_sugges": "Предложек", "stats_started": "Запуск", "stats_last": "Обновлено",
        "stats_uptime": "Аптайм", "stats_contacts": "Связь",
        "compose_title": "Новый пост", "publish": "Опубликовать",
        "toast_new": "Опубликовано!", "toast_copied": "Ссылка скопирована", "toast_copy_fail": "Ошибка копирования",
        "toast_approved": "Принято!", "toast_rejected": "Отклонено!",
        "toast_err": "Ошибка:", "toast_img": "Обработка фото...", "toast_img_ok": "Фото готово",
        "toast_img_err": "Ошибка фото", "toast_img_big": "Фото слишком большое",
        "ext_title": "Переход на сайт", "ext_desc": "Вы переходите:", "ext_go": "Перейти"
    },
    "en": {
        "login": "Sign in", "reg": "Sign up", "username": "Username", "nickname": "Nickname",
        "password": "Password", "re_pass": "Confirm password", "captcha": "I'm not a robot",
        "register_btn": "Create account", "login_btn": "Sign in", "logout": "Sign out",
        "profile": "Profile", "cabinet": "Cabinet", "home": "Home", "stats": "Stats",
        "suggestions": "Suggestions", "edit_profile": "Edit", "bugreport": "Bug report",
        "total_posts": "posts", "description": "Bio", "desc_placeholder": "Tell about yourself...",
        "create_post": "Post", "post_placeholder": "What's new?", "my_posts": "My posts",
        "no_posts": "No posts yet...", "pin": "Pin", "unpin": "Unpin", "delete": "Delete",
        "copy_link": "Copy", "confirm_delete": "Delete post?",
        "home_title": "Home", "home_empty": "No posts yet...",
        "prev": "Prev", "next": "Next", "page": "Page", "of": "of", "found": "found",
        "search_q": "Search text...", "search_author": "Author",
        "post_visibility": "Visibility", "vis_public": "Feed", "vis_private": "Only profile",
        "private_label": "Private", "suggested_by": "Suggested by:",
        "sugges_empty": "No suggestions", "sugges_approve": "Approve", "sugges_reject": "Reject",
        "sugges_title": "Suggest post for", "sugges_name": "Your name",
        "sugges_content": "Post text", "sugges_send": "Send",
        "sugges_disabled": "Suggestions disabled", "sugges_own": "Can't suggest to self",
        "sugges_enable": "Enable suggestions", "sugges_photo_enable": "Allow photos",
        "rules": "Suggestion rules", "rules_ph": "Write rules...",
        "attach_photo": "Attach photo", "attach_avatar": "Change avatar",
        "save": "Save", "cancel": "Cancel",
        "bugreport_title": "Bug report", "bugreport_name": "Your name", "bugreport_desc": "Describe issue",
        "bugreport_send": "Send", "bugreport_my": "My reports",
        "privacy_title": "Privacy Policy",
        "privacy_text": "1. Data. We collect only username, nickname and hashed password.<br><br>2. Usage. Data is used for authentication.<br><br>3. Content. Stored on Supabase.<br><br>4. Cookies. For session and language.<br><br>5. Rights. Edit or delete data anytime.",
        "privacy_agree": "Accept", "privacy_link": "privacy",
        "stats_title": "Stats", "stats_users": "Users", "stats_posts": "Posts",
        "stats_sugges": "Suggestions", "stats_started": "Started", "stats_last": "Updated",
        "stats_uptime": "Uptime", "stats_contacts": "Contacts",
        "compose_title": "New post", "publish": "Publish",
        "toast_new": "Published!", "toast_copied": "Link copied", "toast_copy_fail": "Copy failed",
        "toast_approved": "Approved!", "toast_rejected": "Rejected!",
        "toast_err": "Error:", "toast_img": "Processing...", "toast_img_ok": "Photo ready",
        "toast_img_err": "Photo error", "toast_img_big": "Photo too big",
        "ext_title": "External site", "ext_desc": "You're going to:", "ext_go": "Continue"
    }
}

def t(k, l="ru"): return LOCALES.get(l, LOCALES["ru"]).get(k, k)

def fmt_date(iso):
    if not iso: return ""
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%y %H:%M")
    except: return iso[:10]

def get_css():
    return f"""
    <link href="{BOOTSTRAP_CSS}" rel="stylesheet">
    <style>
    :root {{
        --tw-blue: #1d9bf0; --tw-blue-hover: #1a8cd8;
        --tw-black: #0f1419; --tw-gray: #536471;
        --tw-border: #eff3f4; --tw-border2: #cfd9de;
        --tw-hover: #f7f9f9; --tw-danger: #f4212e;
        --tw-private: #7856ff;
    }}
    * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
    html, body {{ margin: 0; padding: 0; background: #fff; color: var(--tw-black); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.4; }}
    a {{ color: var(--tw-blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .tw-shell {{ display: flex; max-width: 1265px; margin: 0 auto; min-height: 100vh; }}
    .tw-sidebar {{ width: 275px; flex-shrink: 0; position: sticky; top: 0; height: 100vh; padding: 8px 12px; border-right: 1px solid var(--tw-border); display: flex; flex-direction: column; gap: 4px; }}
    .tw-logo {{ padding: 12px; color: var(--tw-blue); display: inline-flex; align-items: center; justify-content: center; width: 52px; height: 52px; border-radius: 50%; transition: background .15s; }}
    .tw-logo:hover {{ background: rgba(29,155,240,.1); text-decoration: none; }}
    .tw-nav {{ display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }}
    .tw-nav a {{ display: flex; align-items: center; gap: 16px; padding: 12px 16px; color: var(--tw-black); font-size: 20px; font-weight: 400; border-radius: 999px; transition: background .15s; }}
    .tw-nav a:hover {{ background: var(--tw-hover); text-decoration: none; }}
    .tw-nav a.active {{ font-weight: 700; }}
    .tw-nav a svg {{ flex-shrink: 0; }}
    .tw-compose-btn {{ margin: 12px 0; padding: 14px; background: var(--tw-blue); color: #fff; border: none; border-radius: 999px; font-size: 17px; font-weight: 700; cursor: pointer; transition: background .15s; display: flex; align-items: center; justify-content: center; gap: 8px; }}
    .tw-compose-btn:hover {{ background: var(--tw-blue-hover); }}
    .tw-compose-btn svg {{ display: none; }}
    .tw-user-card {{ margin-top: auto; padding: 12px; display: flex; align-items: center; gap: 10px; border-radius: 999px; transition: background .15s; }}
    .tw-user-card:hover {{ background: var(--tw-hover); }}
    .tw-user-card a {{ color: var(--tw-black); text-decoration: none; display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }}
    .tw-user-card a:hover {{ text-decoration: none; }}
    .tw-user-card .tw-user-ava {{ width: 40px; height: 40px; border-radius: 8px; object-fit: cover; background: #e1e8ed; flex-shrink: 0; }}
    .tw-user-card .tw-user-info {{ display: flex; flex-direction: column; min-width: 0; }}
    .tw-user-card .tw-user-info b {{ font-size: 15px; color: var(--tw-black); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .tw-user-card .tw-user-info span {{ color: var(--tw-gray); font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .tw-user-card .tw-logout {{ padding: 8px; border-radius: 50%; color: var(--tw-gray); display: flex; align-items: center; justify-content: center; }}
    .tw-user-card .tw-logout:hover {{ background: rgba(244,33,46,.1); color: var(--tw-danger); }}
    .tw-lang {{ display: flex; gap: 4px; padding: 8px 12px; margin-top: 4px; }}
    .tw-lang a {{ flex: 1; padding: 6px; text-align: center; font-size: 13px; font-weight: 700; border-radius: 999px; border: 1px solid var(--tw-border2); color: var(--tw-gray); transition: all .15s; }}
    .tw-lang a:hover {{ background: var(--tw-hover); text-decoration: none; }}
    .tw-lang a.active {{ background: var(--tw-black); color: #fff; border-color: var(--tw-black); }}
    .tw-main {{ flex: 1; min-width: 0; max-width: 600px; border-right: 1px solid var(--tw-border); }}
    .tw-header {{ position: sticky; top: 0; background: rgba(255,255,255,.85); backdrop-filter: blur(12px); border-bottom: 1px solid var(--tw-border); padding: 12px 16px; z-index: 100; }}
    .tw-header h1 {{ margin: 0; font-size: 20px; font-weight: 800; }}
    .tw-page {{ padding: 0; }}
    .tw-search {{ padding: 12px 16px; border-bottom: 1px solid var(--tw-border); display: flex; gap: 8px; flex-wrap: wrap; }}
    .tw-search input {{ flex: 1; min-width: 120px; padding: 10px 14px; background: var(--tw-hover); border: 1px solid var(--tw-border); border-radius: 999px; font-size: 14px; outline: none; }}
    .tw-search input:focus {{ border-color: var(--tw-blue); background: #fff; }}
    .tw-search button {{ padding: 10px 18px; background: var(--tw-blue); color: #fff; border: none; border-radius: 999px; font-weight: 700; cursor: pointer; }}
    .tw-search button:hover {{ background: var(--tw-blue-hover); }}
    .tw-post {{ padding: 12px 16px; border-bottom: 1px solid var(--tw-border); display: flex; gap: 12px; transition: background .15s; }}
    .tw-post:hover {{ background: var(--tw-hover); }}
    .tw-post-ava {{ width: 40px; height: 40px; border-radius: 8px; object-fit: cover; background: #e1e8ed; flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: var(--tw-gray); font-weight: 800; font-size: 18px; }}
    .tw-post-body {{ flex: 1; min-width: 0; }}
    .tw-post-hd {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 2px; }}
    .tw-post-hd a {{ color: var(--tw-black); font-weight: 700; }}
    .tw-post-hd a:hover {{ text-decoration: underline; }}
    .tw-post-hd .handle {{ color: var(--tw-gray); }}
    .tw-post-hd .time {{ color: var(--tw-gray); }}
    .tw-post-hd .time::before {{ content: "· "; }}
    .tw-post-content {{ font-size: 15px; line-height: 1.45; margin: 4px 0; word-wrap: break-word; white-space: pre-wrap; }}
    .tw-post-content a.ext-link {{ color: var(--tw-blue); }}
    .tw-post-img {{ margin-top: 10px; border-radius: 16px; overflow: hidden; border: 1px solid var(--tw-border); max-width: 100%; }}
    .tw-post-img img {{ display: block; width: 100%; height: auto; max-height: 500px; object-fit: cover; cursor: zoom-in; }}
    .tw-post-meta {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 8px; font-size: 13px; color: var(--tw-gray); }}
    .tw-post-meta .badge {{ padding: 2px 8px; background: var(--tw-hover); border-radius: 999px; font-weight: 600; font-size: 12px; }}
    .tw-post-meta .badge.private {{ background: rgba(120,86,255,.1); color: var(--tw-private); }}
    .tw-post-meta .badge.sugg {{ background: rgba(29,155,240,.1); color: var(--tw-blue); }}
    .tw-post-actions {{ display: flex; gap: 4px; margin-top: 8px; margin-left: -6px; }}
    .tw-act {{ display: inline-flex; align-items: center; gap: 4px; padding: 6px 10px; border-radius: 999px; color: var(--tw-gray); font-size: 13px; font-weight: 600; cursor: pointer; background: transparent; border: none; transition: all .15s; }}
    .tw-act:hover {{ background: rgba(29,155,240,.1); color: var(--tw-blue); }}
    .tw-act.danger:hover {{ background: rgba(244,33,46,.1); color: var(--tw-danger); }}
    .tw-act.pin:hover {{ background: rgba(120,86,255,.1); color: var(--tw-private); }}
    .tw-page-nav {{ display: flex; justify-content: center; align-items: center; gap: 12px; padding: 16px; border-top: 1px solid var(--tw-border); flex-wrap: wrap; }}
    .tw-page-nav a, .tw-page-nav .disabled {{ padding: 10px 18px; background: #fff; border: 1px solid var(--tw-border2); border-radius: 999px; font-weight: 700; font-size: 14px; color: var(--tw-black); display: inline-flex; align-items: center; gap: 6px; }}
    .tw-page-nav a:hover {{ background: var(--tw-hover); text-decoration: none; }}
    .tw-page-nav .disabled {{ opacity: .4; pointer-events: none; }}
    .tw-page-info {{ color: var(--tw-gray); font-size: 14px; font-weight: 600; }}
    .tw-profile {{ padding: 0; }}
    .tw-profile-cover {{ height: 140px; background: linear-gradient(135deg, #1d9bf0, #7856ff); position: relative; }}
    .tw-profile-info {{ padding: 12px 16px; position: relative; }}
    .tw-profile-ava {{ width: 100px; height: 100px; border-radius: 16px; object-fit: cover; background: #e1e8ed; border: 4px solid #fff; position: absolute; top: -50px; left: 16px; }}
    .tw-profile-ava-ph {{ width: 100px; height: 100px; border-radius: 16px; background: #e1e8ed; border: 4px solid #fff; position: absolute; top: -50px; left: 16px; display: flex; align-items: center; justify-content: center; color: var(--tw-gray); font-weight: 800; font-size: 36px; }}
    .tw-profile-name {{ margin-top: 60px; }}
    .tw-profile-name h2 {{ margin: 0; font-size: 20px; font-weight: 800; }}
    .tw-profile-name .handle {{ color: var(--tw-gray); }}
    .tw-profile-bio {{ margin-top: 8px; font-size: 15px; }}
    .tw-profile-meta {{ margin-top: 12px; display: flex; gap: 16px; flex-wrap: wrap; color: var(--tw-gray); font-size: 14px; }}
    .tw-profile-meta b {{ color: var(--tw-black); }}
    .tw-profile-actions {{ display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }}
    .tw-btn {{ padding: 8px 18px; border-radius: 999px; font-weight: 700; font-size: 14px; border: 1px solid var(--tw-border2); background: #fff; color: var(--tw-black); cursor: pointer; transition: all .15s; display: inline-flex; align-items: center; gap: 6px; }}
    .tw-btn:hover {{ background: var(--tw-hover); text-decoration: none; }}
    .tw-btn.primary {{ background: var(--tw-black); color: #fff; border-color: var(--tw-black); }}
    .tw-btn.primary:hover {{ background: #272c30; }}
    .tw-btn.blue {{ background: var(--tw-blue); color: #fff; border-color: var(--tw-blue); }}
    .tw-btn.blue:hover {{ background: var(--tw-blue-hover); }}
    .tw-btn.danger {{ background: var(--tw-danger); color: #fff; border-color: var(--tw-danger); }}
    .tw-modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 9000; display: none; justify-content: center; align-items: flex-start; padding: 20px; }}
    .tw-modal.show {{ display: flex; }}
    .tw-modal-box {{ background: #fff; border-radius: 16px; max-width: 600px; width: 100%; box-shadow: 0 8px 30px rgba(0,0,0,.15); display: flex; flex-direction: column; max-height: 90vh; }}
    .tw-modal-hd {{ padding: 16px; border-bottom: 1px solid var(--tw-border); display: flex; align-items: center; justify-content: space-between; }}
    .tw-modal-hd h3 {{ margin: 0; font-size: 17px; font-weight: 800; }}
    .tw-modal-close {{ padding: 8px; border: none; background: transparent; border-radius: 50%; cursor: pointer; color: var(--tw-gray); display: flex; align-items: center; justify-content: center; }}
    .tw-modal-close:hover {{ background: var(--tw-hover); }}
    .tw-modal-body {{ padding: 16px; overflow-y: auto; flex: 1; display: flex; gap: 12px; }}
    .tw-modal-footer {{ padding: 12px 16px; border-top: 1px solid var(--tw-border); display: flex; justify-content: flex-end; gap: 8px; }}
    .tw-compose-textarea {{ width: 100%; min-height: 120px; border: none; resize: vertical; font-size: 19px; padding: 8px 0; outline: none; font-family: inherit; background: transparent; }}
    .tw-compose-textarea::placeholder {{ color: var(--tw-gray); }}
    .tw-compose-opt {{ display: flex; gap: 6px; margin: 8px 0; flex-wrap: wrap; }}
    .tw-compose-opt label {{ flex: 1; min-width: 120px; padding: 10px 14px; background: var(--tw-hover); border: 1px solid var(--tw-border2); border-radius: 999px; font-size: 13px; font-weight: 700; cursor: pointer; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px; transition: all .15s; }}
    .tw-compose-opt input[type=radio] {{ display: none; }}
    .tw-compose-opt label.selected {{ background: var(--tw-blue); color: #fff; border-color: var(--tw-blue); }}
    .tw-compose-opt label.selected.priv {{ background: var(--tw-private); border-color: var(--tw-private); }}
    .tw-img-preview {{ max-width: 100%; max-height: 200px; border-radius: 12px; margin-top: 8px; display: block; cursor: zoom-in; }}
    .tw-file-row {{ display: flex; align-items: center; gap: 8px; margin-top: 8px; }}
    .tw-file-row input[type=file] {{ display: none; }}
    .tw-file-row label {{ padding: 8px 12px; border-radius: 999px; cursor: pointer; color: var(--tw-blue); display: flex; align-items: center; gap: 6px; font-weight: 600; }}
    .tw-file-row label:hover {{ background: rgba(29,155,240,.1); }}
    .tw-suggest-card {{ padding: 16px; border-bottom: 1px solid var(--tw-border); }}
    .tw-suggest-card:hover {{ background: var(--tw-hover); }}
    .tw-suggest-hd {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
    .tw-suggest-hd b {{ font-size: 15px; }}
    .tw-suggest-hd span {{ color: var(--tw-gray); font-size: 13px; }}
    .tw-suggest-body {{ padding: 12px; background: var(--tw-hover); border-radius: 12px; margin-bottom: 10px; font-size: 15px; }}
    .tw-suggest-img {{ margin-top: 8px; border-radius: 10px; overflow: hidden; }}
    .tw-suggest-img img {{ width: 100%; max-height: 300px; object-fit: cover; display: block; cursor: zoom-in; }}
    .tw-suggest-actions {{ display: flex; gap: 8px; margin-top: 8px; }}
    .tw-stats-row {{ padding: 16px; border-bottom: 1px solid var(--tw-border); display: flex; justify-content: space-between; align-items: center; }}
    .tw-stats-row b {{ font-weight: 700; }}
    .tw-stats-row span {{ font-weight: 800; color: var(--tw-blue); font-size: 20px; }}
    .tw-contacts {{ padding: 16px; background: var(--tw-hover); border-radius: 12px; margin: 16px; }}
    .tw-contacts b {{ display: block; margin-bottom: 8px; }}
    .tw-contacts a {{ display: inline-flex; align-items: center; gap: 6px; margin-right: 12px; }}
    .tw-form {{ padding: 16px; display: flex; flex-direction: column; gap: 12px; }}
    .tw-form label {{ font-weight: 700; font-size: 14px; margin-bottom: -4px; }}
    .tw-form input, .tw-form textarea, .tw-form select {{ width: 100%; padding: 12px 14px; border: 1px solid var(--tw-border2); border-radius: 8px; font-size: 15px; outline: none; font-family: inherit; background: #fff; }}
    .tw-form input:focus, .tw-form textarea:focus {{ border-color: var(--tw-blue); }}
    .tw-form textarea {{ resize: vertical; min-height: 100px; }}
    .tw-switch {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--tw-hover); border-radius: 8px; cursor: pointer; }}
    .tw-switch b {{ font-size: 14px; }}
    .tw-switch input {{ width: 24px !important; height: 24px; cursor: pointer; }}
    .tw-avatar-edit {{ display: flex; align-items: center; gap: 16px; padding-bottom: 8px; }}
    .tw-avatar-edit .av {{ width: 80px; height: 80px; border-radius: 12px; object-fit: cover; background: #e1e8ed; border: 2px solid var(--tw-border2); display: flex; align-items: center; justify-content: center; color: var(--tw-gray); font-weight: 800; font-size: 28px; cursor: zoom-in; }}
    .tw-empty {{ padding: 60px 20px; text-align: center; color: var(--tw-gray); font-size: 15px; }}
    .tw-empty svg {{ color: var(--tw-border2); margin-bottom: 12px; }}
    .tw-rules {{ padding: 16px; background: #fff9e6; border-left: 4px solid #f1c40f; margin: 16px; border-radius: 8px; }}
    .tw-rules b {{ display: block; margin-bottom: 8px; }}
    .tw-rules div {{ white-space: pre-wrap; font-size: 14px; line-height: 1.5; }}
    /* Auth page */
    .auth-shell {{ display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; background: #fff; }}
    .auth-logo {{ color: var(--tw-blue); margin-bottom: 8px; }}
    .auth-h1 {{ font-size: 34px; font-weight: 900; margin: 0 0 24px; }}
    .auth-tabs {{ display: flex; gap: 4px; margin-bottom: 16px; background: var(--tw-hover); border-radius: 999px; padding: 4px; }}
    .auth-tabs button {{ padding: 10px 20px; background: transparent; border: none; border-radius: 999px; cursor: pointer; font-weight: 700; font-size: 14px; color: var(--tw-gray); }}
    .auth-tabs button.active {{ background: #fff; color: var(--tw-black); box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
    .auth-card {{ width: 100%; max-width: 400px; display: flex; flex-direction: column; gap: 12px; }}
    .auth-card form {{ display: flex; flex-direction: column; gap: 12px; }}
    .auth-input {{ width: 100%; padding: 14px 16px; border: 1px solid var(--tw-border2); border-radius: 8px; font-size: 15px; outline: none; }}
    .auth-input:focus {{ border-color: var(--tw-blue); }}
    .auth-eye {{ position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: transparent; border: none; cursor: pointer; color: var(--tw-gray); padding: 6px; }}
    .auth-eye-wrap {{ position: relative; }}
    .auth-check {{ display: flex; align-items: center; gap: 8px; font-size: 14px; cursor: pointer; }}
    .auth-check input {{ width: 18px; height: 18px; cursor: pointer; }}
    .auth-btn {{ padding: 14px; background: var(--tw-black); color: #fff; border: none; border-radius: 999px; font-weight: 700; font-size: 16px; cursor: pointer; }}
    .auth-btn:hover {{ background: #272c30; }}
    .auth-btn.blue {{ background: var(--tw-blue); }}
    .auth-btn.blue:hover {{ background: var(--tw-blue-hover); }}
    .auth-error {{ padding: 12px; background: rgba(244,33,46,.1); border-radius: 8px; color: var(--tw-danger); font-weight: 600; font-size: 14px; text-align: center; }}
    .auth-lang {{ margin-top: 24px; display: flex; gap: 6px; }}
    .auth-lang a {{ padding: 6px 14px; border: 1px solid var(--tw-border2); border-radius: 999px; font-size: 13px; font-weight: 700; color: var(--tw-gray); }}
    .auth-lang a.active {{ background: var(--tw-black); color: #fff; border-color: var(--tw-black); }}
    .auth-footer {{ margin-top: 24px; text-align: center; font-size: 12px; color: var(--tw-gray); }}
    .auth-footer a {{ color: var(--tw-gray); }}
    /* Toast */
    #toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(20px); background: var(--tw-blue); color: #fff; padding: 12px 24px; border-radius: 999px; font-weight: 700; font-size: 14px; opacity: 0; transition: all .3s; z-index: 99999; pointer-events: none; max-width: 90%; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,.15); }}
    #toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
    /* Confirm modal */
    #confirm-modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 10000; display: none; justify-content: center; align-items: center; padding: 20px; }}
    #confirm-modal.show {{ display: flex; }}
    .confirm-box {{ background: #fff; border-radius: 16px; padding: 24px; max-width: 320px; width: 100%; text-align: center; }}
    .confirm-box p {{ margin: 0 0 16px; font-size: 16px; font-weight: 600; }}
    .confirm-actions {{ display: flex; gap: 8px; }}
    .confirm-actions button {{ flex: 1; padding: 12px; border-radius: 999px; font-weight: 700; border: none; cursor: pointer; }}
    .confirm-cancel {{ background: var(--tw-hover); }}
    .confirm-ok {{ background: var(--tw-danger); color: #fff; }}
    /* Image viewer */
    #img-viewer {{ position: fixed; inset: 0; background: rgba(0,0,0,.95); z-index: 20000; display: none; justify-content: center; align-items: center; padding: 20px; cursor: zoom-out; }}
    #img-viewer.show {{ display: flex; }}
    #img-viewer img {{ max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 8px; }}
    .img-viewer-close {{ position: absolute; top: 16px; right: 16px; background: rgba(255,255,255,.2); color: #fff; border: none; width: 40px; height: 40px; border-radius: 50%; font-size: 22px; cursor: pointer; display: flex; align-items: center; justify-content: center; }}
    /* Link modal */
    #link-modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 10000; display: none; justify-content: center; align-items: center; padding: 20px; }}
    #link-modal.show {{ display: flex; }}
    .link-box {{ background: #fff; border-radius: 16px; padding: 24px; max-width: 400px; width: 100%; }}
    .og-preview {{ margin: 12px 0; padding: 12px; background: var(--tw-hover); border-radius: 8px; }}
    .og-preview img {{ max-width: 100%; border-radius: 6px; margin-bottom: 8px; }}
    /* Mobile bottom nav */
    .mobile-nav {{ display: none; position: fixed; bottom: 0; left: 0; right: 0; background: rgba(255,255,255,.95); backdrop-filter: blur(12px); border-top: 1px solid var(--tw-border); z-index: 5000; padding: 4px 0 calc(4px + env(safe-area-inset-bottom)); }}
    .mnav {{ display: flex; justify-content: space-around; align-items: center; }}
    .mnav-item {{ flex: 1; display: flex; align-items: center; justify-content: center; color: var(--tw-gray); padding: 10px 0; transition: color .15s; }}
    .mnav-item.active {{ color: var(--tw-blue); }}
    .mnav-compose {{ width: 44px; height: 44px; margin: 0 8px; background: var(--tw-blue); color: #fff !important; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: 0 0 auto; }}
    @media (max-width: 900px) {{
        .tw-sidebar {{ display: none; }}
        .tw-main {{ max-width: 100%; border: none; }}
        .mobile-nav {{ display: block; }}
        body {{ padding-bottom: 70px; }}
        .tw-modal {{ padding: 0; }}
        .tw-modal-box {{ max-height: 100vh; border-radius: 0; min-height: 100vh; }}
    }}
    @media (max-width: 500px) {{
        .tw-post {{ padding: 10px 12px; }}
        .tw-post-ava, .tw-post-img {{ border-radius: 6px; }}
        .tw-post-img img {{ max-height: 300px; }}
        .tw-search {{ flex-direction: column; }}
        .tw-search button {{ width: 100%; }}
    }}
    </style>
    """

def get_js(lang, token, current_user=""):
    js = """
    <script>
    const T = "__TOKEN__";
    const ME = "__ME__";
    const L = {
        "confirm": "__CONFIRM__", "copied": "__COPIED__", "copy_fail": "__COPY_FAIL__",
        "img": "__IMG__", "img_ok": "__IMG_OK__", "img_err": "__IMG_ERR__", "img_big": "__IMG_BIG__",
        "new_post": "__NEW_POST__", "approved": "__APPROVED__", "rejected": "__REJECTED__",
        "err": "__ERR__"
    };
    function showToast(msg) {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        clearTimeout(t._tm);
        t._tm = setTimeout(() => t.classList.remove('show'), 3000);
    }
    function viewImage(src) {
        if (!src) return;
        document.getElementById('img-viewer-img').src = src;
        document.getElementById('img-viewer').classList.add('show');
        document.body.style.overflow = 'hidden';
    }
    function closeImgViewer() {
        document.getElementById('img-viewer').classList.remove('show');
        document.body.style.overflow = '';
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeImgViewer(); });
    function showConfirm(msg, cb) {
        const m = document.getElementById('confirm-modal');
        document.getElementById('confirm-text').textContent = msg;
        m.classList.add('show');
        const ok = document.getElementById('confirm-ok');
        const cancel = document.getElementById('confirm-cancel');
        const nOk = ok.cloneNode(true);
        const nCancel = cancel.cloneNode(true);
        ok.parentNode.replaceChild(nOk, ok);
        cancel.parentNode.replaceChild(nCancel, cancel);
        nOk.onclick = () => { m.classList.remove('show'); cb(true); };
        nCancel.onclick = () => { m.classList.remove('show'); cb(false); };
    }
    async function rpc(method, params) {
        const res = await fetch('/rpc', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': T },
            body: JSON.stringify({ method, params })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || 'RPC Error');
        return data;
    }
    function tp(inputId, btn) {
        const x = document.getElementById(inputId);
        if (x.type === 'password') { x.type = 'text'; btn.innerHTML = '__SVG_EYE_OFF__'; }
        else { x.type = 'password'; btn.innerHTML = '__SVG_EYE__'; }
    }
    function copyPost(user, rid) {
        if (!user) return;
        const url = window.location.origin + '/' + user + '/' + rid;
        navigator.clipboard.writeText(url).then(() => showToast(L.copied)).catch(() => showToast(L.copy_fail));
    }
    async function compressImage(file, maxW=1000, q=0.75) {
        return new Promise((resolve, reject) => {
            if (!file.type.startsWith('image/')) return reject('Not image');
            const r = new FileReader();
            r.onload = e => {
                const img = new Image();
                img.onload = () => {
                    try {
                        const c = document.createElement('canvas');
                        let w = img.width, h = img.height;
                        if (w > maxW) { h = Math.round(h*maxW/w); w = maxW; }
                        c.width = w; c.height = h;
                        const x = c.getContext('2d');
                        x.fillStyle = '#fff'; x.fillRect(0,0,w,h);
                        x.drawImage(img, 0, 0, w, h);
                        let b = c.toDataURL('image/jpeg', q);
                        let qq = q;
                        while (b.length > 800000 && qq > 0.3) { qq -= 0.1; b = c.toDataURL('image/jpeg', qq); }
                        if (b.length > 850000) return reject('big');
                        resolve(b);
                    } catch (err) { reject(err); }
                };
                img.onerror = () => reject('load');
                img.src = e.target.result;
            };
            r.onerror = () => reject('read');
            r.readAsDataURL(file);
        });
    }
    // Compose
    window.postImageCache = "";
    async function handlePostImage(input) {
        const file = input.files[0];
        const preview = document.getElementById('post-img-preview');
        if (!file) { window.postImageCache = ""; if(preview) preview.style.display='none'; return; }
        showToast(L.img);
        try {
            const b64 = await compressImage(file, 1000, 0.75);
            window.postImageCache = b64;
            if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); }
            showToast(L.img_ok);
        } catch (e) {
            window.postImageCache = "";
            showToast(e === 'big' ? L.img_big : L.img_err);
            input.value = '';
            if(preview) preview.style.display='none';
        }
    }
    async function handleAvatarChange(input) {
        const file = input.files[0];
        const hidden = document.getElementById('avatar-data');
        const preview = document.getElementById('avatar-preview');
        if (!file) { if(hidden) hidden.value = ""; return; }
        showToast(L.img);
        try {
            const b64 = await compressImage(file, 300, 0.8);
            if(hidden) hidden.value = b64;
            if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); }
            showToast(L.img_ok);
        } catch (e) {
            showToast(e === 'big' ? L.img_big : L.img_err);
            input.value = '';
        }
    }
    function openCompose() { document.getElementById('compose-modal').classList.add('show'); }
    function closeCompose() {
        document.getElementById('compose-modal').classList.remove('show');
        window.postImageCache = "";
        const p = document.getElementById('post-img-preview');
        if(p) { p.style.display = 'none'; p.src = ''; }
        const f = document.getElementById('compose-form');
        if(f) f.reset();
        document.querySelectorAll('.tw-compose-opt label').forEach(x => x.classList.remove('selected'));
        const first = document.querySelector('.tw-compose-opt label');
        if (first) first.classList.add('selected');
    }
    document.querySelectorAll('.tw-compose-opt label').forEach(el => {
        el.addEventListener('click', () => {
            document.querySelectorAll('.tw-compose-opt label').forEach(x => x.classList.remove('selected'));
            el.classList.add('selected');
            const r = el.querySelector('input[type=radio]');
            if (r) r.checked = true;
        });
    });
    async function submitCompose(e) {
        e.preventDefault();
        const f = e.target;
        const c = f.querySelector('textarea').value.trim();
        if (!c) return;
        const vis = f.querySelector('input[name=visibility]:checked');
        const visibility = vis ? vis.value : 'public';
        const img = window.postImageCache || "";
        const btn = f.querySelector('button[type=submit]');
        btn.disabled = true;
        try {
            await rpc('create_record', { content: c, image_data: img, visibility: visibility, client_id: crypto.randomUUID() });
            showToast(L.new_post);
            closeCompose();
            setTimeout(() => location.reload(), 500);
        } catch (x) {
            showToast(L.err + ' ' + x.message);
            btn.disabled = false;
        }
    }
    async function deletePost(rid) {
        showConfirm(L.confirm, async (yes) => {
            if (!yes) return;
            try {
                await rpc('delete_record', { post_id: rid });
                const el = document.querySelector(`[data-post-id="${rid}"]`);
                if (el) el.remove();
            } catch (x) { showToast(L.err + ' ' + x.message); }
        });
    }
    async function pinPost(rid) {
        try {
            await rpc('pin_record', { post_id: rid });
            location.reload();
        } catch (x) { showToast(L.err + ' ' + x.message); }
    }
    async function approveSugg(sid) {
        try {
            await rpc('approve_suggestion', { suggestion_id: sid });
            showToast(L.approved);
            const el = document.getElementById('sugg-' + sid);
            if (el) el.remove();
        } catch (x) { showToast(L.err + ' ' + x.message); }
    }
    async function rejectSugg(sid) {
        try {
            await rpc('reject_suggestion', { suggestion_id: sid });
            showToast(L.rejected);
            const el = document.getElementById('sugg-' + sid);
            if (el) el.remove();
        } catch (x) { showToast(L.err + ' ' + x.message); }
    }
    async function handleSuggImage(input) {
        const file = input.files[0];
        const preview = document.getElementById('sugg-img-preview');
        if (!file) { window.suggImageCache = ""; if(preview) preview.style.display='none'; return; }
        showToast(L.img);
        try {
            const b64 = await compressImage(file, 1000, 0.75);
            window.suggImageCache = b64;
            if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); }
            showToast(L.img_ok);
        } catch (e) {
            window.suggImageCache = "";
            showToast(e === 'big' ? L.img_big : L.img_err);
        }
    }
    window.suggImageCache = "";
    async function submitSuggestion(e) {
        e.preventDefault();
        const f = e.target;
        const target = f.dataset.nickname;
        const name = f.querySelector('input[name=sugg_name]').value.trim();
        const content = f.querySelector('textarea[name=content]').value.trim();
        if (!name || !content) return;
        const btn = f.querySelector('button[type=submit]');
        btn.disabled = true;
        try {
            await rpc('submit_suggestion', { target_nickname: target, sugg_name: name, content: content, image_data: window.suggImageCache || "" });
            showToast(L.new_post);
            f.reset();
            window.suggImageCache = "";
            const p = document.getElementById('sugg-img-preview');
            if(p) p.style.display = 'none';
        } catch (x) { showToast(L.err + ' ' + x.message); }
        finally { btn.disabled = false; }
    }
    let pendingUrl = "";
    async function showLinkWarning(e, el) {
        e.preventDefault();
        pendingUrl = el.getAttribute('data-url');
        if (!pendingUrl) return;
        document.getElementById('link-modal-confirm').href = pendingUrl;
        document.getElementById('og-preview').innerHTML = '<div style="color:#536471;font-size:13px">__EXT_LOADING__</div>';
        document.getElementById('link-modal').classList.add('show');
        try {
            const res = await fetch('/api/og?url=' + encodeURIComponent(pendingUrl));
            const data = await res.json();
            let html = '';
            if (data.image) html += `<img src="${data.image}" style="max-width:100%;max-height:200px;border-radius:8px;margin-bottom:8px;">`;
            if (data.title) html += `<div style="font-weight:700;margin-bottom:4px;">${data.title}</div>`;
            if (data.description) html += `<div style="color:#536471;font-size:13px;">${data.description}</div>`;
            document.getElementById('og-preview').innerHTML = html || '<div style="color:#536471;font-size:13px;">—</div>';
        } catch (e) {
            document.getElementById('og-preview').innerHTML = '<div style="color:#536471;font-size:13px;">—</div>';
        }
    }
    function closeLinkModal() { document.getElementById('link-modal').classList.remove('show'); }
    // WS
    let ws;
    (function connectWS() {
        const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
        ws = new WebSocket(proto + location.host + '/ws');
        ws.onmessage = (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.type === 'delete_record') {
                    const el = document.querySelector(`[data-post-id="${d.post_id}"]`);
                    if (el) el.remove();
                } else if (d.type === 'new_record') {
                    showToast(L.new_post);
                }
            } catch(err) {}
        };
        ws.onclose = () => setTimeout(connectWS, 3000);
    })();
    if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(()=>{}));
    </script>
    """
    repl = [
        ("__TOKEN__", token), ("__ME__", current_user),
        ("__CONFIRM__", t('confirm_delete', lang)), ("__COPIED__", t('toast_copied', lang)),
        ("__COPY_FAIL__", t('toast_copy_fail', lang)), ("__IMG__", t('toast_img', lang)),
        ("__IMG_OK__", t('toast_img_ok', lang)), ("__IMG_ERR__", t('toast_img_err', lang)),
        ("__IMG_BIG__", t('toast_img_big', lang)), ("__NEW_POST__", t('toast_new', lang)),
        ("__APPROVED__", t('toast_approved', lang)), ("__REJECTED__", t('toast_rejected', lang)),
        ("__ERR__", t('toast_err', lang)), ("__EXT_LOADING__", "Загрузка..." if lang=="ru" else "Loading..."),
        ("__SVG_EYE_OFF__", svg('eye_off', 20)), ("__SVG_EYE__", svg('eye', 20)),
    ]
    for k, v in repl: js = js.replace(k, v)
    return js

def get_modals(lang):
    return f"""
    <div id="toast"></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()">
        <button class="img-viewer-close" onclick="closeImgViewer()">&times;</button>
        <img id="img-viewer-img" src="" alt="">
    </div>
    <div id="confirm-modal">
        <div class="confirm-box">
            <p id="confirm-text"></p>
            <div class="confirm-actions">
                <button id="confirm-cancel" class="confirm-cancel">{t('cancel',lang)}</button>
                <button id="confirm-ok" class="confirm-ok">OK</button>
            </div>
        </div>
    </div>
    <div id="link-modal">
        <div class="link-box">
            <h3 style="margin:0 0 8px;font-size:17px;font-weight:800;">{t('ext_title',lang)}</h3>
            <p style="margin:0 0 12px;font-size:14px;color:#536471;">{t('ext_desc',lang)}</p>
            <div id="og-preview" class="og-preview"></div>
            <div style="display:flex;gap:8px;justify-content:flex-end;">
                <button onclick="closeLinkModal()" class="tw-btn">{t('cancel',lang)}</button>
                <a id="link-modal-confirm" href="#" target="_blank" class="tw-btn blue">{t('ext_go',lang)}</a>
            </div>
        </div>
    </div>
    <div id="compose-modal" class="tw-modal" onclick="if(event.target===this)closeCompose()">
        <div class="tw-modal-box">
            <div class="tw-modal-hd">
                <h3>{t('compose_title',lang)}</h3>
                <button class="tw-modal-close" onclick="closeCompose()">{svg('x')}</button>
            </div>
            <form id="compose-form" onsubmit="submitCompose(event)">
                <div class="tw-modal-body">
                    <div class="tw-post-ava" style="width:40px;height:40px;">{svg('user', 20)}</div>
                    <div style="flex:1;min-width:0;">
                        <textarea class="tw-compose-textarea" name="content" placeholder="{t('post_placeholder',lang)}" required maxlength="500"></textarea>
                        <div class="tw-compose-opt">
                            <label class="selected"><input type="radio" name="visibility" value="public" checked>{t('vis_public',lang)}</label>
                            <label><input type="radio" name="visibility" value="private">{t('vis_private',lang)}</label>
                        </div>
                        <div class="tw-file-row">
                            <label for="compose-img">{svg('image', 20)} {t('attach_photo',lang)}</label>
                            <input type="file" id="compose-img" accept="image/*" onchange="handlePostImage(this)">
                        </div>
                        <img id="post-img-preview" class="tw-img-preview" style="display:none;">
                    </div>
                </div>
                <div class="tw-modal-footer">
                    <button type="submit" class="tw-btn blue" style="min-width:120px;">{t('publish',lang)}</button>
                </div>
            </form>
        </div>
    </div>
    """

def get_sidebar(lang, viewer, active="", avatar="", username="", nickname=""):
    items = [
        ("/home", "home", t('home',lang), "home"),
        ("/cabinet", "user", t('cabinet',lang), "cabinet"),
        ("/cabinet/suggestions", "message", t('suggestions',lang), "sugg"),
        ("/stats", "chart", t('stats',lang), "stats"),
        ("/bugreport", "bell", t('bugreport',lang), "bug"),
        ("/cabinet/edit", "edit", t('edit_profile',lang), "edit"),
    ]
    nav = "".join(f'<a href="{u}" class="{"active" if active==k else ""}">{svg(i)}<span>{lbl}</span></a>' for u,i,lbl,k in items)
    lang_current = "cabinet" if active in ("cabinet","sugg","edit") else active
    ru_act = "active" if lang=="ru" else ""
    en_act = "active" if lang=="en" else ""
    if avatar:
        ava = f'<img src="{avatar}" class="tw-user-ava" alt="">'
    else:
        initial = (username or nickname or "?")[0].upper()
        ava = f'<div class="tw-user-ava" style="display:flex;align-items:center;justify-content:center;font-weight:800;color:#536471;">{initial}</div>'
    return f"""
    <aside class="tw-sidebar">
        <a href="/home" class="tw-logo">{svg('logo', 28)}</a>
        <nav class="tw-nav">{nav}</nav>
        <button class="tw-compose-btn" onclick="openCompose()">{t('create_post',lang)}</button>
        <div class="tw-user-card">
            <a href="/{nickname}">{ava}<div class="tw-user-info"><b>{username}</b><span>@{nickname}</span></div></a>
            <a href="/logout" class="tw-logout" title="{t('logout',lang)}">{svg('logout')}</a>
        </div>
        <div class="tw-lang">
            <a href="/set_lang/ru?next=/{lang_current}" class="{ru_act}">RU</a>
            <a href="/set_lang/en?next=/{lang_current}" class="{en_act}">EN</a>
        </div>
    </aside>
    """

def get_mobile_nav(lang, active="", viewer=""):
    items = [
        ("/home", "home", "home"),
        ("/cabinet", "user", "cabinet"),
        ("/stats", "chart", "stats"),
        ("/cabinet/edit", "edit", "edit"),
    ]
    links = ""
    for i, (u, ic, k) in enumerate(items):
        cls = "active" if active == k else ""
        links += f'<a href="{u}" class="mnav-item {cls}">{svg(ic, 24)}</a>'
        if i == 1:
            links += f'<a href="#" onclick="openCompose();return false;" class="mnav-item mnav-compose">{svg("plus", 22)}</a>'
    return f'<nav class="mobile-nav"><div class="mnav">{links}</div></nav>'

def get_footer(lang):
    contacts = " · ".join(f'<a href="mailto:{e}">{e}</a>' for e in CONTACT_EMAILS)
    return f"""
    <div style="border-top:1px solid #eff3f4;padding:16px 20px;text-align:center;font-size:12px;color:#536471;background:#fff;">
        <div>{contacts}</div>
        <div style="margin-top:6px;">Solid Link · FastAPICloud · v{APP_VERSION} ({SERVER_START_DATE})</div>
    </div>
    """

def base_layout(lang, token, viewer, active, content_html, avatar="", username="", nickname="", extra_head=""):
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#1d9bf0">
    <title>Solid Link</title>
    {get_css()}{extra_head}
    </head><body>
    <div class="tw-shell">
        {get_sidebar(lang, viewer, active, avatar, username, nickname)}
        <main class="tw-main">{content_html}</main>
    </div>
    {get_mobile_nav(lang, active, viewer)}
    {get_modals(lang)}
    {get_js(lang, token, viewer)}
    </body></html>
    """

def auth_html(lang, error="", token=""):
    err = f'<div class="auth-error">{error}</div>' if error else ""
    html = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#1d9bf0">
    <title>Solid Link</title>
    {get_css()}
    </head><body>
    <div class="auth-shell">
        <div class="auth-logo">{svg('logo', 44)}</div>
        <h1 class="auth-h1">Solid Link</h1>
        <div class="auth-tabs">
            <button type="button" class="active" onclick="showAuthTab('login',this)">{t('login',lang)}</button>
            <button type="button" onclick="showAuthTab('reg',this)">{t('reg',lang)}</button>
        </div>
        <div class="auth-card" id="auth-login">
            <form action="/login" method="post">
                <input type="hidden" name="csrf_token" value="{token}">
                <input class="auth-input" type="text" name="nickname" placeholder="{t('nickname',lang)}" required>
                <div class="auth-eye-wrap">
                    <input class="auth-input" type="password" name="password" id="lp" placeholder="{t('password',lang)}" required style="padding-right:44px;">
                    <button type="button" class="auth-eye" onclick="tp('lp',this)">{svg('eye',20)}</button>
                </div>
                <label class="auth-check"><input type="checkbox" name="captcha" required>{t('captcha',lang)}</label>
                {err}
                <button class="auth-btn" type="submit">{t('login_btn',lang)}</button>
            </form>
        </div>
        <div class="auth-card" id="auth-reg" style="display:none;">
            <form action="/register" method="post">
                <input type="hidden" name="csrf_token" value="{token}">
                <input class="auth-input" type="text" name="username" placeholder="{t('username',lang)}" required>
                <input class="auth-input" type="text" name="nickname" placeholder="{t('nickname',lang)}" required>
                <div class="auth-eye-wrap">
                    <input class="auth-input" type="password" name="password" id="rp" placeholder="{t('password',lang)}" required style="padding-right:44px;">
                    <button type="button" class="auth-eye" onclick="tp('rp',this)">{svg('eye',20)}</button>
                </div>
                <div class="auth-eye-wrap">
                    <input class="auth-input" type="password" name="re_pass" id="rr" placeholder="{t('re_pass',lang)}" required style="padding-right:44px;">
                    <button type="button" class="auth-eye" onclick="tp('rr',this)">{svg('eye',20)}</button>
                </div>
                <label class="auth-check"><input type="checkbox" name="captcha" required>{t('captcha',lang)}</label>
                <label class="auth-check"><input type="checkbox" name="privacy" required><span>{t('privacy_agree',lang)} <a href="/privacy" target="_blank">{t('privacy_link',lang)}</a></span></label>
                <button class="auth-btn blue" type="submit">{t('register_btn',lang)}</button>
            </form>
        </div>
        <div class="auth-lang">
            <a href="/set_lang/ru?next=/" class="{'active' if lang=='ru' else ''}">RU</a>
            <a href="/set_lang/en?next=/" class="{'active' if lang=='en' else ''}">EN</a>
        </div>
        <div class="auth-footer">
            <a href="/home">→ {t('home',lang)}</a> · <a href="/stats">{t('stats',lang)}</a>
        </div>
    </div>
    {get_modals(lang)}
    {get_js(lang, token, "")}
    <script>
    function showAuthTab(tab, btn) {{
        document.querySelectorAll('.auth-tabs button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('auth-login').style.display = tab === 'login' ? 'flex' : 'none';
        document.getElementById('auth-reg').style.display = tab === 'reg' ? 'flex' : 'none';
    }}
    </script>
    </body></html>
    """
    return html

def render_post_card(p, lang, own=False, viewer="", show_handle=False):
    rid = esc(p.get('id'))
    if not rid: return ""
    nick = esc(p.get('user_nickname',''))
    content = linkify(p.get('content',''))
    date = fmt_date(p.get('created_at',''))
    img = esc(p.get('image_data',''))
    sugg = esc(p.get('suggested_by',''))
    vis = p.get('visibility','public') or 'public'
    pinned = bool(p.get('is_pinned', False))
    
    img_html = f'<div class="tw-post-img"><img src="{img}" onclick="viewImage(this.src)"></div>' if img else ""
    sugg_html = f'<span class="badge sugg">{t("suggested_by",lang)} {sugg}</span>' if sugg else ""
    priv_html = f'<span class="badge private">{t("private_label",lang)}</span>' if vis == 'private' else ""
    pin_html = f'<span class="badge">{t("pin",lang)}</span>' if pinned else ""
    
    handle = f'<span class="handle">@{nick}</span>' if show_handle else ""
    author_name = nick
    
    actions = ""
    if viewer:
        actions += f'<button class="tw-act" onclick="copyPost(\'{nick}\',\'{rid}\')">{svg("link",16)} {t("copy_link",lang)}</button>'
    if own:
        pin_lbl = t('unpin',lang) if pinned else t('pin',lang)
        actions += f'<button class="tw-act pin" onclick="pinPost(\'{rid}\')">{svg("pin",16)} {pin_lbl}</button>'
        actions += f'<button class="tw-act danger" onclick="deletePost(\'{rid}\')">{svg("trash",16)} {t("delete",lang)}</button>'
    
    return f"""
    <article class="tw-post" data-post-id="{rid}">
        <div class="tw-post-ava">{nick[0].upper() if nick else "?"}</div>
        <div class="tw-post-body">
            <div class="tw-post-hd">
                <a href="/{nick}">{author_name}</a>
                {handle}
                <span class="time">{date}</span>
            </div>
            <div class="tw-post-content">{content}</div>
            {img_html}
            <div class="tw-post-meta">{pin_html}{priv_html}{sugg_html}</div>
            <div class="tw-post-actions">{actions}</div>
        </div>
    </article>
    """

def home_html(lang, token, posts, page, total, q, author, viewer):
    total_pages = max(1, (total + PER_PAGE - 1)//PER_PAGE)
    qs = ""
    if q: qs += "&q=" + quote(q)
    if author: qs += "&author=" + quote(author)
    prev_href = f"/home?page={page-1}{qs}" if page > 1 else "#"
    next_href = f"/home?page={page+1}{qs}" if page < total_pages else "#"
    prev_cls = "" if page > 1 else "disabled"
    next_cls = "" if page < total_pages else "disabled"
    
    if not posts:
        posts_html = f'<div class="tw-empty">{svg("search",40)}<div>{t("home_empty",lang)}</div></div>'
    else:
        posts_html = "".join(render_post_card(p, lang, own=(viewer == p.get('user_nickname')), viewer=viewer, show_handle=True) for p in posts)
    
    content = f"""
    <div class="tw-header"><h1>{t('home',lang)}</h1></div>
    <form method="get" action="/home" class="tw-search">
        <input type="text" name="q" value="{esc(q)}" placeholder="{t('search_q',lang)}">
        <input type="text" name="author" value="{esc(author)}" placeholder="{t('search_author',lang)}">
        <button type="submit">{svg('search',16)} {t('search',lang) if 'search' in LOCALES[lang] else 'Search'}</button>
    </form>
    {posts_html}
    <div class="tw-page-nav">
        <a href="{prev_href}" class="{prev_cls}">{svg('chev_l',16)} {t('prev',lang)}</a>
        <span class="tw-page-info">{t('page',lang)} {page} {t('of',lang)} {total_pages} · {t('found',lang)}: {total}</span>
        <a href="{next_href}" class="{next_cls}">{t('next',lang)} {svg('chev_r',16)}</a>
    </div>
    """
    return base_layout(lang, token, viewer, "home", content)

def dashboard_html(nickname, user, my_p, lang, token, viewer):
    avatar = esc(user.get('avatar_data',''))
    username = esc(user.get('username',''))
    if not my_p:
        posts_html = f'<div class="tw-empty">{svg("message",40)}<div>{t("no_posts",lang)}</div></div>'
    else:
        posts_html = "".join(render_post_card(p, lang, own=True, viewer=viewer) for p in my_p)
    
    desc = esc(user.get('description',''))
    initial = (username or nickname or "?")[0].upper()
    ava_html = f'<img src="{avatar}" class="tw-profile-ava" onclick="viewImage(this.src)">' if avatar else f'<div class="tw-profile-ava-ph">{initial}</div>'
    
    content = f"""
    <div class="tw-header"><h1>{t('cabinet',lang)}</h1></div>
    <div class="tw-profile">
        <div class="tw-profile-cover"></div>
        <div class="tw-profile-info">
            {ava_html}
            <div class="tw-profile-name">
                <h2>{username}</h2>
                <span class="handle">@{esc(nickname)}</span>
            </div>
            {f'<div class="tw-profile-bio">{desc}</div>' if desc else ''}
            <div class="tw-profile-meta">
                <div><b>{len(my_p)}</b> {t('total_posts',lang)}</div>
            </div>
            <div class="tw-profile-actions">
                <a href="/cabinet/edit" class="tw-btn">{svg('edit',16)} {t('edit_profile',lang)}</a>
                <a href="/{esc(nickname)}" class="tw-btn">{svg('user',16)} {t('profile',lang)}</a>
            </div>
        </div>
    </div>
    <div class="tw-header" style="position:static;margin-top:8px;"><h1 style="font-size:17px;">{t('my_posts',lang)}</h1></div>
    {posts_html}
    """
    return base_layout(lang, token, viewer, "cabinet", content, avatar, username, nickname)

def suggestions_page_html(nickname, suggestions, lang, token):
    if not suggestions:
        rh = f'<div class="tw-empty">{svg("message",40)}<div>{t("sugges_empty",lang)}</div></div>'
    else:
        rh = ""
        for s in suggestions:
            sid = esc(s.get('id'))
            nm = esc(s.get('suggested_by_name',''))
            content = linkify(s.get('content',''))
            dt = fmt_date(s.get('created_at',''))
            img = esc(s.get('image_data',''))
            img_html = f'<div class="tw-suggest-img"><img src="{img}" onclick="viewImage(this.src)"></div>' if img else ""
            rh += f"""
            <div class="tw-suggest-card" id="sugg-{sid}">
                <div class="tw-suggest-hd"><b>{nm}</b><span>{dt}</span></div>
                <div class="tw-suggest-body">{content}</div>
                {img_html}
                <div class="tw-suggest-actions">
                    <button class="tw-btn blue" onclick="approveSugg('{sid}')">{svg('check',16)} {t('sugges_approve',lang)}</button>
                    <button class="tw-btn danger" onclick="rejectSugg('{sid}')">{svg('x',16)} {t('sugges_reject',lang)}</button>
                </div>
            </div>
            """
    content = f"""
    <div class="tw-header"><h1>{t('suggestions',lang)}</h1></div>
    {rh}
    <div style="padding:16px;text-align:center;"><a href="/cabinet" class="tw-btn">{svg('chev_l',16)} {t('cancel',lang)}</a></div>
    """
    return base_layout(lang, token, nickname, "sugg", content)

def sugges_form_html(nickname, lang, token, error="", viewer="", rules="", enabled=True, photo_enabled=True):
    is_own = (viewer == nickname)
    rules_block = f'<div class="tw-rules"><b>{t("rules",lang)}</b><div>{esc(rules)}</div></div>' if rules else ""
    
    if is_own:
        form = f'<div class="tw-empty">{svg("x",40)}<div>{t("sugges_own",lang)}</div></div>'
    elif not enabled:
        form = f'<div class="tw-empty">{svg("lock",40)}<div>{t("sugges_disabled",lang)}</div></div>'
    else:
        photo_block = ""
        if photo_enabled:
            photo_block = f"""
            <div class="tw-file-row">
                <label for="sugg-img">{svg('image',18)} {t('attach_photo',lang)}</label>
                <input type="file" id="sugg-img" accept="image/*" onchange="handleSuggImage(this)">
            </div>
            <img id="sugg-img-preview" class="tw-img-preview" style="display:none;">
            """
        form = f"""
        <form class="tw-form" data-nickname="{esc(nickname)}" onsubmit="submitSuggestion(event)">
            <label>{t('sugges_name',lang)}</label>
            <input type="text" name="sugg_name" maxlength="60" required>
            <label>{t('sugges_content',lang)}</label>
            <textarea name="content" maxlength="500" required></textarea>
            {photo_block}
            <button type="submit" class="tw-btn blue" style="width:100%;padding:14px;">{t('sugges_send',lang)}</button>
        </form>
        """
    
    content = f"""
    <div class="tw-header"><h1>{t('sugges_title',lang)} @{esc(nickname)}</h1></div>
    {rules_block}
    {form}
    <div style="padding:16px;text-align:center;"><a href="/{esc(nickname)}" class="tw-btn">{svg('chev_l',16)} {t('cancel',lang)}</a></div>
    """
    return base_layout(lang, token, viewer or "", "sugg", content)

def edit_html(nickname, user, lang, token):
    desc = esc(user.get('description',''))
    rules = esc(user.get('sugges_rules',''))
    avatar = esc(user.get('avatar_data',''))
    username = esc(user.get('username',''))
    initial = (username or nickname or "?")[0].upper()
    ava_html = f'<img id="avatar-preview" src="{avatar}" class="av" onclick="viewImage(this.src)">' if avatar else f'<div id="avatar-preview" class="av">{initial}</div>'
    sugges_checked = "checked" if _sugg_enabled(user) else ""
    photo_checked = "checked" if _sugg_photo_enabled(user) else ""
    
    content = f"""
    <div class="tw-header"><h1>{t('edit_profile',lang)}</h1></div>
    <form action="/cabinet/edit" method="post" enctype="multipart/form-data" class="tw-form">
        <input type="hidden" name="csrf_token" value="{token}">
        <input type="hidden" name="avatar_data" id="avatar-data" value="">
        <div class="tw-avatar-edit">
            {ava_html}
            <div class="tw-file-row">
                <label for="avatar-input">{svg('image',18)} {t('attach_avatar',lang)}</label>
                <input type="file" id="avatar-input" accept="image/*" onchange="handleAvatarChange(this)">
            </div>
        </div>
        <label>{t('username',lang)}</label>
        <input type="text" name="username" value="{username}" required>
        <label>{t('description',lang)}</label>
        <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder',lang)}" style="min-height:80px;">{desc}</textarea>
        <label class="tw-switch"><b>{t('sugges_enable',lang)}</b><input type="checkbox" name="sugges_enabled" {sugges_checked}></label>
        <label class="tw-switch"><b>{t('sugges_photo_enable',lang)}</b><input type="checkbox" name="sugges_photo_enabled" {photo_checked}></label>
        <label>{t('rules',lang)}</label>
        <textarea name="sugges_rules" maxlength="1000" placeholder="{t('rules_ph',lang)}" style="min-height:80px;">{rules}</textarea>
        <div style="display:flex;gap:8px;">
            <button type="submit" class="tw-btn blue" style="flex:1;">{t('save',lang)}</button>
            <a href="/cabinet" class="tw-btn" style="flex:1;text-align:center;">{t('cancel',lang)}</a>
        </div>
    </form>
    """
    return base_layout(lang, token, nickname, "edit", content, avatar, username, nickname)

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    avatar = esc(user.get('avatar_data',''))
    username = esc(user.get('username',''))
    desc = esc(user.get('description',''))
    initial = (username or nickname or "?")[0].upper()
    ava_html = f'<img src="{avatar}" class="tw-profile-ava" onclick="viewImage(this.src)">' if avatar else f'<div class="tw-profile-ava-ph">{initial}</div>'
    
    if not records:
        posts_html = f'<div class="tw-empty">{svg("message",40)}<div>{t("no_posts",lang)}</div></div>'
    else:
        posts_html = "".join(render_post_card(p, lang, own=is_owner, viewer=viewer) for p in records)
    
    sugg_btn = ""
    if not is_owner and _sugg_enabled(user):
        sugg_btn = f'<a href="/{esc(nickname)}/sugges" class="tw-btn blue">{svg("message",16)} {t("suggestions",lang)}</a>'
    
    content = f"""
    <div class="tw-header"><h1>@{esc(nickname)}</h1></div>
    <div class="tw-profile">
        <div class="tw-profile-cover"></div>
        <div class="tw-profile-info">
            {ava_html}
            <div class="tw-profile-name">
                <h2>{username}</h2>
                <span class="handle">@{esc(nickname)}</span>
            </div>
            {f'<div class="tw-profile-bio">{desc}</div>' if desc else ''}
            <div class="tw-profile-meta">
                <div><b>{len(records)}</b> {t('total_posts',lang)}</div>
            </div>
            <div class="tw-profile-actions">
                {sugg_btn}
            </div>
        </div>
    </div>
    <div class="tw-header" style="position:static;margin-top:8px;"><h1 style="font-size:17px;">{t('my_posts',lang) if is_owner else t('home_title',lang)}</h1></div>
    {posts_html}
    """
    return base_layout(lang, token, viewer or "", "home", content, avatar, username, nickname)

def record_page_html(nickname, user, record, lang, token, viewer):
    is_owner = (viewer == nickname)
    avatar = esc(user.get('avatar_data',''))
    username = esc(user.get('username',''))
    post_html = render_post_card(record, lang, own=is_owner, viewer=viewer, show_handle=True)
    content = f"""
    <div class="tw-header">
        <a href="/{esc(nickname)}" class="tw-btn" style="padding:6px;">{svg('chev_l',16)} {t('back_home',lang)}</a>
    </div>
    {post_html}
    """
    return base_layout(lang, token, viewer or "", "home", content, avatar, username, nickname)

def bugreport_html(username, reports, lang, token):
    items = ""
    for r in reports:
        st = esc(r.get('status','Принято'))
        st_cls = 'blue' if st in ('Принято','Accepted') else ('danger' if st in ('Отклонено','Rejected') else '')
        items += f'<div class="tw-suggest-card"><div class="tw-suggest-hd"><b>{st}</b><span>{fmt_date(r.get("created_at",""))}</span></div><div class="tw-suggest-body">{esc(r.get("content",""))}</div></div>'
    if not items: items = f'<div class="tw-empty">{svg("bell",40)}<div>—</div></div>'
    
    content = f"""
    <div class="tw-header"><h1>{t('bugreport_title',lang)}</h1></div>
    <form action="/bugreport" method="post" class="tw-form">
        <input type="hidden" name="csrf_token" value="{token}">
        <label>{t('bugreport_name',lang)}</label>
        <input type="text" name="name" value="{esc(username)}" required>
        <label>{t('bugreport_desc',lang)}</label>
        <textarea name="content" required style="min-height:100px;"></textarea>
        <button type="submit" class="tw-btn blue">{t('bugreport_send',lang)}</button>
    </form>
    <div class="tw-header" style="position:static;margin-top:8px;"><h1 style="font-size:17px;">{t('bugreport_my',lang)}</h1></div>
    {items}
    """
    return base_layout(lang, token, "", "bug", content)

def privacy_html(lang, token):
    content = f"""
    <div class="tw-header"><h1>{t('privacy_title',lang)}</h1></div>
    <div style="padding:16px;font-size:15px;line-height:1.6;">{t('privacy_text',lang)}</div>
    <div style="padding:16px;text-align:center;"><a href="/home" class="tw-btn">{svg('chev_l',16)} {t('back_home',lang)}</a></div>
    """
    return base_layout(lang, token, "", "", content)

def stats_html(lang, token, uc, pc, sc, lu, viewer=""):
    start = SERVER_START_DT.strftime("%d.%m.%y %H:%M UTC")
    lu_str = fmt_date(lu) if lu else "—"
    up = _uptime(lang)
    contacts = "".join(f'<a href="mailto:{e}">{svg("email",16)} {e}</a>' for e in CONTACT_EMAILS)
    
    content = f"""
    <div class="tw-header"><h1>{t('stats_title',lang)}</h1></div>
    <div class="tw-stats-row"><b>{t('stats_users',lang)}</b><span>{uc}</span></div>
    <div class="tw-stats-row"><b>{t('stats_posts',lang)}</b><span>{pc}</span></div>
    <div class="tw-stats-row"><b>{t('stats_sugges',lang)}</b><span>{sc}</span></div>
    <div class="tw-stats-row"><b>{t('stats_started',lang)}</b><span style="font-size:15px;color:#0f1419;">{start}</span></div>
    <div class="tw-stats-row"><b>{t('stats_last',lang)}</b><span style="font-size:15px;color:#0f1419;">{lu_str}</span></div>
    <div class="tw-stats-row"><b>{t('stats_uptime',lang)}</b><span>{up}</span></div>
    <div class="tw-contacts">
        <b>{t('stats_contacts',lang)}</b>
        {contacts}
    </div>
    """
    return base_layout(lang, token, viewer, "stats", content)

# --- ROUTES ---
@app.get("/set_lang/{lang}")
async def set_lang(lang: str, next: str = "/home"):
    res = RedirectResponse(next, 303)
    res.set_cookie("lang", lang if lang in ["ru","en"] else "ru", max_age=31536000)
    return res

@app.get("/", response_class=HTMLResponse)
async def index(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if nickname:
        try:
            rdb = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
            if rdb.data:
                resp = RedirectResponse("/home", 303); set_csrf_cookie(resp, token, r); return resp
        except Exception: pass
    res = HTMLResponse(auth_html(lang, "", token)); set_csrf_cookie(res, token, r); return res

@app.get("/home", response_class=HTMLResponse)
async def home_page(r: Request, page: int = 1, q: str = "", author: str = "", lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    page = max(1, int(page or 1))
    posts, total = await _fetch_home_posts(page=page, per_page=PER_PAGE, q=q, author=author)
    res = HTMLResponse(home_html(lang, token, posts, page, total, q, author, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r); viewer = r.cookies.get("nickname") or ""
    try: uc, pc, sc, lu = await _stats_data()
    except Exception: uc, pc, sc, lu = 0,0,0,None
    res = HTMLResponse(stats_html(lang, token, uc, pc, sc, lu, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    res = HTMLResponse(privacy_html(lang, token)); set_csrf_cookie(res, token, r); return res

@app.post("/register", response_class=HTMLResponse)
async def register(r: Request, res: Response, username: str = Form(...), nickname: str = Form(...), password: str = Form(...), re_pass: str = Form(...), captcha: str = Form(None), privacy: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('captcha',lang), token)
    if not privacy: return auth_html(lang, "Примите политику" if lang=="ru" else "Accept policy", token)
    if password != re_pass: return auth_html(lang, "Пароли не совпадают" if lang=="ru" else "Passwords don't match", token)
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
        if x.data: return auth_html(lang, "Ник занят" if lang=="ru" else "Nickname taken", token)
        await asyncio.to_thread(lambda: sb.table('users').insert({"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}).execute())
    except Exception as e:
        return auth_html(lang, f"DB: {str(e)}", token)
    resp = RedirectResponse("/cabinet", 303)
    secure = r.url.scheme == "https"
    resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
    set_csrf_cookie(resp, token, r); return resp

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r); ip = r.client.host if r.client else "0.0.0.0"
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('captcha',lang), token)
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('password').eq('nickname', nickname).execute())
        user = x.data[0] if x.data else None
        if user and verify_password(password, user.get("password","")):
            _login_clear(ip)
            if len(user["password"]) == 64:
                await asyncio.to_thread(lambda: sb.table('users').update({"password": hash_password(password)}).eq('nickname', nickname).execute())
            resp = RedirectResponse("/cabinet", 303)
            secure = r.url.scheme == "https"
            resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
            set_csrf_cookie(resp, token, r); return resp
        _login_fail(ip)
    except Exception as e:
        return auth_html(lang, f"DB: {str(e)}", token)
    return auth_html(lang, "Неверный логин/пароль" if lang=="ru" else "Invalid login", token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname, include_private=True)
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(nickname, user_data, po, lang, token, nickname))
    set_csrf_cookie(res, token, r); return res

@app.get("/cabinet/suggestions", response_class=HTMLResponse)
async def cabinet_suggestions(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    s_data = await _fetch_suggestions(nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(suggestions_page_html(nickname, s_data, lang, token))
    set_csrf_cookie(res, token, r); return res

@app.get("/{nickname}/sugges", response_class=HTMLResponse)
async def sugges_form(nickname: str, r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r); viewer = r.cookies.get("nickname") or ""
    user_data = await _fetch_user(nickname)
    if not user_data: return HTMLResponse(f"<h2>{t('user_not_found',lang) if 'user_not_found' in LOCALES[lang] else 'User not found'}</h2>", 404)
    rules = user_data.get('sugges_rules','') or ''
    res = HTMLResponse(sugges_form_html(nickname, lang, token, viewer=viewer, rules=rules, enabled=_sugg_enabled(user_data), photo_enabled=_sugg_photo_enabled(user_data)))
    set_csrf_cookie(res, token, r); return res

def merge_memory(recs, nick, include_private=False):
    f = []
    for x in (recs or []):
        if not isinstance(x, dict): continue
        xid = x.get('id')
        if not xid or xid in deleted_records: continue
        vis = x.get('visibility','public') or 'public'
        if vis == 'private' and not include_private: continue
        if xid in pinned_records: x['is_pinned'] = pinned_records[xid]
        f.append(x)
    for rid, x in pending_records.items():
        if isinstance(x, dict) and x.get('user_nickname') == nick:
            vis = x.get('visibility','public') or 'public'
            if vis == 'private' and not include_private: continue
            f.append(x)
    try: f.sort(key=lambda x: (bool(x.get('is_pinned')), str(x.get('created_at') or '')), reverse=True)
    except Exception: pass
    return f

@app.post("/rpc")
async def rpc_endpoint(req: RPCRequest, r: Request, nickname: str = Cookie(None)):
    if not check_csrf(r): raise HTTPException(403, "CSRF")
    if req.method == "submit_suggestion":
        target = req.params.get("target_nickname","").strip()
        name = req.params.get("sugg_name","").strip()[:60]
        content = req.params.get("content","").strip()[:500]
        img = valid_b64(req.params.get("image_data",""))
        if not target or not name or not content: raise HTTPException(400, "Missing")
        if nickname and target == nickname: raise HTTPException(400, "Self")
        try:
            u = await asyncio.to_thread(lambda: sb.table('users').select('nickname,sugges_enabled,sugges_photo_enabled').eq('nickname', target).execute())
            if not u.data: raise HTTPException(404, "Not found")
            tu = u.data[0]
            if not _sugg_enabled(tu): raise HTTPException(400, "Disabled")
            if not _sugg_photo_enabled(tu): img = ""
        except HTTPException: raise
        except Exception as e: raise HTTPException(500, str(e))
        d = {"author_nickname": target, "suggested_by_name": name, "content": content, "status": "pending", "image_data": img}
        try: await asyncio.to_thread(lambda: sb.table('suggestions').insert(d).execute())
        except Exception:
            d.pop("image_data", None)
            await asyncio.to_thread(lambda: sb.table('suggestions').insert(d).execute())
        return {"status": "ok"}
    if not nickname: raise HTTPException(401, "Unauth")
    try:
        if req.method == "create_record":
            content = req.params.get("content","").strip()
            cid = req.params.get("client_id")
            img = valid_b64(req.params.get("image_data",""))
            vis = req.params.get("visibility","public") or "public"
            if vis not in ("public","private"): vis = "public"
            i = cid or str(uuid.uuid4()); n = datetime.now(timezone.utc).isoformat()
            pd = {"id": i, "user_nickname": nickname, "content": content, "is_pinned": False, "created_at": n, "image_data": img, "visibility": vis}
            try: await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
            except Exception:
                pd.pop("image_data", None)
                try: await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
                except Exception:
                    pd.pop("visibility", None)
                    await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        if req.method == "delete_record":
            rid = req.params.get("post_id")
            await asyncio.to_thread(lambda: sb.table('posts').delete().eq('id', rid).eq('user_nickname', nickname).execute())
            await manager.broadcast({"type": "delete_record", "post_id": rid})
            return {"status": "ok"}
        if req.method == "pin_record":
            rid = req.params.get("post_id")
            x = await asyncio.to_thread(lambda: sb.table('posts').select('is_pinned').eq('id', rid).eq('user_nickname', nickname).execute())
            if not x.data: raise HTTPException(404, "Not found")
            ns = not x.data[0].get('is_pinned', False)
            if ns:
                await asyncio.to_thread(lambda: sb.table('posts').update({"is_pinned": False}).eq('user_nickname', nickname).neq('id', rid).execute())
            await asyncio.to_thread(lambda: sb.table('posts').update({"is_pinned": ns}).eq('id', rid).eq('user_nickname', nickname).execute())
            return {"status": "ok"}
        if req.method == "approve_suggestion":
            sid = req.params.get("suggestion_id")
            s = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('id', sid).eq('author_nickname', nickname).execute())
            if not s.data: raise HTTPException(404, "Not found")
            sugg = s.data[0]; i = str(uuid.uuid4()); n = datetime.now(timezone.utc).isoformat()
            np = {"id": i, "user_nickname": nickname, "content": sugg.get('content',''), "is_pinned": False, "created_at": n, "suggested_by": sugg.get('suggested_by_name',''), "image_data": sugg.get('image_data','') or '', "visibility": "public"}
            try: await asyncio.to_thread(lambda: sb.table('posts').insert(np).execute())
            except Exception:
                np.pop("suggested_by", None); np.pop("image_data", None); np.pop("visibility", None)
                await asyncio.to_thread(lambda: sb.table('posts').insert(np).execute())
            await asyncio.to_thread(lambda: sb.table('suggestions').delete().eq('id', sid).execute())
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok"}
        if req.method == "reject_suggestion":
            sid = req.params.get("suggestion_id")
            await asyncio.to_thread(lambda: sb.table('suggestions').delete().eq('id', sid).eq('author_nickname', nickname).execute())
            return {"status": "ok"}
        raise HTTPException(400, "Unknown")
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/cabinet/edit", response_class=HTMLResponse)
async def edit(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(edit_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r); return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), sugges_enabled: str = Form(None), sugges_photo_enabled: str = Form(None), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token): return RedirectResponse("/cabinet/edit", 303)
    update = {"username": username, "description": description, "sugges_rules": sugges_rules, "sugges_enabled": bool(sugges_enabled), "sugges_photo_enabled": bool(sugges_photo_enabled)}
    av = valid_b64(avatar_data)
    if av: update["avatar_data"] = av
    try: await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
    except Exception:
        update.pop("avatar_data", None); update.pop("sugges_enabled", None); update.pop("sugges_photo_enabled", None)
        try: await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
        except Exception: pass
    return RedirectResponse("/cabinet", 303)

@app.get("/bugreport", response_class=HTMLResponse)
async def bugreport(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    u = ""; rp = []
    if nickname:
        try:
            x = await asyncio.to_thread(lambda: sb.table('users').select('username').eq('nickname', nickname).execute())
            if x.data: u = x.data[0].get('username') or ""
            y = await asyncio.to_thread(lambda: sb.table('bug_reports').select('*').eq('user_nickname', nickname).order('created_at', desc=True).execute())
            rp = y.data or []
        except Exception: pass
    token = get_csrf_token(r)
    res = HTMLResponse(bugreport_html(u, rp, lang, token))
    set_csrf_cookie(res, token, r); return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return RedirectResponse("/bugreport", 303)
    d = {"name": name, "content": content, "status": "Принято" if lang == "ru" else "Accepted"}
    if nickname: d["user_nickname"] = nickname
    await asyncio.to_thread(lambda: sb.table('bug_reports').insert(d).execute())
    return RedirectResponse("/bugreport", 303)

@app.get("/logout")
async def logout():
    res = RedirectResponse("/", 303); res.delete_cookie("nickname"); return res

@app.get("/{nickname}/{rid}", response_class=HTMLResponse)
async def record_page(nickname: str, rid: str, r: Request, lang: str = Cookie("ru")):
    try:
        u, x = await asyncio.gather(
            asyncio.to_thread(lambda: sb.table('users').select('username,avatar_data,sugges_enabled,sugges_photo_enabled').eq('nickname', nickname).execute()),
            asyncio.to_thread(lambda: sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute())
        )
        if not u.data: return HTMLResponse("<h2>Not found</h2>", 404)
        if not x.data: return HTMLResponse("<h2>Not found</h2>", 404)
        u_data = u.data[0]; rec = x.data[0]
        if rec.get('visibility') == 'private' and r.cookies.get("nickname") != nickname:
            return HTMLResponse("<h2>Not found</h2>", 404)
    except Exception:
        return HTMLResponse("<h2>Error</h2>", 500)
    token = get_csrf_token(r); viewer = r.cookies.get("nickname") or ""
    res = HTMLResponse(record_page_html(nickname, u_data, rec, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        return HTMLResponse("<h2>Not found</h2><a href='/home'>OK</a>", 404)
    viewer = r.cookies.get("nickname") or ""
    is_owner = (viewer == nickname)
    po = merge_memory(p_data, nickname, include_private=is_owner)
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, user_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
