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

APP_VERSION = "0.23"
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
    for sel in ('username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
                'username,description,sugges_rules,avatar_data,sugges_enabled',
                'username,description,sugges_rules,avatar_data',
                'username,description,sugges_rules',
                'username,description'):
        try:
            res = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nickname).execute())
            return res.data[0] if res.data else None
        except Exception:
            continue
    return DB_UNAVAILABLE

async def _fetch_posts(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').eq('user_nickname', nickname).execute())
        return res.data or []
    except Exception: return []

async def _fetch_feed(limit=30):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').order('created_at', desc=True).limit(limit).execute())
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
        {"name": "Solid", "short_name": "Solid", "start_url": "/",
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

SVG_ICONS = {
    "lock": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='11' width='18' height='11' rx='2' ry='2'/><path d='M7 11V7a5 5 0 0 1 10 0v4'/></svg>",
    "pencil": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 20h9'/><path d='M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z'/></svg>",
    "lightbulb": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 18h6'/><path d='M10 22h4'/><path d='M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14'/></svg>",
    "gear": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'/><path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'/></svg>",
    "image": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>",
    "shield": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/></svg>",
    "bug": "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#4da6ff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='8' y='6' width='8' height='14' rx='4'/><path d='M19 7l-3 2'/><path d='M5 7l3 2'/><path d='M19 19l-3-2'/><path d='M5 19l3-2'/><path d='M20 13h-4'/><path d='M4 13h4'/><path d='M10 4l1 2'/><path d='M14 4l-1 2'/></svg>",
}

SVG_NAV_FEED = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/><polyline points='9 22 9 12 15 12 15 22'/></svg>"""
SVG_NAV_CREATE = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='16'/><line x1='8' y1='12' x2='16' y2='12'/></svg>"""
SVG_NAV_CABINET = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'/><circle cx='12' cy='7' r='4'/></svg>"""
SVG_NAV_SETTINGS = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'/><path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'/></svg>"""
SVG_NAV_SUGGES = """<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='22 12 16 12 14 15 10 15 8 12 2 12'/><path d='M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'/></svg>"""

def bottom_nav_html(lang):
    current = _current_path.get() or "/"
    feed_active = "active" if current == "/cabinet" else ""
    create_active = "active" if current == "/cabinet/new" else ""
    profile_active = "active" if current == "/cabinet/profile" else ""
    sug_active = "active" if current == "/cabinet/suggestions" else ""
    set_active = "active" if current == "/settings" else ""
    return f"""
    <nav class="bottom-nav" aria-label="Навигация">
        <a href="/cabinet" class="bottom-nav-item {feed_active}">
            {SVG_NAV_FEED}
            <span>{t('nav_feed', lang)}</span>
        </a>
        <a href="/cabinet/new" class="bottom-nav-item {create_active}">
            {SVG_NAV_CREATE}
            <span>{t('nav_create', lang)}</span>
        </a>
        <a href="/cabinet/profile" class="bottom-nav-item {profile_active}">
            {SVG_NAV_CABINET}
            <span>{t('nav_profile', lang)}</span>
        </a>
        <a href="/cabinet/suggestions" class="bottom-nav-item {sug_active}">
            {SVG_NAV_SUGGES}
            <span>{t('nav_sugges', lang)}</span>
        </a>
        <a href="/settings" class="bottom-nav-item {set_active}">
            {SVG_NAV_SETTINGS}
            <span>{t('nav_settings', lang)}</span>
        </a>
    </nav>
    <script>document.body.classList.add('has-bottom-nav');</script>
    """

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
            .post-image { width: 100%; max-height: 500px; object-fit: cover; display: block; cursor: zoom-in; }
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
            #toast { position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%); background: #333; color: white; padding: 12px 24px; border-radius: 8px; opacity: 0; transition: opacity 0.3s; z-index: 9999; font-weight: bold; pointer-events: none; text-align: center; max-width: 90%; }
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
            .stats-card { background: #a9a9a9; padding: 15px; border-radius: 5px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;}
            .stats-card b { font-size: 17px; }
            .stats-value { font-weight: bold; color: #1e8449; font-size: 22px; }
            .contacts-box { background: #222; color: white; padding: 18px; border-radius: 5px; margin-top: 20px; line-height: 1.8;}
            .contacts-box b { display: block; margin-bottom: 8px; font-size: 16px;}
            .contacts-box a { color: #4da6ff; }

            /* ===== Settings page ===== */
            .settings-card { background: #161b22; border-radius: 12px; padding: 18px; margin-bottom: 12px; border: 1px solid #21262d; }
            .settings-card h3 { color: #4da6ff; margin: 0 0 14px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 0.6px; font-weight: bold; }
            .settings-card .lang-switch { justify-content: flex-start; margin: 0; }
            .settings-about-text { color: #c9d1d9; font-size: 15px; line-height: 1.55; margin: 0 0 12px 0; }
            .settings-version { color: #666; font-size: 13px; margin: 0; }
            .settings-link { display: flex; align-items: center; justify-content: space-between; padding: 14px 4px; border-bottom: 1px solid #21262d; color: #c9d1d9; font-size: 15px; font-weight: bold; }
            .settings-link:last-child { border-bottom: none; }
            .settings-link:hover { color: #4da6ff; text-decoration: none; }
            .settings-link::after { content: '›'; color: #666; font-size: 20px; font-weight: normal; }

            /* ===== Image / avatar skeletons ===== */
            .image-skeleton {
                margin: 10px 0 0;
                border-radius: 10px;
                overflow: hidden;
                background: linear-gradient(90deg, #1a1a1a 0%, #2a2a2a 50%, #1a1a1a 100%);
                background-size: 200% 100%;
                animation: shimmer 1.5s infinite linear;
                min-height: 100px;
                position: relative;
            }
            .image-skeleton.loaded { animation: none; background: transparent; min-height: 0; }
            .image-skeleton .post-image { margin: 0; opacity: 0; transition: opacity 0.4s; }
            .image-skeleton .post-image.loaded { opacity: 1; }
            .avatar-skeleton {
                display: block; width: 120px; height: 120px; margin: 0 auto 10px;
                border-radius: 8px; overflow: hidden;
                background: linear-gradient(90deg, #2a2a2a 0%, #3a3a3a 50%, #2a2a2a 100%);
                background-size: 200% 100%;
                animation: shimmer 1.5s infinite linear;
            }
            .avatar-skeleton.loaded { animation: none; background: transparent; }
            .avatar-skeleton .avatar { margin: 0; width: 100%; height: 100%; opacity: 0; transition: opacity 0.4s; border-radius: 0; }
            .avatar-skeleton .avatar.loaded { opacity: 1; }
            @keyframes shimmer {
                0% { background-position: 200% 0; }
                100% { background-position: -200% 0; }
            }

            /* ===== Button spinner ===== */
            .btn-spinner {
                display: inline-block;
                width: 18px; height: 18px;
                border: 2px solid rgba(0,0,0,0.3);
                border-top-color: #000;
                border-radius: 50%;
                animation: spin 0.6s linear infinite;
                vertical-align: middle;
            }
            @keyframes spin { to { transform: rotate(360deg); } }

            /* ===== Progress bar ===== */
            .progress-bar {
                position: fixed; top: 0; left: 0;
                height: 3px; width: 0;
                background: linear-gradient(90deg, #4da6ff 0%, #9b59b6 50%, #4da6ff 100%);
                background-size: 200% 100%;
                animation: progress-shimmer 1.5s linear infinite;
                z-index: 99999;
                opacity: 0;
                pointer-events: none;
            }
            .progress-bar.show { width: 80%; opacity: 1; transition: width 0.4s ease-out, opacity 0.2s; }
            @keyframes progress-shimmer { 0% { background-position: 0% 0%; } 100% { background-position: 200% 0%; } }

            /* ===== Image viewer (improved) ===== */
            #img-viewer {
                position: fixed; top: 0; left: 0;
                width: 100vw; height: 100vh; height: 100dvh;
                background: rgba(0,0,0,0.95);
                backdrop-filter: blur(8px);
                z-index: 20000;
                display: none;
                justify-content: center;
                align-items: center;
                padding: 0;
            }
            #img-viewer.show { display: flex; animation: fadeIn 0.2s; }
            #img-viewer-img {
                max-width: 90vw;
                max-height: 82vh;
                max-height: 82dvh;
                object-fit: contain;
                border-radius: 6px;
                transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                cursor: zoom-in;
                user-select: none;
                -webkit-user-select: none;
                touch-action: manipulation;
                box-shadow: 0 0 40px rgba(0,0,0,0.6);
            }
            #img-viewer-img.zoomed {
                transform: scale(2.2);
                cursor: zoom-out;
            }
            .img-viewer-close {
                position: fixed;
                top: max(14px, calc(env(safe-area-inset-top, 0px) + 10px));
                right: max(14px, calc(env(safe-area-inset-right, 0px) + 10px));
                background: rgba(255,255,255,0.15);
                color: #fff;
                border: 2px solid rgba(255,255,255,0.3);
                width: 48px; height: 48px;
                border-radius: 50%;
                font-size: 26px;
                line-height: 1;
                cursor: pointer;
                display: flex; align-items: center; justify-content: center;
                transition: background 0.2s, transform 0.15s;
                z-index: 20002;
                -webkit-tap-highlight-color: transparent;
                backdrop-filter: blur(4px);
                font-weight: bold;
                padding: 0;
            }
            .img-viewer-close:hover { background: rgba(255,255,255,0.3); }
            .img-viewer-close:active { transform: scale(0.92); }
            @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

            /* ===== Dual view ===== */
            .desktop-only { display: block; }
            .mobile-only { display: none; }

            /* ===== Feed layout ===== */
            .mobile-feed { padding: 12px 12px 20px; }
            .mobile-feed .feed-title {
                color: #fff;
                font-size: 20px;
                margin: 0 0 12px;
                text-align: center;
                background: #000;
                padding: 14px;
                border-radius: 14px;
                letter-spacing: 1px;
            }
            .feed-list { display: flex; flex-direction: column; gap: 12px; width: 100%; }
            .feed-list .post-item { border-radius: 12px; }
            .feed-post-header {
                padding: 12px 15px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid rgba(0,0,0,0.12);
                font-size: 14px;
            }
            .feed-post-header a { color: #2a5db0; font-weight: bold; }
            .feed-post-time { color: #555; font-weight: normal; font-size: 12px; }

            /* ===== Create page ===== */
            .create-page-container {
                width: 100%;
                max-width: 700px;
                margin: 0 auto;
            }
            .create-page-title {
                color: #fff;
                font-size: 24px;
                text-align: center;
                margin: 0 0 20px;
                letter-spacing: 1px;
            }
            .create-page-form {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .create-page-textarea {
                width: 100%;
                min-height: 300px;
                height: 40vh;
                padding: 14px;
                font-size: 16px;
                border-radius: 12px;
                background: #a9a9a9;
                border: none;
                resize: vertical;
                font-family: 'RuFont', 'Titillium Web', Arial, sans-serif;
            }

            /* ===== Bottom navigation ===== */
            .bottom-nav { display: none; }

            /* ===== Mobile app-like styles ===== */
            @media (max-width: 768px) {
                body { background-color: #ececec; }
                .page-content {
                    justify-content: flex-start;
                    padding: 12px 12px 40px 12px;
                    min-height: 100vh;
                    min-height: 100dvh;
                }
                body.has-bottom-nav .page-content {
                    padding-bottom: 100px;
                }
                .desktop-only { display: none !important; }
                .mobile-only { display: block; }
                .container { flex-direction: column; padding: 15px; gap: 20px; border-width: 5px; width: 100%; border-radius: 16px; }
                .auth-wrapper { width: 100%; }
                .auth-wrapper-inner { flex-direction: column; gap: 10px; width: 100%; align-items: stretch;}
                .label-text { font-size: 24px; text-align: center; margin: 10px 0 0 0; order: -1; }
                .dashboard-container { flex-direction: column; gap: 12px; }
                .sidebar { width: 100%; border-radius: 18px; padding: 14px; }
                .sidebar .lang-switch { display: none; }
                .main-content { width: 100%; }
                .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
                .error-msg { text-align: center; }
                .login-lang-wrapper { justify-content: center; }
                .create-post-box { padding: 12px; border-radius: 18px; }
                .post-item { padding: 0; border-radius: 12px; }
                .post-content { padding: 12px 12px 0; font-size: 16px; }
                .post-footer { padding: 10px; flex-direction: column; align-items: flex-start; gap: 5px; }
                .post-date { margin-left: 0; }
                input[type="text"], input[type="password"], textarea, select { font-size: 16px; padding: 14px; border-radius: 10px; }
                button, .btn, .file-label { font-size: 16px; padding: 14px; border-radius: 10px; }
                .sidebar h2 { font-size: 20px; }
                .avatar, .avatar-upload, .avatar-skeleton { width: 100px; height: 100px; border-radius: 16px; }
                .avatar-upload-icon { opacity: 1; background: rgba(0,0,0,0.35); }
                .post-image { max-height: 400px; border-radius: 10px; }
                .sugg-actions { flex-direction: column; }
                .action-btn { padding: 8px 12px; font-size: 13px; border-radius: 8px; }
                .modal-box { padding: 20px; border-radius: 16px; }
                .stats-card { font-size: 15px; border-radius: 12px; }
                .stats-value { font-size: 18px;}
                .info-card { border-radius: 12px; }
                .posts-area { border-radius: 18px; padding: 12px; }
                .suggestion-card { border-radius: 14px; }

                /* Footer mobile: only on settings, as compact info */
                .footer { display: none; }
                body.show-footer .footer {
                    display: flex;
                    margin: 20px 12px 12px;
                    padding: 18px 14px;
                    background: #161b22;
                    border-radius: 14px;
                    border: 1px solid #21262d;
                    gap: 10px;
                    font-size: 13px;
                    color: #c9d1d9;
                }
                body.show-footer .footer > div:first-child { font-size: 13px; color: #c9d1d9; }
                body.show-footer .footer > div:first-child a { color: #4da6ff; border-bottom: none; }
                body.show-footer .footer-links {
                    font-size: 12px;
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: center;
                    gap: 6px;
                    color: #888;
                }
                body.show-footer .footer-links a {
                    color: #4da6ff;
                    padding: 4px 8px;
                    border-bottom: none;
                    background: rgba(77, 166, 255, 0.1);
                    border-radius: 8px;
                }
                body.show-footer .footer-contacts { font-size: 11px; color: #888; word-break: break-all; }
                body.show-footer .footer-contacts a { color: #4da6ff; border-bottom: none; }
                body.show-footer .footer-badge { margin-top: 6px; }
                body.show-footer .footer-badge img { width: 130px; height: auto; }
                body.show-footer .footer > div:last-child { font-size: 11px; color: #666; }

                /* Bottom navigation */
                .bottom-nav {
                    display: flex;
                    position: fixed;
                    bottom: 0; left: 0; right: 0;
                    background: #000;
                    border-top: 1px solid #1a1a1a;
                    z-index: 5000;
                    padding-top: 6px;
                    padding-bottom: max(6px, env(safe-area-inset-bottom));
                    box-shadow: 0 -4px 20px rgba(0,0,0,0.15);
                }
                .bottom-nav-item {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    padding: 6px 2px;
                    color: #777;
                    font-size: 10px;
                    gap: 3px;
                    text-decoration: none;
                    font-weight: bold;
                    transition: color 0.15s ease;
                    -webkit-tap-highlight-color: transparent;
                    cursor: pointer;
                    user-select: none;
                    position: relative;
                }
                .bottom-nav-item span {
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 100%;
                    font-size: 10px;
                }
                .bottom-nav-item svg { width: 22px; height: 22px; display: block; }
                .bottom-nav-item.active { color: #4da6ff; }
                .bottom-nav-item.active::before {
                    content: '';
                    position: absolute;
                    top: 0;
                    width: 24px; height: 3px;
                    border-radius: 0 0 3px 3px;
                    background: #4da6ff;
                }

                /* Settings mobile tweaks */
                .settings-card { padding: 16px; border-radius: 14px; }
                .settings-card h3 { font-size: 13px; }
                .settings-link { padding: 16px 4px; }

                /* Create page full height on mobile */
                .create-page-textarea {
                    min-height: 45vh;
                    height: 45vh;
                    font-size: 16px;
                }
                .create-page-title { font-size: 20px; margin-bottom: 16px; }

                /* Toast above nav */
                #toast { bottom: 100px; }

                .mobile-feed { padding: 8px 4px 8px; }
                .mobile-feed .feed-title { font-size: 18px; padding: 12px; }
                .feed-post-header { padding: 10px 14px; font-size: 13px; }
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

        // Image viewer with zoom
        function viewImage(src) {
            if (!src) return;
            const img = document.getElementById('img-viewer-img');
            img.src = src;
            img.classList.remove('zoomed');
            document.getElementById('img-viewer').classList.add('show');
            document.body.style.overflow = 'hidden';
        }
        function closeImgViewer() {
            document.getElementById('img-viewer').classList.remove('show');
            document.getElementById('img-viewer-img').classList.remove('zoomed');
            document.body.style.overflow = '';
        }
        function toggleImgZoom(img) {
            img.classList.toggle('zoomed');
        }
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeImgViewer(); });

        // Skeleton load handler for images
        window.skelLoad = function(el) {
            el.classList.add('loaded');
            if (el.parentElement) el.parentElement.classList.add('loaded');
        };

        // Progress bar
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

        // Existing create handler (optimistic add on cabinet page)
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
            if (!a) { try { await rpc('create_record', { content: c, client_id: i, image_data: img }); location.reload(); } catch (x) { showToast(L.tf + ' ' + x.message); } return; }
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
            if (img) {
                const wrap = document.createElement('div'); wrap.className = 'image-skeleton';
                const imgEl = document.createElement('img'); imgEl.className = 'post-image loaded'; imgEl.src = img; imgEl.onclick = function() { viewImage(this.src); };
                wrap.appendChild(imgEl); wrap.classList.add('loaded');
                item.appendChild(wrap);
            }
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

        // Create page handler (redirects after success)
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
                setTimeout(() => { window.location.href = '/cabinet'; }, 500);
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
    <div id="modal-overlay" class="modal-overlay"><div class="modal-box"><p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p><div class="modal-actions"><button id="modal-cancel" class="btn" style="background:#aaa;color:black;">__CANCEL__</button><button id="modal-confirm" class="btn btn-danger">OK</button></div></div></div>
    <div id="link-modal" class="modal-overlay"><div class="modal-box" style="text-align: left;"><h3 style="margin-top:0;">__EXT_TITLE__</h3><p style="font-size:14px; color:#555; margin-bottom:10px;">__EXT_DESC__</p><div id="og-preview" class="og-box"><p style="margin:0; font-size:14px; color:#666;">__EXT_LOADING__</p></div><div class="modal-actions"><button onclick="closeLinkModal()" class="btn" style="background:#aaa;color:black;">__CANCEL__</button><a id="link-modal-confirm" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-danger" style="text-decoration: none; display: flex; align-items: center; justify-content: center;">__EXT_CONTINUE__</a></div></div></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()">
        <button class="img-viewer-close" onclick="event.stopPropagation();closeImgViewer()" aria-label="Close">&times;</button>
        <img id="img-viewer-img" src="" alt="" onclick="event.stopPropagation();toggleImgZoom(this)">
    </div>
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
        <div>__CREATED_BY__ <a href="http://solid-link.ddns.net" target="_blank" rel="noopener noreferrer">Solid</a> | __HOSTING__ <a href="https://fastapicloud.com" target="_blank" rel="noopener noreferrer">FastAPICloud</a></div>
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
    og_title = "Solid — Вход / Регистрация" if lang == "ru" else "Solid — Login / Registration"
    og_desc = "Solid — простая социальная платформа с записями и предложкой" if lang == "ru" else "Solid — simple social platform with records and suggestions"
    og = og_tags(og_title, og_desc, "/", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__LOGIN__ / __REG__ — Solid</title>__OG__
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

def _img_html(img_src, extra_onclick=True):
    """Wraps a post image in a skeleton container."""
    if not img_src: return ""
    oc = " onclick=\"viewImage(this.src)\"" if extra_onclick else ""
    return f'<div class="image-skeleton"><img class="post-image" src="{img_src}" loading="lazy" onload="window.skelLoad(this)"{oc}></div>'

def _avatar_html(avatar_src):
    if not avatar_src: return ""
    return f'<div class="avatar-skeleton"><img class="avatar" src="{avatar_src}" loading="lazy" onload="window.skelLoad(this)" onclick="viewImage(this.src)"></div>'

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
        img_html = _img_html(img)
        out += f"<div class='post-wrapper' id='post-{rid}'>{acts}<div class='post-item {pc}'><div class='post-content'>{content}</div>{img_html}<div class='post-footer'>{sugg_html}<div class='post-date' data-iso='{iso}'>{date}</div></div></div></div>"
    return out

def render_feed_records(records, lang, viewer=None):
    if not records or not isinstance(records, list): return f"<div class='post-item empty-state'>{t('no_posts', lang)}</div>"
    out = ""
    for x in records:
        if not isinstance(x, dict): continue
        rid = esc(x.get('id'))
        if not rid: continue
        content = linkify(x.get('content'))
        date = format_date(esc(x.get('created_at')))
        iso = esc(x.get('created_at', ''))
        img = sanitize_url(x.get('image_data', ''))
        poster = esc(x.get('user_nickname', ''))
        sugg_by = esc(x.get('suggested_by', ''))
        sugg_html = f"<div class='post-suggested'>{t('suggested_by', lang)} {sugg_by}</div>" if sugg_by else ""
        img_html = _img_html(img)
        out += f"""<div class='post-wrapper' id='post-{rid}'>
            <div class='post-item'>
                <div class='feed-post-header'>
                    <a href='/{quote(poster, safe="")}'>@{poster}</a>
                    <span class='feed-post-time' data-iso='{iso}'>{date}</span>
                </div>
                <div class='post-content'>{content}</div>
                {img_html}
                <div class='post-footer'>{sugg_html}</div>
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

def dashboard_html(nickname, user, my_p, feed_posts, lang, token, viewer, sugg_count=0):
    rh_my = render_records(my_p, lang, own=True, uid=viewer)
    rh_feed = render_feed_records(feed_posts, lang, viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = _avatar_html(avatar)
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    badge = f'<span class="badge">{sugg_count}</span>' if sugg_count else ''
    safe_nick_url = quote(nickname, safe='')
    og_title = f"Лента — Solid" if lang == "ru" else f"Feed — Solid"
    og_desc = desc or ("Solid — лента записей" if lang == "ru" else "Solid — records feed")
    og = og_tags(og_title, og_desc, "/cabinet", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__CABINET__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="desktop-only">
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
    </div>
    </div>
    <div class="mobile-only">
        <div class="page-content mobile-feed">
            <div class="feed-title">__FEED_TITLE__</div>
            <div class="feed-list">__FEED_HTML__</div>
        </div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__CABINET__",t('cabinet',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__NICK_URL__",safe_nick_url),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__LINK_PROFILE__",t('link_profile',lang)),("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(my_p))),("__EDIT_PROFILE__",t('edit_profile',lang)),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__BADGE__",badge),("__LOGOUT__",t('logout',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__CREATE_POST_PLACEHOLDER__",t('create_post_placeholder',lang)),("__ATTACH_PHOTO__",t('attach_photo',lang)),("__SVG_CAMERA__",SVG_CAMERA),("__CREATE_POST_BTN__",t('create_post_btn',lang)),("__MY_POSTS__",t('my_posts',lang)),("__RECORDS_HTML__",rh_my),("__FEED_TITLE__",t('feed_title',lang)),("__FEED_HTML__",rh_feed),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def create_page_html(nickname, lang, token):
    og_title = t('create_page_title', lang) + " — Solid"
    og_desc = t('create_post_placeholder', lang)
    og = og_tags(og_title, og_desc, "/cabinet/new", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__TITLE__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
        <div class="create-page-container">
            <h1 class="create-page-title">__TITLE__</h1>
            <form class="create-page-form" onsubmit="hcNew(event)">
                <textarea class="create-page-textarea" name="content" placeholder="__PLACEHOLDER__" required maxlength="5000" autofocus></textarea>
                <img id="post-img-preview" class="img-preview" style="display:none;">
                <div class="post-buttons-row">
                    <label class="file-label" for="post-file-input">__SVG_CAMERA__ __ATTACH_PHOTO__</label>
                    <input type="file" id="post-file-input" accept="image/*" onchange="handlePostImage(this)" style="display:none;">
                    <button type="submit" id="create-post-btn">__CREATE_BTN__</button>
                </div>
            </form>
        </div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('create_page_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__PLACEHOLDER__",t('create_post_placeholder',lang)),("__SVG_CAMERA__",SVG_CAMERA),("__ATTACH_PHOTO__",t('attach_photo',lang)),("__CREATE_BTN__",t('create_post_btn',lang)),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def profile_page_html(nickname, user, my_p, lang, token, viewer):
    rh = render_records(my_p, lang, own=(viewer == nickname), uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = _avatar_html(avatar)
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    safe_nick_url = quote(nickname, safe='')
    og_title = f"{nickname} — Solid"
    og_desc = desc or (f"Профиль {nickname}" if lang == "ru" else f"Profile {nickname}")
    og = og_tags(og_title, og_desc, "/cabinet/profile", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PROFILE__ __NICKNAME__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar">
        <h2>__PROFILE__</h2>
        __AVATAR__
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br><a href="/__NICK_URL__" target="_blank" rel="noopener noreferrer">__NICKNAME__ __LINK_PROFILE__</a></div>__DB__
        <div class="info-card"><b>__TOTAL_POSTS__:</b><br>__POST_COUNT__</div>
        <a href="/cabinet/edit" class="btn edit-btn">__EDIT_PROFILE__</a>
        <a href="/cabinet/suggestions" class="btn sugges-btn">__SUGGESTIONS_TITLE__</a>
        <form action="/logout" method="get" style="margin: 0; width: 100%;"><button type="submit" class="logout-btn">__LOGOUT__</button></form>
        <div class="lang-switch"><a href="/set_lang/ru?next=/cabinet/profile" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/profile" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div>
    <div class="main-content"><div class="posts-area" style="min-height:400px"><h2>__MY_POSTS__</h2>__RECORDS_HTML__</div></div></div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__PROFILE__",t('profile',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__NICK_URL__",safe_nick_url),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__LINK_PROFILE__",t('link_profile',lang)),("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(my_p))),("__EDIT_PROFILE__",t('edit_profile',lang)),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__LOGOUT__",t('logout',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__MY_POSTS__",t('my_posts',lang)),("__RECORDS_HTML__",rh),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
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
            img_html = _img_html(img)
            rh += f"<div class='suggestion-card' id='sugg-{sid}'><div class='sugg-author'><span class='sugg-name'>{sugg_by}</span><span class='sugg-date' data-iso='{iso}'>{date}</span></div><div class='sugg-content'>{content}</div>{img_html}<div class='sugg-actions' style='margin-top:10px;'><button class='btn sugg-approve' onclick=\"approveSugg('{sid}')\">{t('sugges_approve',lang)}</button><button class='btn sugg-reject' onclick=\"rejectSugg('{sid}')\">{t('sugges_reject',lang)}</button></div></div>"
    og_title = t('suggestions_title', lang) + " — " + nickname
    og = og_tags(og_title, "Solid — suggestions", "/cabinet/suggestions", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__SUGGESTIONS_TITLE__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="posts-area" style="min-height:300px;padding:20px;"><h2>__SUGGESTIONS_TITLE__</h2>__SUGGESTIONS_HTML__</div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">__BACK__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/suggestions" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/suggestions" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__SUGGESTIONS_HTML__",rh),("__BACK__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
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
    og = og_tags(og_title, "Solid — suggestions", f"/{quote(nickname, safe='')}/sugges", lang=lang)
    safe_nick_url = quote(nickname, safe='')
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__TITLE__ __NICKNAME__ — Solid</title>__OG__
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
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('sugges_title',lang)),("__OG__",og),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__RULES_BLOCK__",rules_block),("__MSG__",msg_html),("__FORM_BLOCK__",form_block),("__BACK__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang) if viewer else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def edit_html(nickname, user, lang, token):
    desc = esc(user.get('description'))
    rules = esc(user.get('sugges_rules', ''))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_display = "block" if avatar else "none"
    avatar_html = f'<label class="avatar-upload" for="avatar-file-input"><div class="avatar-skeleton"><img id="avatar-preview" class="avatar" src="{avatar}" style="display:{avatar_display};opacity:{1 if avatar else 0}" onload="window.skelLoad(this)" onerror="this.parentElement.classList.add(\'loaded\')"></div><div class="avatar-upload-icon">{SVG_UPLOAD}</div></label>'
    user_username = esc(user.get('username'))
    sugges_checked = "checked" if user_sugges_enabled(user) else ""
    photo_checked = "checked" if user_sugges_photo_enabled(user) else ""
    og_title = "Редактировать профиль — Solid" if lang == "ru" else "Edit Profile — Solid"
    og = og_tags(og_title, desc or "", "/cabinet/edit", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__EDIT_PROFILE__ — Solid</title>__OG__
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
            <a href="/cabinet/profile" class="btn" style="background:#a9a9a9">__CANCEL__</a>
        </form>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/edit" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/edit" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div></div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__EDIT_PROFILE__",t('edit_profile',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__TOKEN__",token),("__AVATAR_HTML__",avatar_html),("__ATTACH_AVATAR__",t('attach_avatar',lang)),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__DESCRIPTION__",t('description',lang)),("__DESC_PLACEHOLDER__",t('desc_placeholder',lang)),("__DESC__",desc),("__DESC_LEN__",str(len(desc))),("__SUGGES_ENABLE_LABEL__",t('sugges_enable_label',lang)),("__SUGGES_CHECKED__",sugges_checked),("__SUGGES_PHOTO_ENABLE_LABEL__",t('sugges_photo_enable_label',lang)),("__PHOTO_CHECKED__",photo_checked),("__RULES_LABEL__",t('rules_edit_label',lang)),("__RULES_PLACEHOLDER__",t('rules_placeholder',lang)),("__RULES__",rules),("__RULES_LEN__",str(len(rules))),("__SAVE_CHANGES__",t('save_changes',lang)),("__CANCEL__",t('cancel',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    rh = render_records(records, lang, own=is_owner, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = _avatar_html(avatar)
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if is_owner or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    og_title = f"{nickname} — Solid"
    og_desc = desc or (f"Профиль {nickname}" if lang == "ru" else f"Profile {nickname}")
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}", image=avatar, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PROFILE__ __NICKNAME__ — Solid</title>__OG__
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
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__PROFILE__",t('profile',lang)),("__OG__",og),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer or "")),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(records))),("__SUGG_BTN__",sugg_btn),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BACK_HOME__",t('back_home',lang)),("__USER_POSTS__",t('user_posts',lang)),("__RECORDS_HTML__",rh),("__BOTTOM_NAV__",bottom_nav_html(lang) if viewer else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, uid=viewer)
    avatar = sanitize_url(user.get('avatar_data', ''))
    avatar_html = _avatar_html(avatar)
    safe_nick_url = quote(nickname, safe='')
    sugg_btn = "" if (viewer == nickname) or not user_sugges_enabled(user) else f"<a href='/{safe_nick_url}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    raw_content = record.get('content', '') or ''
    snippet = strip_html(raw_content)[:150] + ('...' if len(raw_content) > 150 else '')
    og_title = f"Запись от {nickname} — Solid" if lang == "ru" else f"Record by {nickname} — Solid"
    og_desc = snippet or "Solid"
    img_data = sanitize_url(record.get('image_data', ''))
    og = og_tags(og_title, og_desc, f"/{safe_nick_url}/{quote(str(record.get('id', '')), safe='')}", image=img_data, lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__RECORD_PAGE__ — Solid</title>__OG__
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
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__RECORD_PAGE__",t('record_page',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer or "")),("__PROFILE__",t('profile',lang)),("__AVATAR__",avatar_html),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__NICK_URL__",safe_nick_url),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",esc(user.get('username'))),("__SUGG_BTN__",sugg_btn),("__BACK_HOME__",t('back_home',lang)),("__RECORDS_HTML__",rh),("__BOTTOM_NAV__",bottom_nav_html(lang) if viewer else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def bugreport_html(username, reports, lang, token, show_nav=False):
    rh = "<div class='post-item'>Заявок пока нет...</div>" if not reports else ""
    for x in reports:
        date_str = format_date(esc(x.get('created_at')))
        iso_str = esc(x.get('created_at', ''))
        rh += f"<div class='post-item' style='border-left-color:transparent'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;'><b>{t('bugreport_title',lang)}</b><span class='status-badge status-{esc(x.get('status','Принято')).replace(' ','-')}'>{esc(x.get('status','Принято'))}</span></div><div class='post-content' style='text-align:left;'>{esc(x.get('content'))}</div><div class='post-date' data-iso='{iso_str}'>{date_str}</div></div>"
    og_title = "Баг-репорт — Solid" if lang == "ru" else "Bug Report — Solid"
    og = og_tags(og_title, "Solid", "/bugreport", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__BUGREPORT_TITLE__ — Solid</title>__OG__
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
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",esc(username)),("__BUGREPORT_NAME__",t('bugreport_name',lang)),("__BUGREPORT_DESC__",t('bugreport_desc',lang)),("__BUGREPORT_SEND__",t('bugreport_send',lang)),("__BUGREPORT_MY__",t('bugreport_my',lang)),("__REPORTS_HTML__",rh),("__CANCEL__",t('cancel',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang) if show_nav else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def privacy_html(lang, token):
    og_title = "Политика конфиденциальности — Solid" if lang == "ru" else "Privacy Policy — Solid"
    og_desc = "Политика конфиденциальности Solid" if lang == "ru" else "Solid Privacy Policy"
    og = og_tags(og_title, og_desc, "/privacy", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PRIVACY_TITLE__ — Solid</title>__OG__
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

def settings_html(nickname, user, lang, token):
    og_title = "Настройки — Solid" if lang == "ru" else "Settings — Solid"
    og_desc = "Настройки приложения Solid"
    og = og_tags(og_title, og_desc, "/settings", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__SETTINGS_TITLE__ — Solid</title>__OG__
    __CSS____JS__</head><body class="show-footer">
    <div class="page-content">
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px">
        <div class="posts-area" style="padding:20px;">
            <h2 style="color:#fff;text-align:center;margin-bottom:20px">__SETTINGS_TITLE__</h2>

            <div class="settings-card">
                <h3>__SETTINGS_LANGUAGE__</h3>
                <div class="lang-switch">
                    <a href="/set_lang/ru?next=/settings" class="btn lang-btn __RU_ACTIVE__">RU</a>
                    <a href="/set_lang/en?next=/settings" class="btn lang-btn __EN_ACTIVE__">EN</a>
                </div>
            </div>

            <div class="settings-card">
                <h3>__SETTINGS_ABOUT__</h3>
                <p class="settings-about-text">__SETTINGS_ABOUT_TEXT__</p>
                <p class="settings-version">__SETTINGS_VERSION__: v__APP_VERSION__ (__SERVER_START_DATE__)</p>
            </div>

            <div class="settings-card">
                <h3>__SETTINGS_LINKS__</h3>
                <a href="/privacy" class="settings-link">__PRIVACY_TITLE__</a>
                <a href="/docs" class="settings-link">__FAQ_LINK__</a>
                <a href="/stats" class="settings-link">__STATS_LINK__</a>
                <a href="/bugreport" class="settings-link">__BUGREPORT_TITLE__</a>
            </div>

            <form action="/logout" method="get" style="margin: 0; width: 100%;">
                <button type="submit" class="logout-btn" style="border-radius:10px;">__LOGOUT__</button>
            </form>
        </div>
    </div></div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),("__SETTINGS_TITLE__",t('settings_title',lang)),("__SETTINGS_LANGUAGE__",t('settings_language',lang)),("__SETTINGS_ABOUT__",t('settings_about',lang)),("__SETTINGS_ABOUT_TEXT__",t('settings_about_text',lang)),("__SETTINGS_VERSION__",t('settings_version',lang)),("__SETTINGS_LINKS__",t('settings_links',lang)),("__PRIVACY_TITLE__",t('privacy_title',lang)),("__FAQ_LINK__",t('faq_link',lang)),("__STATS_LINK__",t('stats_link',lang)),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__LOGOUT__",t('logout',lang)),("__APP_VERSION__",APP_VERSION),("__SERVER_START_DATE__",SERVER_START_DATE),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang)),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

def stats_html(lang, token, users_count, posts_count, sugg_count, last_update_iso, viewer=""):
    uptime = _uptime_str(lang)
    started = SERVER_START_DT.strftime("%d.%m.%y %H:%M UTC")
    last_upd = format_date(last_update_iso) if last_update_iso else "—"
    last_upd_iso = esc(last_update_iso or "")
    contacts_html = "".join(f"<div style='margin-top:6px;'><a href='mailto:{e}'>{e}</a></div>" for e in CONTACT_EMAILS)
    og_title = "Статистика — Solid" if lang == "ru" else "Stats — Solid"
    og_desc = f"Пользователей: {users_count}, записей: {posts_count}" if lang == "ru" else f"Users: {users_count}, records: {posts_count}"
    og = og_tags(og_title, og_desc, "/stats", lang=lang)
    s = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__STATS_TITLE__ — Solid</title>__OG__
    __CSS____JS__</head><body>
    <div class="page-content">
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:800px">
        <div class="posts-area" style="padding:20px;min-height:400px;">
            <h2>__STATS_TITLE__</h2>
            <div class="stats-card"><b>__STATS_USERS__</b><span class="stats-value">__USERS_COUNT__</span></div>
            <div class="stats-card"><b>__STATS_POSTS__</b><span class="stats-value">__POSTS_COUNT__</span></div>
            <div class="stats-card"><b>__STATS_SUGGES__</b><span class="stats-value">__SUGG_COUNT__</span></div>
            <div class="stats-card"><b>__STATS_STARTED__</b><span style="font-size:15px;">__STARTED__</span></div>
            <div class="stats-card"><b>__STATS_LAST_UPDATE__</b><span style="font-size:15px;" data-iso="__LAST_UPDATE_ISO__">__LAST_UPDATE__</span></div>
            <div class="stats-card"><b>__STATS_UPTIME__</b><span class="stats-value" style="color:#2a5db0;">__UPTIME__</span></div>
            <div class="contacts-box">
                <b>__STATS_CONTACTS__</b>
                <div>__STATS_CONTACTS_DESC__</div>
                __CONTACTS_HTML__
            </div>
        </div>
        <a href="/" class="btn" style="background:#a9a9a9;margin-top:15px;">__BACK__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/stats" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/stats" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>
    </div>
    __BOTTOM_NAV__
    __FOOTER__
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__STATS_TITLE__",t('stats_title',lang)),("__OG__",og),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__STATS_USERS__",t('stats_users',lang)),("__STATS_POSTS__",t('stats_posts',lang)),("__STATS_SUGGES__",t('stats_sugges',lang)),("__STATS_STARTED__",t('stats_started',lang)),("__STATS_LAST_UPDATE__",t('stats_last_update',lang)),("__STATS_UPTIME__",t('stats_uptime',lang)),("__STATS_CONTACTS__",t('stats_contacts',lang)),("__STATS_CONTACTS_DESC__",t('stats_contacts_desc',lang)),("__CONTACTS_HTML__",contacts_html),("__USERS_COUNT__",str(users_count)),("__POSTS_COUNT__",str(posts_count)),("__SUGG_COUNT__",str(sugg_count)),("__STARTED__",started),("__LAST_UPDATE__",last_upd),("__LAST_UPDATE_ISO__",last_upd_iso),("__UPTIME__",uptime),("__BACK__",t('stats_back',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),("__BOTTOM_NAV__",bottom_nav_html(lang) if viewer else ""),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        s = s.replace(k, v)
    return s

# ---------- Docsify / FAQ ----------

def faq_markdown(lang: str) -> str:
    sections = FAQ_DATA.get(lang, FAQ_DATA["ru"])
    lines = [f"# {t('faq_title', lang)}", "", t('faq_intro', lang), ""]
    for icon_key, title, items in sections:
        svg = SVG_ICONS.get(icon_key, "")
        icon_html = f'<span class="docs-icon">{svg}</span> ' if svg else ""
        lines.append(f"## {icon_html}{title}")
        lines.append("")
        for q, a in items:
            lines.append(f"### {q}")
            lines.append("")
            lines.append(a)
            lines.append("")
    return "\n".join(lines)

def docs_html(lang: str, token: str) -> str:
    og_title = "FAQ — Solid"
    og_desc = "Часто задаваемые вопросы о Solid" if lang == "ru" else "Frequently asked questions about Solid"
    og = og_tags(og_title, og_desc, "/docs", lang=lang)
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
            @font-face {{
                font-family: 'RuFont';
                src: url('/static/ru_font.ttf') format('truetype');
                font-weight: 300 700;
                font-display: swap;
            }}
            body {{
                font-family: 'RuFont', 'Titillium Web', Arial, sans-serif;
                background: #0d1117;
            }}
            :root {{ --theme-color: #4da6ff; }}
            .sidebar {{ background: #0d1117; border-right: 1px solid #21262d; }}
            .sidebar ul li a {{ color: #c9d1d9; }}
            .sidebar ul li.active > a,
            .sidebar ul li a:hover {{ color: #4da6ff; border-right: 2px solid #4da6ff; }}
            .sidebar-toggle {{ background: #4da6ff; }}
            .sidebar-nav .docs-icon, .sidebar-nav svg {{ display: none; }}
            .markdown-section {{ color: #c9d1d9; }}
            .markdown-section h1, .markdown-section h2, .markdown-section h3 {{ color: #ffffff; }}
            .markdown-section h2 {{
                display: flex; align-items: center; gap: 12px;
                border-bottom: 2px solid #21262d;
                padding-bottom: 12px; margin-top: 40px;
            }}
            .markdown-section h2 svg {{ flex-shrink: 0; }}
            .markdown-section code {{ background: #161b22; color: #79c0ff; }}
            .markdown-section a {{ color: #4da6ff; }}
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
                onlyCover: false,
                auto2top: true,
                executeScript: false,
                noEmoji: false,
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

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(r: Request, setlang: str = None):
    lang = _resolve_lang(r, setlang)
    nickname = r.cookies.get("nickname")
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if user_data is DB_UNAVAILABLE:
        return HTMLResponse("<h2>Server temporarily unavailable</h2>", 503)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_html(nickname, user_data, lang, token))
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
    user_data, p_data, sc, feed_data = await asyncio.gather(
        _fetch_user(nickname), _fetch_posts(nickname), _fetch_suggestion_count(nickname), _fetch_feed(30)
    )
    if user_data is DB_UNAVAILABLE:
        body = "<h2>Сервер временно недоступен. <a href='/cabinet'>Повторить</a></h2>" if lang == "ru" else "<h2>Server temporarily unavailable. <a href='/cabinet'>Retry</a></h2>"
        return HTMLResponse(body, status_code=503)
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(nickname, user_data, po, feed_data, lang, token, nickname, sc))
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
    res = HTMLResponse(profile_page_html(nickname, user_data, po, lang, token, nickname))
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
    return RedirectResponse("/cabinet/profile", 303)

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
