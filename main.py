from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, httpx, asyncio, time as time_module, traceback, os
from datetime import datetime, timezone
from urllib.parse import quote
from contextvars import ContextVar

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

APP_VERSION = "0.31"
SERVER_START_DT = datetime.now(timezone.utc)
SERVER_START_DATE = SERVER_START_DT.strftime("%d.%m.%y")
CONTACT_EMAILS = ["sldshr.confirmation@gmail.com", "sldshr.confirm@yandex.ru"]
SITE_URL = "https://solid.fastapicloud.dev"
DESTROY_BASE = "https://destroy.spritefusion.com/?from=badge&url="

_current_path: ContextVar[str] = ContextVar("current_path", default="/")

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

CACHE = {"posts": [], "users": {}}

@app.on_event("startup")
async def load_cache():
    print("Загрузка данных из БД в оперативку...")
    try:
        res_posts = await asyncio.to_thread(lambda: sb.table('posts').select('*').execute())
        CACHE["posts"] = res_posts.data or []
        res_users = await asyncio.to_thread(lambda: sb.table('users').select('*').execute())
        for u in (res_users.data or []):
            CACHE["users"][u['nickname']] = u
        print(f"Успешно загружено: {len(CACHE['posts'])} постов, {len(CACHE['users'])} пользователей.")
    except Exception as e:
        print(f"Ошибка при загрузке кэша: {e}")

deleted_records, pinned_records, pending_records = set(), {}, {}
MAX_B64_LEN = 900000
POST_MAX_LEN = 5000
VALID_NICK_RE = re.compile(r'^[a-zA-Z0-9_\-]{3,30}$')
VALID_USER_RE = re.compile(r'^[\w\s\-]{1,60}$', re.UNICODE)

class _DBUnavailable:
    pass
DB_UNAVAILABLE = _DBUnavailable()

_RATE_BUCKETS = {}
_LOGIN_FAILS = {}

def _rate_ok(key, limit=60, window=60):
    now = time_module.time()
    lst = _RATE_BUCKETS.setdefault(key, [])
    lst[:] = [t for t in lst if now - t < window]
    if len(lst) >= limit: return False
    lst.append(now)
    return True

def _login_fails(ip):
    now = time_module.time()
    return len([t for t in _LOGIN_FAILS.get(ip, []) if now - t < 300])

def _login_fail(ip):
    now = time_module.time()
    lst = _LOGIN_FAILS.setdefault(ip, [])
    lst[:] = [t for t in lst if now - t < 300]
    lst.append(now)

def _login_clear(ip): _LOGIN_FAILS.pop(ip, None)

def _resolve_lang(r: Request, setlang: str = None) -> str:
    if setlang in ("ru", "en"): return setlang
    c = r.cookies.get("lang")
    if c in ("ru", "en"): return c
    return "ru"

def _set_lang_cookie(res: Response, r: Request, lang: str):
    res.set_cookie("lang", lang, path="/", max_age=31536000, samesite="lax",
                   secure=(r.url.scheme == "https"), httponly=True)

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://fonts.cdnfonts.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net https://fonts.cdnfonts.com; "
    "img-src 'self' data: https: blob:; "
    "connect-src 'self' https: wss:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

@app.middleware("http")
async def security_mw(request: Request, call_next):
    _current_path.set(request.url.path)
    path = request.url.path
    ip = request.client.host if request.client else "0.0.0.0"
    if path in ("/login", "/register", "/rpc") and not _rate_ok(f"auth:{ip}", 40, 60):
        return Response("Too Many Requests", status_code=429)
    if path == "/login" and request.method == "POST" and _login_fails(ip) >= 10:
        return Response("Too many login attempts. Wait 5 min.", status_code=429, media_type="text/plain")
    try:
        response = await call_next(request)
    except Exception:
        traceback.print_exc()
        return Response("Internal Server Error", status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = CSP
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/static/") or path in ("/manifest.json", "/sw.js"):
        pass
    elif path == "/api/og":
        response.headers["Cache-Control"] = "public, max-age=3600"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    traceback.print_exc()
    lang = _resolve_lang(request)
    msg = "Ошибка сервера" if lang == "ru" else "Server error"
    return HTMLResponse(f"<h1 style='color:red'>{msg}</h1><a href='/'>OK</a>", status_code=500)

@app.get("/static/ru_font.ttf")
async def ru_font():
    for p in ("/app/static/ru_font.ttf", "static/ru_font.ttf", "/app/ru_font.ttf", "ru_font.ttf", "./static/ru_font.ttf"):
        if os.path.exists(p):
            return FileResponse(p, media_type="font/ttf", headers={"Cache-Control": "public, max-age=31536000, immutable"})
    return Response("Font not found", status_code=404)

def esc(val): return html.escape(str(val)) if val is not None else ""

def strip_html(s):
    if not s: return ""
    return re.sub(r'<[^>]+>', '', str(s))

def sanitize_url(u):
    if not u: return ""
    u = str(u)
    if re.match(r'^https?://', u, re.I): return u
    if re.match(r'^data:image/', u, re.I): return u
    return ""

def linkify(text):
    if not text: return ""
    s = html.escape(text)
    return re.sub(r'(https?://[^\s]+)', r'<a href="#" class="ext-link" data-url="\1" onclick="showLinkWarning(event, this)">\1</a>', s).replace('\n', '<br>')

def valid_b64(s):
    if not s: return ""
    s = str(s)
    if len(s) > MAX_B64_LEN or not s.startswith("data:image/"): return ""
    return s

def clean_content(s):
    if not s: return ""
    s = str(s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    return s[:POST_MAX_LEN]

def _uptime_str(lang="ru"):
    delta = datetime.now(timezone.utc) - SERVER_START_DT
    sec = int(delta.total_seconds())
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}д" if lang == "ru" else f"{d}d")
    parts.append(f"{h:02d}:{m:02d}:{s:02d}")
    return " ".join(parts)

def og_tags(title, description="", path="", image="", lang="ru"):
    full_url = SITE_URL + path if path else SITE_URL
    desc = strip_html(description)[:250] if description else ""
    safe_img = sanitize_url(image)
    parts = [
        f'<meta property="og:title" content="{esc(title)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Solid">',
        f'<meta property="og:url" content="{esc(full_url)}">',
        f'<meta property="og:locale" content="{"ru_RU" if lang == "ru" else "en_US"}">',
    ]
    if desc:
        parts.append(f'<meta property="og:description" content="{esc(desc)}">')
        parts.append(f'<meta name="description" content="{esc(desc)}">')
    if safe_img:
        parts.append(f'<meta property="og:image" content="{esc(safe_img)}">')
    parts.append('<meta name="twitter:card" content="summary">')
    parts.append(f'<meta name="twitter:title" content="{esc(title)}">')
    if desc:
        parts.append(f'<meta name="twitter:description" content="{esc(desc)}">')
    return "".join(parts)

async def _fetch_user(nickname):
    if nickname in CACHE["users"]:
        return dict(CACHE["users"][nickname])
    for sel in ('username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
                'username,description,sugges_rules,avatar_data,sugges_enabled',
                'username,description,sugges_rules,avatar_data',
                'username,description,sugges_rules',
                'username,description'):
        try:
            res = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nickname).execute())
            if res.data:
                CACHE["users"][nickname] = res.data[0]
                return res.data[0]
            return None
        except Exception:
            continue
    return DB_UNAVAILABLE

async def _fetch_posts(nickname):
    try:
        user_posts = [p for p in CACHE["posts"] if p.get('user_nickname') == nickname]
        user_posts.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return user_posts
    except Exception: return []

async def _fetch_suggestions(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('author_nickname', nickname).eq('status', 'pending').order('created_at', desc=True).execute())
        return res.data or []
    except Exception: return []

async def _fetch_suggestion_count(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('suggestions').select('id', count='exact').eq('author_nickname', nickname).eq('status','pending').execute())
        return res.count if getattr(res, 'count', None) is not None else len(res.data or [])
    except Exception: return 0

async def _stats_data():
    users_count = len(CACHE["users"])
    posts_count = len(CACHE["posts"])
    sugg_count, last_update = 0, None
    try:
        s = await asyncio.to_thread(lambda: sb.table('suggestions').select('id', count='exact').execute())
        sugg_count = s.count if getattr(s, 'count', None) is not None else len(s.data or [])
    except Exception: pass
    if CACHE["posts"]:
        try: last_update = max([p.get('created_at') for p in CACHE["posts"] if p.get('created_at')])
        except Exception: pass
    return users_count, posts_count, sugg_count, last_update

def user_sugges_enabled(u):
    return bool(u) and isinstance(u, dict) and u.get('sugges_enabled') is not False

