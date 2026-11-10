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

APP_VERSION = "0.20"
SERVER_START_DT = datetime.now(timezone.utc)
SERVER_START_DATE = SERVER_START_DT.strftime("%d.%m.%y")
CONTACT_EMAILS = ["sldshr.confirmation@gmail.com", "sldshr.confirm@yandex.ru"]
SITE_URL = "https://solid.fastapicloud.dev"
DESTROY_BASE = "https://destroy.spritefusion.com/?from=badge&url="

_current_path: ContextVar[str] = ContextVar("current_path", default="/")

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

deleted_records, pinned_records, pending_records = set(), {}, {}
MAX_B64_LEN = 900000
POST_MAX_LEN = 5000
VALID_NICK_RE = re.compile(r'^[a-zA-Z0-9_\-]{3,30}$')
VALID_USER_RE = re.compile(r'^[a-zA-Z0-9_\- ]{1,60}$')

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
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
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
        '<meta property="og:site_name" content="Solid Link">',
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
    last_exc = None
    for sel in ('username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
                'username,description,sugges_rules,avatar_data,sugges_enabled',
                'username,description,sugges_rules,avatar_data',
                'username,description,sugges_rules',
                'username,description'):
        try:
            res = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nickname).execute())
            return res.data[0] if res.data else None
        except Exception as e:
            last_exc = e
            continue
    return DB_UNAVAILABLE