def user_sugges_photo_enabled(u):
    return bool(u) and isinstance(u, dict) and u.get('sugges_photo_enabled') is not False

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws): await ws.accept(); self.active_connections.append(ws)
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
    return JSONResponse({
        "name": "Solid",
        "short_name": "Solid",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#000000",
        "orientation": "portrait",
        "categories": ["social", "utilities"],
        "icons": [
            {
                "src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xIDExczQtOCAxMS04IDExIDggMTEgOC00IDgtMTEgOC0xMS04LTExLTh6Ij48L3BhdGg+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMSIgcj0iMyI+PC9jaXJjbGU+PC9zdmc+",
                "sizes": "192x192",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ],
        "shortcuts": [
            {
                "name": "Новый пост",
                "url": "/cabinet/new",
                "icons": [{"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PGxpbmUgeDE9IjEyIiB5MT0iOCIgeDI9IjEyIiB5Mj0iMTYiLz48bGluZSB4MT0iOCIgeTE9IjEyIiB4Mj0iMTYiIHkyPSIxMiIvPjwvc3ZnPg==", "sizes": "192x192"}]
            }
        ]
    }, headers={"Cache-Control": "public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = """
    const CACHE_NAME = 'solid-v3';
    const STATIC_ASSETS = ['/manifest.json', '/static/ru_font.ttf'];
    self.addEventListener('install', (e) => {
        self.skipWaiting();
        e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(STATIC_ASSETS).catch(() => {})));
    });
    self.addEventListener('activate', (e) => {
        e.waitUntil(
            caches.keys()
                .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
                .then(() => self.clients.claim())
        );
    });
    self.addEventListener('fetch', (e) => {
        if (e.request.method !== 'GET') return;
        const url = new URL(e.request.url);
        if (url.origin !== self.location.origin) return;

        if (e.request.mode === 'navigate') {
            e.respondWith(
                fetch(e.request).catch(() => caches.match('/'))
            );
            return;
        }

        if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
            e.respondWith(
                caches.match(e.request).then((cached) => {
                    if (cached) return cached;
                    return fetch(e.request).then((resp) => {
                        if (resp && resp.ok) {
                            const clone = resp.clone();
                            caches.open(CACHE_NAME).then((c) => c.put(e.request, clone));
                        }
                        return resp;
                    });
                })
            );
        }
    });
    """
    return Response(content=js, media_type="application/javascript", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/api/og")
async def get_og(url: str):
    if not url.startswith("http://") and not url.startswith("https://"): return {"title": "", "description": "", "image": ""}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0, follow_redirects=True)
            hc = resp.text
            def gm(prop):
                m = re.search(fr'<meta[^>]+(?:property|name)=["\']og:{prop}["\'][^>]+content=["\']([^"\']*)["\']', hc, re.I)
                if not m: m = re.search(fr'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']og:{prop}["\']', hc, re.I)
                return m.group(1) if m else ""
            t = gm("title")
            if not t:
                tm = re.search(r'<title>([^<]*)</title>', hc, re.I)
                if tm: t = tm.group(1)
            return {"title": strip_html(t)[:200], "description": strip_html(gm("description"))[:300], "image": sanitize_url(gm("image"))}
    except Exception: return {"title": "", "description": "", "image": ""}

def hash_password(p): return bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(p, h):
    try:
        if len(h) == 64 and hashlib.sha256(p.encode()).hexdigest() == h: return True
        return bcrypt.checkpw(p.encode('utf-8'), h.encode('utf-8'))
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
async def val_handler(request: Request, exc: RequestValidationError):
    lang = _resolve_lang(request, request.query_params.get("setlang"))
    if request.url.path in ("/settings/account", "/cabinet/edit"):
        return RedirectResponse("/settings/account?error=empty", 303)
    em = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    res = HTMLResponse(content=auth_html(lang, em, token), status_code=422)
    set_csrf_cookie(res, token, request)
    return res

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

PRIVACY_RU = """1. Общие положения<br>Настоящая Политика конфиденциальности описывает, какие данные собирает Solid, как они используются и защищаются. Используя Сайт, вы соглашаетесь с данной Политикой. Если вы не согласны с её условиями — пожалуйста, не используйте Сайт.<br><br>2. Какие данные мы собираем<br>• Имя (юзернейм) — отображаемое имя, указанное при регистрации.<br>• Никнейм — уникальный идентификатор для входа.<br>• Пароль — хранится в защищённом виде.<br>• Описание профиля и аватар — по вашему желанию.<br>• Записи и предложки — контент, который вы публикуете.<br>• Технические данные — служебные файлы для работы сайта.<br><br>3. Как мы используем данные<br>• Аутентификация и поддержание сессии.<br>• Отображение профиля, записей и предложек.<br>• Защита от злоупотреблений.<br>• Мы не используем ваши данные для рекламы и не продаём их третьим лицам.<br><br>4. Хранение данных<br>Данные хранятся на защищённых серверах. Мы принимаем разумные меры для их защиты, однако ни один метод передачи через интернет не является абсолютно безопасным.<br><br>5. Служебные файлы<br>Сайт использует служебные файлы браузера для поддержания сессии, защиты форм и запоминания языка. Вы можете очистить их в настройках браузера, но это разлогинит вас.<br><br>6. Ваш контент<br>Все записи, комментарии и предложки являются вашей интеллектуальной собственностью. Публикуя контент, вы подтверждаете, что имеете на него право. Мы не несём ответственности за контент пользователей.<br><br>7. Передача третьим лицам<br>Мы не передаём ваши персональные данные третьим лицам, за исключением случаев, предусмотренных законом.<br><br>8. Безопасность<br>Мы используем современные методы защиты аккаунтов и данных.<br><br>9. Ваши права<br>• Изменить имя, описание и аватар в личном кабинете.<br>• Удалить свои записи.<br>• Отключить предложку.<br>• Запросить удаление аккаунта через контакты администрации.<br><br>10. Дети<br>Сайт не предназначен для лиц младше 13 лет. Если вы младше — не регистрируйтесь.<br><br>11. Изменения политики<br>Мы можем обновлять эту Политику. Актуальная версия всегда доступна по адресу /privacy. Дата последнего обновления указана в подвале сайта.<br><br>12. Контакты<br>По вопросам конфиденциальности: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru"""

PRIVACY_EN = """1. General provisions<br>This Privacy Policy describes what data Solid collects, how it is used and protected. By using the Site you agree to this Policy. If you disagree with its terms — please do not use the Site.<br><br>2. Data we collect<br>• Name (username) — display name you provide during registration.<br>• Nickname — a unique identifier for login.<br>• Password — stored in a protected form.<br>• Profile description and avatar — at your discretion.<br>• Records and suggestions — content you publish.<br>• Technical data — service files required for site operation.<br><br>3. How we use data<br>• Authentication and session maintenance.<br>• Displaying profile, records and suggestions.<br>• Abuse prevention.<br>• We do not use your data for advertising and do not sell it to third parties.<br><br>4. Data storage<br>Data is stored on protected servers. We take reasonable measures to protect it, however no method of transmission over the internet is completely secure.<br><br>5. Service files<br>The Site uses browser service files to maintain session, protect forms and remember language. You can clear them in browser settings, but this will log you out.<br><br>6. Your content<br>All records, comments and suggestions are your intellectual property. By publishing content, you confirm you have the right to it. We are not responsible for user content.<br><br>7. Third parties<br>We do not share your personal data with third parties, except as required by law.<br><br>8. Security<br>We use modern methods to protect accounts and data.<br><br>9. Your rights<br>• Edit your name, description and avatar in your cabinet.<br>• Delete your records.<br>• Disable suggestions.<br>• Request account deletion via administrator contacts.<br><br>10. Children<br>The Site is not intended for persons under 13 years of age. If you are younger — do not register.<br><br>11. Policy changes<br>We may update this Policy. The current version is always available at /privacy. The date of the last update is shown in the site footer.<br><br>12. Contacts<br>For privacy-related questions: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru"""

FAQ_DATA = {
    "ru": [
        ("lock", "Регистрация и вход", [
            ("Как зарегистрироваться?", 'На главной странице заполните форму «Регистрация»: укажите юзернейм (ваше имя), никнейм (уникальный логин), пароль не короче 8 символов и его повтор. Поставьте обе галочки — «Я не робот» и согласие с политикой. Нажмите «Зарегистрироваться!».'),
            ("Какой никнейм можно выбрать?", 'От 3 до 30 символов: латинские буквы a–z, цифры 0–9, знаки подчёркивания <code>_</code> и дефис <code>-</code>. Никнейм уникален — если он занят, выберите другой.'),
            ("Забыли пароль — что делать?", 'Напишите администрации по адресам из подвала сайта: <a href="mailto:sldshr.confirmation@gmail.com">sldshr.confirmation@gmail.com</a> или <a href="mailto:sldshr.confirm@yandex.ru">sldshr.confirm@yandex.ru</a>. Укажите ваш никнейм.'),
            ("Как выйти из аккаунта?", 'В разделе «Настройки» нажмите «Выйти» или найдите красную кнопку в левой панели на компьютере.'),
        ]),
        ("pencil", "Записи и посты", [
            ("Как создать запись?", 'Откройте раздел «Создать» (на телефоне — иконка плюса внизу). Напишите текст и нажмите «Создать». Запись сразу появится в ленте и на вашей странице.'),
            ("Какая максимальная длина записи?", 'До 5000 символов. Символы переноса строки сохраняются.'),
            ("Как прикрепить фото?", 'В форме создания записи нажмите «Фото» и выберите изображение. Фото автоматически сожмётся и прикрепится к записи.'),
            ("Как закрепить запись?", 'Наведите на запись и нажмите «Закрепить» в правом верхнем углу. Закреплённая запись всегда будет наверху. Можно закрепить только одну запись одновременно.'),
            ("Как удалить запись?", 'Наведите на запись, нажмите «Удалить», подтвердите действие. Удаление необратимо.'),
            ("Как поделиться ссылкой на запись?", 'Наведите на запись и нажмите «Ссылка» — ссылка скопируется в буфер обмена.'),
            ("Что такое автопревью ссылок?", 'Если в записи есть URL, при клике откроется диалог с превью: заголовок, описание и картинка с того сайта. Это защита от случайных переходов.'),
        ]),
        ("lightbulb", "Предложка", [
            ("Что такое предложка?", 'Это форма обратной связи для ваших читателей: они могут предложить пост, который вы одобрите или отклоните. Найти её можно по адресу /ваш_никнейм/sugges.'),
            ("Как предложить пост?", 'Откройте страницу пользователя и нажмите «Предложить пост». Введите ваше имя и текст, при желании прикрепите фото, нажмите «Отправить».'),
            ("Как включить или отключить предложку?", 'В разделе «Редактировать профиль» есть переключатель «Разрешить предложку». Отключённая предложка скрывает кнопку у всех посетителей.'),
            ("Как отключить фото в предложке?", 'Там же — переключатель «Разрешить фото в предложке». Если выключить, форма предложки будет без загрузки фото.'),
            ("Как модерировать предложки?", 'Нажмите «Предложки» (вкладка внизу на телефоне). Каждую можно «Одобрить» (превратится в вашу запись с пометкой автора) или «Отклонить» (удалить).'),
            ("Как задать правила для предложки?", 'В «Редактировать профиль» в поле «Правила предложки» (до 1000 символов). Они будут показаны всем, кто открывает форму.'),
            ("Можно ли предложить пост самому себе?", 'Нет. Свои посты создавайте напрямую в разделе «Создать».'),
        ]),
        ("gear", "Профиль и настройки", [
            ("Как изменить имя или описание?", 'В «Редактировать профиль» укажите новое имя и описание (до 300 символов) и сохраните изменения.'),
            ("Как сменить аватар?", 'На странице редактирования профиля нажмите на аватар — откроется выбор файла. Фото автоматически подстроится под аватар.'),
            ("Где найти настройки?", 'Откройте раздел «Настройки» — на телефоне это нижняя панель, на компьютере — прямая ссылка /settings. Там можно сменить язык и посмотреть информацию о приложении.'),
            ("Как сменить язык?", 'В разделе «Настройки» выберите RU или EN. Выбор запоминается автоматически.'),
            ("Где посмотреть статистику сайта?", 'Ссылка «Статистика» в подвале или в настройках.'),
            ("Как удалить аккаунт?", 'Напишите администрации. Мы удалим аккаунт и все связанные записи в течение 7 дней.'),
        ]),
        ("image", "Фото и изображения", [
            ("Какие форматы фото поддерживаются?", 'Любые, которые умеет открывать браузер: JPEG, PNG, WebP, GIF.'),
            ("Почему фото сжимаются?", 'Чтобы сайт работал быстрее и не занимал много места. Сжатие происходит автоматически при загрузке.'),
            ("Фото не загружается — что делать?", 'Попробуйте выбрать файл поменьше или изображение попроще. Если проблема повторяется — сообщите через баг-репорт.'),
            ("Как посмотреть фото в полном размере?", 'Кликните по изображению — откроется просмотрщик. В нём можно кликнуть по фото, чтобы увеличить. Закрыть — крестик сверху справа или клавишей Esc.'),
        ]),
        ("shield", "Безопасность", [
            ("Мои данные в безопасности?", 'Да, мы используем современные методы защиты аккаунтов и данных.'),
            ("Кто видит мои данные?", 'Публично видны только те данные, которые вы указали в профиле: имя, никнейм, описание, аватар и записи.'),
            ("Что такое политика конфиденциальности?", 'Документ, описывающий какие данные мы собираем и как их используем. Полный текст — по ссылке в подвале или на /privacy.'),
        ]),
        ("bug", "Проблемы и поддержка", [
            ("Как сообщить о баге?", 'Откройте /bugreport, опишите проблему. Все ваши заявки видны там же со статусом: Принято, В работе, Исправлено, Отклонено.'),
            ("Не работает вход — что проверить?", '1) Никнейм точно такой, как при регистрации. 2) Пароль не короче 8 символов. 3) Галочка «Я не робот» поставлена. Если не помогает — напишите администрации.'),
            ("Почему не приходит письмо?", 'Письма мы не отправляем — вся связь через форму баг-репорта или контакты в подвале.'),
            ("С кем связаться?", 'Email администрации: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru. Отвечаем в течение 1–2 дней.'),
            ("Что такое «аптайм» в статистике?", 'Время с момента запуска сервера. Если сервер перезапущен — счётчик начинается заново.'),
        ]),
    ],
    "en": [
        ("lock", "Registration & Login", [
            ("How do I register?", 'On the home page, fill in the "Registration" form: enter a username (your name), nickname (unique login), a password of at least 8 characters, and repeat it. Tick both boxes — "I am not a robot" and the privacy policy agreement. Click "Register!".'),
            ("What nickname can I choose?", 'From 3 to 30 characters: latin letters a–z, digits 0–9, underscores <code>_</code> and hyphens <code>-</code>. Nickname is unique — pick another if taken.'),
            ("I forgot my password — what now?", 'Email the administration at the addresses in the footer: <a href="mailto:sldshr.confirmation@gmail.com">sldshr.confirmation@gmail.com</a> or <a href="mailto:sldshr.confirm@yandex.ru">sldshr.confirm@yandex.ru</a>. Include your nickname.'),
            ("How do I log out?", 'In "Settings" tap "Logout", or find the red button in the left panel on desktop.'),
        ]),
        ("pencil", "Records & Posts", [
            ("How do I create a record?", 'Open "Create" (on mobile — the plus icon at the bottom). Type your text and tap "Create". The record appears immediately in the feed and on your page.'),
            ("What is the max record length?", 'Up to 5000 characters. Line breaks are preserved.'),
            ("How do I attach a photo?", 'In the create form tap "Photo" and pick an image. The photo is auto-compressed and attached.'),
            ("How do I pin a record?", 'Hover over the record and click "Pin" in the top-right corner. Only one record can be pinned at a time.'),
            ("How do I delete a record?", 'Hover over the record, click "Delete", confirm. Deletion is irreversible.'),
            ("How do I share a link to a record?", 'Hover over the record and click "Link" — the URL is copied to clipboard.'),
            ("What is auto link preview?", 'If a record contains a URL, clicking it opens a dialog with a preview: title, description and image from that site.'),
        ]),
        ("lightbulb", "Suggestions", [
            ("What is the suggestion box?", 'It is a feedback form for your readers: they can suggest a post that you approve or reject. Available at /your_nickname/sugges.'),
            ("How do I suggest a post?", 'Open a user page and click "Suggest a post". Enter your name and text, optionally attach a photo, click "Send".'),
            ("How do I enable or disable suggestions?", 'In "Edit Profile" there is a toggle "Enable suggestions". Disabled suggestions hide the button from all visitors.'),
            ("How do I disable photos in suggestions?", 'Same place — "Allow photos in suggestions" toggle.'),
            ("How do I moderate suggestions?", 'Tap "Suggestions" (bottom tab on mobile). Each can be "Approve" or "Reject".'),
            ("How do I set rules for suggestions?", 'In "Edit Profile" under "Suggestion rules" (up to 1000 chars).'),
            ("Can I suggest a post to myself?", 'No. Create your posts directly in "Create".'),
        ]),
        ("gear", "Profile & Settings", [
            ("How do I change name or description?", 'In "Edit Profile" enter a new name and description (up to 300 chars) and save.'),
            ("How do I change my avatar?", 'On the profile edit page click the avatar — a file picker opens.'),
            ("Where do I find settings?", 'Open "Settings" — bottom bar on mobile, or direct URL /settings. There you can change language and view app info.'),
            ("How do I change the language?", 'In "Settings" choose RU or EN. The choice is remembered automatically.'),
            ("Where can I see site statistics?", 'The "Stats" link in the footer or in settings.'),
            ("How do I delete my account?", 'Email the administration. We will delete the account and all related records within 7 days.'),
        ]),
        ("image", "Photos & Images", [
            ("Which photo formats are supported?", 'Any your browser can open: JPEG, PNG, WebP, GIF.'),
            ("Why are photos compressed?", 'To keep the site fast. Compression happens automatically on upload.'),
            ("A photo fails to upload — what to do?", 'Try a smaller file or a simpler image. If it keeps failing — report via bug-report.'),
            ("How do I view a photo full-size?", 'Click the image — a viewer opens. Click the image again to zoom. Close with the X in the top-right corner or Esc.'),
        ]),
        ("shield", "Security", [
            ("Is my data safe?", 'Yes, we use modern methods to protect accounts and data.'),
            ("Who sees my data?", 'Publicly visible: only what you put in your profile — name, nickname, description, avatar and records.'),
            ("What is the privacy policy?", 'A document describing what data we collect and how we use it. Full text — at /privacy.'),
        ]),
        ("bug", "Problems & Support", [
            ("How do I report a bug?", 'Open /bugreport and describe the issue. Your reports are listed there with status.'),
            ("Login doesn\'t work — what to check?", '1) Nickname exactly as at registration. 2) Password at least 8 chars. 3) "I am not a robot" ticked. If it still fails — email the administration.'),
            ("Why don\'t I receive emails?", 'We do not send emails — all contact via the bug-report form or footer addresses.'),
            ("Who do I contact?", 'Admin email: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru. We reply within 1–2 days.'),
            ("What is \'uptime\' in stats?", 'Time since server start. If the server restarts, the counter starts over.'),
        ]),
    ]
}

LOCALES = {
    "ru": {
        "reg": "Регистрация", "login": "Вход", "username": "юзернейм", "nickname": "никнейм",
        "password": "пароль", "re_pass": "повтор пароля", "captcha": "Я не робот",
        "register_btn": "Зарегистрироваться!", "login_btn": "Войти", "profile": "ПРОФИЛЬ",
        "total_posts": "Всего записей", "logout": "Выйти", "edit_profile": "Редактировать профиль",
        "save_changes": "Сохранить изменения", "description": "Описание",
        "desc_placeholder": "Расскажите о себе...",
        "create_post_btn": "Создать", "create_post_placeholder": "Напишите что-нибудь...",
        "my_posts": "МОИ ЗАПИСИ", "user_posts": "ЗАПИСИ ПОЛЬЗОВАТЕЛЯ",
        "no_posts": "Записей пока нет...", "pin": "Закрепить", "unpin": "Открепить", "delete": "Удалить",
        "confirm_delete": "Удалить запись?", "created_by": "Создано:", "hosting": "Хостинг:",
        "back_home": "На главную", "user_not_found": "Пользователь не найден.",
        "alert_captcha": "Подтвердите, что вы не робот!", "alert_pass_mismatch": "Пароли не совпадают!",
        "alert_nick_taken": "Такой никнейм уже занят!", "alert_bad_login": "Неверный никнейм или пароль!",
        "alert_desc_long": "Описание > 300 символов!", "link_profile": "(Ссылка)", "cancel": "Отмена",
        "username_label": "Имя", "nickname_label": "Никнейм", "bugreport_title": "Баг-репорт",
        "bugreport_name": "Ваше имя", "bugreport_desc": "Описание проблемы", "bugreport_send": "Отправить",
        "bugreport_my": "Мои заявки", "privacy_title": "Политика конфиденциальности",
        "privacy_text": PRIVACY_RU,
        "privacy_agree": "Я согласен с", "privacy_link": "Политикой конфиденциальности",
        "alert_privacy": "Примите политику!", "cabinet": "ЛИЧНЫЙ КАБИНЕТ",
        "record_page": "Запись", "copy_link": "Ссылка",
        "ext_title": "Переход на внешний сайт", "ext_desc": "Вы покидаете наш сайт и переходите по ссылке:",
        "ext_continue": "Перейти", "ext_loading": "Загрузка превью...",
        "suggestions_title": "ПРЕДЛОЖКИ", "suggestions_btn": "Предложить пост",
        "sugges_title": "Предложить пост для", "sugges_name": "Ваше имя",
        "sugges_content": "Текст поста", "sugges_send": "Отправить",
        "sugges_success": "Предложение отправлено! Спасибо!",
        "sugges_empty": "Предложек пока нет...",
        "sugges_approve": "Одобрить", "sugges_reject": "Отклонить",
        "suggested_by": "Предложено:", "sugges_own": "Вы не можете предложить пост самому себе.",
        "sugges_error_fill": "Заполните все поля!", "sugges_error_self": "Нельзя предложить самому себе",
        "rules_title": "Правила для предложки", "rules_placeholder": "Напишите правила для тех, кто предлагает посты...",
        "rules_edit_label": "Правила предложки (до 1000 символов)", "rules_alert_long": "Правила > 1000 символов!",
        "rules_none": "Правила не установлены",
        "attach_photo": "Фото", "attach_avatar": "Аватар", "remove_photo": "Убрать фото",
        "img_compressing": "Сжатие фото...", "img_ready": "Фото готово", "img_error": "Ошибка фото",
        "img_too_big": "Фото слишком большое", "view_photo": "Просмотр фото",
        "sugges_disabled": "Предложка отключена у этого пользователя",
        "sugges_enable_label": "Разрешить предложку", "sugges_enabled_label": "Предложка включена",
        "sugges_photo_enable_label": "Разрешить фото в предложке",
        "sugges_photo_disabled": "Фото в предложке отключены",
        "toast_new": "Новая запись добавлена!", "toast_link": "Ссылка скопирована!",
        "toast_copy_fail": "Не удалось скопировать", "toast_approved": "Одобрено!",
        "toast_rejected": "Отклонено!", "toast_approved_removed": "Одобрено и удалено!",
        "toast_rejected_removed": "Отклонено и удалено!", "toast_failed": "Ошибка:", "toast_csrf": "Ошибка безопасности (CSRF). Обновите страницу.",
        "err_empty": "Заполните обязательные поля!",
        "err_db": "Ошибка базы данных. Попробуйте позже.",
        "stats_link": "Статистика", "faq_link": "FAQ",
        "stats_title": "СТАТИСТИКА", "stats_users": "Пользователей", "stats_posts": "Записей",
        "stats_sugges": "Предложек", "stats_started": "Сервер запущен", "stats_last_update": "Последнее обновление",
        "stats_uptime": "Аптайм", "stats_contacts": "Связь с администрацией",
        "stats_contacts_desc": "По любым вопросам и предложениям:", "stats_back": "На главную",
        "post_too_long": "Пост слишком длинный (макс 5000 символов)",
        "err_nick_format": "Никнейм: 3-30 символов, только a-z, 0-9, _, -",
        "err_user_format": "Имя: 1-60 символов, только буквы/цифры/пробел/_-",
        "err_pass_short": "Пароль должен быть не короче 8 символов",
        "faq_title": "ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ",
        "faq_intro": "Здесь собраны ответы на частые вопросы о Solid. Если не нашли ответ — напишите администрации по контактам ниже.",
        "nav_feed": "Лента", "nav_create": "Создать", "nav_profile": "Профиль",
        "nav_sugges": "Предложки", "nav_settings": "Настройки",
        "feed_title": "ЛЕНТА",
        "create_page_title": "НОВЫЙ ПОСТ",
        "settings_title": "НАСТРОЙКИ",
        "settings_language": "Язык интерфейса",
        "settings_about": "О приложении",
        "settings_about_text": "Solid — простая социальная платформа для записей и предложек. Делитесь мыслями, собирайте предложки от читателей и оставайтесь на связи.",
        "settings_links": "Полезные ссылки",
        "settings_version": "Версия",
        "pwa_install": "Установить приложение",
        "settings_info": "Инфо",
        "settings_account": "Аккаунт",
        "settings_appearance": "Оформление",
        "back": "Назад",
        "settings_account_title": "Настройки аккаунта",
    },
    "en": {
        "reg": "Registration", "login": "Login", "username": "username", "nickname": "nickname",
        "password": "password", "re_pass": "re enter pass", "captcha": "I am not a robot",
        "register_btn": "Register!", "login_btn": "Login", "profile": "PROFILE",
        "total_posts": "Total records", "logout": "Logout", "edit_profile": "Edit Profile",
        "save_changes": "Save changes", "description": "Description",
        "desc_placeholder": "Tell about yourself...",
        "create_post_btn": "Create", "create_post_placeholder": "Write something...",
        "my_posts": "MY RECORDS", "user_posts": "USER RECORDS",
        "no_posts": "No records yet...", "pin": "Pin", "unpin": "Unpin", "delete": "Delete",
        "confirm_delete": "Delete record?", "created_by": "Created by:", "hosting": "Hosting:",
        "back_home": "Back to home", "user_not_found": "User not found.",
        "alert_captcha": "Confirm you are not a robot!", "alert_pass_mismatch": "Passwords do not match!",
        "alert_nick_taken": "Nickname is taken!", "alert_bad_login": "Invalid login!",
        "alert_desc_long": "Description > 300 chars!", "link_profile": "(Link)", "cancel": "Cancel",
        "username_label": "Name", "nickname_label": "Nickname", "bugreport_title": "Bug Report",
        "bugreport_name": "Your Name", "bugreport_desc": "Issue Description", "bugreport_send": "Send",
        "bugreport_my": "My Reports", "privacy_title": "Privacy Policy",
        "privacy_text": PRIVACY_EN,
        "privacy_agree": "I agree to the", "privacy_link": "Privacy Policy",
        "alert_privacy": "Accept the Privacy Policy!", "cabinet": "PERSONAL CABINET",
        "record_page": "Record", "copy_link": "Link",
        "ext_title": "Leaving site", "ext_desc": "You are leaving our site and going to:",
        "ext_continue": "Continue", "ext_loading": "Loading preview...",
        "suggestions_title": "SUGGESTIONS", "suggestions_btn": "Suggest a post",
        "sugges_title": "Suggest a post for", "sugges_name": "Your Name",
        "sugges_content": "Post text", "sugges_send": "Send",
        "sugges_success": "Suggestion sent! Thank you!",
        "sugges_empty": "No suggestions yet...",
        "sugges_approve": "Approve", "sugges_reject": "Reject",
        "suggested_by": "Suggested by:", "sugges_own": "You can't suggest to yourself.",
        "sugges_error_fill": "Fill all fields!", "sugges_error_self": "Can't suggest to yourself",
        "rules_title": "Suggestion rules", "rules_placeholder": "Write rules for people who suggest posts...",
        "rules_edit_label": "Suggestion rules (max 1000 chars)", "rules_alert_long": "Rules > 1000 chars!",
        "rules_none": "No rules set",
        "attach_photo": "Photo", "attach_avatar": "Avatar", "remove_photo": "Remove photo",
        "img_compressing": "Compressing photo...", "img_ready": "Photo ready", "img_error": "Photo error",
        "img_too_big": "Photo is too big", "view_photo": "View photo",
        "sugges_disabled": "Suggestions are disabled for this user",
        "sugges_enable_label": "Enable suggestions", "sugges_enabled_label": "Suggestions enabled",
        "sugges_photo_enable_label": "Allow photos in suggestions",
        "sugges_photo_disabled": "Photos in suggestions are disabled",
        "toast_new": "New record added!", "toast_link": "Link copied!",
        "toast_copy_fail": "Failed to copy", "toast_approved": "Approved!",
        "toast_rejected": "Rejected!", "toast_approved_removed": "Approved & removed!",
        "toast_rejected_removed": "Rejected & removed!", "toast_failed": "Error:", "toast_csrf": "Security error (CSRF). Refresh the page.",
        "err_empty": "Fill required fields!",
        "err_db": "Database error. Try again later.",
        "stats_link": "Stats", "faq_link": "FAQ",
        "stats_title": "STATISTICS", "stats_users": "Users", "stats_posts": "Records",
        "stats_sugges": "Suggestions", "stats_started": "Server started", "stats_last_update": "Last update",
        "stats_uptime": "Uptime", "stats_contacts": "Contact administration",
        "stats_contacts_desc": "For questions and suggestions:", "stats_back": "Back to home",
        "post_too_long": "Post too long (max 5000 chars)",
        "err_nick_format": "Nickname: 3-30 chars, only a-z, 0-9, _, -",
        "err_user_format": "Name: 1-60 chars, letters/digits/space/_-",
        "err_pass_short": "Password must be at least 8 chars",
        "faq_title": "FREQUENTLY ASKED QUESTIONS",
        "faq_intro": "Here are answers to frequently asked questions about Solid. If you couldn't find an answer — contact the administration below.",
        "nav_feed": "Feed", "nav_create": "Create", "nav_profile": "Profile",
        "nav_sugges": "Suggestions", "nav_settings": "Settings",
        "feed_title": "FEED",
        "create_page_title": "NEW POST",
        "settings_title": "SETTINGS",
        "settings_language": "Interface language",
        "settings_about": "About",
        "settings_about_text": "Solid is a simple social platform for records and suggestions. Share your thoughts, collect suggestions from readers and stay in touch.",
        "settings_links": "Useful links",
        "settings_version": "Version",
        "pwa_install": "Install App",
        "settings_info": "Info",
        "settings_account": "Account",
        "settings_appearance": "Appearance",
        "back": "Back",
        "settings_account_title": "Account Settings",
    }
}

def t(k, l="ru"): return LOCALES.get(l, LOCALES["ru"]).get(k, k)

def format_date(iso):
    if not iso: return ""
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except: return iso[:10]

SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""
SVG_UPLOAD = """<svg xmlns='http://www.w3.org/2000/svg' width='36' height='36' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'></path><polyline points='17 8 12 3 7 8'></polyline><line x1='12' y1='3' x2='12' y2='15'></line></svg>"""
SVG_CAMERA = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z'></path><circle cx='12' cy='13' r='4'></circle></svg>"""
SVG_BACK = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='19' y1='12' x2='5' y2='12'></line><polyline points='12 19 5 12 12 5'></polyline></svg>"""

# Sidebar & Bottom Nav Icons
SVG_NAV_HOME = """<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/><polyline points='9 22 9 12 15 12 15 22'/></svg>"""
SVG_NAV_CREATE = """<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='16'/><line x1='8' y1='12' x2='16' y2='12'/></svg>"""
SVG_NAV_PROFILE = """<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'/><circle cx='12' cy='7' r='4'/></svg>"""
SVG_NAV_SETTINGS = """<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'/><path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'/></svg>"""
SVG_NAV_SUGGES = """<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='22 12 16 12 14 15 10 15 8 12 2 12'/><path d='M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'/></svg>"""
SVG_INFO = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><line x1='12' y1='16' x2='12' y2='12'></line><line x1='12' y1='8' x2='12.01' y2='8'></line></svg>"""
SVG_USER = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'></path><circle cx='12' cy='7' r='4'></circle></svg>"""
SVG_PALETTE = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='13.5' cy='6.5' r='.5' fill='currentColor'></circle><circle cx='17.5' cy='10.5' r='.5' fill='currentColor'></circle><circle cx='8.5' cy='7.5' r='.5' fill='currentColor'></circle><circle cx='6.5' cy='12.5' r='.5' fill='currentColor'></circle><path d='M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z'></path></svg>"""

def bottom_nav_html(lang):
    current = _current_path.get() or "/"
    create_active = "active" if current == "/cabinet/new" else ""
    sug_active = "active" if current == "/cabinet/suggestions" else ""
    set_active = "active" if current.startswith("/settings") else ""
    profile_active = ""
    if current.startswith("/cabinet") and current not in ("/cabinet/new", "/cabinet/suggestions"):
        profile_active = "active"
    return f"""
    <nav class="bottom-nav" aria-label="Навигация">
        <a href="/cabinet/new" class="bottom-nav-item {create_active}">{SVG_NAV_CREATE}</a>
        <a href="/cabinet/profile" class="bottom-nav-item {profile_active}">{SVG_NAV_PROFILE}</a>
        <a href="/cabinet/suggestions" class="bottom-nav-item {sug_active}">{SVG_NAV_SUGGES}</a>
        <a href="/settings" class="bottom-nav-item {set_active}">{SVG_NAV_SETTINGS}</a>
    </nav>
    <script>document.body.classList.add('has-bottom-nav');</script>
    """

def pc_sidebar_html(lang, nickname, avatar, username):
    current = _current_path.get() or "/"
    home_active = "active" if current in ("/cabinet", "/cabinet/profile") else ""
    sug_active = "active" if current == "/cabinet/suggestions" else ""
    set_active = "active" if current.startswith("/settings") else ""
    
    avatar_html = f'<img src="{avatar}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">' if avatar else f'<div style="width:40px;height:40px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:bold;">{username[0].upper()}</div>'
    
    return f"""
    <aside class="pc-sidebar">
        <div class="sidebar-logo">Solid</div>
        <a href="/cabinet/profile" class="sidebar-item {home_active}">
            {SVG_NAV_HOME} <span>ЛК</span>
        </a>
        <a href="/cabinet/suggestions" class="sidebar-item {sug_active}">
            {SVG_NAV_SUGGES} <span>Предложка</span>
        </a>
        <a href="javascript:void(0)" onclick="openCreateModal()" class="sidebar-item">
            {SVG_NAV_CREATE} <span>Создать пост</span>
        </a>
        <a href="/settings" class="sidebar-item {set_active}">
            {SVG_NAV_SETTINGS} <span>Настройки</span>
        </a>
        <div class="sidebar-profile">
            <a href="/cabinet/profile" style="display:flex; align-items:center; gap:10px; text-decoration:none; color:#fff;">
                {avatar_html}
                <div>
                    <div style="font-weight:bold; font-size:15px;">{username}</div>
                    <div style="color:#888; font-size:13px;">@{nickname}</div>
                </div>
            </a>
            <button onclick="confirmLogout()" style="background:transparent; border:none; color:#e63946; cursor:pointer; width:auto; padding:5px; margin-left:auto;" title="Выйти">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
            </button>
        </div>
    </aside>
    """

_CSS_CACHE = None
def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        _CSS_CACHE = """
        <style>
            @import url('https://fonts.cdnfonts.com/css/herokid');
            @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@300;400;600;700&display=swap');

            @font-face {
                font-family: 'RuFont';
                src: url('/static/ru_font.ttf') format('truetype');
                font-weight: 300 700;
                font-display: swap;
            }

            * { box-sizing: border-box; }
            html, body { margin: 0; padding: 0; background: #000; color: #e7e9ea; font-family: 'Source Sans 3', 'RuFont', Arial, sans-serif; }
            
            h1, h2, h3, h4, h5, h6 { font-family: 'Herokid', 'Impact', sans-serif; color: #e7e9ea !important; margin: 0; letter-spacing: 0.5px; }

            /* Layout */
            .pc-layout { display: none; }
            .mobile-layout { display: block; min-height: 100vh; min-height: 100dvh; padding-bottom: 70px; }

            /* Auth Page */
            .auth-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
            .auth-box { background: #16181c; border: 1px solid #2f3336; padding: 40px; border-radius: 16px; width: 100%; max-width: 400px; }
            .auth-title { font-size: 32px; text-align: center; margin-bottom: 24px; }
            .input-group { position: relative; margin-bottom: 16px; }
            input[type="text"], input[type="password"], textarea, select { background-color: #202327; border: 1px solid #333; color: #e7e9ea; border-radius: 8px; padding: 16px; font-size: 16px; width: 100%; font-family: 'Source Sans 3', sans-serif; transition: all 0.2s; }
            input[type="text"]:focus, input[type="password"]:focus, textarea:focus { outline: none; border-color: #1d9bf0; background-color: #202327; color: #fff; }
            .eye-btn { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: transparent; border: none; cursor: pointer; padding: 5px; display: flex; align-items: center; justify-content: center; opacity: 0.6; width: auto; }
            .eye-btn:hover { opacity: 1; }
            
            button, .btn { background-color: #e7e9ea; color: #000; border: none; border-radius: 9999px; padding: 14px; font-size: 16px; font-weight: 700; font-family: 'Source Sans 3', sans-serif; cursor: pointer; width: 100%; transition: background 0.2s; text-align: center; display: block; text-decoration: none; }
            button:hover, .btn:hover { background-color: #d7dbdc; }
            .btn-blue { background-color: #1d9bf0; color: #fff; }
            .btn-blue:hover { background-color: #1a8cd8; }
            .btn-danger { background-color: #e63946; color: #fff; }
            .btn-danger:hover { background-color: #d62828; }

            .captcha-container { display: flex; align-items: center; gap: 10px; background: #202327; padding: 12px; border-radius: 8px; border: 1px solid #333; margin-bottom: 12px; cursor: pointer; font-size: 15px; }
            .captcha-container input { width: 20px; height: 20px; cursor: pointer; }
            
            .error-msg { color: #e63946; font-size: 14px; text-align: center; margin-bottom: 15px; font-weight: 600; }
            .privacy-link { color: #1d9bf0; text-decoration: none; }
            .privacy-link:hover { text-decoration: underline; }

            /* Content Pages */
            .content-wrapper { max-width: 600px; margin: 0 auto; border-left: 1px solid #2f3336; border-right: 1px solid #2f3336; min-height: 100vh; }
            .page-header { padding: 16px 20px; border-bottom: 1px solid #2f3336; display: flex; align-items: center; gap: 15px; position: sticky; top: 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(12px); z-index: 100; }
            .page-header h2 { font-size: 20px; }
            .back-btn { color: #e7e9ea; display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; transition: background 0.2s; text-decoration: none; }
            .back-btn:hover { background: rgba(255,255,255,0.1); text-decoration: none; }

            /* Post Card */
            .post-card { padding: 16px 20px; border-bottom: 1px solid #2f3336; display: flex; gap: 12px; transition: background 0.2s; cursor: pointer; }
            .post-card:hover { background: rgba(255,255,255,0.03); }
            .post-avatar { width: 48px; height: 48px; border-radius: 50%; object-fit: cover; flex-shrink: 0; background: #333; }
            .post-body { flex: 1; min-width: 0; }
            .post-header { display: flex; align-items: center; gap: 5px; margin-bottom: 4px; flex-wrap: wrap; }
            .post-author { color: #e7e9ea; font-weight: 700; font-size: 15px; text-decoration: none; }
            .post-author:hover { text-decoration: underline; }
            .post-nickname { color: #71767b; font-size: 15px; }
            .post-dot { color: #71767b; }
            .post-date { color: #71767b; font-size: 15px; }
            .post-text { font-size: 15px; line-height: 1.5; color: #e7e9ea; white-space: pre-wrap; word-break: break-word; margin-bottom: 10px; }
            .post-text a { color: #1d9bf0; text-decoration: none; }
            .post-text a:hover { text-decoration: underline; }
            .post-img { width: 100%; max-height: 500px; object-fit: cover; border-radius: 16px; border: 1px solid #2f3336; margin-top: 10px; margin-bottom: 10px; cursor: zoom-in; }
            .post-actions { display: flex; justify-content: space-between; align-items: center; max-width: 400px; margin-top: 10px; }
            .action-icon { color: #71767b; display: flex; align-items: center; gap: 5px; font-size: 13px; background: none; border: none; padding: 8px; border-radius: 50%; cursor: pointer; transition: all 0.2s; width: auto; }
            .action-icon:hover { color: #1d9bf0; background: rgba(29,155,240,0.1); }
            .action-icon.del:hover { color: #f4212e; background: rgba(244,33,46,0.1); }

            /* Create Post Modal */
            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(91,112,131,0.4); z-index: 10000; justify-content: center; align-items: center; padding: 20px; backdrop-filter: blur(4px); }
            .modal-overlay.show { display: flex; }
            .modal-box { background: #000; border: 1px solid #2f3336; border-radius: 16px; width: 100%; max-width: 600px; padding: 0; overflow: hidden; display: flex; flex-direction: column; }
            .modal-header { padding: 12px 16px; border-bottom: 1px solid #2f3336; display: flex; justify-content: space-between; align-items: center; }
            .modal-header button { background: #1d9bf0; color: #fff; border-radius: 9999px; padding: 8px 20px; font-size: 15px; width: auto; }
            .modal-header button:disabled { opacity: 0.5; cursor: not-allowed; }
            .modal-header button:hover { background: #1a8cd8; }
            .modal-body { padding: 16px; display: flex; gap: 12px; }
            .modal-textarea { background: transparent; border: none; color: #e7e9ea; font-size: 20px; resize: none; height: 150px; padding: 0; width: 100%; }
            .modal-textarea:focus { outline: none; border: none; background: transparent; }
            .modal-footer { padding: 12px 16px; border-top: 1px solid #2f3336; display: flex; justify-content: flex-start; }
            .modal-close { background: transparent; color: #e7e9ea; border: none; cursor: pointer; padding: 8px; border-radius: 50%; width: auto; }
            .modal-close:hover { background: rgba(255,255,255,0.1); }

            /* Settings Menu */
            .settings-menu-list { display: flex; flex-direction: column; }
            .settings-menu-item { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid #2f3336; text-decoration: none; color: #e7e9ea; transition: background 0.2s; }
            .settings-menu-item:hover { background: rgba(255,255,255,0.03); }
            .settings-menu-item-left { display: flex; align-items: center; gap: 15px; font-weight: 700; font-size: 16px; }
            .settings-menu-item svg { color: #e7e9ea; }
            .settings-menu-item::after { content: '›'; color: #71767b; font-size: 24px; font-weight: normal; }

            /* Image Viewer */
            #img-viewer { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.95); backdrop-filter: blur(8px); z-index: 20000; display: none; justify-content: center; align-items: center; }
            #img-viewer.show { display: flex; animation: fadeIn 0.2s; }
            #img-viewer-img { max-width: 90vw; max-height: 90vh; object-fit: contain; border-radius: 8px; }
            .img-viewer-close { position: absolute; top: 20px; right: 20px; background: rgba(0,0,0,0.6); color: #fff; border: 2px solid #fff; width: 44px; height: 44px; border-radius: 50%; font-size: 24px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
            @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

            /* Toast */
            #toast { position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: #1d9bf0; color: #fff; padding: 12px 24px; border-radius: 8px; opacity: 0; transition: opacity 0.3s; z-index: 9999; font-weight: 600; pointer-events: none; font-size: 15px; }
            #toast.show { opacity: 1; }

            /* Progress bar */
            .progress-bar { position: fixed; top: 0; left: 0; height: 3px; width: 0; background: #1d9bf0; z-index: 99999; opacity: 0; pointer-events: none; }
            .progress-bar.show { width: 80%; opacity: 1; transition: width 0.4s ease-out, opacity 0.2s; }

            .bottom-nav { display: flex; position: fixed; bottom: 0; left: 0; right: 0; background: #000; border-top: 1px solid #2f3336; z-index: 5000; height: 60px; padding-bottom: env(safe-area-inset-bottom); }
            .bottom-nav-item { flex: 1; display: flex; align-items: center; justify-content: center; color: #71767b; transition: color 0.15s; position: relative; text-decoration: none; }
            .bottom-nav-item svg { width: 26px; height: 26px; }
            .bottom-nav-item.active { color: #1d9bf0; pointer-events: none; }
            .bottom-nav-item.active::before { content: ''; position: absolute; top: 0; width: 30px; height: 3px; background: #1d9bf0; border-radius: 0 0 3px 3px; }

            /* Media Queries */
            @media (min-width: 769px) {
                .mobile-layout { display: none; }
                .pc-layout { display: flex; justify-content: center; max-width: 1200px; margin: 0 auto; min-height: 100vh; }
                
                .pc-sidebar { width: 275px; padding: 20px; display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; border-right: 1px solid #2f3336; }
                .sidebar-logo { font-family: 'Herokid', 'Impact', sans-serif; font-size: 32px; color: #e7e9ea; margin-bottom: 30px; padding-left: 10px; }
                .sidebar-item { display: flex; align-items: center; gap: 20px; padding: 12px 15px; color: #e7e9ea; text-decoration: none; font-size: 20px; font-weight: 600; border-radius: 9999px; margin-bottom: 5px; transition: background 0.2s; cursor: pointer; background: transparent; border: none; width: 100%; text-align: left; }
                .sidebar-item:hover { background: rgba(255,255,255,0.1); }
                .sidebar-item.active { font-weight: 700; }
                .sidebar-item svg { width: 26px; height: 26px; }
                .sidebar-profile { margin-top: auto; padding: 12px; display: flex; align-items: center; background: #16181c; border-radius: 9999px; border: 1px solid #2f3336; }
                
                .pc-main { flex: 1; max-width: 600px; border-right: 1px solid #2f3336; min-height: 100vh; }
                .pc-right-panel { width: 350px; padding: 20px; display: none; }
                @media (min-width: 1024px) { .pc-right-panel { display: block; } }
            }
        </style>
        """
    return _CSS_CACHE

def get_js(lang, token, current_user=""):
    js = """
    <script>
        const T = "__TOKEN__";
        const ME = "__ME__";
        const L = {
            d: "__DEL__", p: "__PIN__", u: "__UNPIN__", c: "__CONFIRM__",
            n: "__NOPOSTS__", cl: "__COPYLINK__", sf: "__SUGG_FILL__", ss: "__SUGG_SELF__", su: "__SUGG_SUCCESS__",
            ic: "__IMG_COMPRESSING__", ir: "__IMG_READY__", ie: "__IMG_ERROR__", ib: "__IMG_BIG__",
            tn: "__TOAST_NEW__", tl: "__TOAST_LINK__", tc: "__TOAST_COPY_FAIL__",
            tar: "__TOAST_APPROVED_REMOVED__", trr: "__TOAST_REJECTED_REMOVED__", tf: "__TOAST_FAILED__",
            ptl: "__POST_TOO_LONG__"
        };
        function escHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
        function safeUrl(u) { if (!u) return ''; u = String(u); if (/^https?:\\/\\//i.test(u) || /^data:image\\//i.test(u)) return u; return ''; }
        function formatLocalDates() {
            const opts = { day: '2-digit', month: 'short', year: 'numeric' };
            document.querySelectorAll('[data-iso]').forEach(el => {
                const iso = el.getAttribute('data-iso');
                if (!iso) return;
                try { const d = new Date(iso); if (isNaN(d.getTime())) return; el.textContent = d.toLocaleString(undefined, opts); } catch(e) {}
            });
        }
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', formatLocalDates);
        else formatLocalDates();

        function viewImage(src) {
            if (!src) return;
            const img = document.getElementById('img-viewer-img');
            img.src = src;
            document.getElementById('img-viewer').classList.add('show');
            document.body.style.overflow = 'hidden';
        }
        function closeImgViewer() {
            document.getElementById('img-viewer').classList.remove('show');
            document.body.style.overflow = '';
        }
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeImgViewer(); });

        window.skelLoad = function(el) {
            el.classList.add('loaded');
            if (el.parentElement) el.parentElement.classList.add('loaded');
        };

        (function() {
            const bar = document.getElementById('progress-bar');
            if (!bar) return;
            document.addEventListener('click', function(e) {
                const link = e.target.closest && e.target.closest('a[href]');
                if (!link) return;
                const href = link.getAttribute('href');
                if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) return;
                if (link.target === '_blank' || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
                try {
                    const u = new URL(href, window.location.origin);
                    if (u.origin !== window.location.origin) return;
                } catch { return; }
                bar.classList.add('show');
            });
            window.addEventListener('pagehide', () => bar.classList.remove('show'));
        })();

        function openCreateModal() {
            const m = document.getElementById('create-modal');
            if (m) { m.classList.add('show'); document.getElementById('modal-textarea').focus(); }
        }
        function closeCreateModal() {
            const m = document.getElementById('create-modal');
            if (m) m.classList.remove('show');
        }

        async function compressImage(file, maxWidth=1000, quality=0.75) {
            return new Promise((resolve, reject) => {
                if (!file.type.startsWith('image/')) return reject('Not an image');
                const reader = new FileReader();
                reader.onload = (e) => {
                    const img = new Image();
                    img.onload = () => {
                        try {
                            const c = document.createElement('canvas');
                            let w = img.width, h = img.height;
                            if (w > maxWidth) { h = Math.round(h*maxWidth/w); w = maxWidth; }
                            c.width = w; c.height = h;
                            const ctx = c.getContext('2d');
                            ctx.fillStyle = '#fff'; ctx.fillRect(0,0,w,h);
                            ctx.drawImage(img, 0, 0, w, h);
                            let b64 = c.toDataURL('image/jpeg', quality);
                            let q = quality;
                            while (b64.length > 800000 && q > 0.3) { q -= 0.1; b64 = c.toDataURL('image/jpeg', q); }
                            if (b64.length > 850000) return reject('Image too big');
                            resolve(b64);
                        } catch (err) { reject(err); }
                    };
                    img.onerror = () => reject('Load error');
                    img.src = e.target.result;
                };
                reader.onerror = () => reject('Read error');
                reader.readAsDataURL(file);
            });
        }
        window.postImageCache = ""; window.suggImageCache = "";
        async function handlePostImage(input) {
            const file = input.files[0]; 
            const container = document.getElementById('post-img-container'); 
            const preview = document.getElementById('post-img-preview'); 
            const btn = document.getElementById('modal-submit-btn') || document.getElementById('create-post-btn');
            if (!file) { window.postImageCache = ""; if(container) container.style.display='none'; return; }
            showToast(L.ic); if(btn) btn.disabled = true;
            try { 
                const b64 = await compressImage(file, 1000, 0.75); 
                window.postImageCache = b64; 
                if (preview) { 
                    preview.src = b64; 
                    if (container) container.style.display = 'block'; 
                    preview.onclick = () => viewImage(b64); 
                } 
                showToast(L.ir); 
            }
            catch (e) { 
                window.postImageCache = ""; 
                showToast(e === 'Image too big' ? L.ib : L.ie); 
                input.value = ''; 
                if(container) container.style.display='none'; 
            }
            finally { if(btn) btn.disabled = false; }
        }
        
        function removePostImage() {
            window.postImageCache = "";
            const input = document.getElementById('post-file-input');
            if(input) input.value = "";
            const container = document.getElementById('post-img-container');
            if(container) container.style.display = 'none';
            const preview = document.getElementById('post-img-preview');
            if(preview) preview.src = "";
        }

        async function handleSuggImage(input) {
            const file = input.files[0]; const preview = document.getElementById('sugg-img-preview'); const btn = document.getElementById('sugg-submit-btn');
            if (!file) { window.suggImageCache = ""; if(preview) preview.style.display='none'; return; }
            showToast(L.ic); if(btn) btn.disabled = true;
            try { const b64 = await compressImage(file, 1000, 0.75); window.suggImageCache = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); } showToast(L.ir); }
            catch (e) { window.suggImageCache = ""; showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; if(preview) preview.style.display='none'; }
            finally { if(btn) btn.disabled = false; }
        }
        async function handleAvatarChange(input) {
            const file = input.files[0]; const hidden = document.getElementById('avatar-data'); const preview = document.getElementById('avatar-preview');
            if (!file) { hidden.value = ""; return; }
            showToast(L.ic);
            try { const b64 = await compressImage(file, 300, 0.8); hidden.value = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; preview.parentElement.classList.add('loaded'); } showToast(L.ir); }
            catch (e) { showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; }
        }
        if ('serviceWorker' in navigator) { window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW failed', err)); }); }
        
        let ws;
        function connectWS() {
            const proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            ws = new WebSocket(proto + window.location.host + '/ws');
            ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.type === 'delete_record') { const p = document.getElementById('post-' + d.post_id); if (p) p.remove(); } else if (d.type === 'new_record') { showToast(L.tn); } };
            ws.onclose = () => setTimeout(connectWS, 3000);
        }
        connectWS();
        function copyLink(btn) { const user = btn.dataset.user || ''; const rid = btn.dataset.rid || ''; if (!user) return; const url = window.location.origin + '/' + encodeURIComponent(user) + '/' + encodeURIComponent(rid); navigator.clipboard.writeText(url).then(() => showToast(L.tl)).catch(() => showToast(L.tc)); }
        function showToast(msg) { const t = document.getElementById('toast'); if (!t) return; t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3000); }
        
        function showConfirm(msg, cb) { 
            const m = document.getElementById('modal-overlay'); 
            document.getElementById('modal-text').textContent = msg; 
            m.classList.add('show'); 
            const cBtn = document.getElementById('modal-confirm'); 
            const xBtn = document.getElementById('modal-cancel'); 
            const nC = cBtn.cloneNode(true); 
            const nX = xBtn.cloneNode(true); 
            cBtn.parentNode.replaceChild(nC, cBtn); 
            xBtn.parentNode.replaceChild(nX, xBtn); 
            nC.onclick = () => { m.classList.remove('show'); cb(true); }; 
            nX.onclick = () => { m.classList.remove('show'); cb(false); }; 
        }
        
        function confirmLogout() {
            showConfirm("Вы уверены, что хотите выйти?", (yes) => {
                if (yes) window.location.href = '/logout';
            });
        }

        let pendingUrl = "";
        async function showLinkWarning(e, el) {
            e.preventDefault(); pendingUrl = el.getAttribute('data-url'); if (!pendingUrl) return;
            document.getElementById('link-modal-confirm').href = pendingUrl;
            const ogBox = document.getElementById('og-preview');
            ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#666;">' + escHtml('__EXT_LOADING__') + '</p>';
            document.getElementById('link-modal').classList.add('show');
            try {
                const res = await fetch('/api/og?url=' + encodeURIComponent(pendingUrl));
                const data = await res.json();
                if (data.title || data.description || data.image) {
                    let html = '';
                    const imgUrl = safeUrl(data.image);
                    if (imgUrl) html += '<img src="' + escHtml(imgUrl) + '" class="og-img">';
                    if (data.title) html += '<h4 class="og-title">' + escHtml(data.title) + '</h4>';
                    if (data.description) html += '<p class="og-desc">' + escHtml(data.description) + '</p>';
                    ogBox.innerHTML = html;
                } else { ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#666;">No preview</p>'; }
            } catch (err) { ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#666;">Failed to load</p>'; }
        }
        function closeLinkModal() { document.getElementById('link-modal').classList.remove('show'); }
        async function rpc(method, params) { const res = await fetch('/rpc', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': T }, body: JSON.stringify({ method, params }) }); const data = await res.json(); if (!res.ok) throw new Error(data.detail || data.error || 'RPC Error'); return data; }
        function tp(i, b) { const x = document.getElementById(i); if (x.type === 'password') { x.type = 'text'; b.innerHTML = `__SVG_EYE_OFF__`; } else { x.type = 'password'; b.innerHTML = `__SVG_EYE__`; } }
        function uc(e) { document.getElementById('char-count').innerText = e.value.length + ' / 300'; }
        function ucRules(e) { document.getElementById('rules-count').innerText = e.value.length + ' / 1000'; }

        async function submitModalPost(e) {
            e.preventDefault();
            const f = e.target, c = f.querySelector('textarea').value.trim();
            if (!c) return;
            if (c.length > 5000) { showToast(L.ptl); return; }
            const img = window.postImageCache || "";
            const btn = document.getElementById('modal-submit-btn');
            btn.disabled = true; btn.innerHTML = '...';
            try {
                await rpc('create_record', { content: c, image_data: img });
                showToast(L.tn);
                closeCreateModal();
                setTimeout(() => { window.location.reload(); }, 500);
            } catch (x) {
                showToast(L.tf + ' ' + x.message);
                btn.disabled = false; btn.innerHTML = 'Опубликовать';
            }
        }

        async function hcNew(e) {
            e.preventDefault();
            const f = e.target, c = f.querySelector('textarea').value.trim();
            if (!c) return;
            if (c.length > 5000) { showToast(L.ptl); return; }
            const img = window.postImageCache || "";
            const btn = f.querySelector('button[type="submit"]');
            const originalText = btn.innerHTML;
            btn.disabled = true; btn.innerHTML = '<span class="btn-spinner"></span>';
            try {
                await rpc('create_record', { content: c, image_data: img });
                showToast(L.tn);
                setTimeout(() => { window.location.href = '/cabinet/profile'; }, 500);
            } catch (x) {
                showToast(L.tf + ' ' + x.message);
                btn.disabled = false; btn.innerHTML = originalText;
            }
        }

        function hd(i) { showConfirm(L.c, async (yes) => { if (!yes) return; const w = document.getElementById('post-' + i); w.style.opacity = '0'; setTimeout(() => w.style.display = 'none', 300); try { await rpc('delete_record', { post_id: i }); w.remove(); } catch (x) { w.style.opacity = '1'; w.style.display = 'block'; showToast(L.tf + ' ' + x.message); } }); }
        async function hp(i, b) {
            const w = document.getElementById('post-' + i), p = w.querySelector('.post-item'), s = p.classList.contains('pinned');
            if (s) { p.classList.remove('pinned'); b.textContent = L.p; }
            else {
                document.querySelectorAll('.post-item.pinned').forEach(el => { el.classList.remove('pinned'); const ww = el.closest('.post-wrapper'); if (ww) { const btn = ww.querySelector('.pin-btn'); if (btn) btn.textContent = L.p; } });
                p.classList.add('pinned'); b.textContent = L.u;
                const a = w.parentNode; a.insertBefore(w, a.children[1]);
            }
            try { await rpc('pin_record', { post_id: i }); }
            catch (x) { if (s) { p.classList.add('pinned'); b.textContent = L.u; } else { p.classList.remove('pinned'); b.textContent = L.p; } showToast(L.tf + ' ' + x.message); }
        }
        async function submitSuggestion(event) {
            event.preventDefault(); const f = event.target; const target = f.dataset.nickname;
            const name = f.querySelector('input[name="sugg_name"]').value.trim();
            const content = f.querySelector('textarea[name="content"]').value.trim();
            if (!name || !content) { showToast(L.sf); return; }
            if (ME && target === ME) { showToast(L.ss); return; }
            const btn = f.querySelector('button[type="submit"]'); const img = window.suggImageCache || ""; btn.disabled = true;
            try { await rpc('submit_suggestion', { target_nickname: target, sugg_name: name, content: content, image_data: img }); showToast(L.su); f.reset(); window.suggImageCache = ""; const preview = document.getElementById('sugg-img-preview'); if (preview) preview.style.display = 'none'; }
            catch (x) { showToast(L.tf + ' ' + x.message); }
            finally { btn.disabled = false; }
        }
        async function approveSugg(suggId) { try { await rpc('approve_suggestion', { suggestion_id: suggId }); const card = document.getElementById('sugg-' + suggId); if (card) card.remove(); showToast(L.tar); } catch (x) { showToast(L.tf + ' ' + x.message); } }
        async function rejectSugg(suggId) { try { await rpc('reject_suggestion', { suggestion_id: suggId }); const card = document.getElementById('sugg-' + suggId); if (card) card.remove(); showToast(L.trr); } catch (x) { showToast(L.tf + ' ' + x.message); } }
    </script>
    """
    reps = [("__TOKEN__", token),("__ME__", current_user),("__DEL__", t('delete',lang)),("__PIN__", t('pin',lang)),("__UNPIN__", t('unpin',lang)),("__CONFIRM__", t('confirm_delete',lang)),("__NOPOSTS__", t('no_posts',lang)),("__COPYLINK__", t('copy_link',lang)),("__EXT_LOADING__", t('ext_loading',lang)),("__SUGG_FILL__", t('sugges_error_fill',lang)),("__SUGG_SELF__", t('sugges_error_self',lang)),("__SUGG_SUCCESS__", t('sugges_success',lang)),("__IMG_COMPRESSING__", t('img_compressing',lang)),("__IMG_READY__", t('img_ready',lang)),("__IMG_ERROR__", t('img_error',lang)),("__IMG_BIG__", t('img_too_big',lang)),("__TOAST_NEW__", t('toast_new',lang)),("__TOAST_LINK__", t('toast_link',lang)),("__TOAST_COPY_FAIL__", t('toast_copy_fail',lang)),("__TOAST_APPROVED_REMOVED__", t('toast_approved_removed',lang)),("__TOAST_REJECTED_REMOVED__", t('toast_rejected_removed',lang)),("__TOAST_FAILED__", t('toast_failed',lang)),("__POST_TOO_LONG__", t('post_too_long',lang)),("__SVG_EYE_OFF__", SVG_EYE_OFF),("__SVG_EYE__", SVG_EYE)]
    for k, v in reps: js = js.replace(k, v)
    return js

def get_overlay(lang):
    s = """
    <div id="progress-bar" class="progress-bar"></div>
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay"><div class="modal-box" style="max-width:400px; padding:30px; text-align:center;"><p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p><div class="modal-actions" style="display:flex; gap:10px;"><button id="modal-cancel" class="btn" style="background:#333;color:#fff;">__CANCEL__</button><button id="modal-confirm" class="btn btn-danger">OK</button></div></div></div>
    <div id="link-modal" class="modal-overlay"><div class="modal-box" style="text-align: left; padding:20px;"><h3 style="margin-top:0;">__EXT_TITLE__</h3><p style="font-size:14px; color:#888; margin-bottom:10px;">__EXT_DESC__</p><div id="og-preview" style="background:#16181c; padding:15px; border-radius:12px;"><p style="margin:0; font-size:14px; color:#888;">__EXT_LOADING__</p></div><div class="modal-actions" style="display:flex; gap:10px; margin-top:20px;"><button onclick="closeLinkModal()" class="btn" style="background:#333;color:#fff;">__CANCEL__</button><a id="link-modal-confirm" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-blue" style="text-decoration: none; display: flex; align-items: center; justify-content: center;">__EXT_CONTINUE__</a></div></div></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()">
        <button class="img-viewer-close" onclick="event.stopPropagation();closeImgViewer()" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
        <img id="img-viewer-img" src="" alt="">
    </div>
    """
    for k, v in [("__CANCEL__", t('cancel',lang)),("__EXT_TITLE__", t('ext_title',lang)),("__EXT_DESC__", t('ext_desc',lang)),("__EXT_LOADING__", t('ext_loading',lang)),("__EXT_CONTINUE__", t('ext_continue',lang))]:
        s = s.replace(k, v)
    return s

def auth_html(lang, error_msg="", token=""):
    eb = f"<div class='error-msg'>{esc(error_msg)}</div>" if error_msg else ""
    og_title = "Solid — Вход / Регистрация" if lang == "ru" else "Solid — Login / Registration"
    og_desc = "Solid — простая социальная платформа с записями и предложкой" if lang == "ru" else "Solid — simple social platform with records and suggestions"
    og = og_tags(og_title, og_desc, "/", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__LOGIN__ / __REG__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="auth-container">
        <div class="auth-box">
            <div class="auth-title">__REG__</div>
            __ERROR__
            <form action="/register" method="post">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <div class="input-group"><input type="text" name="username" placeholder="__USERNAME__" required maxlength="60"></div>
                <div class="input-group"><input type="text" name="nickname" placeholder="__NICKNAME__" required maxlength="30" pattern="[a-zA-Z0-9_\\-]{3,30}" title="3-30: a-z 0-9 _ -"></div>
                <div class="input-group"><input type="password" name="password" id="rp" placeholder="__PASSWORD__" required minlength="8"><button type="button" class="eye-btn" onclick="tp('rp',this)">__SVG_EYE__</button></div>
                <div class="input-group"><input type="password" name="re_pass" id="rr" placeholder="__REPASS__" required minlength="8"><button type="button" class="eye-btn" onclick="tp('rr',this)">__SVG_EYE__</button></div>
                <label class="captcha-container"><input type="checkbox" name="captcha" required> __CAPTCHA__</label>
                <label class="captcha-container"><input type="checkbox" name="privacy" required><span>__PRIVACY_AGREE__ <a href="/privacy" target="_blank" rel="noopener noreferrer" class="privacy-link">__PRIVACY_LINK__</a></span></label>
                <button type="submit" class="btn-blue" style="margin-top:10px;">__REG_BTN__</button>
            </form>
            
            <hr style="border:0; border-top:1px solid #333; margin:30px 0;">
            
            <div class="auth-title" style="font-size:26px;">__LOGIN__</div>
            <form action="/login" method="post">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <div class="input-group"><input type="text" name="nickname" placeholder="__NICKNAME__" required></div>
                <div class="input-group"><input type="password" name="password" id="lp" placeholder="__PASSWORD__" required><button type="button" class="eye-btn" onclick="tp('lp',this)">__SVG_EYE__</button></div>
                <label class="captcha-container"><input type="checkbox" name="captcha" required> __CAPTCHA__</label>
                <button type="submit" style="margin-top:10px;">__LOGIN_BTN__</button>
            </form>
            
            <div style="margin-top:20px; text-align:center;">
                <a href="/set_lang/ru?next=/" class="btn" style="display:inline-block; width:auto; padding:6px 15px; font-size:14px; background:#333; color:#fff; margin:0 5px; text-decoration:none; border-radius:20px;" class="__RU_ACTIVE__">RU</a>
                <a href="/set_lang/en?next=/" class="btn" style="display:inline-block; width:auto; padding:6px 15px; font-size:14px; background:#333; color:#fff; margin:0 5px; text-decoration:none; border-radius:20px;" class="__EN_ACTIVE__">EN</a>
            </div>
        </div>
    </div>
    __OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__LOGIN__",t('login',lang)),("__REG__",t('reg',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",t('username',lang)),("__NICKNAME__",t('nickname',lang)),("__PASSWORD__",t('password',lang)),("__REPASS__",t('re_pass',lang)),("__CAPTCHA__",t('captcha',lang)),("__PRIVACY_AGREE__",t('privacy_agree',lang)),("__PRIVACY_LINK__",t('privacy_link',lang)),("__REG_BTN__",t('register_btn',lang)),("__LOGIN_BTN__",t('login_btn',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__ERROR__",eb),("__OVERLAY__",get_overlay(lang)),("__SVG_EYE__",SVG_EYE)]:
        s = s.replace(k, v)
    return s

def _img_html(img_src, extra_onclick=True):
    if not img_src: return ""
    oc = " onclick=\"viewImage(this.src)\"" if extra_onclick else ""
    return f'<img class="post-img" src="{img_src}" loading="lazy" onload="window.skelLoad(this)"{oc}>'

def _avatar_html(avatar_src, username):
    if not avatar_src: 
        return f'<div class="post-avatar" style="display:flex;align-items:center;justify-content:center;font-weight:bold;color:#fff;font-size:20px;">{username[0].upper()}</div>'
    return f'<img class="post-avatar" src="{avatar_src}" loading="lazy" onload="window.skelLoad(this)" onclick="viewImage(this.src)">'

def render_records(records, lang, own=False, uid=None):
    if not records or not isinstance(records, list): return f"<div style='padding:40px; text-align:center; color:#71767b;'>{t('no_posts', lang)}</div>"
    out = ""
    for x in records:
        if not isinstance(x, dict): continue
        rid = esc(x.get('id'))
        if not rid: continue
        pinned = bool(x.get('is_pinned', False))
        content = linkify(x.get('content'))
        date = format_date(esc(x.get('created_at')))
        iso = esc(x.get('created_at', ''))
        sugg_by = esc(x.get('suggested_by', ''))
        img = sanitize_url(x.get('image_data', ''))
        safe_nick = esc(x.get('user_nickname', ''))
        
        # Get user details for post header
        user_info = CACHE["users"].get(safe_nick, {})
        display_name = esc(user_info.get('username', safe_nick))
        avatar_data = sanitize_url(user_info.get('avatar_data', ''))
        avatar_html = _avatar_html(avatar_data, display_name)
        
        acts = "<div class='post-actions'>"
        acts += f"<button class='action-icon' onclick='copyLink(this)' data-user='{safe_nick}' data-rid='{rid}'>🔗 {t('copy_link', lang)}</button>"
        if own:
            acts += f"<button onclick='hp(\"{rid}\",this)' class='action-icon pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button>"
            acts += f"<button onclick='hd(\"{rid}\",this)' class='action-icon del'>{t('delete', lang)}</button>"
        acts += "</div>"
        
        sugg_html = f"<div style='font-size:13px; color:#1d9bf0; margin-bottom:8px;'>↳ {t('suggested_by', lang)} {sugg_by}</div>" if sugg_by else ""
        img_html = _img_html(img)
        
        out += f"""
        <div class='post-wrapper' id='post-{rid}'>
            <div class='post-card'>
                {avatar_html}
                <div class='post-body'>
                    <div class='post-header'>
                        <a href='/{safe_nick}' class='post-author'>{display_name}</a>
                        <span class='post-nickname'>@{safe_nick}</span>
                        <span class='post-dot'>·</span>
                        <span class='post-date' data-iso='{iso}'>{date}</span>
                    </div>
                    {sugg_html}
                    <div class='post-text'>{content}</div>
                    {img_html}
                    {acts}
                </div>
            </div>
        </div>"""
    return out

def merge_memory(db_records, nickname):
    f = []
    if not db_records or not isinstance(db_records, list): db_records = []
    for x in db_records:
        if not isinstance(x, dict): continue
        x_id = x.get('id')
        if not x_id or x_id in deleted_records: continue
        if x_id in pinned_records: x['is_pinned'] = pinned_records[x_id]
        f.append(x)
    for rid, x in pending_records.items():
        if isinstance(x, dict) and x.get('user_nickname') == nickname: f.append(x)
    try: f.sort(key=lambda x: (bool(x.get('is_pinned')), str(x.get('created_at') or '')), reverse=True)
    except Exception: pass
    return f

def create_post_modal(lang):
    return f"""
    <div id="create-modal" class="modal-overlay">
        <div class="modal-box">
            <div class="modal-header">
                <button type="button" onclick="closeCreateModal()" class="modal-close">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
                <button type="button" id="modal-submit-btn" onclick="document.getElementById('modal-form').requestSubmit()">{t('create_post_btn', lang)}</button>
            </div>
            <form id="modal-form" onsubmit="submitModalPost(event)">
                <div class="modal-body">
                    <div class="modal-textarea" contenteditable="true" id="modal-textarea" oninput="document.getElementById('hidden-modal-text').value = this.innerText" style="outline:none;"></div>
                    <textarea name="content" id="hidden-modal-text" style="display:none;"></textarea>
                </div>
                <div style="padding: 0 16px 16px;">
                    <div id="post-img-container" style="display:none; position:relative; margin-bottom:10px;">
                        <img id="post-img-preview" class="img-preview">
                        <button type="button" onclick="removePostImage()" style="position:absolute; top:10px; right:10px; background:rgba(0,0,0,0.6); color:white; border:none; border-radius:50%; width:32px; height:32px; cursor:pointer; font-size:18px; line-height:1;">&times;</button>
                    </div>
                </div>
                <div class="modal-footer">
                    <label class="file-label" for="post-file-input" style="background:transparent; border:none; padding:8px; width:auto; cursor:pointer; color:#1d9bf0;">
                        {SVG_CAMERA}
                    </label>
                    <input type="file" id="post-file-input" accept="image/*" onchange="handlePostImage(this)" style="display:none;">
                </div>
            </form>
        </div>
    </div>
    """

def feed_html(nickname, user, my_p, lang, token, viewer, sugg_count=0):
    rh_my = render_records(my_p, lang, own=True, uid=viewer)
    user_username = esc(user.get('username'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    og_title = f"Лента — Solid" if lang == "ru" else f"Feed — Solid"
    og = og_tags(og_title, "", "/cabinet", image=avatar, lang=lang)
    
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar, user_username)
    
    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('feed_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, viewer)}</head><body>
    
    <!-- PC Layout -->
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <h2>{t('feed_title', lang)}</h2>
            </div>
            <div style="padding: 20px; border-bottom: 1px solid #2f3336; display: flex; gap: 12px; cursor: pointer;" onclick="openCreateModal()">
                <div class="post-avatar" style="display:flex;align-items:center;justify-content:center;font-weight:bold;color:#fff;background:#333;">{user_username[0].upper()}</div>
                <div style="flex:1; display:flex; align-items:center; color:#71767b; font-size:20px;">{t('create_post_placeholder', lang)}</div>
                <button class="btn-blue" style="width:auto; padding:8px 20px;">{t('create_post_btn', lang)}</button>
            </div>
            {rh_my}
        </div>
    </div>

    <!-- Mobile Layout -->
    <div class="mobile-layout">
        <div class="page-header">
            <h2>{t('feed_title', lang)}</h2>
        </div>
        {rh_my}
    </div>

    {create_post_modal(lang)}
    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def create_page_html(nickname, lang, token):
    og_title = t('create_page_title', lang) + " — Solid"
    og = og_tags(og_title, "", "/cabinet/new", lang=lang)
    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('create_page_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    <script>if(window.innerWidth > 768) window.location.href='/cabinet';</script>
    
    <div class="mobile-layout">
        <div class="page-header">
            <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
            <h2>{t('create_page_title', lang)}</h2>
        </div>
        <div style="padding: 20px;">
            <form onsubmit="hcNew(event)" style="display:flex; flex-direction:column; gap:15px;">
                <textarea name="content" placeholder="{t('create_post_placeholder', lang)}" required maxlength="5000" style="height:200px; font-size:20px; border:none; background:transparent; padding:0;" autofocus></textarea>
                <div id="post-img-container" style="display:none; position:relative;">
                    <img id="post-img-preview" class="img-preview">
                    <button type="button" onclick="removePostImage()" style="position:absolute; top:10px; right:10px; background:rgba(0,0,0,0.6); color:white; border:none; border-radius:50%; width:32px; height:32px; cursor:pointer; font-size:18px; line-height:1;">&times;</button>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid #2f3336; padding-top:15px;">
                    <label class="file-label" for="post-file-input" style="background:transparent; border:none; padding:8px; width:auto; cursor:pointer; color:#1d9bf0;">
                        {SVG_CAMERA}
                    </label>
                    <input type="file" id="post-file-input" accept="image/*" onchange="handlePostImage(this)" style="display:none;">
                    <button type="submit" id="create-post-btn" class="btn-blue" style="width:auto; padding:10px 24px;">{t('create_post_btn', lang)}</button>
                </div>
            </form>
        </div>
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def suggestions_page_html(nickname, suggestions, lang, token):
    if not suggestions:
        rh = f"<div style='padding:40px; text-align:center; color:#71767b;'>{t('sugges_empty', lang)}</div>"
    else:
        rh = ""
        for sg in suggestions:
            sid = esc(sg.get('id'))
            sugg_by = esc(sg.get('suggested_by_name'))
            content = linkify(sg.get('content'))
            date = format_date(esc(sg.get('created_at')))
            iso = esc(sg.get('created_at', ''))
            img = sanitize_url(sg.get('image_data', ''))
            img_html = _img_html(img)
            rh += f"""
            <div class='post-card' id='sugg-{sid}'>
                <div class='post-body'>
                    <div class='post-header'>
                        <span class='post-author'>{sugg_by}</span>
                        <span class='post-date' data-iso='{iso}'>{date}</span>
                    </div>
                    <div class='post-text'>{content}</div>
                    {img_html}
                    <div style='display:flex; gap:10px; margin-top:15px;'>
                        <button class='btn-blue' onclick="approveSugg('{sid}')" style='padding:8px 20px; width:auto;'>{t('sugges_approve',lang)}</button>
                        <button class='btn-danger' onclick="rejectSugg('{sid}')" style='padding:8px 20px; width:auto;'>{t('sugges_reject',lang)}</button>
                    </div>
                </div>
            </div>"""
    og_title = t('suggestions_title', lang) + " — " + nickname
    og = og_tags(og_title, "Solid — suggestions", "/cabinet/suggestions", lang=lang)
    
    user = CACHE["users"].get(nickname, {})
    avatar = sanitize_url(user.get('avatar_data', ''))
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar, esc(user.get('username', nickname)))

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('suggestions_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <h2>{t('suggestions_title', lang)}</h2>
            </div>
            {rh}
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <h2>{t('suggestions_title', lang)}</h2>
        </div>
        {rh}
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def sugges_form_html(nickname, lang, token, error="", viewer="", rules="", enabled=True, photo_enabled=True):
    msg_html = f"<div class='error-msg'>{esc(error)}</div>" if error else ""
    is_own = (viewer == nickname)
    if is_own: form_block = f"<div class='error-msg'>{t('sugges_own', lang)}</div>"
    elif not enabled: form_block = f"<div class='error-msg'>{t('sugges_disabled', lang)}</div>"
    else:
        safe_nick_attr = esc(nickname)
        photo_block = f"<label class='file-label' for='sugg-file-input' style='color:#1d9bf0; background:transparent; border:none; display:flex; align-items:center; gap:8px; cursor:pointer;'>{SVG_CAMERA} <span>{t('attach_photo', lang)}</span></label><input type='file' id='sugg-file-input' accept='image/*' onchange='handleSuggImage(this)' style='display:none;'><img id='sugg-img-preview' class='img-preview' style='display:none;'>" if photo_enabled else ""
        form_block = f"<form data-nickname='{safe_nick_attr}' onsubmit='submitSuggestion(event)' style='display:flex;flex-direction:column;gap:15px;'><input type='text' name='sugg_name' placeholder='{t('sugges_name',lang)}' required maxlength='60'><textarea name='content' placeholder='{t('sugges_content',lang)}' required maxlength='500' style='height:150px;'></textarea>{photo_block}<button type='submit' id='sugg-submit-btn' class='btn-blue'>{t('sugges_send',lang)}</button></form>"
    rules_block = f"<div style='background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:20px;'><b style='display:block; margin-bottom:8px; color:#1d9bf0;'>{t('rules_title',lang)}</b><div style='color:#e7e9ea; font-size:14px; white-space:pre-wrap;'>{esc(rules)}</div></div>" if rules else ""
    
    og_title = f"Предложить пост для {nickname}" if lang == "ru" else f"Suggest a post for {nickname}"
    og = og_tags(og_title, "Solid — suggestions", f"/{quote(nickname, safe='')}/sugges", lang=lang)
    safe_nick_url = quote(nickname, safe='')
    
    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('sugges_title', lang)} {nickname} — Solid</title>{og}
    {get_css()}{get_js(lang, token, viewer)}</head><body>
    
    <div class="auth-container">
        <div class="auth-box">
            <h2 style="text-align:center; margin-bottom:20px;">{t('sugges_title', lang)} {nickname}</h2>
            {msg_html}
            {rules_block}
            {form_block}
            <a href="/cabinet" class="btn" style="background:#333; color:#fff; margin-top:15px;">{t('back_home',lang)}</a>
        </div>
    </div>

    {bottom_nav_html(lang) if viewer else ""}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def settings_menu_html(nickname, user, lang, token):
    og_title = "Настройки — Solid" if lang == "ru" else "Settings — Solid"
    og = og_tags(og_title, "", "/settings", lang=lang)
    
    avatar = sanitize_url(user.get('avatar_data', ''))
    username = esc(user.get('username'))
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar, username)

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('settings_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <h2>{t('settings_title', lang)}</h2>
            </div>
            <div class="settings-menu-list">
                <a href="/settings/info" class="settings-menu-item">
                    <div class="settings-menu-item-left">
                        {SVG_INFO} {t('settings_info', lang)}
                    </div>
                </a>
                <a href="/settings/account" class="settings-menu-item">
                    <div class="settings-menu-item-left">
                        {SVG_USER} {t('settings_account', lang)}
                    </div>
                </a>
                <a href="/settings/appearance" class="settings-menu-item">
                    <div class="settings-menu-item-left">
                        {SVG_PALETTE} {t('settings_appearance', lang)}
                    </div>
                </a>
            </div>
            <div style="padding: 20px;">
                <button onclick="confirmLogout()" class="btn-danger">{t('logout', lang)}</button>
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <h2>{t('settings_title', lang)}</h2>
        </div>
        <div class="settings-menu-list">
            <a href="/settings/info" class="settings-menu-item">
                <div class="settings-menu-item-left">
                    {SVG_INFO} {t('settings_info', lang)}
                </div>
            </a>
            <a href="/settings/account" class="settings-menu-item">
                <div class="settings-menu-item-left">
                    {SVG_USER} {t('settings_account', lang)}
                </div>
            </a>
            <a href="/settings/appearance" class="settings-menu-item">
                <div class="settings-menu-item-left">
                    {SVG_PALETTE} {t('settings_appearance', lang)}
                </div>
            </a>
        </div>
        <div style="padding: 20px;">
            <button onclick="confirmLogout()" class="btn-danger">{t('logout', lang)}</button>
        </div>
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def settings_info_html(nickname, user, lang, token):
    og_title = "Инфо — Solid" if lang == "ru" else "Info — Solid"
    og = og_tags(og_title, "", "/settings/info", lang=lang)
    
    avatar = sanitize_url(user.get('avatar_data', ''))
    username = esc(user.get('username'))
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar, username)
    contacts = " | ".join(f"<a href='mailto:{e}'>{e}</a>" for e in CONTACT_EMAILS)
    current_url = SITE_URL + "/settings/info"
    badge_url = DESTROY_BASE + quote(current_url, safe='')

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>Инфо — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/settings" class="back-btn">{SVG_BACK}</a>
                <h2>{t('settings_info', lang)}</h2>
            </div>
            <div style="padding: 20px; text-align:center; color:#e7e9ea;">
                <div style="font-size:32px; font-family:'Herokid','Impact',sans-serif; margin-bottom:10px;">Solid</div>
                <div style="font-size:14px; color:#71767b; margin-bottom:20px;">v{APP_VERSION} ({SERVER_START_DATE})</div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:20px; border-radius:16px; text-align:left; margin-bottom:20px;">
                    <div style="margin-bottom:10px;"><b>{t('created_by',lang)}</b> <a href="http://solid-link.ddns.net" target="_blank" style="color:#1d9bf0; text-decoration:none;">Solid</a></div>
                    <div style="margin-bottom:10px;"><b>{t('hosting',lang)}</b> <a href="https://fastapicloud.com" target="_blank" style="color:#1d9bf0; text-decoration:none;">FastAPICloud</a></div>
                    <div style="margin-bottom:10px;"><b>{t('stats_contacts',lang)}</b></div>
                    <div style="color:#1d9bf0;">{contacts}</div>
                </div>
                <div style="display:flex; flex-direction:column; gap:10px;">
                    <a href="/privacy" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('privacy_title',lang)}</a>
                    <a href="/docs" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('faq_link',lang)}</a>
                    <a href="/stats" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('stats_link',lang)}</a>
                    <a href="/bugreport" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('bugreport_title',lang)}</a>
                </div>
                <div style="margin-top:20px;">
                    <a href="{badge_url}" target="_blank">
                        <img src="https://destroy.spritefusion.com/badge.svg" alt="Destroy this website" width="180" height="40" />
                    </a>
                </div>
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/settings" class="back-btn">{SVG_BACK}</a>
            <h2>{t('settings_info', lang)}</h2>
        </div>
        <div style="padding: 20px; text-align:center; color:#e7e9ea;">
            <div style="font-size:32px; font-family:'Herokid','Impact',sans-serif; margin-bottom:10px;">Solid</div>
            <div style="font-size:14px; color:#71767b; margin-bottom:20px;">v{APP_VERSION} ({SERVER_START_DATE})</div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:20px; border-radius:16px; text-align:left; margin-bottom:20px;">
                <div style="margin-bottom:10px;"><b>{t('created_by',lang)}</b> <a href="http://solid-link.ddns.net" target="_blank" style="color:#1d9bf0; text-decoration:none;">Solid</a></div>
                <div style="margin-bottom:10px;"><b>{t('hosting',lang)}</b> <a href="https://fastapicloud.com" target="_blank" style="color:#1d9bf0; text-decoration:none;">FastAPICloud</a></div>
                <div style="margin-bottom:10px;"><b>{t('stats_contacts',lang)}</b></div>
                <div style="color:#1d9bf0;">{contacts}</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:10px;">
                <a href="/privacy" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('privacy_title',lang)}</a>
                <a href="/docs" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('faq_link',lang)}</a>
                <a href="/stats" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('stats_link',lang)}</a>
                <a href="/bugreport" class="btn" style="background:#16181c; border:1px solid #2f3336; color:#e7e9ea;">{t('bugreport_title',lang)}</a>
            </div>
            <div style="margin-top:20px;">
                <a href="{badge_url}" target="_blank">
                    <img src="https://destroy.spritefusion.com/badge.svg" alt="Destroy this website" width="180" height="40" />
                </a>
            </div>
        </div>
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def settings_account_html(nickname, user, lang, token, error=""):
    desc = esc(user.get('description'))
    rules = esc(user.get('sugges_rules', ''))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_display = "block" if avatar else "none"
    avatar_html = f'<label class="avatar-upload" for="avatar-file-input" style="width:100px;height:100px;border-radius:50%;overflow:hidden;position:relative;display:block;cursor:pointer;border:2px solid #2f3336;margin:0 auto 20px;"><div class="avatar-skeleton"><img id="avatar-preview" class="avatar" src="{avatar}" style="display:{avatar_display};opacity:{1 if avatar else 0};width:100%;height:100%;object-fit:cover;" onload="window.skelLoad(this)" onerror="this.parentElement.classList.add(\'loaded\')"></div><div class="avatar-upload-icon" style="position:absolute;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 0.2s;">{SVG_UPLOAD}</div></label>'
    user_username = esc(user.get('username'))
    sugges_checked = "checked" if user_sugges_enabled(user) else ""
    photo_checked = "checked" if user_sugges_photo_enabled(user) else ""
    og_title = "Аккаунт — Solid" if lang == "ru" else "Account — Solid"
    og = og_tags(og_title, desc or "", "/settings/account", image=avatar, lang=lang)
    
    err_block = ""
    if error == "csrf":
        err_block = f"<div class='error-msg'>{t('toast_csrf', lang)}</div>"
    elif error == "format":
        err_block = f"<div class='error-msg'>{t('err_user_format', lang)}</div>"
    elif error == "desc":
        err_block = f"<div class='error-msg'>{t('alert_desc_long', lang)}</div>"
    elif error == "rules":
        err_block = f"<div class='error-msg'>{t('rules_alert_long', lang)}</div>"
    elif error == "empty":
        err_block = f"<div class='error-msg'>{t('err_empty', lang)}</div>"
    elif error == "db":
        err_block = f"<div class='error-msg'>{t('err_db', lang)}</div>"

    avatar_side = sanitize_url(user.get('avatar_data', ''))
    username_side = esc(user.get('username'))
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar_side, username_side)

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('settings_account_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/settings" class="back-btn">{SVG_BACK}</a>
                <h2>{t('settings_account_title', lang)}</h2>
            </div>
            <div style="padding: 20px;">
                {err_block}
                <form action="/settings/account" method="post" style="display:flex;flex-direction:column;gap:15px">
                    <input type="hidden" name="csrf_token" value="{token}">
                    <input type="hidden" name="avatar_data" id="avatar-data" value="">
                    {avatar_html}
                    <input type="file" id="avatar-file-input" accept="image/*" onchange="handleAvatarChange(this)" style="display:none;">
                    <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('username_label',lang)}</div>
                    <input type="text" name="username" value="{user_username}" required maxlength="60">
                    <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('description',lang)}</div>
                    <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder',lang)}" oninput="uc(this)" style="height:100px;">{desc}</textarea>
                    <div id="char-count" style="color:#71767b;text-align:right;font-size:12px; margin-top:-10px;">{len(desc)} / 300</div>
                    <label class="captcha-container" style="justify-content:space-between;"><span>{t('sugges_enable_label',lang)}</span><input type="checkbox" name="sugges_enabled" {sugges_checked}></label>
                    <label class="captcha-container" style="justify-content:space-between;"><span>{t('sugges_photo_enable_label',lang)}</span><input type="checkbox" name="sugges_photo_enabled" {photo_checked}></label>
                    <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('rules_edit_label',lang)}</div>
                    <textarea name="sugges_rules" maxlength="1000" placeholder="{t('rules_placeholder',lang)}" oninput="ucRules(this)" style="height:100px;">{rules}</textarea>
                    <div id="rules-count" style="color:#71767b;text-align:right;font-size:12px; margin-top:-10px;">{len(rules)} / 1000</div>
                    <button type="submit" class="btn-blue" style="margin-top:10px;">{t('save_changes',lang)}</button>
                </form>
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/settings" class="back-btn">{SVG_BACK}</a>
            <h2>{t('settings_account_title', lang)}</h2>
        </div>
        <div style="padding: 20px;">
            {err_block}
            <form action="/settings/account" method="post" style="display:flex;flex-direction:column;gap:15px">
                <input type="hidden" name="csrf_token" value="{token}">
                <input type="hidden" name="avatar_data" id="avatar-data" value="">
                {avatar_html}
                <input type="file" id="avatar-file-input" accept="image/*" onchange="handleAvatarChange(this)" style="display:none;">
                <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('username_label',lang)}</div>
                <input type="text" name="username" value="{user_username}" required maxlength="60">
                <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('description',lang)}</div>
                <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder',lang)}" oninput="uc(this)" style="height:100px;">{desc}</textarea>
                <div id="char-count" style="color:#71767b;text-align:right;font-size:12px; margin-top:-10px;">{len(desc)} / 300</div>
                <label class="captcha-container" style="justify-content:space-between;"><span>{t('sugges_enable_label',lang)}</span><input type="checkbox" name="sugges_enabled" {sugges_checked}></label>
                <label class="captcha-container" style="justify-content:space-between;"><span>{t('sugges_photo_enable_label',lang)}</span><input type="checkbox" name="sugges_photo_enabled" {photo_checked}></label>
                <div style="color:#71767b;font-size:14px;font-weight:bold;">{t('rules_edit_label',lang)}</div>
                <textarea name="sugges_rules" maxlength="1000" placeholder="{t('rules_placeholder',lang)}" oninput="ucRules(this)" style="height:100px;">{rules}</textarea>
                <div id="rules-count" style="color:#71767b;text-align:right;font-size:12px; margin-top:-10px;">{len(rules)} / 1000</div>
                <button type="submit" class="btn-blue" style="margin-top:10px;">{t('save_changes',lang)}</button>
            </form>
        </div>
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def settings_appearance_html(nickname, user, lang, token):
    og_title = "Оформление — Solid" if lang == "ru" else "Appearance — Solid"
    og = og_tags(og_title, "", "/settings/appearance", lang=lang)
    
    avatar = sanitize_url(user.get('avatar_data', ''))
    username = esc(user.get('username'))
    pc_sidebar = pc_sidebar_html(lang, nickname, avatar, username)

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>Оформление — Solid</title>{og}
    {get_css()}{get_js(lang, token, nickname)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/settings" class="back-btn">{SVG_BACK}</a>
                <h2>{t('settings_appearance', lang)}</h2>
            </div>
            <div style="padding: 20px;">
                <h3 style="margin-bottom:20px; font-size:18px;">{t('settings_language', lang)}</h3>
                <div style="display:flex; gap:15px;">
                    <a href="/set_lang/ru?next=/settings/appearance" class="btn" style="background:{'#1d9bf0' if lang=='ru' else '#16181c'}; color:#fff; border:1px solid #2f3336;">RU (Русский)</a>
                    <a href="/set_lang/en?next=/settings/appearance" class="btn" style="background:{'#1d9bf0' if lang=='en' else '#16181c'}; color:#fff; border:1px solid #2f3336;">EN (English)</a>
                </div>
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/settings" class="back-btn">{SVG_BACK}</a>
            <h2>{t('settings_appearance', lang)}</h2>
        </div>
        <div style="padding: 20px;">
            <h3 style="margin-bottom:20px; font-size:18px;">{t('settings_language', lang)}</h3>
            <div style="display:flex; flex-direction:column; gap:10px;">
                <a href="/set_lang/ru?next=/settings/appearance" class="btn" style="background:{'#1d9bf0' if lang=='ru' else '#16181c'}; color:#fff; border:1px solid #2f3336;">RU (Русский)</a>
                <a href="/set_lang/en?next=/settings/appearance" class="btn" style="background:{'#1d9bf0' if lang=='en' else '#16181c'}; color:#fff; border:1px solid #2f3336;">EN (English)</a>
            </div>
        </div>
    </div>

    {bottom_nav_html(lang)}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    rh = render_records(records, lang, own=is_owner, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = _avatar_html(avatar, user_username)
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if is_owner or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn-blue' style='margin-top:15px; display:inline-block; text-decoration:none;'>{t('suggestions_btn', lang)}</a>"
    og_title = f"{nickname} — Solid"
    og_desc = desc or (f"Профиль {nickname}" if lang == "ru" else f"Profile {nickname}")
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}", image=avatar, lang=lang)
    
    pc_sidebar = pc_sidebar_html(lang, viewer or nickname, sanitize_url(CACHE["users"].get(viewer, {}).get('avatar_data', '')), esc(CACHE["users"].get(viewer, {}).get('username', viewer)))

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{user_username} (@{nickname}) — Solid</title>{og}
    {get_css()}{get_js(lang, token, viewer or "")}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
                <div>
                    <h2 style="font-size:18px;">{user_username}</h2>
                    <div style="font-size:13px; color:#71767b;">{len(records)} {t('stats_posts', lang)}</div>
                </div>
            </div>
            <div style="padding: 20px; border-bottom: 1px solid #2f3336; display:flex; gap:20px; align-items:flex-start;">
                <div style="width:80px; height:80px; flex-shrink:0;">
                    {avatar_html.replace('class="post-avatar"', 'style="width:80px;height:80px;border-radius:50%;object-fit:cover;"')}
                </div>
                <div style="flex:1;">
                    <h2 style="font-size:22px; margin-bottom:2px;">{user_username}</h2>
                    <div style="color:#71767b; margin-bottom:15px;">@{nickname}</div>
                    <div style="margin-bottom:15px; font-size:15px;">{desc}</div>
                    {sugg_btn}
                </div>
            </div>
            {rh}
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
            <div>
                <h2 style="font-size:18px;">{user_username}</h2>
                <div style="font-size:13px; color:#71767b;">{len(records)} {t('stats_posts', lang)}</div>
            </div>
        </div>
        <div style="padding: 20px; border-bottom: 1px solid #2f3336; display:flex; gap:20px; align-items:flex-start;">
            <div style="width:80px; height:80px; flex-shrink:0;">
                {avatar_html.replace('class="post-avatar"', 'style="width:80px;height:80px;border-radius:50%;object-fit:cover;"')}
            </div>
            <div style="flex:1;">
                <h2 style="font-size:22px; margin-bottom:2px;">{user_username}</h2>
                <div style="color:#71767b; margin-bottom:15px;">@{nickname}</div>
                <div style="margin-bottom:15px; font-size:15px;">{desc}</div>
                {sugg_btn}
            </div>
        </div>
        {rh}
    </div>

    {bottom_nav_html(lang) if viewer else ""}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, uid=viewer)
    avatar = sanitize_url(user.get('avatar_data', ''))
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if (viewer == nickname) or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn-blue' style='margin-top:15px; display:inline-block; text-decoration:none;'>{t('suggestions_btn', lang)}</a>"
    raw_content = record.get('content', '') or ''
    snippet = strip_html(raw_content)[:150] + ('...' if len(raw_content) > 150 else '')
    og_title = f"Запись от {nickname} — Solid" if lang == "ru" else f"Record by {nickname} — Solid"
    og_desc = snippet or "Solid"
    img_data = sanitize_url(record.get('image_data', ''))
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}/{quote(str(record.get('id', '')), safe='')}", image=img_data, lang=lang)
    
    pc_sidebar = pc_sidebar_html(lang, viewer or nickname, sanitize_url(CACHE["users"].get(viewer, {}).get('avatar_data', '')), esc(CACHE["users"].get(viewer, {}).get('username', viewer)))

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('record_page', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, viewer or "")}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/{safe_nick_url}" class="back-btn">{SVG_BACK}</a>
                <h2>{t('record_page', lang)}</h2>
            </div>
            {rh}
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/{safe_nick_url}" class="back-btn">{SVG_BACK}</a>
            <h2>{t('record_page', lang)}</h2>
        </div>
        {rh}
    </div>

    {bottom_nav_html(lang) if viewer else ""}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def bugreport_html(username, reports, lang, token, show_nav=False):
    rh = "<div style='padding:40px; text-align:center; color:#71767b;'>Заявок пока нет...</div>" if not reports else ""
    for x in reports:
        date_str = format_date(esc(x.get('created_at')))
        iso_str = esc(x.get('created_at', ''))
        rh += f"""
        <div class='post-card'>
            <div class='post-body'>
                <div class='post-header'>
                    <span class='post-author'>{t('bugreport_title',lang)}</span>
                    <span style='background:#1d9bf0; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px;'>{esc(x.get('status','Принято'))}</span>
                </div>
                <div class='post-text'>{esc(x.get('content'))}</div>
                <div style='color:#71767b; font-size:13px;' data-iso='{iso_str}'>{date_str}</div>
            </div>
        </div>"""
    og_title = "Баг-репорт — Solid" if lang == "ru" else "Bug Report — Solid"
    og = og_tags(og_title, "Solid", "/bugreport", lang=lang)
    
    pc_sidebar = pc_sidebar_html(lang, "", "", "")

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('bugreport_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, "")}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
                <h2>{t('bugreport_title', lang)}</h2>
            </div>
            <div style="padding:20px; border-bottom:1px solid #2f3336;">
                <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:15px">
                    <input type="hidden" name="csrf_token" value="{token}">
                    <input type="text" name="name" value="{esc(username)}" placeholder="{t('bugreport_name',lang)}" required maxlength="60">
                    <textarea name="content" placeholder="{t('bugreport_desc',lang)}" required maxlength="5000" style="height:100px;"></textarea>
                    <button type="submit" class="btn-blue">{t('bugreport_send',lang)}</button>
                </form>
            </div>
            <div style="padding:10px 20px; border-bottom:1px solid #2f3336;"><h3>{t('bugreport_my',lang)}</h3></div>
            {rh}
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
            <h2>{t('bugreport_title', lang)}</h2>
        </div>
        <div style="padding:20px; border-bottom:1px solid #2f3336;">
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:15px">
                <input type="hidden" name="csrf_token" value="{token}">
                <input type="text" name="name" value="{esc(username)}" placeholder="{t('bugreport_name',lang)}" required maxlength="60">
                <textarea name="content" placeholder="{t('bugreport_desc',lang)}" required maxlength="5000" style="height:100px;"></textarea>
                <button type="submit" class="btn-blue">{t('bugreport_send',lang)}</button>
            </form>
        </div>
        <div style="padding:10px 20px; border-bottom:1px solid #2f3336;"><h3>{t('bugreport_my',lang)}</h3></div>
        {rh}
    </div>

    {bottom_nav_html(lang) if show_nav else ""}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def privacy_html(lang, token):
    og_title = "Политика конфиденциальности — Solid" if lang == "ru" else "Privacy Policy — Solid"
    og = og_tags(og_title, "", "/privacy", lang=lang)
    pc_sidebar = pc_sidebar_html(lang, "", "", "")

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('privacy_title', lang)} — Solid</title>{og}
    {get_css()}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
                <h2>{t('privacy_title', lang)}</h2>
            </div>
            <div style="padding: 20px; color:#e7e9ea; font-size:15px; line-height:1.6;">
                {t('privacy_text',lang)}
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/cabinet" class="back-btn">{SVG_BACK}</a>
            <h2>{t('privacy_title', lang)}</h2>
        </div>
        <div style="padding: 20px; color:#e7e9ea; font-size:15px; line-height:1.6;">
            {t('privacy_text',lang)}
        </div>
    </div>

    {get_overlay(lang)}
    </body></html>
    """
    return s

def stats_html(lang, token, users_count, posts_count, sugg_count, last_update_iso, viewer=""):
    uptime = _uptime_str(lang)
    started = SERVER_START_DT.strftime("%d.%m.%y %H:%M UTC")
    last_upd = format_date(last_update_iso) if last_update_iso else "—"
    last_upd_iso = esc(last_update_iso or "")
    contacts_html = "".join(f"<div style='margin-top:6px;'><a href='mailto:{e}' style='color:#1d9bf0;'>{e}</a></div>" for e in CONTACT_EMAILS)
    og_title = "Статистика — Solid" if lang == "ru" else "Stats — Solid"
    og = og_tags(og_title, "", "/stats", lang=lang)
    pc_sidebar = pc_sidebar_html(lang, viewer or "", "", "")

    s = f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>{t('stats_title', lang)} — Solid</title>{og}
    {get_css()}{get_js(lang, token, viewer)}</head><body>
    
    <div class="pc-layout">
        {pc_sidebar}
        <div class="pc-main">
            <div class="page-header">
                <a href="/settings/info" class="back-btn">{SVG_BACK}</a>
                <h2>{t('stats_title', lang)}</h2>
            </div>
            <div style="padding: 20px;">
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_users',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{users_count}</span></div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_posts',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{posts_count}</span></div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_sugges',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{sugg_count}</span></div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_started',lang)}</b><span style="font-size:14px;">{started}</span></div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_last_update',lang)}</b><span style="font-size:14px;" data-iso="{last_upd_iso}">{last_upd}</span></div>
                <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_uptime',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{uptime}</span></div>
            </div>
        </div>
    </div>

    <div class="mobile-layout">
        <div class="page-header">
            <a href="/settings/info" class="back-btn">{SVG_BACK}</a>
            <h2>{t('stats_title', lang)}</h2>
        </div>
        <div style="padding: 20px;">
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_users',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{users_count}</span></div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_posts',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{posts_count}</span></div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_sugges',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{sugg_count}</span></div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_started',lang)}</b><span style="font-size:14px;">{started}</span></div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_last_update',lang)}</b><span style="font-size:14px;" data-iso="{last_upd_iso}">{last_upd}</span></div>
            <div style="background:#16181c; border:1px solid #2f3336; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;"><b>{t('stats_uptime',lang)}</b><span style="font-size:20px; font-weight:bold; color:#1d9bf0;">{uptime}</span></div>
        </div>
    </div>

    {bottom_nav_html(lang) if viewer else ""}
    {get_overlay(lang)}
    </body></html>
    """
    return s

def faq_markdown(lang: str) -> str:
    sections = FAQ_DATA.get(lang, FAQ_DATA["ru"])
    lines = [f"# {t('faq_title', lang)}", "", t('faq_intro', lang), ""]
    for icon_key, title, items in sections:
        lines.append(f"## {title}")
        lines.append("")
        for q, a in items:
            lines.append(f"### {q}")
            lines.append("")
            lines.append(a)
            lines.append("")
    return "\n".join(lines)

def docs_html(lang: str, token: str) -> str:
    og_title = "FAQ — Solid"
    og = og_tags(og_title, "", "/docs", lang=lang)
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>FAQ — Solid</title>
        {og}
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/docsify@4/themes/dark.css">
        <style>
            @import url('https://fonts.cdnfonts.com/css/herokid');
            @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@300;400;600;700&display=swap');
            @font-face {{
                font-family: 'RuFont';
                src: url('/static/ru_font.ttf') format('truetype');
                font-weight: 300 700;
                font-display: swap;
            }}
            body {{ font-family: 'Source Sans 3', 'RuFont', Arial, sans-serif; background: #0d1117; color: #e7e9ea; }}
            h1, h2, h3, .app-name {{ font-family: 'Herokid', 'Impact', sans-serif !important; letter-spacing: 0.5px; color: #fff !important; }}
            :root {{ --theme-color: #1d9bf0; }}
            .sidebar {{ background: #0d1117; border-right: 1px solid #21262d; }}
            .sidebar ul li a {{ color: #c9d1d9; }}
            .sidebar ul li.active > a, .sidebar ul li a:hover {{ color: #1d9bf0; border-right: 2px solid #1d9bf0; }}
            .sidebar-toggle {{ background: #1d9bf0; }}
            .markdown-section {{ color: #c9d1d9; }}
            .markdown-section h1, .markdown-section h2, .markdown-section h3 {{ color: #ffffff; }}
            .markdown-section h2 {{ border-bottom: 2px solid #21262d; padding-bottom: 12px; margin-top: 40px; }}
            .markdown-section code {{ background: #161b22; color: #79c0ff; }}
            .markdown-section a {{ color: #1d9bf0; }}
            .app-nav {{ background: #0d1117; }}
            .app-nav a {{ color: #c9d1d9; }}
            .app-name, .app-name-link {{ color: #ffffff !important; }}
        </style>
        <script>
            window.$docsify = {{
                name: 'Solid',
                loadSidebar: false,
                subMaxLevel: 2,
                basePath: '/docs/',
                homepage: 'README.md',
                coverpage: false,
                auto2top: true,
                mergeNavbar: true,
                search: {{ placeholder: 'Поиск...', noData: 'Ничего не найдено' }}
            }};
        </script>
    </head>
    <body>
        <div id="app"></div>
        <script src="https://cdn.jsdelivr.net/npm/docsify@4"></script>
        <script src="https://cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
    </body>
    </html>
    """

@app.get("/set_lang/{lang}")
async def set_lang(lang: str, r: Request, next: str = "/"):
    effective_lang = lang if lang in ("ru", "en") else "ru"
    if not next.startswith("/") or next.startswith("//"): next = "/"
    sep = "&" if "?" in next else "?"
    target = next + sep + f"setlang={effective_lang}"
    res = RedirectResponse(target, 303)
    res.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    _set_lang_cookie(res, r, effective_lang)
    return res

@app.get("/", response_class=HTMLResponse)
async def index(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    token = get_csrf_token(r)
    if r.cookies.get("nickname"):
        resp = RedirectResponse("/cabinet", 303)
        set_csrf_cookie(resp, token, r)
        if setlang in ("ru", "en"): _set_lang_cookie(resp, r, lang)
        return resp
    res = HTMLResponse(auth_html(lang, "", token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    try: uc, pc, sc, lu = await _stats_data()
    except Exception as e:
        print(f"stats error: {e}"); uc, pc, sc, lu = 0, 0, 0, None
    res = HTMLResponse(stats_html(lang, token, uc, pc, sc, lu, viewer))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    token = get_csrf_token(r)
    res = HTMLResponse(privacy_html(lang, token)); set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/settings", response_class=HTMLResponse)
async def settings_menu(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_menu_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/settings/info", response_class=HTMLResponse)
async def settings_info(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_info_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/settings/account", response_class=HTMLResponse)
async def settings_account(r: Request, setlang: str = None, error: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_account_html(nickname, user_data, lang, token, error=error))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/settings/appearance", response_class=HTMLResponse)
async def settings_appearance(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_appearance_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    token = get_csrf_token(r)
    res = HTMLResponse(docs_html(lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/docs/README.md", response_class=PlainTextResponse)
async def docs_readme(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    return PlainTextResponse(faq_markdown(lang), media_type="text/markdown; charset=utf-8")

@app.post("/register", response_class=HTMLResponse)
async def register(r: Request, res: Response, username: str = Form(...), nickname: str = Form(...), password: str = Form(...), re_pass: str = Form(...), captcha: str = Form(None), privacy: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    if lang not in ("ru", "en"): lang = "ru"
    token = get_csrf_token(r)
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    if not privacy: return auth_html(lang, t('alert_privacy', lang), token)
    username = (username or "").strip()[:60]
    nickname = (nickname or "").strip()
    if not VALID_USER_RE.match(username): return auth_html(lang, t('err_user_format', lang), token)
    if not VALID_NICK_RE.match(nickname): return auth_html(lang, t('err_nick_format', lang), token)
    if len(password) < 8: return auth_html(lang, t('err_pass_short', lang), token)
    if password != re_pass: return auth_html(lang, t('alert_pass_mismatch', lang), token)
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
        if x.data: return auth_html(lang, t('alert_nick_taken', lang), token)
        await asyncio.to_thread(lambda: sb.table('users').insert({"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}).execute())
        
        CACHE["users"][nickname] = {"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
    resp = RedirectResponse("/cabinet", 303)
    secure = r.url.scheme == "https"
    resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
    set_csrf_cookie(resp, token, r); return resp

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    if lang not in ("ru", "en"): lang = "ru"
    token = get_csrf_token(r)
    ip = r.client.host if r.client else "0.0.0.0"
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    try:
        user = CACHE["users"].get(nickname)
        if not user:
            x = await asyncio.to_thread(lambda: sb.table('users').select('password').eq('nickname', nickname).execute())
            user = x.data[0] if x.data else None
            if user:
                CACHE["users"][nickname] = user
                
        if user and verify_password(password, user.get("password", "")):
            _login_clear(ip)
            if len(user["password"]) == 64:
                new_hash = hash_password(password)
                await asyncio.to_thread(lambda: sb.table('users').update({"password": new_hash}).eq('nickname', nickname).execute())
                CACHE["users"][nickname]["password"] = new_hash
            resp = RedirectResponse("/cabinet", 303)
            secure = r.url.scheme == "https"
            resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
            set_csrf_cookie(resp, token, r); return resp
        _login_fail(ip)
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
    return auth_html(lang, t('alert_bad_login', lang), token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    
    user_data, p_data, sc = await asyncio.gather(
        _fetch_user(nickname), _fetch_posts(nickname), _fetch_suggestion_count(nickname)
    )
    if user_data is DB_UNAVAILABLE:
        body = "<h2>Сервер временно недоступен. <a href='/cabinet'>Повторить</a></h2>" if lang == "ru" else "<h2>Server temporarily unavailable. <a href='/cabinet'>Retry</a></h2>"
        return HTMLResponse(body, status_code=503)
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(feed_html(nickname, user_data, po, lang, token, nickname, sc))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/cabinet/profile", response_class=HTMLResponse)
async def cabinet_profile(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, user_data, po, lang, token, nickname))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/cabinet/new", response_class=HTMLResponse)
async def cabinet_new(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(create_page_html(nickname, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/cabinet/suggestions", response_class=HTMLResponse)
async def cabinet_suggestions(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    s_data = await _fetch_suggestions(nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(suggestions_page_html(nickname, s_data, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/{nickname}/sugges", response_class=HTMLResponse)
async def sugges_form(nickname: str, r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
    rules = user_data.get('sugges_rules', '') or ''
    enabled = user_sugges_enabled(user_data)
    photo_enabled = user_sugges_photo_enabled(user_data)
    res = HTMLResponse(sugges_form_html(nickname, lang, token, viewer=viewer, rules=rules, enabled=enabled, photo_enabled=photo_enabled))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.post("/rpc")
async def rpc_endpoint(req: RPCRequest, r: Request, nickname: str = Cookie(None)):
    if not check_csrf(r): raise HTTPException(status_code=403, detail="CSRF Error")
    if req.method == "submit_suggestion":
        target = req.params.get("target_nickname", "").strip()
        sugg_name = req.params.get("sugg_name", "").strip()[:60]
        content = clean_content(req.params.get("content", ""))[:500]
        image_data = valid_b64(req.params.get("image_data", ""))
        if not target or not sugg_name or not content: raise HTTPException(400, "Missing fields")
        if not VALID_NICK_RE.match(target): raise HTTPException(400, "Bad target")
        if nickname and target == nickname: raise HTTPException(400, "Cannot suggest to yourself")
        try:
            u = await asyncio.to_thread(lambda: sb.table('users').select('nickname,sugges_enabled,sugges_photo_enabled').eq('nickname', target).execute())
            if not u.data: raise HTTPException(404, "User not found")
            tu = u.data[0]
            if not user_sugges_enabled(tu): raise HTTPException(400, "Suggestions disabled")
            if not user_sugges_photo_enabled(tu): image_data = ""
        except HTTPException: raise
        except Exception as e: raise HTTPException(500, str(e))
        data = {"author_nickname": target, "suggested_by_name": sugg_name, "content": content, "status": "pending", "image_data": image_data}
        try: await asyncio.to_thread(lambda: sb.table('suggestions').insert(data).execute())
        except Exception:
            data.pop("image_data", None)
            await asyncio.to_thread(lambda: sb.table('suggestions').insert(data).execute())
        return {"status": "ok"}
    if not nickname: raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        if req.method == "create_record":
            content = clean_content(req.params.get("content", ""))
            if not content.strip(): raise HTTPException(400, "Empty")
            client_id = req.params.get("client_id")
            image_data = valid_b64(req.params.get("image_data", ""))
            i = client_id if client_id and re.match(r'^[a-f0-9\-]{10,40}$', client_id) else str(uuid.uuid4())
            n = datetime.now(timezone.utc).isoformat()
            pd = {"id": i, "user_nickname": nickname, "content": content.strip(), "is_pinned": False, "created_at": n, "image_data": image_data}
            try: await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
            except Exception:
                pd.pop("image_data", None)
                await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
            
            CACHE["posts"].append(pd)
            
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        elif req.method == "delete_record":
            rid = req.params.get("post_id")
            await asyncio.to_thread(lambda: sb.table('posts').delete().eq('id', rid).eq('user_nickname', nickname).execute())
            
            CACHE["posts"] = [p for p in CACHE["posts"] if p.get("id") != rid]
            
            await manager.broadcast({"type": "delete_record", "post_id": rid})
            return {"status": "ok"}
        elif req.method == "pin_record":
            rid = req.params.get("post_id")
            x = await asyncio.to_thread(lambda: sb.table('posts').select('is_pinned').eq('id', rid).eq('user_nickname', nickname).execute())
            if not x.data: raise HTTPException(404, "Not found")
            ns = not x.data[0].get('is_pinned', False)
            if ns:
                await asyncio.to_thread(lambda: sb.table('posts').update({"is_pinned": False}).eq('user_nickname', nickname).neq('id', rid).execute())
            await asyncio.to_thread(lambda: sb.table('posts').update({"is_pinned": ns}).eq('id', rid).eq('user_nickname', nickname).execute())
            
            for p in CACHE["posts"]:
                if p.get("user_nickname") == nickname:
                    p["is_pinned"] = (p.get("id") == rid) and ns
                    
            return {"status": "ok", "is_pinned": ns}
        elif req.method == "approve_suggestion":
            sid = req.params.get("suggestion_id")
            s = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('id', sid).eq('author_nickname', nickname).execute())
            if not s.data: raise HTTPException(404, "Suggestion not found")
            sugg = s.data[0]
            i = str(uuid.uuid4()); n = datetime.now(timezone.utc).isoformat()
            np = {"id": i, "user_nickname": nickname, "content": clean_content(sugg.get('content', '')), "is_pinned": False, "created_at": n, "suggested_by": sugg.get('suggested_by_name', ''), "image_data": valid_b64(sugg.get('image_data', '') or '')}
            try: await asyncio.to_thread(lambda: sb.table('posts').insert(np).execute())
            except Exception:
                np.pop("suggested_by", None); np.pop("image_data", None)
                await asyncio.to_thread(lambda: sb.table('posts').insert(np).execute())
            await asyncio.to_thread(lambda: sb.table('suggestions').delete().eq('id', sid).execute())
            
            CACHE["posts"].append(np)
            
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        elif req.method == "reject_suggestion":
            sid = req.params.get("suggestion_id")
            await asyncio.to_thread(lambda: sb.table('suggestions').delete().eq('id', sid).eq('author_nickname', nickname).execute())
            return {"status": "ok"}
        raise HTTPException(400, "Unknown method")
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/settings/account", response_class=HTMLResponse)
async def settings_account_action(r: Request, res: Response, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), sugges_enabled: str = Form(None), sugges_photo_enabled: str = Form(None), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if lang not in ("ru", "en"): lang = "ru"
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token):
        return RedirectResponse("/settings/account?error=csrf", 303)
    username = (username or "").strip()[:60]
    if not VALID_USER_RE.match(username):
        return RedirectResponse("/settings/account?error=format", 303)
    if len(description) > 300:
        return RedirectResponse("/settings/account?error=desc", 303)
    if len(sugges_rules) > 1000:
        return RedirectResponse("/settings/account?error=rules", 303)
    update = {"username": username, "description": description, "sugges_rules": sugges_rules, "sugges_enabled": bool(sugges_enabled), "sugges_photo_enabled": bool(sugges_photo_enabled)}
    av = valid_b64(avatar_data)
    if av: update["avatar_data"] = av
    try: 
        await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
        if nickname in CACHE["users"]:
            CACHE["users"][nickname].update(update)
        return RedirectResponse("/settings/account", 303)
    except Exception:
        update.pop("avatar_data", None); update.pop("sugges_enabled", None); update.pop("sugges_photo_enabled", None)
        try: 
            await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
            if nickname in CACHE["users"]:
                CACHE["users"][nickname].update(update)
            return RedirectResponse("/settings/account", 303)
        except Exception:
            return RedirectResponse("/settings/account?error=db", 303)

@app.get("/cabinet/edit")
async def cabinet_edit_redirect():
    return RedirectResponse("/settings/account", 303)

@app.post("/cabinet/edit")
async def cabinet_edit_post_redirect():
    return RedirectResponse("/settings/account", 303)

@app.get("/bugreport", response_class=HTMLResponse)
async def bugreport(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    u = ""; rp = []; show_nav = False
    if nickname:
        show_nav = True
        try:
            x = await asyncio.to_thread(lambda: sb.table('users').select('username').eq('nickname', nickname).execute())
            if x.data: u = x.data[0].get('username') or ""
            y = await asyncio.to_thread(lambda: sb.table('bug_reports').select('*').eq('user_nickname', nickname).order('created_at', desc=True).execute())
            rp = y.data or []
        except Exception: pass
    token = get_csrf_token(r)
    res = HTMLResponse(bugreport_html(u, rp, lang, token, show_nav=show_nav))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): 
        return RedirectResponse("/bugreport", 303)
    d = {"name": name[:60], "content": clean_content(content)[:5000], "status": "Принято" if lang == "ru" else "Accepted"}
    if nickname: d["user_nickname"] = nickname
    await asyncio.to_thread(lambda: sb.table('bug_reports').insert(d).execute())
    return RedirectResponse("/bugreport", 303)

@app.get("/logout")
async def logout():
    res = RedirectResponse("/", 303); res.delete_cookie("nickname"); return res

@app.get("/{nickname}/{rid}", response_class=HTMLResponse)
async def record_page(nickname: str, rid: str, r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    try:
        u = await _fetch_user(nickname)
        if u is DB_UNAVAILABLE: return HTMLResponse("<h2>DB Error</h2>", 500)
        
        rec = next((p for p in CACHE["posts"] if p.get("id") == rid and p.get("user_nickname") == nickname), None)
        if not rec:
            x = await asyncio.to_thread(lambda: sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute())
            rec = x.data[0] if x.data else None
            
        if not u: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
        if not rec: return HTMLResponse(f"<h2>{t('no_posts', lang)}</h2>", 404)
    except Exception:
        return HTMLResponse(f"<h2>DB Error</h2>", 500)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    res = HTMLResponse(record_page_html(nickname, u, rec, lang, token, viewer))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data:
        return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/'>OK</a></h2>", 404)
    viewer = r.cookies.get("nickname") or ""
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, user_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