async def _fetch_posts(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').eq('user_nickname', nickname).execute())
        return res.data or []
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
    users_count, posts_count, sugg_count, last_update = 0, 0, 0, None
    try:
        u = await asyncio.to_thread(lambda: sb.table('users').select('nickname', count='exact').execute())
        users_count = u.count if getattr(u, 'count', None) is not None else len(u.data or [])
    except Exception: pass
    try:
        p = await asyncio.to_thread(lambda: sb.table('posts').select('id', count='exact').execute())
        posts_count = p.count if getattr(p, 'count', None) is not None else len(p.data or [])
    except Exception: pass
    try:
        s = await asyncio.to_thread(lambda: sb.table('suggestions').select('id', count='exact').execute())
        sugg_count = s.count if getattr(s, 'count', None) is not None else len(s.data or [])
    except Exception: pass
    try:
        r = await asyncio.to_thread(lambda: sb.table('posts').select('created_at').order('created_at', desc=True).limit(1).execute())
        if r.data: last_update = r.data[0].get('created_at')
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
    return JSONResponse(
        {"name": "Solid Link", "short_name": "SolidLink", "start_url": "/",
         "display": "standalone", "background_color": "#f4f4f4", "theme_color": "#000000",
         "icons": [{"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xIDExczQtOCAxMS04IDExIDggMTEgOC00IDgtMTEgOC0xMS04LTExLTh6Ij48L3BhdGg+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMSIgcj0iMyI+PC9jaXJjbGU+PC9zdmc+", "sizes": "192x192", "type": "image/svg+xml"}]},
        headers={"Cache-Control": "public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = """
    const CACHE_NAME = 'solid-link-v2';
    const STATIC_ASSETS = ['/manifest.json'];
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
    return Response(content=js, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

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
    em = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    res = HTMLResponse(content=auth_html(lang, em, token), status_code=422)
    set_csrf_cookie(res, token, request)
    return res

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

PRIVACY_RU = """1. Общие положения<br>
Настоящая Политика конфиденциальности описывает, какие данные собирает Solid Link, как они используются, хранятся и защищаются. Используя Сайт, вы соглашаетесь с данной Политикой. Если вы не согласны с её условиями — пожалуйста, не используйте Сайт.<br><br>

2. Какие данные мы собираем<br>
• <b>Имя (юзернейм)</b> — отображаемое имя, указанное вами при регистрации.<br>
• <b>Никнейм</b> — уникальный идентификатор, используемый для входа.<br>
• <b>Пароль</b> — хранится исключительно в виде bcrypt-хеша; оригинал не сохраняется и не может быть восстановлен.<br>
• <b>Описание профиля и аватар</b> — по вашему желанию.<br>
• <b>Записи и предложки</b> — контент, который вы публикуете.<br>
• <b>Технические данные</b> — cookies для сессии, CSRF-токен, предпочитаемый язык.<br><br>

3. Как мы используем данные<br>
• Аутентификация и поддержание сессии.<br>
• Отображение профиля, записей и предложек.<br>
• Борьба со злоупотреблениями (rate limiting, CSRF-защита).<br>
• Мы не используем ваши данные для рекламы и не продаём их третьим лицам.<br><br>

4. Хранение данных<br>
Данные хранятся на серверах Supabase (PostgreSQL). Мы принимаем разумные меры для их защиты, однако ни один метод передачи через интернет не является абсолютно безопасным.<br><br>

5. Cookies<br>
Сайт использует следующие cookies:<br>
• <code>nickname</code> — поддержание сессии пользователя.<br>
• <code>csrf_token</code> — защита от CSRF-атак.<br>
• <code>lang</code> — запоминание выбранного языка.<br>
Вы можете удалить cookies в настройках браузера, но это разлогинит вас и сбросит настройки.<br><br>

6. Ваш контент<br>
Все записи, комментарии и предложки являются вашей интеллектуальной собственностью. Публикуя контент, вы подтверждаете, что имеете на него право. Мы не несём ответственности за контент пользователей.<br><br>

7. Передача третьим лицам<br>
Мы не передаём ваши персональные данные третьим лицам, за исключением случаев, предусмотренных законом, или когда это необходимо для работы сервиса (например, хостинг Supabase).<br><br>

8. Безопасность<br>
Пароли хешируются алгоритмом bcrypt. Используются CSRF-токены, rate limiting, CSP-заголовки, защищённые cookies (HttpOnly, SameSite=Lax, Secure на HTTPS).<br><br>

9. Ваши права<br>
• Изменить имя, описание и аватар в личном кабинете.<br>
• Удалить свои записи.<br>
• Отключить предложку.<br>
• Запросить удаление аккаунта через контакты администрации.<br><br>

10. Дети<br>
Сайт не предназначен для лиц младше 13 лет. Если вы младше — не регистрируйтесь.<br><br>

11. Изменения политики<br>
Мы можем обновлять эту Политику. Актуальная версия всегда доступна по адресу /privacy. Дата последнего обновления указана в подвале сайта.<br><br>

12. Контакты<br>
По вопросам конфиденциальности: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru"""

PRIVACY_EN = """1. General provisions<br>
This Privacy Policy describes what data Solid Link collects, how it is used, stored and protected. By using the Site you agree to this Policy. If you disagree with its terms — please do not use the Site.<br><br>

2. Data we collect<br>
• <b>Name (username)</b> — the display name you provide during registration.<br>
• <b>Nickname</b> — a unique identifier used for login.<br>
• <b>Password</b> — stored exclusively as a bcrypt hash; the original is never stored and cannot be recovered.<br>
• <b>Profile description and avatar</b> — at your discretion.<br>
• <b>Records and suggestions</b> — content you publish.<br>
• <b>Technical data</b> — session cookies, CSRF token, preferred language.<br><br>

3. How we use data<br>
• Authentication and session maintenance.<br>
• Displaying profile, records and suggestions.<br>
• Abuse prevention (rate limiting, CSRF protection).<br>
• We do not use your data for advertising and do not sell it to third parties.<br><br>

4. Data storage<br>
Data is stored on Supabase (PostgreSQL) servers. We take reasonable measures to protect it, however no method of transmission over the internet is completely secure.<br><br>

5. Cookies<br>
The Site uses the following cookies:<br>
• <code>nickname</code> — maintains your session.<br>
• <code>csrf_token</code> — protects against CSRF attacks.<br>
• <code>lang</code> — remembers your chosen language.<br>
You can delete cookies in your browser settings, but this will log you out and reset preferences.<br><br>

6. Your content<br>
All records, comments and suggestions are your intellectual property. By publishing content, you confirm you have the right to it. We are not responsible for user content.<br><br>

7. Third parties<br>
We do not share your personal data with third parties, except as required by law, or when necessary for the service to function (e.g., Supabase hosting).<br><br>

8. Security<br>
Passwords are hashed with bcrypt. We use CSRF tokens, rate limiting, CSP headers, and secure cookies (HttpOnly, SameSite=Lax, Secure on HTTPS).<br><br>

9. Your rights<br>
• Edit your name, description and avatar in your cabinet.<br>
• Delete your records.<br>
• Disable suggestions.<br>
• Request account deletion via administrator contacts.<br><br>

10. Children<br>
The Site is not intended for persons under 13 years of age. If you are younger — do not register.<br><br>

11. Policy changes<br>
We may update this Policy. The current version is always available at /privacy. The date of the last update is shown in the site footer.<br><br>

12. Contacts<br>
For privacy-related questions: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru"""

# ИСПРАВЛЕННЫЙ FAQ_DATA: все вложенные двойные кавычки заменены на одинарные
FAQ_DATA = {
    "ru": [
        ("🔐", "Регистрация и вход", [
            ("Как зарегистрироваться?", 'На главной странице заполните форму «Регистрация»: укажите юзернейм (ваше имя), никнейм (уникальный логин), пароль не короче 8 символов и его повтор. Поставьте обе галочки — «Я не робот» и согласие с политикой. Нажмите «Зарегистрироваться!».'),
            ("Какой никнейм можно выбрать?", 'От 3 до 30 символов: латинские буквы a–z, цифры 0–9, знаки подчёркивания <code>_</code> и дефис <code>-</code>. Никнейм уникален — если он занят, выберите другой.'),
            ("Забыли пароль — что делать?", 'Напишите администрации по адресам из подвала сайта: <a href="mailto:sldshr.confirmation@gmail.com">sldshr.confirmation@gmail.com</a> или <a href="mailto:sldshr.confirm@yandex.ru">sldshr.confirm@yandex.ru</a>. Укажите ваш никнейм.'),
            ("Как выйти из аккаунта?", 'В личном кабинете нажмите красную кнопку «Выйти» в левой панели.'),
            ("Что за ошибка «Too Many Requests»?", 'Сработал rate limit: слишком много попыток за минуту. Подождите 60 секунд, для логина — до 5 минут.'),
        ]),
        ("📝", "Записи и посты", [
            ("Как создать запись?", 'В личном кабинете введите текст в поле «Напишите что-нибудь...» и нажмите «Создать». Запись сразу появится в разделе «Мои записи» и на вашей публичной странице.'),
            ("Какая максимальная длина записи?", 'До 5000 символов. Символы переноса строки сохраняются.'),
            ("Как прикрепить фото?", 'В форме создания записи нажмите «Фото» и выберите изображение. Фото автоматически сожмётся и прикрепится к записи.'),
            ("Как закрепить запись?", 'Наведите на запись и нажмите «Закрепить» в правом верхнем углу. Закреплённая запись всегда будет наверху. Можно закрепить только одну запись одновременно.'),
            ("Как удалить запись?", 'Наведите на запись, нажмите «Удалить», подтвердите действие. Удаление необратимо.'),
            ("Как поделиться ссылкой на запись?", 'Наведите на запись и нажмите «Ссылка» — ссылка скопируется в буфер обмена. Она ведёт на страницу этой конкретной записи.'),
            ("Что такое автопревью ссылок?", 'Если в записи есть URL, при клике откроется диалог с превью: заголовок, описание и картинка с того сайта. Это защита от случайных переходов.'),
        ]),
        ("💡", "Предложка", [
            ("Что такое предложка?", 'Это форма обратной связи для ваших читателей: они могут предложить пост, который вы одобрите или отклоните. Найти её можно по адресу /ваш_никнейм/sugges.'),
            ("Как предложить пост?", 'Откройте страницу пользователя и нажмите «Предложить пост». Введите ваше имя и текст, при желании прикрепите фото, нажмите «Отправить».'),
            ("Как включить или отключить предложку?", 'В /cabinet/edit есть переключатель «Разрешить предложку». Отключённая предложка скрывает кнопку у всех посетителей.'),
            ("Как отключить фото в предложке?", 'Там же — переключатель «Разрешить фото в предложке». Если выключить, форма предложки будет без загрузки фото.'),
            ("Как модерировать предложки?", 'В личном кабинете нажмите «Предложки». Каждую можно «Одобрить» (превратится в вашу запись с пометкой автора) или «Отклонить» (удалить).'),
            ("Как задать правила для предложки?", 'В /cabinet/edit в поле «Правила предложки» (до 1000 символов). Они будут показаны всем, кто открывает форму.'),
            ("Можно ли предложить пост самому себе?", 'Нет. Свои посты создавайте напрямую в личном кабинете.'),
        ]),
        ("⚙️", "Профиль и настройки", [
            ("Как изменить имя или описание?", 'В /cabinet/edit укажите новое имя и описание (до 300 символов) и сохраните изменения.'),
            ("Как сменить аватар?", 'На странице редактирования нажмите на аватар — откроется выбор файла. Фото сожмётся до 300×300 пикселей.'),
            ("Как сменить язык?", 'Кнопки RU / EN в подвале любой страницы или в сайдбаре. Выбор запоминается в cookie на год.'),
            ("Где посмотреть статистику сайта?", 'Ссылка «Статистика» в подвале: количество пользователей, записей, предложек, аптайм и контакты администрации.'),
            ("Как удалить аккаунт?", 'Напишите администрации. Мы удалим аккаунт и все связанные записи в течение 7 дней.'),
        ]),
        ("🖼️", "Фото и изображения", [
            ("Какие форматы фото поддерживаются?", 'Любые, которые умеет открывать браузер: JPEG, PNG, WebP, GIF. На сервер отправляется сжатый JPEG.'),
            ("Почему фото сжимаются?", 'Чтобы сайт работал быстро и не перегружал хранилище. Сжатие происходит в браузере до отправки: до 1000px по ширине для постов и до 300px для аватара.'),
            ("Максимальный размер изображения?", 'После сжатия — до ~800 КБ в base64. Если оригинал огромный, сжатие произойдёт с потерей качества.'),
            ("Как посмотреть фото в полном размере?", 'Кликните по изображению — откроется просмотрщик. Закрыть можно клавишей Esc или кликом вне фото.'),
        ]),
        ("🔒", "Безопасность и приватность", [
            ("Как хранятся пароли?", 'Только в виде bcrypt-хеша. Оригинал пароля не сохраняется и не может быть восстановлен.'),
            ("Кто видит мои данные?", 'Публично видны: имя, никнейм, описание, аватар, записи. Пароль, CSRF-токен и служебные cookies — нет.'),
            ("Что такое CSRF-токен?", 'Скрытый токен, который защищает формы от подделки запросов. Без него действие не выполнится.'),
            ("Что за ошибка «CSRF Error»?", 'Cookie устарел или очистился. Обновите страницу — токен выдастся заново.'),
            ("Как защищены сессии?", 'Cookies HttpOnly, SameSite=Lax, Secure на HTTPS. Плюс заголовки CSP, X-Frame-Options, HSTS.'),
            ("Что такое политика конфиденциальности?", 'Документ, описывающий какие данные мы собираем и как их используем. Полный текст — по ссылке в подвале или на /privacy.'),
        ]),
        ("🐞", "Проблемы и поддержка", [
            ("Как сообщить о баге?", 'Откройте /bugreport, опишите проблему. Все ваши заявки видны там же со статусом: Принято, В работе, Исправлено, Отклонено.'),
            ("Не работает вход — что проверить?", '1) Никнейм точно такой, как при регистрации. 2) Пароль не короче 8 символов. 3) Галочка «Я не робот» поставлена. 4) Нет блокировки по rate limit.'),
            ("Почему не приходит письмо?", 'Письма мы не отправляем — вся связь через форму баг-репорта или контакты в подвале.'),
            ("С кем связаться?", 'Email администрации: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru. Отвечаем в течение 1–2 дней.'),
            ("Что такое «аптайм» в статистике?", 'Время с момента запуска сервера. Если сервер перезапущен — счётчик начинается заново.'),
        ]),
    ],
    "en": [
        ("🔐", "Registration & Login", [
            ("How do I register?", 'On the home page, fill in the "Registration" form: enter a username (your name), nickname (unique login), a password of at least 8 characters, and repeat it. Tick both boxes — "I am not a robot" and the privacy policy agreement. Click "Register!".'),
            ("What nickname can I choose?", 'From 3 to 30 characters: latin letters a–z, digits 0–9, underscores <code>_</code> and hyphens <code>-</code>. Nickname is unique — pick another if taken.'),
            ("I forgot my password — what now?", 'Email the administration at the addresses in the footer: <a href="mailto:sldshr.confirmation@gmail.com">sldshr.confirmation@gmail.com</a> or <a href="mailto:sldshr.confirm@yandex.ru">sldshr.confirm@yandex.ru</a>. Include your nickname.'),
            ("How do I log out?", 'In your personal cabinet click the red "Logout" button in the left panel.'),
            ("What is the 'Too Many Requests' error?", 'Rate limit triggered: too many attempts in a minute. Wait 60 seconds, for login — up to 5 minutes.'),
        ]),
        ("📝", "Records & Posts", [
            ("How do I create a record?", 'In your cabinet type text into the "Write something..." field and click "Create". The record appears immediately in "My records" and on your public page.'),
            ("What is the max record length?", 'Up to 5000 characters. Line breaks are preserved.'),
            ("How do I attach a photo?", 'In the create-record form click "Photo" and pick an image. The photo is auto-compressed and attached.'),
            ("How do I pin a record?", 'Hover over the record and click "Pin" in the top-right corner. The pinned record stays at the top. Only one record can be pinned at a time.'),
            ("How do I delete a record?", 'Hover over the record, click "Delete", confirm. Deletion is irreversible.'),
            ("How do I share a link to a record?", 'Hover over the record and click "Link" — the URL is copied to clipboard. It links to that exact record page.'),
            ("What is auto link preview?", 'If a record contains a URL, clicking it opens a dialog with a preview: title, description and image from that site. This prevents accidental clicks.'),
        ]),
        ("💡", "Suggestions", [
            ("What is the suggestion box?", 'It is a feedback form for your readers: they can suggest a post that you approve or reject. Available at /your_nickname/sugges.'),
            ("How do I suggest a post?", 'Open a user page and click "Suggest a post". Enter your name and text, optionally attach a photo, click "Send".'),
            ("How do I enable or disable suggestions?", 'In /cabinet/edit there is a toggle "Enable suggestions". Disabled suggestions hide the button from all visitors.'),
            ("How do I disable photos in suggestions?", 'Same place — "Allow photos in suggestions" toggle. If off, the suggestion form has no photo upload.'),
            ("How do I moderate suggestions?", 'In your cabinet click "Suggestions". Each can be "Approve" (becomes your record with the author noted) or "Reject" (deleted).'),
            ("How do I set rules for suggestions?", 'In /cabinet/edit under "Suggestion rules" (up to 1000 chars). They are shown to everyone who opens the form.'),
            ("Can I suggest a post to myself?", 'No. Create your posts directly in your cabinet.'),
        ]),
        ("⚙️", "Profile & Settings", [
            ("How do I change name or description?", 'In /cabinet/edit enter a new name and description (up to 300 chars) and save.'),
            ("How do I change my avatar?", 'On the edit page click the avatar — a file picker opens. The photo is compressed to 300×300 pixels.'),
            ("How do I change the language?", 'RU / EN buttons in the footer of any page or in the sidebar. The choice is stored in a cookie for a year.'),
            ("Where can I see site statistics?", 'The "Stats" link in the footer: users, records, suggestions, uptime and admin contacts.'),
            ("How do I delete my account?", 'Email the administration. We will delete the account and all related records within 7 days.'),
        ]),
        ("🖼️", "Photos & Images", [
            ("Which photo formats are supported?", 'Any your browser can open: JPEG, PNG, WebP, GIF. A compressed JPEG is uploaded.'),
            ("Why are photos compressed?", 'To keep the site fast and storage light. Compression happens in the browser before upload: up to 1000px wide for posts, 300px for avatars.'),
            ("What is the max image size?", 'After compression — up to ~800 KB in base64. Very large originals will be compressed with quality loss.'),
            ("How do I view a photo full-size?", 'Click the image — a viewer opens. Close with Esc or click outside the photo.'),
        ]),
        ("🔒", "Security & Privacy", [
            ("How are passwords stored?", 'Only as a bcrypt hash. The original is never stored and cannot be recovered.'),
            ("Who sees my data?", 'Publicly visible: name, nickname, description, avatar, records. Password, CSRF token and service cookies — no.'),
            ("What is a CSRF token?", 'A hidden token protecting forms from request forgery. Without it, the action will not run.'),
            ("What is the 'CSRF Error'?", 'The cookie expired or was cleared. Refresh the page — a new token is issued.'),
            ("How are sessions protected?", 'HttpOnly cookies, SameSite=Lax, Secure on HTTPS. Plus CSP, X-Frame-Options, HSTS headers.'),
            ("What is the privacy policy?", 'A document describing what data we collect and how we use it. Full text — at /privacy.'),
        ]),
        ("🐞", "Problems & Support", [
            ("How do I report a bug?", 'Open /bugreport and describe the issue. Your reports are listed there with status: Accepted, In Progress, Fixed, Rejected.'),
            ("Login doesn\'t work — what to check?", '1) Nickname exactly as at registration. 2) Password at least 8 chars. 3) "I am not a robot" ticked. 4) No rate limit block.'),
            ("Why don\'t I receive emails?", 'We do not send emails — all contact via the bug-report form or footer addresses.'),
            ("Who do I contact?", 'Admin email: sldshr.confirmation@gmail.com, sldshr.confirm@yandex.ru. We reply within 1–2 days.'),
            ("What is 'uptime' in stats?", 'Time since server start. If the server restarts, the counter starts over.'),
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
        "toast_rejected_removed": "Отклонено и удалено!", "toast_failed": "Ошибка:", "toast_csrf": "Ошибка CSRF",
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
        "faq_intro": "Здесь собраны ответы на частые вопросы о Solid Link. Если не нашли ответ — напишите администрации по контактам ниже."
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
        "toast_rejected_removed": "Rejected & removed!", "toast_failed": "Error:", "toast_csrf": "CSRF error",
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
        "faq_intro": "Here are answers to frequently asked questions about Solid Link. If you couldn't find an answer — contact the administration below."
    }
}

def t(k, l="ru"): return LOCALES.get(l, LOCALES["ru"]).get(k, k)

def format_date(iso):
    if not iso: return ""
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except: return iso[:10]

SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""
SVG_UPLOAD = """<svg xmlns='http://www.w3.org/2000/svg' width='36' height='36' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'></path><polyline points='17 8 12 3 7 8'></polyline><line x1='12' y1='3' x2='12' y2='15'></line></svg>"""
SVG_CAMERA = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z'></path><circle cx='12' cy='13' r='4'></circle></svg>"""

_CSS_CACHE = None
def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        _CSS_CACHE = """
        <style>
            @font-face {
                font-family: 'RuFont';
                src: url('/static/ru_font.ttf') format('truetype');
                font-weight: 300 700;
                font-display: swap;
            }
            @import url('https://fonts.googleapis.com/css2?family=Titillium+Web:wght@300;400;600;700&display=swap');
            * { box-sizing: border-box; }
            html, body { margin: 0; padding: 0; }
            body {
                font-family: 'RuFont', 'Titillium Web', Arial, sans-serif;
                background-color: #f4f4f4;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }
            .page-content {
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 20px;
                width: 100%;
            }
            a { color: black; text-decoration: none; font-weight: bold; }
            a:hover { text-decoration: underline; }
            .container { background: white; padding: 30px; border: 10px solid #e0e0e0; display: flex; gap: 40px; align-items: flex-start; max-width: 100%; }
            .footer { text-align: center; font-size: 16px; font-weight: bold; color: #555; width: 100%; padding: 20px; display: flex; flex-direction: column; gap: 5px; }
            .footer a { color: #000; border-bottom: 2px solid #000; }
            .footer-links { font-size: 14px; color: #777; }
            .footer-links a { color: #555; border-bottom: 1px solid #555; font-weight: normal; }
            .footer-contacts { font-size: 13px; color: #666; font-weight: normal; }
            .footer-contacts a { color: #2a5db0; }
            .footer-badge { margin-top: 10px; display: flex; justify-content: center; }
            .footer-badge a { border: none; }
            .footer-badge img { display: block; border: 0; }
            .auth-wrapper { display: flex; gap: 20px; flex-direction: column; width: 340px; }
            .auth-wrapper-inner { display: flex; gap: 20px; align-items: flex-end; width: 100%;}
            .form-box { background-color: black; padding: 5px; display: flex; flex-direction: column; gap: 5px; border: 2px solid #ccc; width: 100%;}
            .form-box form { display: flex; flex-direction: column; gap: 5px; margin: 0; width: 100%;}
            .input-group { position: relative; display: flex; align-items: center; width: 100%; }
            input[type="text"], input[type="password"], textarea, select { background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px; font-family: 'RuFont', 'Titillium Web', Arial, sans-serif; width: 100%; text-align: center; outline: none; }
            textarea { text-align: left; resize: vertical; }
            .file-label { display: flex; align-items: center; justify-content: center; gap: 8px; background: #a9a9a9; padding: 12px; cursor: pointer; font-weight: bold; font-size: 18px; color: black; user-select: none; }
            .file-label:hover { background: #8c8c8c; }
            button, .btn { background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px; font-family: 'RuFont', 'Titillium Web', Arial, sans-serif; width: 100%; text-align: center; cursor: pointer; color: black; font-weight: bold; display: inline-block; border: 1px solid transparent; }
            button:hover, .btn:hover { background-color: #8c8c8c; }
            button:disabled { opacity: 0.6; cursor: wait; }
            .eye-btn { position: absolute; right: 5px; background: transparent; border: none; cursor: pointer; width: 40px; padding: 5px; display: flex; align-items: center; justify-content: center; }
            .label-text { font-size: 32px; font-weight: normal; margin-bottom: 10px; white-space: nowrap; }
            .captcha-container { background-color: #a9a9a9; padding: 10px; display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; cursor: pointer; font-size: 16px; font-weight: bold; text-align: center;}
            .captcha-container input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; flex-shrink: 0;}
            .privacy-link { color: #0000ff; text-decoration: underline; margin-left: 5px;}
            .dashboard-container { display: flex; gap: 20px; width: 100%; max-width: 1200px; margin: 0 auto; align-items: flex-start; }
            .sidebar { background: black; padding: 10px; width: 350px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; }
            .sidebar h2 { color: white; text-align: center; font-size: 24px; margin: 10px 0; }
            .info-card { background: #a9a9a9; padding: 15px; font-size: 18px; text-align: center; word-wrap: break-word; white-space: pre-wrap; }
            .avatar { width: 120px; height: 120px; border-radius: 8px; object-fit: cover; display: block; margin: 0 auto 10px auto; border: 3px solid #a9a9a9; background: #333; cursor: zoom-in; }
            .avatar-upload {
                position: relative; width: 120px; height: 120px; margin: 0 auto 12px auto;
                border-radius: 8px; overflow: hidden; cursor: pointer; background: #333;
                border: 3px solid #a9a9a9; display: block;
            }
            .avatar-upload .avatar-img { width: 100%; height: 100%; object-fit: cover; display: block; }
            .avatar-upload-icon {
                position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
                background: rgba(0,0,0,0.55); opacity: 0; transition: opacity 0.2s;
                pointer-events: none;
            }
            .avatar-upload:hover .avatar-upload-icon { opacity: 1; }
            .logout-btn { margin-top: 10px; background: #ff4d4d; }
            .logout-btn:hover { background: #cc0000; }
            .edit-btn { background: #4da6ff; margin-top: 5px; color: white;}
            .edit-btn:hover { background: #1a82e2; }
            .sugges-btn { background: #9b59b6; color: white; margin-top: 5px; position: relative; }
            .sugges-btn:hover { background: #8e44ad; }
            .badge { background: #ff4d4d; color: white; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin-left: 6px; font-weight: bold; }
            .main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
            .create-post-box { background: black; padding: 10px; display: flex; flex-direction: column; gap: 10px; border-radius: 5px; }
            .create-post-box form { display: flex; flex-direction: column; gap: 8px; }
            .create-post-box textarea { height: 120px; font-size: 16px; padding: 10px; border-radius: 3px; }
            .post-buttons-row { display: flex; gap: 8px; align-items: stretch; }
            .post-buttons-row > .file-label,
            .post-buttons-row > button { flex: 1; margin: 0; min-width: 0; }
            .img-preview { max-width: 100%; max-height: 200px; border-radius: 5px; display: block; margin: 0 auto; cursor: zoom-in;}
            .post-item { background: #a9a9a9; padding: 0; overflow: hidden; border-left: 5px solid transparent; display: flex; flex-direction: column; border-radius: 3px; }
            .post-item.pinned { border-left: 5px solid #ff4d4d; background: #d9d9d9; }
            .post-content { padding: 15px 15px 0; margin-bottom: 10px; font-size: 18px; text-align: center; word-break: break-word; white-space: pre-wrap; }
            .post-content a.ext-link { color: #0000ff; text-decoration: underline; word-break: break-all; }
            .post-image { width: 100%; max-height: 500px; object-fit: cover; display: block; margin: 10px 0 0; cursor: zoom-in; }
            .post-footer { padding: 10px 15px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #888; flex-wrap: wrap; gap: 10px; }
            .post-date { font-size: 12px; color: #555; margin-left: auto; }
            .post-suggested { font-size: 13px; color: #1e8449; font-weight: bold; }
            .posts-area { background: black; padding: 10px; border-radius: 5px; display: flex; flex-direction: column; gap: 10px; min-height: 300px;}
            .posts-area h2 { color: white; font-size: 24px; margin: 0 0 10px 0; text-align: center;}
            .post-wrapper { position: relative; transition: opacity 0.3s ease; }
            .post-actions { position: absolute; top: 5px; right: 5px; display: flex; gap: 5px; opacity: 0; transition: opacity 0.2s; z-index: 10; }
            .post-wrapper:hover .post-actions { opacity: 1; }
            .action-btn { background: black; color: white; border: none; padding: 5px 10px; font-size: 12px; cursor: pointer; border-radius: 3px; width: auto; font-weight: normal; font-family: 'RuFont', 'Titillium Web', Arial, sans-serif;}
            .action-btn:hover { background: #ff4d4d; }
            .action-btn.pin-btn:hover { background: #4da6ff; }
            .action-btn.link-btn:hover { background: #f1c40f; color: black; }
            .suggestion-card { background: #a9a9a9; padding: 15px; border-radius: 5px; border-left: 5px solid #9b59b6; margin-bottom: 10px; }
            .sugg-author { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #888; flex-wrap: wrap;}
            .sugg-name { font-weight: bold; color: #333; font-size: 14px; }
            .sugg-date { font-size: 12px; color: #666; }
            .sugg-content { font-size: 16px; margin-bottom: 10px; text-align: center; white-space: pre-wrap; word-break: break-word;}
            .sugg-actions { display: flex; gap: 10px; }
            .sugg-approve { background: #2ecc71; color: white; padding: 8px; }
            .sugg-approve:hover { background: #27ae60; }
            .sugg-reject { background: #e74c3c; color: white; padding: 8px; }
            .sugg-reject:hover { background: #c0392b; }
            .rules-box { background: #fff9e6; border-left: 5px solid #9b59b6; padding: 15px; border-radius: 5px; margin-bottom: 15px; color: #000; }
            .rules-box b { display: block; margin-bottom: 8px; font-size: 15px; }
            .rules-content { font-size: 14px; white-space: pre-wrap; line-height: 1.4; }
            .toggle-row { background: #a9a9a9; padding: 12px; border-radius: 3px; display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 15px; font-weight: bold; cursor: pointer; }
            .toggle-row input[type="checkbox"] { width: 24px; height: 24px; cursor: pointer; }
            .status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; color: white; margin-left: 10px;}
            .status-Принято, .status-Accepted { background: #4da6ff; }
            .status-В-работе, .status-In-Progress { background: #f1c40f; }
            .status-Исправлено, .status-Fixed { background: #2ecc71; }
            .status-Отклонено, .status-Rejected { background: #e74c3c; }
            .lang-switch { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
            .lang-btn { background: transparent; border: 2px solid #a9a9a9; color: #a9a9a9; padding: 8px 15px; width: auto; font-size: 16px; font-weight: bold; cursor: pointer; transition: all 0.2s; font-family: 'RuFont', 'Titillium Web', Arial, sans-serif;}
            .lang-btn:hover { background: #a9a9a9; color: black; }
            .lang-btn.active { background: #4da6ff; border-color: #4da6ff; color: white; }
            .login-lang-wrapper { display: flex; justify-content: flex-end; width: 100%; margin-top: 5px; }
            .privacy-content { background: white; color: black; padding: 20px; font-size: 18px; line-height: 1.5; text-align: left; word-wrap: break-word; border-radius: 3px;}
            .privacy-content code { background: #eee; padding: 2px 6px; border-radius: 3px; font-family: monospace; font-size: 15px; }
            .error-msg { color: #ff4d4d; font-weight: bold; font-size: 18px; text-align: right; width: 100%; margin-top: 10px; min-height: 20px; }
            #toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #333; color: white; padding: 12px 24px; border-radius: 5px; opacity: 0; transition: opacity 0.3s; z-index: 9999; font-weight: bold; pointer-events: none; text-align: center; max-width: 90%; }
            #toast.show { opacity: 1; }
            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; justify-content: center; align-items: center; padding: 15px; }
            .modal-overlay.show { display: flex; }
            .modal-box { background: white; padding: 30px; border-radius: 5px; max-width: 400px; width: 100%; text-align: center; border: 5px solid #000; }
            .modal-actions { display: flex; gap: 10px; margin-top: 20px; }
            .btn-danger { background: #ff4d4d; color: white; }
            .btn-danger:hover { background: #cc0000; }
            .og-box { margin: 15px 0; padding: 10px; background: #f9f9f9; border-radius: 5px; border: 1px solid #ddd; text-align: left; overflow: hidden;}
            .og-img { max-width: 100%; max-height: 200px; border-radius: 5px; margin-bottom: 10px; object-fit: cover; }
            .og-title { margin: 0 0 5px 0; font-size: 16px; color: #000; font-weight: bold; word-break: break-word;}
            .og-desc { margin: 0; font-size: 14px; color: #555; word-break: break-word;}
            #img-viewer { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); backdrop-filter: blur(8px); z-index: 20000; display: none; justify-content: center; align-items: center; cursor: zoom-out; padding: 15px; animation: fadeIn 0.2s; }
            #img-viewer.show { display: flex; }
            #img-viewer-img { max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 8px; box-shadow: 0 0 40px rgba(0,0,0,0.8); }
            .img-viewer-close { position: absolute; top: 20px; right: 20px; background: rgba(255,255,255,0.2); color: #fff; border: none; width: 48px; height: 48px; border-radius: 50%; font-size: 28px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; }
            .img-viewer-close:hover { background: rgba(255,255,255,0.5); }
            @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
            .stats-card { background: #a9a9a9; padding: 15px; border-radius: 5px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;}
            .stats-card b { font-size: 17px; }
            .stats-value { font-weight: bold; color: #1e8449; font-size: 22px; }
            .contacts-box { background: #222; color: white; padding: 18px; border-radius: 5px; margin-top: 20px; line-height: 1.8;}
            .contacts-box b { display: block; margin-bottom: 8px; font-size: 16px;}
            .contacts-box a { color: #4da6ff; }
            .faq-intro { background: #222; padding: 20px; border-radius: 8px; margin-bottom: 25px; color: #ddd; font-size: 16px; line-height: 1.6; border: 1px solid #333; }
            .faq-section { background: #1a1a1a; padding: 25px; border-radius: 8px; margin-bottom: 20px; border-left: 6px solid #4da6ff; }
            .faq-section h3 { color: #fff; margin: 0 0 18px 0; font-size: 24px; border-bottom: 2px solid #333; padding-bottom: 12px; }
            .faq-item { background: #2a2a2a; padding: 15px 18px; border-radius: 5px; margin-bottom: 10px; border-left: 3px solid #9b59b6; }
            .faq-q { font-weight: bold; font-size: 17px; margin-bottom: 8px; color: #4da6ff; }
            .faq-a { font-size: 15px; color: #ddd; line-height: 1.6; }
            .faq-a a { color: #4da6ff; text-decoration: underline; }
            .faq-a code { background: #444; padding: 2px 6px; border-radius: 3px; font-family: monospace; color: #ff9; font-size: 14px; }
            @media (max-width: 768px) {
                .page-content { padding: 8px; }
                .container { flex-direction: column; padding: 15px; gap: 20px; border-width: 5px; width: 100%; }
                .auth-wrapper { width: 100%; }
                .auth-wrapper-inner { flex-direction: column; gap: 10px; width: 100%; align-items: stretch;}
                .label-text { font-size: 24px; text-align: center; margin: 10px 0 0 0; order: -1; }
                .dashboard-container { flex-direction: column; gap: 15px; }
                .sidebar { width: 100%; }
                .main-content { width: 100%; }
                .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
                .error-msg { text-align: center; }
                .login-lang-wrapper { justify-content: center; }
                .create-post-box { padding: 10px; }
                .post-item { padding: 0; }
                .post-content { padding: 10px 10px 0; font-size: 16px; }
                .post-footer { padding: 10px; flex-direction: column; align-items: flex-start; gap: 5px; }
                .post-date { margin-left: 0; }
                input[type="text"], input[type="password"], textarea, select { font-size: 16px; padding: 12px; }
                button, .btn, .file-label { font-size: 16px; padding: 14px; }
                .post-content { font-size: 16px; }
                .sidebar h2 { font-size: 20px; }
                .avatar, .avatar-upload { width: 100px; height: 100px; }
                .avatar-upload-icon { opacity: 1; background: rgba(0,0,0,0.35); }
                .post-image { max-height: 400px; }
                .sugg-actions { flex-direction: column; }
                .action-btn { padding: 8px 12px; font-size: 13px; }
                .modal-box { padding: 20px; }
                .stats-card { font-size: 15px;}
                .stats-value { font-size: 18px;}
                .footer-badge img { width: 160px; height: 36px; }
                .faq-section { padding: 18px; }
                .faq-section h3 { font-size: 20px; }
                .faq-q { font-size: 15px; }
                .faq-a { font-size: 14px; }
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
            const opts = { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' };
            document.querySelectorAll('[data-iso]').forEach(el => {
                const iso = el.getAttribute('data-iso');
                if (!iso) return;
                try { const d = new Date(iso); if (isNaN(d.getTime())) return; el.textContent = d.toLocaleString(undefined, opts); } catch(e) {}
            });
        }
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', formatLocalDates);
        else formatLocalDates();
        function viewImage(src) { if (!src) return; document.getElementById('img-viewer-img').src = src; document.getElementById('img-viewer').classList.add('show'); document.body.style.overflow = 'hidden'; }
        function closeImgViewer() { document.getElementById('img-viewer').classList.remove('show'); document.body.style.overflow = ''; }
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeImgViewer(); });
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
            const file = input.files[0]; const preview = document.getElementById('post-img-preview'); const btn = document.getElementById('create-post-btn');
            if (!file) { window.postImageCache = ""; if(preview) preview.style.display='none'; return; }
            showToast(L.ic); if(btn) btn.disabled = true;
            try { const b64 = await compressImage(file, 1000, 0.75); window.postImageCache = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); } showToast(L.ir); }
            catch (e) { window.postImageCache = ""; showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; if(preview) preview.style.display='none'; }
            finally { if(btn) btn.disabled = false; }
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
            try { const b64 = await compressImage(file, 300, 0.8); hidden.value = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; } showToast(L.ir); }
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
        function showToast(msg) { const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3000); }
        function showConfirm(msg, cb) { const m = document.getElementById('modal-overlay'); document.getElementById('modal-text').textContent = msg; m.classList.add('show'); const cBtn = document.getElementById('modal-confirm'); const xBtn = document.getElementById('modal-cancel'); const nC = cBtn.cloneNode(true); const nX = xBtn.cloneNode(true); cBtn.parentNode.replaceChild(nC, cBtn); xBtn.parentNode.replaceChild(nX, xBtn); nC.onclick = () => { m.classList.remove('show'); cb(true); }; nX.onclick = () => { m.classList.remove('show'); cb(false); }; }
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
        async function hc(e) {
            e.preventDefault();
            const f = e.target, c = f.querySelector('textarea').value.trim();
            if (!c) return;
            if (c.length > 5000) { showToast(L.ptl); return; }
            const i = crypto.randomUUID(), n = new Date();
            const d = n.toLocaleString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
            const iso = n.toISOString();
            const img = window.postImageCache || "";
            const a = document.querySelector('#my-records-container');
            const m = a.querySelector('.empty-state'); if (m) m.remove();
            const w = document.createElement('div'); w.className = 'post-wrapper'; w.id = 'post-' + i;
            const acts = document.createElement('div'); acts.className = 'post-actions';
            const linkBtn = document.createElement('button'); linkBtn.className = 'action-btn link-btn'; linkBtn.textContent = L.cl; linkBtn.dataset.user = ME; linkBtn.dataset.rid = i;
            linkBtn.addEventListener('click', function() { copyLink(this); });
            const pinBtn = document.createElement('button'); pinBtn.className = 'action-btn pin-btn'; pinBtn.textContent = L.p;
            pinBtn.addEventListener('click', function() { hp(i, this); });
            const delBtn = document.createElement('button'); delBtn.className = 'action-btn'; delBtn.textContent = L.d;
            delBtn.addEventListener('click', function() { hd(i); });
            acts.append(linkBtn, pinBtn, delBtn);
            const item = document.createElement('div'); item.className = 'post-item';
            const contentEl = document.createElement('div'); contentEl.className = 'post-content'; contentEl.textContent = c;
            item.appendChild(contentEl);
            if (img) { const imgEl = document.createElement('img'); imgEl.className = 'post-image'; imgEl.src = img; imgEl.onclick = function() { viewImage(this.src); }; item.appendChild(imgEl); }
            const footer = document.createElement('div'); footer.className = 'post-footer';
            const dateEl = document.createElement('div'); dateEl.className = 'post-date'; dateEl.dataset.iso = iso; dateEl.textContent = d;
            footer.appendChild(dateEl); item.appendChild(footer);
            w.appendChild(acts); w.appendChild(item);
            let inserted = false; const wrappers = a.querySelectorAll('.post-wrapper');
            for (let ww of wrappers) { if (!ww.querySelector('.pinned')) { a.insertBefore(w, ww); inserted = true; break; } }
            if (!inserted) a.appendChild(w);
            f.reset(); window.postImageCache = ""; const preview = document.getElementById('post-img-preview'); if (preview) preview.style.display = 'none';
            try { await rpc('create_record', { content: c, client_id: i, image_data: img }); } catch (x) { w.remove(); showToast(L.tf + ' ' + x.message); }
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
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay"><div class="modal-box"><p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p><div class="modal-actions"><button id="modal-cancel" class="btn" style="background:#aaa;color:black;">__CANCEL__</button><button id="modal-confirm" class="btn btn-danger">OK</button></div></div></div>
    <div id="link-modal" class="modal-overlay"><div class="modal-box" style="text-align: left;"><h3 style="margin-top:0;">__EXT_TITLE__</h3><p style="font-size:14px; color:#555; margin-bottom:10px;">__EXT_DESC__</p><div id="og-preview" class="og-box"><p style="margin:0; font-size:14px; color:#666;">__EXT_LOADING__</p></div><div class="modal-actions"><button onclick="closeLinkModal()" class="btn" style="background:#aaa;color:black;">__CANCEL__</button><a id="link-modal-confirm" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-danger" style="text-decoration: none; display: flex; align-items: center; justify-content: center;">__EXT_CONTINUE__</a></div></div></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()"><button class="img-viewer-close" onclick="closeImgViewer()">&times;</button><img id="img-viewer-img" src="" alt=""></div>
    """
    for k, v in [("__CANCEL__", t('cancel',lang)),("__EXT_TITLE__", t('ext_title',lang)),("__EXT_DESC__", t('ext_desc',lang)),("__EXT_LOADING__", t('ext_loading',lang)),("__EXT_CONTINUE__", t('ext_continue',lang))]:
        s = s.replace(k, v)
    return s

def get_footer(lang):
    contacts = " | ".join(f"<a href='mailto:{e}'>{e}</a>" for e in CONTACT_EMAILS)
    current_path = _current_path.get() or "/"
    current_url = SITE_URL + current_path
    badge_url = DESTROY_BASE + quote(current_url, safe='')
    s = """
    <div class="footer">
        <div>__CREATED_BY__ <a href="http://solid-link.ddns.net" target="_blank" rel="noopener noreferrer">Solid Link</a> | __HOSTING__ <a href="https://fastapicloud.com" target="_blank" rel="noopener noreferrer">FastAPICloud</a></div>
        <div class="footer-links">
            <a href="/docs">__FAQ_LINK__</a> | <a href="/privacy">__PRIVACY_TITLE__</a> | <a href="/bugreport">__BUGREPORT_TITLE__</a> | <a href="/stats">__STATS_LINK__</a>
        </div>
        <div class="footer-contacts">__CONTACTS__</div>
        <div class="footer-badge">
            <a href="__BADGE_URL__" target="_blank" rel="noopener noreferrer">
                <img src="https://destroy.spritefusion.com/badge.svg" alt="Destroy this website" width="180" height="40" />
            </a>
        </div>
        <div style="font-size: 12px; color: #999; margin-top: 5px;">v__APP_VERSION__ (__SERVER_START_DATE__)</div>
    </div>
    """
    for k, v in [("__CREATED_BY__",t('created_by',lang)),("__HOSTING__",t('hosting',lang)),("__FAQ_LINK__",t('faq_link',lang)),("__PRIVACY_TITLE__",t('privacy_title',lang)),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__STATS_LINK__",t('stats_link',lang)),("__CONTACTS__",contacts),("__BADGE_URL__",badge_url),("__APP_VERSION__",APP_VERSION),("__SERVER_START_DATE__",SERVER_START_DATE)]:
        s = s.replace(k, v)
    return s

def auth_html(lang, error_msg="", token=""):
    eb = f"<div class='error-msg'>{esc(error_msg)}</div>" if error_msg else "<div class='error-msg'></div>"
    og_title = "Solid Link — Вход / Регистрация" if lang == "ru" else "Solid Link — Login / Registration"
    og_desc = "Solid Link — простая социальная платформа с записями и предложкой" if lang == "ru" else "Solid Link — simple social platform with records and suggestions"
    og = og_tags(og_title, og_desc, "/", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__LOGIN__ / __REG__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="container">
        <div class="auth-wrapper"><div class="label-text">__REG__</div><div class="form-box"><form action="/register" method="post">
            <input type="hidden" name="csrf_token" value="__TOKEN__">
            <input type="text" name="username" placeholder="__USERNAME__" required maxlength="60">
            <input type="text" name="nickname" placeholder="__NICKNAME__" required maxlength="30" pattern="[a-zA-Z0-9_\\-]{3,30}" title="3-30: a-z 0-9 _ -">
            <div class="input-group"><input type="password" name="password" id="rp" placeholder="__PASSWORD__" required minlength="8"><button type="button" class="eye-btn" onclick="tp('rp',this)">__SVG_EYE__</button></div>
            <div class="input-group"><input type="password" name="re_pass" id="rr" placeholder="__REPASS__" required minlength="8"><button type="button" class="eye-btn" onclick="tp('rr',this)">__SVG_EYE__</button></div>
            <label class="captcha-container"><input type="checkbox" name="captcha" required> __CAPTCHA__</label>
            <label class="captcha-container" style="background:#8c8c8c;margin-top:2px"><input type="checkbox" name="privacy" required><span>__PRIVACY_AGREE__ <a href="/privacy" target="_blank" rel="noopener noreferrer" class="privacy-link">__PRIVACY_LINK__</a></span></label>
            <button type="submit">__REG_BTN__</button>
        </form></div></div>
        <div class="auth-wrapper"><div class="auth-wrapper-inner"><div class="form-box"><form action="/login" method="post">
            <input type="hidden" name="csrf_token" value="__TOKEN__">
            <input type="text" name="nickname" placeholder="__NICKNAME__" required>
            <div class="input-group"><input type="password" name="password" id="lp" placeholder="__PASSWORD__" required><button type="button" class="eye-btn" onclick="tp('lp',this)">__SVG_EYE__</button></div>
            <label class="captcha-container"><input type="checkbox" name="captcha" required> __CAPTCHA__</label>
            <button type="submit">__LOGIN_BTN__</button>
        </form></div><div class="label-text">__LOGIN__</div></div>
        <div class="login-lang-wrapper"><div class="lang-switch"><a href="/set_lang/ru?next=/" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/" class="btn lang-btn __EN_ACTIVE__">EN</a></div></div>
        __ERROR__</div>
    </div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__LOGIN__",t('login',lang)),("__REG__",t('reg',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",t('username',lang)),("__NICKNAME__",t('nickname',lang)),("__PASSWORD__",t('password',lang)),("__REPASS__",t('re_pass',lang)),("__CAPTCHA__",t('captcha',lang)),("__PRIVACY_AGREE__",t('privacy_agree',lang)),("__PRIVACY_LINK__",t('privacy_link',lang)),("__REG_BTN__",t('register_btn',lang)),("__LOGIN_BTN__",t('login_btn',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__ERROR__",eb),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang)),("__SVG_EYE__",SVG_EYE)]:
        s = s.replace(k, v)
    return s

def render_records(records, lang, own=False, uid=None):
    if not records or not isinstance(records, list): return f"<div class='post-item empty-state'>{t('no_posts', lang)}</div>"
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
        pc = "pinned" if pinned else ""
        acts = "<div class='post-actions'>"
        if uid: acts += f"<button class='action-btn link-btn' data-user='{safe_nick}' data-rid='{rid}' onclick='copyLink(this)'>{t('copy_link', lang)}</button>"
        if own:
            acts += f"<button onclick='hp(\"{rid}\",this)' class='action-btn pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button>"
            acts += f"<button onclick='hd(\"{rid}\",this)' class='action-btn'>{t('delete', lang)}</button>"
        acts += "</div>"
        sugg_html = f"<div class='post-suggested'>{t('suggested_by', lang)} {sugg_by}</div>" if sugg_by else ""
        img_html = f'<img class="post-image" src="{img}" alt="" onclick="viewImage(this.src)">' if img else ""
        out += f"<div class='post-wrapper' id='post-{rid}'>{acts}<div class='post-item {pc}'><div class='post-content'>{content}</div>{img_html}<div class='post-footer'>{sugg_html}<div class='post-date' data-iso='{iso}'>{date}</div></div></div></div>"
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

def dashboard_html(nickname, user, my_p, lang, token, viewer, sugg_count=0):
    rh_my = render_records(my_p, lang, own=True, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar" onclick="viewImage(this.src)">' if avatar else ""
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    badge = f'<span class="badge">{sugg_count}</span>' if sugg_count else ''
    safe_nick_url = quote(nickname, safe='')
    og_title = f"Личный кабинет — {nickname}" if lang == "ru" else f"Personal cabinet — {nickname}"
    og_desc = desc or ("Solid Link — личный кабинет" if lang == "ru" else "Solid Link — personal cabinet")
    og = og_tags(og_title, og_desc, "/cabinet", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__CABINET__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar">
        <h2>__CABINET__</h2>
        __AVATAR__
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br><a href="/__NICK_URL__" target="_blank" rel="noopener noreferrer">__NICKNAME__ __LINK_PROFILE__</a></div>__DB__
        <div class="info-card"><b>__TOTAL_POSTS__:</b><br>__POST_COUNT__</div>
        <a href="/cabinet/edit" class="btn edit-btn">__EDIT_PROFILE__</a>
        <a href="/cabinet/suggestions" class="btn sugges-btn">__SUGGESTIONS_TITLE____BADGE__</a>
        <form action="/logout" method="get" style="margin: 0; width: 100%;"><button type="submit" class="logout-btn">__LOGOUT__</button></form>
        <div class="lang-switch"><a href="/set_lang/ru?next=/cabinet" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div>
    <div class="main-content">
        <div class="create-post-box"><form id="create-form" onsubmit="hc(event)">
            <textarea name="content" placeholder="__CREATE_POST_PLACEHOLDER__" required maxlength="5000"></textarea>
            <img id="post-img-preview" class="img-preview" style="display:none;">
            <div class="post-buttons-row">
                <label class="file-label" for="post-file-input">__SVG_CAMERA__ __ATTACH_PHOTO__</label>
                <input type="file" id="post-file-input" accept="image/*" onchange="handlePostImage(this)" style="display:none;">
                <button type="submit" id="create-post-btn">__CREATE_POST_BTN__</button>
            </div>
        </form></div>
        <div class="posts-area" id="my-records-container"><h2>__MY_POSTS__</h2>__RECORDS_HTML__</div>
    </div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__CABINET__",t('cabinet',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__NICK_URL__",safe_nick_url),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__LINK_PROFILE__",t('link_profile',lang)),("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(my_p))),("__EDIT_PROFILE__",t('edit_profile',lang)),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__BADGE__",badge),("__LOGOUT__",t('logout',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__CREATE_POST_PLACEHOLDER__",t('create_post_placeholder',lang)),("__ATTACH_PHOTO__",t('attach_photo',lang)),("__SVG_CAMERA__",SVG_CAMERA),("__CREATE_POST_BTN__",t('create_post_btn',lang)),("__MY_POSTS__",t('my_posts',lang)),("__RECORDS_HTML__",rh_my),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def suggestions_page_html(nickname, suggestions, lang, token):
    if not suggestions:
        rh = f"<div class='post-item'>{t('sugges_empty', lang)}</div>"
    else:
        rh = ""
        for sg in suggestions:
            sid = esc(sg.get('id'))
            sugg_by = esc(sg.get('suggested_by_name'))
            content = linkify(sg.get('content'))
            date = format_date(esc(sg.get('created_at')))
            iso = esc(sg.get('created_at', ''))
            img = sanitize_url(sg.get('image_data', ''))
            img_html = f'<img class="post-image" src="{img}" alt="" onclick="viewImage(this.src)">' if img else ""
            rh += f"<div class='suggestion-card' id='sugg-{sid}'><div class='sugg-author'><span class='sugg-name'>{sugg_by}</span><span class='sugg-date' data-iso='{iso}'>{date}</span></div><div class='sugg-content'>{content}</div>{img_html}<div class='sugg-actions' style='margin-top:10px;'><button class='btn sugg-approve' onclick=\"approveSugg('{sid}')\">{t('sugges_approve',lang)}</button><button class='btn sugg-reject' onclick=\"rejectSugg('{sid}')\">{t('sugges_reject',lang)}</button></div></div>"
    og_title = t('suggestions_title', lang) + " — " + nickname
    og = og_tags(og_title, "Solid Link — suggestions", "/cabinet/suggestions", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__SUGGESTIONS_TITLE__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="posts-area" style="min-height:300px;padding:20px;"><h2>__SUGGESTIONS_TITLE__</h2>__SUGGESTIONS_HTML__</div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">__BACK__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/suggestions" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/suggestions" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__SUGGESTIONS_HTML__",rh),("__BACK__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def sugges_form_html(nickname, lang, token, error="", viewer="", rules="", enabled=True, photo_enabled=True):
    msg_html = f"<div class='error-msg' style='color:#ff4d4d;'>{esc(error)}</div>" if error else ""
    is_own = (viewer == nickname)
    if is_own: form_block = f"<div class='error-msg' style='color:#ff4d4d;'>{t('sugges_own', lang)}</div>"
    elif not enabled: form_block = f"<div class='error-msg' style='color:#ff4d4d;'>{t('sugges_disabled', lang)}</div>"
    else:
        safe_nick_attr = esc(nickname)
        photo_block = f"<label class='file-label' for='sugg-file-input'>{SVG_CAMERA} {t('attach_photo', lang)}</label><input type='file' id='sugg-file-input' accept='image/*' onchange='handleSuggImage(this)' style='display:none;'><img id='sugg-img-preview' class='img-preview' style='display:none;'>" if photo_enabled else ""
        form_block = f"<form data-nickname='{safe_nick_attr}' onsubmit='submitSuggestion(event)' style='display:flex;flex-direction:column;gap:10px'><input type='text' name='sugg_name' placeholder='{t('sugges_name',lang)}' required maxlength='60' style='background:#a9a9a9;padding:12px;font-size:16px;'><textarea name='content' placeholder='{t('sugges_content',lang)}' required maxlength='500' style='background:#a9a9a9;height:150px;padding:12px;font-size:16px;'></textarea>{photo_block}<button type='submit' id='sugg-submit-btn' style='background:#2ecc71;color:white;font-size:18px;'>{t('sugges_send',lang)}</button></form>"
    rules_block = f"<div class='rules-box'><b>{t('rules_title',lang)}</b><div class='rules-content'>{esc(rules)}</div></div>" if rules else ""
    og_title = f"Предложить пост для {nickname}" if lang == "ru" else f"Suggest a post for {nickname}"
    og = og_tags(og_title, "Solid Link — suggestions", f"/{quote(nickname, safe='')}/sugges", lang=lang)
    safe_nick_url = quote(nickname, safe='')
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__TITLE__ __NICKNAME__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px">
        <div class="posts-area" style="padding:20px;">
            <h2>__TITLE__ __NICKNAME__</h2>
            __RULES_BLOCK____MSG____FORM_BLOCK__
            <a href="/__NICK_URL__" class="btn" style="background:#a9a9a9;margin-top:15px;">__BACK__</a>
            <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/__NICK_URL__/sugges" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/__NICK_URL__/sugges" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
        </div>
    </div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('sugges_title',lang)),("__OG__",og),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__RULES_BLOCK__",rules_block),("__MSG__",msg_html),("__FORM_BLOCK__",form_block),("__BACK__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def edit_html(nickname, user, lang, token):
    desc = esc(user.get('description'))
    rules = esc(user.get('sugges_rules', ''))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_display = "block" if avatar else "none"
    avatar_html = f'<label class="avatar-upload" for="avatar-file-input"><img id="avatar-preview" class="avatar-img" src="{avatar}" alt="avatar" style="display:{avatar_display}"><div class="avatar-upload-icon">{SVG_UPLOAD}</div></label>'
    user_username = esc(user.get('username'))
    sugges_checked = "checked" if user_sugges_enabled(user) else ""
    photo_checked = "checked" if user_sugges_photo_enabled(user) else ""
    og_title = "Редактировать профиль — Solid Link" if lang == "ru" else "Edit Profile — Solid Link"
    og = og_tags(og_title, desc or "", "/cabinet/edit", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__EDIT_PROFILE__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px"><div class="posts-area" style="padding:20px">
        <h2 style="color:#fff;text-align:center">__EDIT_PROFILE__</h2>
        <form action="/cabinet/edit" method="post" style="display:flex;flex-direction:column;gap:10px">
            <input type="hidden" name="csrf_token" value="__TOKEN__">
            <input type="hidden" name="avatar_data" id="avatar-data" value="">
            __AVATAR_HTML__
            <input type="file" id="avatar-file-input" accept="image/*" onchange="handleAvatarChange(this)" style="display:none;">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__USERNAME_LABEL__</div>
            <input type="text" name="username" value="__USERNAME__" required maxlength="60">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__DESCRIPTION__</div>
            <textarea name="description" maxlength="300" placeholder="__DESC_PLACEHOLDER__" oninput="uc(this)" style="background:#a9a9a9;height:120px;padding:12px;font-size:16px">__DESC__</textarea>
            <div id="char-count" style="color:#fff;text-align:right;font-size:14px">__DESC_LEN__ / 300</div>
            <label class="toggle-row"><span>__SUGGES_ENABLE_LABEL__</span><input type="checkbox" name="sugges_enabled" __SUGGES_CHECKED__></label>
            <label class="toggle-row"><span>__SUGGES_PHOTO_ENABLE_LABEL__</span><input type="checkbox" name="sugges_photo_enabled" __PHOTO_CHECKED__></label>
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__RULES_LABEL__</div>
            <textarea name="sugges_rules" maxlength="1000" placeholder="__RULES_PLACEHOLDER__" oninput="ucRules(this)" style="background:#a9a9a9;height:120px;padding:12px;font-size:16px">__RULES__</textarea>
            <div id="rules-count" style="color:#fff;text-align:right;font-size:14px">__RULES_LEN__ / 1000</div>
            <button type="submit" style="background:#4da6ff;color:#fff;margin-top:10px">__SAVE_CHANGES__</button>
            <a href="/cabinet" class="btn" style="background:#a9a9a9">__CANCEL__</a>
        </form>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/edit" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/edit" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__EDIT_PROFILE__",t('edit_profile',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__TOKEN__",token),("__AVATAR_HTML__",avatar_html),("__ATTACH_AVATAR__",t('attach_avatar',lang)),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__DESCRIPTION__",t('description',lang)),("__DESC_PLACEHOLDER__",t('desc_placeholder',lang)),("__DESC__",desc),("__DESC_LEN__",str(len(desc))),("__SUGGES_ENABLE_LABEL__",t('sugges_enable_label',lang)),("__SUGGES_CHECKED__",sugges_checked),("__SUGGES_PHOTO_ENABLE_LABEL__",t('sugges_photo_enable_label',lang)),("__PHOTO_CHECKED__",photo_checked),("__RULES_LABEL__",t('rules_edit_label',lang)),("__RULES_PLACEHOLDER__",t('rules_placeholder',lang)),("__RULES__",rules),("__RULES_LEN__",str(len(rules))),("__SAVE_CHANGES__",t('save_changes',lang)),("__CANCEL__",t('cancel',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    rh = render_records(records, lang, own=is_owner, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar" onclick="viewImage(this.src)">' if avatar else ""
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if is_owner or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    og_title = f"{nickname} — Solid Link"
    og_desc = desc or (f"Профиль {nickname}" if lang == "ru" else f"Profile {nickname}")
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PROFILE__ __NICKNAME__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar">
        <h2>__PROFILE__</h2>
        __AVATAR__
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br>__NICKNAME__</div>__DB__
        <div class="info-card"><b>__TOTAL_POSTS__:</b><br>__POST_COUNT__</div>
        __SUGG_BTN__
        <div class="lang-switch"><a href="/set_lang/ru?next=/__NICK_URL__" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/__NICK_URL__" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
        <a href="/" class="btn" style="margin-top:auto;background:#a9a9a9">__BACK_HOME__</a>
    </div><div class="main-content"><div class="posts-area" style="min-height:500px"><h2>__USER_POSTS__</h2>__RECORDS_HTML__</div></div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__PROFILE__",t('profile',lang)),("__OG__",og),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer or "")),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(records))),("__SUGG_BTN__",sugg_btn),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BACK_HOME__",t('back_home',lang)),("__USER_POSTS__",t('user_posts',lang)),("__RECORDS_HTML__",rh),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, uid=viewer)
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar" onclick="viewImage(this.src)">' if avatar else ""
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if (viewer == nickname) or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    raw_content = record.get('content', '') or ''
    snippet = strip_html(raw_content)[:150] + ('...' if len(raw_content) > 150 else '')
    og_title = f"Запись от {nickname} — Solid Link" if lang == "ru" else f"Record by {nickname} — Solid Link"
    og_desc = snippet or "Solid Link"
    img_data = sanitize_url(record.get('image_data', ''))
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}/{quote(str(record.get('id', '')), safe='')}", image=img_data, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__RECORD_PAGE__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar">
        <h2>__PROFILE__</h2>
        __AVATAR__
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br><a href="/__NICK_URL__">__NICKNAME__</a></div>
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        __SUGG_BTN__
        <a href="/__NICK_URL__" class="btn" style="margin-top:auto;background:#a9a9a9">__BACK_HOME__</a>
    </div><div class="main-content"><div class="posts-area"><h2>__RECORD_PAGE__</h2>__RECORDS_HTML__</div></div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__RECORD_PAGE__",t('record_page',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer or "")),("__PROFILE__",t('profile',lang)),("__AVATAR__",avatar_html),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",esc(user.get('username'))),("__SUGG_BTN__",sugg_btn),("__BACK_HOME__",t('back_home',lang)),("__RECORDS_HTML__",rh),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def bugreport_html(username, reports, lang, token):
    rh = "<div class='post-item'>Заявок пока нет...</div>" if not reports else ""
    for x in reports:
        date_str = format_date(esc(x.get('created_at')))
        iso_str = esc(x.get('created_at', ''))
        rh += f"<div class='post-item' style='border-left-color:transparent'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;'><b>{t('bugreport_title',lang)}</b><span class='status-badge status-{esc(x.get('status','Принято')).replace(' ','-')}'>{esc(x.get('status','Принято'))}</span></div><div class='post-content' style='text-align:left;'>{esc(x.get('content'))}</div><div class='post-date' data-iso='{iso_str}'>{date_str}</div></div>"
    og_title = "Баг-репорт — Solid Link" if lang == "ru" else "Bug Report — Solid Link"
    og = og_tags(og_title, "Solid Link", "/bugreport", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__BUGREPORT_TITLE__ — Solid Link</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="create-post-box"><h2 style="color:#fff;text-align:center;margin:10px 0">__BUGREPORT_TITLE__</h2>
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:5px">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <input type="text" name="name" value="__USERNAME__" placeholder="__BUGREPORT_NAME__" required maxlength="60" style="background:#a9a9a9;padding:12px;margin-bottom:5px">
                <textarea name="content" placeholder="__BUGREPORT_DESC__" required maxlength="5000" style="background:#a9a9a9;height:150px;padding:12px;margin-bottom:5px"></textarea>
                <button type="submit" style="background:#f1c40f;color:#000">__BUGREPORT_SEND__</button>
            </form>
        </div>
        <div class="posts-area"><h2>__BUGREPORT_MY__</h2>__REPORTS_HTML__</div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">__CANCEL__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/bugreport" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/bugreport" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",esc(username)),("__BUGREPORT_NAME__",t('bugreport_name',lang)),("__BUGREPORT_DESC__",t('bugreport_desc',lang)),("__BUGREPORT_SEND__",t('bugreport_send',lang)),("__BUGREPORT_MY__",t('bugreport_my',lang)),("__REPORTS_HTML__",rh),("__CANCEL__",t('cancel',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def privacy_html(lang, token):
    og_title = "Политика конфиденциальности — Solid Link" if lang == "ru" else "Privacy Policy — Solid Link"
    og_desc = "Политика конфиденциальности Solid Link" if lang == "ru" else "Solid Link Privacy Policy"
    og = og_tags(og_title, og_desc, "/privacy", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PRIVACY_TITLE__ — Solid Link</title>__OG__
    __CSS__</head><body>
    <div class="page-content">
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:800px"><div class="posts-area" style="padding:20px">
        <h2 style="color:#fff;text-align:center;margin-bottom:20px">__PRIVACY_TITLE__</h2>
        <div class="privacy-content">__PRIVACY_TEXT__</div>
        <a href="/" class="btn" style="background:#a9a9a9;margin-top:20px">__BACK_HOME__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/privacy" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/privacy" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div></div>
    </div>__FOOTER__</body></html>
    """
    for k, v in [("__LANG__",lang),("__PRIVACY_TITLE__",t('privacy_title',lang)),("__OG__",og),("__CSS__",get_css()),("__PRIVACY_TEXT__",t('privacy_text',lang)),("__BACK_HOME__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__FOOTER__",get_footer(lang))]:
        s = s.replace(k, v)
    return s

# ---------- Docsify / FAQ ----------

def faq_markdown(lang: str) -> str:
    sections = FAQ_DATA.get(lang, FAQ_DATA["ru"])
    lines = [f"# {t('faq_title', lang)}", "", t('faq_intro', lang), ""]
    for icon, title, items in sections:
        lines.append(f"## {icon} {title}")
        lines.append("")
        for q, a in items:
            lines.append(f"### {q}")
            lines.append("")
            lines.append(a)
            lines.append("")
    return "\n".join(lines)

def docs_html(lang: str, token: str) -> str:
    og_title = "FAQ — Solid Link"
    og_desc = "Часто задаваемые вопросы о Solid Link" if lang == "ru" else "Frequently asked questions about Solid Link"
    og = og_tags(og_title, og_desc, "/docs", lang=lang)
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>FAQ — Solid Link</title>
        {og}
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/docsify@4/themes/vue.css">
        <style>
            body {{ font-family: 'RuFont', 'Titillium Web', Arial, sans-serif; }}
            .sidebar {{ background: #f4f4f4; }}
            .sidebar-toggle {{ background: #4da6ff; }}
            .markdown-section {{ max-width: 900px; }}
        </style>
        <script>
            window.$docsify = {{
                name: 'Solid Link',
                repo: '',
                loadSidebar: false,
                subMaxLevel: 2,
                basePath: '/docs/',
                homepage: 'README.md',
                coverpage: false,
                onlyCover: false,
                auto2top: true,
                executeScript: false,
                noEmoji: false,
                mergeNavbar: true,
                formatUpdated: '{{YYYY}}/{{MM}}/{{DD}} {{HH}}:{{mm}}',
                search: {{
                    placeholder: 'Поиск...',
                    noData: 'Ничего не найдено'
                }}
            }};
        </script>
    </head>
    <body>
        <div id="app"></div>
        <script src="https://cdn.jsdelivr.net/npm/docsify@4"></script>
        <script src="https://cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
        <script>
            // Кнопка назад
            document.addEventListener('DOMContentLoaded', function() {{
                const backBtn = document.createElement('a');
                backBtn.href = '/';
                backBtn.textContent = '← На главную';
                backBtn.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#4da6ff;color:#fff;padding:10px 18px;border-radius:5px;text-decoration:none;font-weight:bold;z-index:9999;';
                document.body.appendChild(backBtn);
            }});
        </script>
    </body>
    </html>
    """

# ---------- ROUTES ----------
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
        x = await asyncio.to_thread(lambda: sb.table('users').select('password').eq('nickname', nickname).execute())
        user = x.data[0] if x.data else None
        if user and verify_password(password, user.get("password", "")):
            _login_clear(ip)
            if len(user["password"]) == 64:
                await asyncio.to_thread(lambda: sb.table('users').update({"password": hash_password(password)}).eq('nickname', nickname).execute())
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
    user_data, p_data, sc = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname), _fetch_suggestion_count(nickname))
    if user_data is DB_UNAVAILABLE:
        body = "<h2>Сервер временно недоступен. <a href='/cabinet'>Повторить</a></h2>" if lang == "ru" else "<h2>Server temporarily unavailable. <a href='/cabinet'>Retry</a></h2>"
        return HTMLResponse(body, status_code=503)
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(nickname, user_data, po, lang, token, nickname, sc))
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
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        elif req.method == "delete_record":
            rid = req.params.get("post_id")
            await asyncio.to_thread(lambda: sb.table('posts').delete().eq('id', rid).eq('user_nickname', nickname).execute())
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
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        elif req.method == "reject_suggestion":
            sid = req.params.get("suggestion_id")
            await asyncio.to_thread(lambda: sb.table('suggestions').delete().eq('id', sid).eq('author_nickname', nickname).execute())
            return {"status": "ok"}
        raise HTTPException(400, "Unknown method")
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/cabinet/edit", response_class=HTMLResponse)
async def edit(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(edit_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), sugges_enabled: str = Form(None), sugges_photo_enabled: str = Form(None), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if lang not in ("ru", "en"): lang = "ru"
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
    username = (username or "").strip()[:60]
    if not VALID_USER_RE.match(username):
        return HTMLResponse(f"<script>showToast('{t('err_user_format', lang)}');window.history.back()</script>")
    if len(description) > 300: return HTMLResponse(f"<script>showToast('{t('alert_desc_long', lang)}');window.history.back()</script>")
    if len(sugges_rules) > 1000: return HTMLResponse(f"<script>showToast('{t('rules_alert_long', lang)}');window.history.back()</script>")
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
async def bugreport(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
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
    set_csrf_cookie(res, token, r)
    if setlang in ("ru", "en"): _set_lang_cookie(res, r, lang)
    return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
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
        u, x = await asyncio.gather(
            asyncio.to_thread(lambda: sb.table('users').select('username,avatar_data,sugges_enabled,sugges_photo_enabled').eq('nickname', nickname).execute()),
            asyncio.to_thread(lambda: sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute())
        )
        if not u.data: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
        if not x.data: return HTMLResponse(f"<h2>{t('no_posts', lang)}</h2>", 404)
        u_data = u.data[0]; rec = x.data[0]
    except Exception:
        return HTMLResponse(f"<h2>DB Error</h2>", 500)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    res = HTMLResponse(record_page_html(nickname, u_data, rec, lang, token, viewer))
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
