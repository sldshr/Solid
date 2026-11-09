from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, httpx, asyncio, time as time_module, traceback
from datetime import datetime, timezone
from typing import Optional

app = FastAPI()

APP_VERSION = "0.12"
SERVER_START_DT = datetime.now(timezone.utc)
SERVER_START_DATE = SERVER_START_DT.strftime("%d.%m.%y")
CONTACT_EMAILS = ["sldshr.confirmation@gmail.com", "sldshr.confirm@yandex.ru"]

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

deleted_records, pinned_records, pending_records = set(), {}, {}
MAX_B64_LEN = 900000
MAX_POST_LEN = 5000

# --- RATE LIMITING ---
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
    lst = _LOGIN_FAILS.get(ip, [])
    return len([t for t in lst if now - t < 300])

def _login_fail(ip):
    now = time_module.time()
    lst = _LOGIN_FAILS.setdefault(ip, [])
    lst[:] = [t for t in lst if now - t < 300]
    lst.append(now)

def _login_clear(ip): _LOGIN_FAILS.pop(ip, None)

# --- SECURITY MIDDLEWARE ---
@app.middleware("http")
async def security_mw(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else "0.0.0.0"
    if path in ("/login", "/register", "/rpc"):
        if not _rate_ok(f"auth:{ip}", 40, 60):
            return Response("Too Many Requests", status_code=429)
    if path == "/login" and request.method == "POST":
        if _login_fails(ip) >= 10:
            return Response("Too many login attempts. Wait 5 min.", status_code=429, media_type="text/plain")
    try:
        response = await call_next(request)
    except Exception as e:
        traceback.print_exc()
        return Response("Internal Server Error", status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    traceback.print_exc()
    lang = request.cookies.get("lang", "ru")
    msg = "Ошибка сервера" if lang == "ru" else "Server error"
    return HTMLResponse(f"<h1 style='color:red'>{msg}</h1><a href='/'>OK</a>", status_code=500)

# --- UTILS ---
def esc(val): return html.escape(str(val)) if val is not None else ""

def linkify(text):
    if not text: return ""
    s = html.escape(text)
    return re.sub(r'(https?://[^\s]+)', r'<a href="#" class="ext-link" data-url="\1" onclick="showLinkWarning(event, this)">\1</a>', s).replace('\n', '<br>')

def valid_b64(s):
    if not s: return ""
    s = str(s)
    if len(s) > MAX_B64_LEN or not s.startswith("data:image/"): return ""
    return s

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

# --- DB FETCH ---
async def _fetch_user(nickname):
    for sel in ('username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
                'username,description,sugges_rules,avatar_data,sugges_enabled',
                'username,description,sugges_rules,avatar_data',
                'username,description,sugges_rules',
                'username,description'):
        try:
            res = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nickname).execute())
            return res.data[0] if res.data else None
        except Exception: continue
    return None

async def _fetch_posts(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').eq('user_nickname', nickname).execute())
        return res.data or []
    except Exception: return []

async def _fetch_all_posts(limit=50):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').order('created_at', desc=True).limit(limit).execute())
        return res.data or []
    except Exception: return []

async def _fetch_suggestions(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('author_nickname', nickname).eq('status', 'pending').order('created_at', desc=True).execute())
        return res.data or []
    except Exception: return []

async def _fetch_suggestions_count(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('suggestions').select('id', count='exact').eq('author_nickname', nickname).eq('status', 'pending').execute())
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
    return bool(u) and u.get('sugges_enabled') is not False

def user_sugges_photo_enabled(u):
    return bool(u) and u.get('sugges_photo_enabled') is not False

# --- WEBSOCKET ---
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

# --- PWA / API ---
@app.get("/manifest.json")
async def manifest():
    return JSONResponse(
        {"name": "Solid Link", "short_name": "SolidLink", "start_url": "/",
         "display": "standalone", "background_color": "#0f0f0f", "theme_color": "#0f0f0f",
         "icons": [{"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmMDAwMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xIDExczQtOCAxMS04IDExIDggMTEgOC00IDgtMTEgOC0xMS04LTExLTh6Ij48L3BhdGg+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMSIgcj0iMyI+PC9jaXJjbGU+PC9zdmc+", "sizes": "192x192", "type": "image/svg+xml"}]},
        headers={"Cache-Control": "public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = "self.addEventListener('install', (e) => { e.waitUntil(caches.open('solid-link-v1').then((cache) => cache.addAll(['/']))); }); self.addEventListener('fetch', (e) => { if (e.request.method !== 'GET') return; e.respondWith(caches.match(e.request).then((response) => response || fetch(e.request))); });"
    return Response(content=js, media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})

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
            return {"title": t, "description": gm("description"), "image": gm("image")}
    except Exception: return {"title": "", "description": "", "image": ""}

def hash_password(p): return bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(p, h):
    try:
        if len(h) == 64 and hashlib.sha256(p.encode()).hexdigest() == h: return True
        return bcrypt.checkpw(p.encode('utf-8'), h.encode('utf-8'))
    except: return False

def get_csrf_token(r):
    return r.cookies.get("csrf_token") or secrets.token_hex(32)

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
    lang = request.cookies.get("lang", "ru")
    em = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    res = HTMLResponse(content=auth_html(lang, em, token), status_code=422)
    set_csrf_cookie(res, token, request)
    return res

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

# --- LOCALES ---
LOCALES = {
    "ru": {
        "reg": "Регистрация", "login": "Вход", "username": "юзернейм", "nickname": "никнейм",
        "password": "пароль", "re_pass": "повтор пароля", "captcha": "Я не робот",
        "register_btn": "Зарегистрироваться!", "login_btn": "Войти", "profile": "ПРОФИЛЬ",
        "total_posts": "Всего записей", "logout": "Выйти", "edit_profile": "Редактировать профиль",
        "save_changes": "Сохранить изменения", "description": "Описание", 
        "desc_placeholder": "Расскажите о себе...",
        "create_post_btn": "Создать запись", "create_post_placeholder": "Напишите что-нибудь...",
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
        "privacy_text": "1. Сбор информации. Мы собираем только ваш юзернейм, никнейм и хеш пароля.<br><br>2. Использование данных. Данные используются для аутентификации.<br><br>3. Контент. Ваши записи хранятся на серверах Supabase.<br><br>4. Cookies. Сайт использует cookies для сессии и языка.<br><br>5. Ваши права. Вы можете изменить профиль или удалить записи.",
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
        "attach_photo": "Прикрепить фото", "attach_avatar": "Аватар (квадрат)", "remove_photo": "Убрать фото",
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
        "search_link": "Поиск", "stats_link": "Статистика",
        "stats_title": "СТАТИСТИКА", "stats_users": "Пользователей", "stats_posts": "Записей",
        "stats_sugges": "Предложек", "stats_started": "Сервер запущен", "stats_last_update": "Последнее обновление",
        "stats_uptime": "Аптайм", "stats_contacts": "Связь с администрацией",
        "stats_contacts_desc": "По любым вопросам и предложениям:", "stats_back": "На главную",
        "feed_title": "ГЛАВНАЯ", "feed_link": "Главная", "feed_empty": "Записей пока нет...",
        "suggestions_count": "предложек", "create_new": "Создать",
        "choose_file": "Выбрать файл", "no_file": "Файл не выбран",
        "post_too_long": "Слишком длинный пост (макс. 5000 символов)",
        "menu": "Меню", "close": "Закрыть", "upload": "Загрузить"
    },
    "en": {
        "reg": "Registration", "login": "Login", "username": "username", "nickname": "nickname",
        "password": "password", "re_pass": "re enter pass", "captcha": "I am not a robot",
        "register_btn": "Register!", "login_btn": "Login", "profile": "PROFILE",
        "total_posts": "Total records", "logout": "Logout", "edit_profile": "Edit Profile",
        "save_changes": "Save changes", "description": "Description", 
        "desc_placeholder": "Tell about yourself...",
        "create_post_btn": "Create record", "create_post_placeholder": "Write something...",
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
        "privacy_text": "1. Data Collection. We collect only your username, nickname, and hashed password.<br><br>2. Data Usage. Data is used for authentication.<br><br>3. Content. Your records are stored on Supabase.<br><br>4. Cookies. The site uses cookies for session and language.<br><br>5. Your Rights. You can edit your profile or delete records.",
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
        "attach_photo": "Attach photo", "attach_avatar": "Avatar (square)", "remove_photo": "Remove photo",
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
        "search_link": "Search", "stats_link": "Stats",
        "stats_title": "STATISTICS", "stats_users": "Users", "stats_posts": "Records",
        "stats_sugges": "Suggestions", "stats_started": "Server started", "stats_last_update": "Last update",
        "stats_uptime": "Uptime", "stats_contacts": "Contact administration",
        "stats_contacts_desc": "For questions and suggestions:", "stats_back": "Back to home",
        "feed_title": "HOME", "feed_link": "Home", "feed_empty": "No records yet...",
        "suggestions_count": "suggestions", "create_new": "Create",
        "choose_file": "Choose file", "no_file": "No file chosen",
        "post_too_long": "Post too long (max 5000 chars)",
        "menu": "Menu", "close": "Close", "upload": "Upload"
    }
}

def t(k, l="ru"): return LOCALES.get(l, LOCALES["ru"]).get(k, k)

def format_date(iso):
    if not iso: return ""
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except: return iso[:10]

SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='#f1f1f1' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='#f1f1f1' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""

_CSS_CACHE = None
def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        _CSS_CACHE = """
        <style>
            :root {
                --bg: #0f0f0f;
                --bg-elevated: #212121;
                --bg-hover: #3f3f3f;
                --text: #f1f1f1;
                --text-secondary: #aaaaaa;
                --border: #303030;
                --accent: #ff0000;
                --accent-hover: #cc0000;
                --radius: 12px;
            }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Roboto', Arial, sans-serif;
                background: var(--bg);
                color: var(--text);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                padding-top: 56px;
            }
            a { color: var(--text); text-decoration: none; }
            a:hover { text-decoration: none; }
            /* === HEADER === */
            header {
                position: fixed; top: 0; left: 0; right: 0;
                height: 56px;
                background: var(--bg);
                display: flex;
                align-items: center;
                padding: 0 16px;
                gap: 16px;
                z-index: 1000;
                border-bottom: 1px solid var(--border);
            }
            .logo {
                display: flex; align-items: center; gap: 8px;
                font-weight: bold; font-size: 20px; color: var(--text);
                text-decoration: none;
            }
            .logo-icon {
                width: 32px; height: 32px;
                background: var(--accent);
                border-radius: 8px;
                display: flex; align-items: center; justify-content: center;
                color: white; font-size: 18px; font-weight: bold;
            }
            .header-spacer { flex: 1; }
            .header-user {
                display: flex; align-items: center; gap: 12px;
            }
            .header-user img {
                width: 32px; height: 32px; border-radius: 50%; object-fit: cover;
            }
            /* === LAYOUT === */
            .layout {
                display: flex;
                flex: 1;
            }
            .sidebar {
                width: 240px;
                background: var(--bg);
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
                position: sticky;
                top: 56px;
                height: calc(100vh - 56px);
                overflow-y: auto;
                flex-shrink: 0;
            }
            .sidebar-item {
                display: flex; align-items: center; gap: 16px;
                padding: 10px 16px;
                border-radius: 8px;
                color: var(--text);
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.15s;
                text-decoration: none;
                position: relative;
            }
            .sidebar-item:hover { background: var(--bg-elevated); }
            .sidebar-item.active { background: var(--bg-elevated); font-weight: bold; }
            .sidebar-item .badge {
                background: var(--accent); color: white;
                border-radius: 10px; padding: 2px 8px; font-size: 12px;
                margin-left: auto;
            }
            .main-content {
                flex: 1;
                padding: 24px;
                min-width: 0;
            }
            /* === AUTH === */
            .auth-container {
                display: flex; justify-content: center; align-items: center;
                min-height: calc(100vh - 56px); padding: 20px;
            }
            .auth-box {
                background: var(--bg-elevated);
                padding: 40px;
                border-radius: var(--radius);
                width: 100%;
                max-width: 400px;
            }
            .auth-box h1 { font-size: 28px; margin-bottom: 20px; text-align: center; }
            .auth-box input, .auth-box textarea, .auth-box select {
                background: var(--bg);
                border: 1px solid var(--border);
                color: var(--text);
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 16px;
                width: 100%;
                margin-bottom: 12px;
                outline: none;
            }
            .auth-box input:focus { border-color: var(--accent); }
            .auth-box button {
                background: var(--accent);
                color: white;
                border: none;
                padding: 12px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                width: 100%;
                margin-top: 8px;
            }
            .auth-box button:hover { background: var(--accent-hover); }
            .auth-footer { margin-top: 16px; text-align: center; font-size: 14px; color: var(--text-secondary); }
            .auth-footer a { color: var(--accent); }
            /* === FEED GRID === */
            .feed-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
                gap: 24px 16px;
            }
            .post-card {
                background: var(--bg-elevated);
                border-radius: var(--radius);
                overflow: hidden;
                display: flex;
                flex-direction: column;
                transition: transform 0.15s;
                position: relative;
            }
            .post-card:hover { transform: scale(1.02); }
            .post-card-img {
                width: 100%;
                aspect-ratio: 16/9;
                object-fit: cover;
                background: var(--bg);
                display: block;
            }
            .post-card-body {
                padding: 12px 16px;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .post-card-title {
                font-size: 16px;
                font-weight: 500;
                line-height: 1.4;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }
            .post-card-meta {
                font-size: 14px;
                color: var(--text-secondary);
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                align-items: center;
            }
            .post-card-actions {
                position: absolute;
                top: 8px; right: 8px;
                display: flex;
                gap: 4px;
                opacity: 0;
                transition: opacity 0.2s;
            }
            .post-card:hover .post-card-actions { opacity: 1; }
            .icon-btn {
                background: rgba(0,0,0,0.6);
                color: white;
                border: none;
                border-radius: 50%;
                width: 32px; height: 32px;
                display: flex; align-items: center; justify-content: center;
                cursor: pointer;
                font-size: 14px;
            }
            .icon-btn:hover { background: rgba(0,0,0,0.8); }
            /* === PROFILE / CABINET === */
            .profile-header {
                display: flex; gap: 24px; align-items: flex-start;
                margin-bottom: 32px;
                background: var(--bg-elevated);
                padding: 24px;
                border-radius: var(--radius);
            }
            .profile-avatar {
                width: 120px; height: 120px;
                border-radius: 50%;
                object-fit: cover;
                background: var(--bg);
                flex-shrink: 0;
                cursor: zoom-in;
            }
            .profile-avatar-placeholder {
                width: 120px; height: 120px;
                border-radius: 50%;
                background: var(--bg);
                flex-shrink: 0;
            }
            .profile-info h1 { font-size: 32px; margin-bottom: 8px; }
            .profile-info .username { color: var(--text-secondary); margin-bottom: 8px; }
            .profile-info .bio { color: var(--text-secondary); font-size: 14px; max-width: 500px; }
            .profile-stats {
                display: flex; gap: 24px; margin-top: 16px;
                font-size: 14px; color: var(--text-secondary);
            }
            .profile-stats b { color: var(--text); }
            /* === BUTTONS === */
            .btn {
                display: inline-flex; align-items: center; justify-content: center;
                padding: 10px 20px;
                border-radius: 20px;
                border: none;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.15s;
                text-decoration: none;
                gap: 8px;
            }
            .btn-primary { background: var(--accent); color: white; }
            .btn-primary:hover { background: var(--accent-hover); }
            .btn-secondary { background: var(--bg-elevated); color: var(--text); }
            .btn-secondary:hover { background: var(--bg-hover); }
            .btn-danger { background: #ff4d4d; color: white; }
            .btn-danger:hover { background: #cc0000; }
            .btn-small { padding: 6px 12px; font-size: 12px; border-radius: 16px; }
            /* === FORMS === */
            .form-group { margin-bottom: 16px; }
            .form-group label { display: block; margin-bottom: 6px; font-size: 14px; color: var(--text-secondary); }
            .form-group input, .form-group textarea, .form-group select {
                width: 100%;
                background: var(--bg);
                border: 1px solid var(--border);
                color: var(--text);
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 16px;
                outline: none;
                font-family: inherit;
            }
            .form-group textarea { resize: vertical; min-height: 120px; }
            .form-group input:focus, .form-group textarea:focus { border-color: var(--accent); }
            .form-group .hint { font-size: 12px; color: var(--text-secondary); text-align: right; margin-top: 4px; }
            .form-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 24px; }
            /* === TOGGLE === */
            .toggle-row {
                display: flex; align-items: center; justify-content: space-between;
                padding: 12px 16px;
                background: var(--bg);
                border-radius: 8px;
                margin-bottom: 12px;
                font-size: 14px;
                cursor: pointer;
            }
            .toggle-row input[type="checkbox"] {
                width: 20px; height: 20px;
                accent-color: var(--accent);
                cursor: pointer;
            }
            /* === CUSTOM FILE INPUT === */
            .custom-file-upload {
                display: inline-flex; align-items: center; gap: 8px;
                padding: 10px 20px;
                border-radius: 20px;
                background: var(--bg-elevated);
                color: var(--text);
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.15s;
                border: 1px solid var(--border);
            }
            .custom-file-upload:hover { background: var(--bg-hover); }
            .custom-file-upload input[type="file"] { display: none; }
            /* === IMAGE PREVIEW === */
            .img-preview {
                max-width: 100%;
                max-height: 200px;
                border-radius: 8px;
                margin: 8px 0;
                display: block;
                cursor: zoom-in;
            }
            /* === POST FULL VIEW (single) === */
            .post-full {
                background: var(--bg-elevated);
                border-radius: var(--radius);
                padding: 24px;
                margin-bottom: 24px;
            }
            .post-full .post-full-content {
                font-size: 18px;
                line-height: 1.6;
                margin-bottom: 16px;
                white-space: pre-wrap;
                word-break: break-word;
            }
            .post-full .post-full-image {
                width: 100%;
                max-height: 500px;
                object-fit: cover;
                border-radius: 8px;
                margin: 16px 0;
                cursor: zoom-in;
                display: block;
            }
            .post-full .post-full-meta {
                display: flex; justify-content: space-between; align-items: center;
                font-size: 14px; color: var(--text-secondary);
                border-top: 1px solid var(--border);
                padding-top: 16px;
                flex-wrap: wrap;
                gap: 8px;
            }
            /* === SUGGESTIONS === */
            .suggestion-card {
                background: var(--bg-elevated);
                border-radius: var(--radius);
                padding: 16px;
                margin-bottom: 12px;
            }
            .suggestion-header {
                display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 12px;
                flex-wrap: wrap;
                gap: 8px;
            }
            .suggestion-name { font-weight: 500; }
            .suggestion-date { font-size: 12px; color: var(--text-secondary); }
            .suggestion-content {
                font-size: 15px;
                margin-bottom: 12px;
                white-space: pre-wrap;
                word-break: break-word;
            }
            .suggestion-image {
                width: 100%;
                max-height: 200px;
                object-fit: cover;
                border-radius: 8px;
                margin-bottom: 12px;
                cursor: zoom-in;
            }
            .suggestion-actions { display: flex; gap: 8px; }
            /* === PHOTO VIEWER === */
            #img-viewer {
                display: none;
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.95);
                z-index: 20000;
                justify-content: center; align-items: center;
                cursor: zoom-out;
                padding: 20px;
            }
            #img-viewer.show { display: flex; }
            #img-viewer-img {
                max-width: 95vw; max-height: 95vh;
                object-fit: contain;
                border-radius: 8px;
                user-select: none;
            }
            .img-viewer-close {
                position: absolute; top: 20px; right: 20px;
                background: rgba(255,255,255,0.2); color: white;
                border: none; border-radius: 50%;
                width: 48px; height: 48px;
                font-size: 28px; cursor: pointer;
                display: flex; align-items: center; justify-content: center;
            }
            .img-viewer-close:hover { background: rgba(255,255,255,0.4); }
            /* === MODALS === */
            .modal-overlay {
                display: none;
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.7);
                z-index: 10000;
                justify-content: center; align-items: center;
                padding: 20px;
            }
            .modal-overlay.show { display: flex; }
            .modal-box {
                background: var(--bg-elevated);
                padding: 32px;
                border-radius: var(--radius);
                max-width: 480px;
                width: 100%;
                text-align: center;
                position: relative;
            }
            .modal-actions { display: flex; gap: 12px; margin-top: 24px; justify-content: center; }
            .modal-actions .btn { flex: 1; }
            /* === TOAST === */
            #toast {
                position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
                background: var(--bg-elevated);
                color: var(--text);
                padding: 12px 24px;
                border-radius: 8px;
                opacity: 0;
                transition: opacity 0.3s;
                z-index: 9999;
                font-weight: 500;
                pointer-events: none;
                border: 1px solid var(--border);
            }
            #toast.show { opacity: 1; }
            /* === FOOTER === */
            .footer {
                padding: 24px;
                text-align: center;
                color: var(--text-secondary);
                font-size: 13px;
                border-top: 1px solid var(--border);
                margin-top: auto;
            }
            .footer a { color: var(--text-secondary); }
            .footer a:hover { color: var(--text); }
            .footer-links { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; margin-bottom: 8px; }
            .footer-contacts { font-size: 12px; margin-top: 8px; }
            .footer-contacts a { color: var(--accent); }
            /* === ERRORS === */
            .error-msg { color: #ff4d4d; font-size: 14px; margin-top: 8px; min-height: 20px; }
            /* === SEARCH (removed) === */
            /* === RESPONSIVE === */
            @media (max-width: 900px) {
                .sidebar { display: none; }
                .main-content { padding: 16px; }
                .feed-grid { grid-template-columns: 1fr; }
                .profile-header { flex-direction: column; align-items: center; text-align: center; }
                .profile-info h1 { font-size: 24px; }
                .profile-stats { justify-content: center; }
            }
            @media (min-width: 901px) {
                .menu-toggle { display: none; }
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
                            ctx.fillStyle = '#000'; ctx.fillRect(0,0,w,h);
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
            const preview = document.getElementById('post-img-preview');
            const btn = document.getElementById('create-post-btn');
            const label = input.closest('label');
            const nameSpan = label ? label.querySelector('.file-name') : null;
            if (!file) { window.postImageCache = ""; if(preview) preview.style.display='none'; if(nameSpan) nameSpan.innerText = ''; return; }
            if(nameSpan) nameSpan.innerText = file.name;
            showToast(L.ic); if(btn) btn.disabled = true;
            try { const b64 = await compressImage(file, 1000, 0.75); window.postImageCache = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); } showToast(L.ir); }
            catch (e) { window.postImageCache = ""; showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; if(preview) preview.style.display='none'; if(nameSpan) nameSpan.innerText = ''; }
            finally { if(btn) btn.disabled = false; }
        }
        async function handleSuggImage(input) {
            const file = input.files[0];
            const preview = document.getElementById('sugg-img-preview');
            const btn = document.getElementById('sugg-submit-btn');
            const label = input.closest('label');
            const nameSpan = label ? label.querySelector('.file-name') : null;
            if (!file) { window.suggImageCache = ""; if(preview) preview.style.display='none'; if(nameSpan) nameSpan.innerText = ''; return; }
            if(nameSpan) nameSpan.innerText = file.name;
            showToast(L.ic); if(btn) btn.disabled = true;
            try { const b64 = await compressImage(file, 1000, 0.75); window.suggImageCache = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; preview.onclick = () => viewImage(b64); } showToast(L.ir); }
            catch (e) { window.suggImageCache = ""; showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; if(preview) preview.style.display='none'; if(nameSpan) nameSpan.innerText = ''; }
            finally { if(btn) btn.disabled = false; }
        }
        async function handleAvatarChange(input) {
            const file = input.files[0];
            const hidden = document.getElementById('avatar-data');
            const preview = document.getElementById('avatar-preview');
            const label = input.closest('label');
            const nameSpan = label ? label.querySelector('.file-name') : null;
            if (!file) { hidden.value = ""; if(nameSpan) nameSpan.innerText = ''; return; }
            if(nameSpan) nameSpan.innerText = file.name;
            showToast(L.ic);
            try { const b64 = await compressImage(file, 300, 0.8); hidden.value = b64; if (preview) { preview.src = b64; preview.style.display = 'block'; } showToast(L.ir); }
            catch (e) { showToast(e === 'Image too big' ? L.ib : L.ie); input.value = ''; if(nameSpan) nameSpan.innerText = ''; }
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
        function copyLink(user, rid, btn) { if (!user) return; const url = window.location.origin + '/' + user + '/' + rid; navigator.clipboard.writeText(url).then(() => showToast(L.tl)).catch(() => showToast(L.tc)); }
        function showToast(msg) { const t = document.getElementById('toast'); t.innerText = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3000); }
        function showConfirm(msg, cb) { const m = document.getElementById('modal-overlay'); document.getElementById('modal-text').innerText = msg; m.classList.add('show'); const cBtn = document.getElementById('modal-confirm'); const xBtn = document.getElementById('modal-cancel'); const nC = cBtn.cloneNode(true); const nX = xBtn.cloneNode(true); cBtn.parentNode.replaceChild(nC, cBtn); xBtn.parentNode.replaceChild(nX, xBtn); nC.onclick = () => { m.classList.remove('show'); cb(true); }; nX.onclick = () => { m.classList.remove('show'); cb(false); }; }
        let pendingUrl = "";
        async function showLinkWarning(e, el) {
            e.preventDefault(); pendingUrl = el.getAttribute('data-url'); if (!pendingUrl) return;
            document.getElementById('link-modal-confirm').href = pendingUrl; const ogBox = document.getElementById('og-preview'); ogBox.innerHTML = `<p style="margin:0; font-size:14px; color:#aaa;">__EXT_LOADING__</p>`; document.getElementById('link-modal').classList.add('show');
            try { const res = await fetch('/api/og?url=' + encodeURIComponent(pendingUrl)); const data = await res.json(); if (data.title || data.description || data.image) { let html = ''; if (data.image) html += `<img src="${data.image}" class="og-img" style="max-width:100%;max-height:200px;border-radius:8px;margin-bottom:10px;object-fit:cover;">`; if (data.title) html += `<h4 style="margin:0 0 5px 0;font-size:16px;color:#fff;font-weight:bold;">${data.title}</h4>`; if (data.description) html += `<p style="margin:0;font-size:14px;color:#aaa;">${data.description}</p>`; ogBox.innerHTML = html; } else { ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#aaa;">No preview</p>'; } }
            catch (err) { ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#aaa;">Failed to load</p>'; }
        }
        function closeLinkModal() { document.getElementById('link-modal').classList.remove('show'); }
        async function rpc(method, params) { const res = await fetch('/rpc', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': T }, body: JSON.stringify({ method, params }) }); const data = await res.json(); if (!res.ok) throw new Error(data.detail || data.error || 'RPC Error'); return data; }
        function tp(i, b) { const x = document.getElementById(i); if (x.type === 'password') { x.type = 'text'; b.innerHTML = `__SVG_EYE_OFF__`; } else { x.type = 'password'; b.innerHTML = `__SVG_EYE__`; } }
        function uc(e) { const el = document.getElementById('char-count'); if(el) el.innerText = e.value.length + ' / ' + (e.maxLength || 5000); }
        function ucRules(e) { document.getElementById('rules-count').innerText = e.value.length + ' / 1000'; }
        async function hc(e) {
            e.preventDefault(); const f = e.target, c = f.querySelector('textarea').value.trim(); if (!c) return;
            if (c.length > 5000) { showToast(L.ptl); return; }
            const i = crypto.randomUUID(), n = new Date();
            const d = n.toLocaleDateString('ru-RU') + ' ' + n.toLocaleTimeString('ru-RU', {hour: '2-digit', minute:'2-digit'});
            const img = window.postImageCache || "";
            const a = document.querySelector('#my-records-container');
            if (!a) return;
            const m = a.querySelector('.empty-state'); if (m) m.remove();
            const w = document.createElement('div');
            w.className = 'post-card'; w.id = 'post-' + i;
            w.innerHTML = `<div class="post-card-actions"><button onclick="copyLink('${ME}','${i}',this)" class="icon-btn" title="${L.cl}">🔗</button><button onclick="hp('${i}',this)" class="icon-btn pin-btn" title="${L.p}">📌</button><button onclick="hd('${i}',this)" class="icon-btn" title="${L.d}">🗑️</button></div>${img ? `<img class="post-card-img" src="${img}" onclick="viewImage(this.src)">` : ''}<div class="post-card-body"><div class="post-card-title">${c.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div><div class="post-card-meta"><span>${d}</span></div></div>`;
            let inserted = false; const cards = a.querySelectorAll('.post-card');
            for (let ww of cards) { if (!ww.querySelector('.pinned')) { a.insertBefore(w, ww); inserted = true; break; } }
            if (!inserted) a.appendChild(w);
            f.reset(); window.postImageCache = ""; const preview = document.getElementById('post-img-preview'); if (preview) preview.style.display = 'none';
            try { await rpc('create_record', { content: c, client_id: i, image_data: img }); } catch (x) { w.remove(); showToast(L.tf + ' ' + x.message); }
        }
        function hd(i) { showConfirm(L.c, async (yes) => { if (!yes) return; const w = document.getElementById('post-' + i); if (!w) return; w.style.opacity = '0'; setTimeout(() => w.style.display = 'none', 300); try { await rpc('delete_record', { post_id: i }); w.remove(); } catch (x) { w.style.opacity = '1'; w.style.display = 'block'; showToast(L.tf + ' ' + x.message); } }); }
        async function hp(i, b) {
            const w = document.getElementById('post-' + i); if (!w) return;
            const p = w.querySelector('.post-card'); const s = p && p.classList.contains('pinned');
            if (s) { if (p) p.classList.remove('pinned'); if (b) b.innerText = '📌'; }
            else {
                document.querySelectorAll('.post-card.pinned').forEach(el => { el.classList.remove('pinned'); const ww = el.closest('.post-card'); if (ww) { const btn = ww.querySelector('.pin-btn'); if (btn) btn.innerText = '📌'; } });
                if (p) p.classList.add('pinned'); if (b) b.innerText = '📌';
                const a = w.parentNode; a.insertBefore(w, a.children[1]);
            }
            try { await rpc('pin_record', { post_id: i }); }
            catch (x) { if (s) { if (p) p.classList.add('pinned'); if (b) b.innerText = '📌'; } else { if (p) p.classList.remove('pinned'); if (b) b.innerText = '📌'; } showToast(L.tf + ' ' + x.message); }
        }
        async function submitSuggestion(event) {
            event.preventDefault(); const f = event.target; const target = f.dataset.nickname;
            const name = f.querySelector('input[name="sugg_name"]').value.trim();
            const content = f.querySelector('textarea[name="content"]').value.trim();
            if (!name || !content) { showToast(L.sf); return; }
            if (content.length > 5000) { showToast(L.ptl); return; }
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
    replacements = [("__TOKEN__", token),("__ME__", current_user),("__DEL__", t('delete',lang)),("__PIN__", t('pin',lang)),("__UNPIN__", t('unpin',lang)),("__CONFIRM__", t('confirm_delete',lang)),("__NOPOSTS__", t('no_posts',lang)),("__COPYLINK__", t('copy_link',lang)),("__EXT_LOADING__", t('ext_loading',lang)),("__SUGG_FILL__", t('sugges_error_fill',lang)),("__SUGG_SELF__", t('sugges_error_self',lang)),("__SUGG_SUCCESS__", t('sugges_success',lang)),("__IMG_COMPRESSING__", t('img_compressing',lang)),("__IMG_READY__", t('img_ready',lang)),("__IMG_ERROR__", t('img_error',lang)),("__IMG_BIG__", t('img_too_big',lang)),("__TOAST_NEW__", t('toast_new',lang)),("__TOAST_LINK__", t('toast_link',lang)),("__TOAST_COPY_FAIL__", t('toast_copy_fail',lang)),("__TOAST_APPROVED_REMOVED__", t('toast_approved_removed',lang)),("__TOAST_REJECTED_REMOVED__", t('toast_rejected_removed',lang)),("__TOAST_FAILED__", t('toast_failed',lang)),("__SVG_EYE_OFF__", SVG_EYE_OFF),("__SVG_EYE__", SVG_EYE),("__POST_TOO_LONG__", t('post_too_long',lang))]
    for k, v in replacements: js = js.replace(k, v)
    return js

def get_overlay(lang):
    html_str = """
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay"><div class="modal-box"><p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p><div class="modal-actions"><button id="modal-cancel" class="btn btn-secondary">__CANCEL__</button><button id="modal-confirm" class="btn btn-danger">OK</button></div></div></div>
    <div id="link-modal" class="modal-overlay"><div class="modal-box" style="text-align: left;"><h3 style="margin-top:0;color:#fff;">__EXT_TITLE__</h3><p style="font-size:14px; color:#aaa; margin-bottom:10px;">__EXT_DESC__</p><div id="og-preview" style="margin:15px 0;padding:10px;background:#0f0f0f;border-radius:8px;border:1px solid #303030;"><p style="margin:0; font-size:14px; color:#aaa;">__EXT_LOADING__</p></div><div class="modal-actions"><button onclick="closeLinkModal()" class="btn btn-secondary">__CANCEL__</button><a id="link-modal-confirm" href="#" target="_blank" class="btn btn-primary">__EXT_CONTINUE__</a></div></div></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()"><button class="img-viewer-close" onclick="closeImgViewer()">&times;</button><img id="img-viewer-img" src="" alt=""></div>
    """
    for k, v in [("__CANCEL__", t('cancel',lang)),("__EXT_TITLE__", t('ext_title',lang)),("__EXT_DESC__", t('ext_desc',lang)),("__EXT_LOADING__", t('ext_loading',lang)),("__EXT_CONTINUE__", t('ext_continue',lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def get_footer(lang):
    contacts = " | ".join(f"<a href='mailto:{e}'>{e}</a>" for e in CONTACT_EMAILS)
    html_str = """
    <div class="footer">
        <div class="footer-links">
            <a href="/privacy">__PRIVACY_TITLE__</a>
            <a href="/bugreport">__BUGREPORT_TITLE__</a>
            <a href="/stats">__STATS_LINK__</a>
        </div>
        <div class="footer-contacts">__CONTACTS__</div>
        <div style="margin-top:8px;font-size:12px;color:#666;">v__APP_VERSION__ (__SERVER_START_DATE__)</div>
    </div>
    """
    for k, v in [("__PRIVACY_TITLE__",t('privacy_title',lang)),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__STATS_LINK__",t('stats_link',lang)),("__CONTACTS__",contacts),("__APP_VERSION__",APP_VERSION),("__SERVER_START_DATE__",SERVER_START_DATE)]:
        html_str = html_str.replace(k, v)
    return html_str

def header_html(lang, viewer, active="feed"):
    avatar = ""
    if viewer:
        try:
            # We'll just use a placeholder for now; actual avatar is fetched in pages
            pass
        except: pass
    home_class = "active" if active == "feed" else ""
    cabinet_class = "active" if active == "cabinet" else ""
    return f"""
    <header>
        <a href="/feed" class="logo"><div class="logo-icon">▶</div> Solid Link</a>
        <div class="header-spacer"></div>
        <div class="header-user">
            {f'<a href="/cabinet" style="display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--text);"><span style="font-size:14px;">{esc(viewer)}</span></a>' if viewer else '<a href="/" class="btn btn-secondary btn-small">Войти</a>'}
        </div>
    </header>
    <div class="layout">
        <aside class="sidebar">
            <a href="/feed" class="sidebar-item {home_class}">🏠 {t('feed_link', lang)}</a>
            <a href="/cabinet" class="sidebar-item {cabinet_class}">👤 {t('cabinet', lang)}</a>
            {f'<a href="/cabinet/suggestions" class="sidebar-item">📬 {t("suggestions_title", lang)}</a>' if viewer else ''}
            <a href="/cabinet/edit" class="sidebar-item">⚙️ {t('edit_profile', lang)}</a>
            <a href="/stats" class="sidebar-item">📊 {t('stats_link', lang)}</a>
            <a href="/logout" class="sidebar-item">🚪 {t('logout', lang)}</a>
        </aside>
        <main class="main-content">
    """

def footer_close(lang):
    return f"""
        </main>
    </div>
    {get_footer(lang)}
    {get_overlay(lang)}
    """

def auth_html(lang, error_msg="", token=""):
    eb = f"<div class='error-msg'>{error_msg}</div>" if error_msg else "<div class='error-msg'></div>"
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>__LOGIN__ / __REG__</title>__CSS____JS__</head><body>
    <div class="auth-container">
        <div class="auth-box">
            <h1>__REG__</h1>
            <form action="/register" method="post">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <input type="text" name="username" placeholder="__USERNAME__" required>
                <input type="text" name="nickname" placeholder="__NICKNAME__" required>
                <div style="position:relative;">
                    <input type="password" name="password" id="rp" placeholder="__PASSWORD__" required>
                    <button type="button" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:transparent;border:none;cursor:pointer;width:40px;height:40px;display:flex;align-items:center;justify-content:center;padding:0;" onclick="tp('rp',this)">__SVG_EYE__</button>
                </div>
                <div style="position:relative;">
                    <input type="password" name="re_pass" id="rr" placeholder="__REPASS__" required>
                    <button type="button" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:transparent;border:none;cursor:pointer;width:40px;height:40px;display:flex;align-items:center;justify-content:center;padding:0;" onclick="tp('rr',this)">__SVG_EYE__</button>
                </div>
                <label style="display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:14px;color:#aaa;cursor:pointer;">
                    <input type="checkbox" name="captcha" required style="width:18px;height:18px;accent-color:var(--accent);"> __CAPTCHA__
                </label>
                <label style="display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:14px;color:#aaa;cursor:pointer;">
                    <input type="checkbox" name="privacy" required style="width:18px;height:18px;accent-color:var(--accent);"> __PRIVACY_AGREE__ <a href="/privacy" target="_blank" style="color:var(--accent);">__PRIVACY_LINK__</a>
                </label>
                <button type="submit">__REG_BTN__</button>
            </form>
            <div class="auth-footer">Уже есть аккаунт? <a href="#" onclick="document.querySelector('.auth-box h1').innerText='__LOGIN__'; document.querySelector('.auth-box form').action='/login'; document.querySelector('.auth-box form').innerHTML='<input type=\\'hidden\\' name=\\'csrf_token\\' value=\\'__TOKEN__\\'><input type=\\'text\\' name=\\'nickname\\' placeholder=\\'__NICKNAME__\\' required><div style=\\'position:relative;\\'><input type=\\'password\\' name=\\'password\\' id=\\'lp\\' placeholder=\\'__PASSWORD__\\' required><button type=\\'button\\' style=\\'position:absolute;right:8px;top:50%;transform:translateY(-50%);background:transparent;border:none;cursor:pointer;width:40px;height:40px;display:flex;align-items:center;justify-content:center;padding:0;\\' onclick=\\'tp(\\\"lp\\\",this)\\'><svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'20\\' height=\\'20\\' viewBox=\\'0 0 24 24\\' fill=\\'none\\' stroke=\\'#f1f1f1\\' stroke-width=\\'2\\' stroke-linecap=\\'round\\' stroke-linejoin=\\'round\\'><path d=\\'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z\\'></path><circle cx=\\'12\\' cy=\\'12\\' r=\\'3\\'></circle></svg></button></div><label style=\\'display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:14px;color:#aaa;cursor:pointer;\\'><input type=\\'checkbox\\' name=\\'captcha\\' required style=\\'width:18px;height:18px;accent-color:var(--accent);\\'> __CAPTCHA__</label><button type=\\'submit\\'>__LOGIN_BTN__</button>'; document.querySelector('.auth-footer').innerHTML='Нет аккаунта? <a href=\\'#\\' onclick=\\'location.reload()\\'>__REG__</a>'; return false;">__LOGIN__</a></div>
            <div class="error-msg" style="text-align:center;">__ERROR__</div>
        </div>
    </div>__FOOTER__</body></html>
    """
    for k, v in [("__LANG__",lang),("__LOGIN__",t('login',lang)),("__REG__",t('reg',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",t('username',lang)),("__NICKNAME__",t('nickname',lang)),("__PASSWORD__",t('password',lang)),("__REPASS__",t('re_pass',lang)),("__CAPTCHA__",t('captcha',lang)),("__PRIVACY_AGREE__",t('privacy_agree',lang)),("__PRIVACY_LINK__",t('privacy_link',lang)),("__REG_BTN__",t('register_btn',lang)),("__LOGIN_BTN__",t('login_btn',lang)),("__ERROR__",eb),("__FOOTER__",get_footer(lang)),("__SVG_EYE__",SVG_EYE)]:
        html_str = html_str.replace(k, v)
    return html_str

def render_feed_cards(posts, lang, viewer=""):
    if not posts:
        return f"<div style='text-align:center;padding:60px 20px;color:#aaa;'>{t('feed_empty', lang)}</div>"
    cards = ""
    for p in posts:
        rid = esc(p.get('id',''))
        nick = esc(p.get('user_nickname',''))
        content = esc(p.get('content',''))
        # Truncate for card title
        title = content[:150] + ('...' if len(content) > 150 else '')
        date = format_date(esc(p.get('created_at','')))
        img = esc(p.get('image_data',''))
        img_html = f'<img class="post-card-img" src="{img}" onclick="viewImage(this.src)">' if img else '<div class="post-card-img" style="display:flex;align-items:center;justify-content:center;background:#1a1a1a;color:#555;font-size:48px;">📝</div>'
        actions = ""
        if viewer:
            actions = f'<div class="post-card-actions"><button onclick="copyLink(\'{nick}\',\'{rid}\',this)" class="icon-btn" title="{t("copy_link",lang)}">🔗</button></div>'
        cards += f"""
        <div class="post-card" id="post-{rid}">
            {actions}
            {img_html}
            <div class="post-card-body">
                <a href="/{nick}/{rid}" class="post-card-title">{esc(title)}</a>
                <div class="post-card-meta">
                    <a href="/{nick}" style="color:var(--text);font-weight:500;">{nick}</a>
                    <span>•</span>
                    <span>{date}</span>
                </div>
            </div>
        </div>
        """
    return cards

def feed_html(posts, lang, token, viewer):
    cards = render_feed_cards(posts, lang, viewer)
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('feed_title',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "feed")}
        <div class="feed-grid">{cards}</div>
    {footer_close(lang)}
    </body></html>
    """

def cabinet_html(nickname, user, my_p, sugg_count, lang, token, viewer):
    avatar = esc(user.get('avatar_data',''))
    avatar_html = f'<img class="profile-avatar" src="{avatar}" onclick="viewImage(this.src)">' if avatar else '<div class="profile-avatar-placeholder"></div>'
    desc = esc(user.get('description',''))
    badge = f'<span class="badge">{sugg_count}</span>' if sugg_count > 0 else ''
    posts_html = render_feed_cards(my_p, lang, viewer) if my_p else f'<div style="text-align:center;padding:40px;color:#aaa;">{t("no_posts",lang)}</div>'
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('cabinet',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "cabinet")}
        <div class="profile-header">
            {avatar_html}
            <div class="profile-info">
                <h1>{esc(user.get('username',''))}</h1>
                <div class="username">@{esc(nickname)}</div>
                <div class="bio">{desc if desc else ''}</div>
                <div class="profile-stats">
                    <span><b>{len(my_p)}</b> {t('total_posts',lang)}</span>
                </div>
                <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap;">
                    <a href="/cabinet/edit" class="btn btn-secondary btn-small">⚙️ {t('edit_profile',lang)}</a>
                    <a href="/cabinet/suggestions" class="btn btn-secondary btn-small" style="position:relative;">📬 {t('suggestions_title',lang)} {badge}</a>
                    <a href="/{nickname}" class="btn btn-secondary btn-small">👁️ {t('profile',lang)}</a>
                </div>
            </div>
        </div>
        <div class="form-group" style="margin-bottom:24px;">
            <form id="create-form" onsubmit="hc(event)">
                <textarea name="content" placeholder="{t('create_post_placeholder',lang)}" required maxlength="5000" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:16px;border-radius:8px;width:100%;font-size:16px;min-height:120px;outline:none;resize:vertical;"></textarea>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;flex-wrap:wrap;gap:8px;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                        <label class="custom-file-upload">
                            <input type="file" accept="image/*" onchange="handlePostImage(this)">
                            📷 {t('choose_file',lang)}
                            <span class="file-name" style="font-size:12px;color:#aaa;margin-left:4px;"></span>
                        </label>
                        <span id="char-count" style="font-size:12px;color:#aaa;">0 / 5000</span>
                    </div>
                    <button type="submit" id="create-post-btn" class="btn btn-primary">{t('create_post_btn',lang)}</button>
                </div>
                <img id="post-img-preview" class="img-preview" style="display:none;">
            </form>
        </div>
        <h2 style="margin-bottom:16px;">{t('my_posts',lang)}</h2>
        <div class="feed-grid" id="my-records-container">{posts_html}</div>
    {footer_close(lang)}
    </body></html>
    """

def suggestions_html(nickname, suggestions, lang, token, viewer):
    if not suggestions:
        rh = f"<div style='text-align:center;padding:40px;color:#aaa;'>{t('sugges_empty',lang)}</div>"
    else:
        rh = ""
        for s in suggestions:
            sid = esc(s.get('id',''))
            sugg_by = esc(s.get('suggested_by_name',''))
            content = esc(s.get('content',''))
            date = format_date(esc(s.get('created_at','')))
            img = esc(s.get('image_data',''))
            img_html = f'<img class="suggestion-image" src="{img}" onclick="viewImage(this.src)">' if img else ''
            rh += f"""
            <div class="suggestion-card" id="sugg-{sid}">
                <div class="suggestion-header">
                    <span class="suggestion-name">{sugg_by}</span>
                    <span class="suggestion-date">{date}</span>
                </div>
                <div class="suggestion-content">{content}</div>
                {img_html}
                <div class="suggestion-actions">
                    <button class="btn btn-primary btn-small" onclick="approveSugg('{sid}')">{t('sugges_approve',lang)}</button>
                    <button class="btn btn-danger btn-small" onclick="rejectSugg('{sid}')">{t('sugges_reject',lang)}</button>
                </div>
            </div>
            """
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('suggestions_title',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "cabinet")}
        <h2 style="margin-bottom:24px;">{t('suggestions_title',lang)}</h2>
        {rh}
        <a href="/cabinet" class="btn btn-secondary" style="margin-top:24px;">← {t('back_home',lang)}</a>
    {footer_close(lang)}
    </body></html>
    """

def edit_profile_html(nickname, user, lang, token, viewer):
    desc = esc(user.get('description',''))
    rules = esc(user.get('sugges_rules',''))
    avatar = esc(user.get('avatar_data',''))
    avatar_html = f'<img id="avatar-preview" class="profile-avatar" src="{avatar}" onclick="viewImage(this.src)">' if avatar else '<img id="avatar-preview" class="profile-avatar" style="display:none;">'
    sugges_checked = "checked" if user_sugges_enabled(user) else ""
    photo_checked = "checked" if user_sugges_photo_enabled(user) else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('edit_profile',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "cabinet")}
        <div style="max-width:600px;">
            <h2 style="margin-bottom:24px;">{t('edit_profile',lang)}</h2>
            <form action="/cabinet/edit" method="post" style="display:flex;flex-direction:column;gap:16px;">
                <input type="hidden" name="csrf_token" value="{token}">
                <input type="hidden" name="avatar_data" id="avatar-data" value="">
                <div style="text-align:center;">{avatar_html}</div>
                <label class="custom-file-upload" style="justify-content:center;">
                    <input type="file" accept="image/*" onchange="handleAvatarChange(this)">
                    🖼️ {t('attach_avatar',lang)}
                    <span class="file-name" style="font-size:12px;color:#aaa;margin-left:4px;"></span>
                </label>
                <div class="form-group">
                    <label>{t('username_label',lang)}</label>
                    <input type="text" name="username" value="{esc(user.get('username',''))}" required>
                </div>
                <div class="form-group">
                    <label>{t('description',lang)}</label>
                    <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder',lang)}" oninput="uc(this)">{desc}</textarea>
                    <div class="hint" id="char-count">{len(desc)} / 300</div>
                </div>
                <label class="toggle-row">
                    <span>{t('sugges_enable_label',lang)}</span>
                    <input type="checkbox" name="sugges_enabled" {sugges_checked}>
                </label>
                <label class="toggle-row">
                    <span>{t('sugges_photo_enable_label',lang)}</span>
                    <input type="checkbox" name="sugges_photo_enabled" {photo_checked}>
                </label>
                <div class="form-group">
                    <label>{t('rules_edit_label',lang)}</label>
                    <textarea name="sugges_rules" maxlength="1000" placeholder="{t('rules_placeholder',lang)}" oninput="ucRules(this)">{rules}</textarea>
                    <div class="hint" id="rules-count">{len(rules)} / 1000</div>
                </div>
                <button type="submit" class="btn btn-primary">{t('save_changes',lang)}</button>
                <a href="/cabinet" class="btn btn-secondary">{t('cancel',lang)}</a>
            </form>
        </div>
    {footer_close(lang)}
    </body></html>
    """

def profile_html(nickname, user, posts, lang, token, viewer):
    is_owner = (viewer == nickname)
    avatar = esc(user.get('avatar_data',''))
    avatar_html = f'<img class="profile-avatar" src="{avatar}" onclick="viewImage(this.src)">' if avatar else '<div class="profile-avatar-placeholder"></div>'
    desc = esc(user.get('description',''))
    sugg_btn = "" if is_owner or not user_sugges_enabled(user) else f'<a href="/{nickname}/sugges" class="btn btn-primary btn-small">✉️ {t("suggestions_btn",lang)}</a>'
    posts_html = render_feed_cards(posts, lang, viewer) if posts else f'<div style="text-align:center;padding:40px;color:#aaa;">{t("no_posts",lang)}</div>'
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{esc(nickname)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "feed")}
        <div class="profile-header">
            {avatar_html}
            <div class="profile-info">
                <h1>{esc(user.get('username',''))}</h1>
                <div class="username">@{esc(nickname)}</div>
                <div class="bio">{desc if desc else ''}</div>
                <div class="profile-stats">
                    <span><b>{len(posts)}</b> {t('total_posts',lang)}</span>
                </div>
                <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap;">
                    {sugg_btn}
                </div>
            </div>
        </div>
        <div class="feed-grid">{posts_html}</div>
    {footer_close(lang)}
    </body></html>
    """

def single_post_html(nickname, user, post, lang, token, viewer):
    avatar = esc(user.get('avatar_data',''))
    avatar_html = f'<img class="profile-avatar" style="width:48px;height:48px;border-radius:50%;" src="{avatar}">' if avatar else ''
    content = esc(post.get('content',''))
    date = format_date(esc(post.get('created_at','')))
    img = esc(post.get('image_data',''))
    img_html = f'<img class="post-full-image" src="{img}" onclick="viewImage(this.src)">' if img else ''
    sugg_by = esc(post.get('suggested_by',''))
    sugg_html = f'<div style="font-size:13px;color:#1e8449;font-weight:bold;margin-top:8px;">{t("suggested_by",lang)} {sugg_by}</div>' if sugg_by else ''
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('record_page',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "feed")}
        <div class="post-full">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
                {avatar_html}
                <div>
                    <a href="/{nickname}" style="font-weight:bold;font-size:18px;color:var(--text);">{nickname}</a>
                    <div style="font-size:14px;color:var(--text-secondary);">{date}</div>
                </div>
            </div>
            <div class="post-full-content">{content}</div>
            {img_html}
            {sugg_html}
            <div class="post-full-meta">
                <a href="/{nickname}" class="btn btn-secondary btn-small">← {t('back_home',lang)}</a>
                <button class="btn btn-secondary btn-small" onclick="copyLink('{nickname}','{esc(post.get('id',''))}',this)">{t('copy_link',lang)}</button>
            </div>
        </div>
    {footer_close(lang)}
    </body></html>
    """

def sugges_form_html(nickname, lang, token, error="", viewer="", rules="", enabled=True, photo_enabled=True):
    msg_html = f"<div class='error-msg'>{error}</div>" if error else ""
    is_own = (viewer == nickname)
    if is_own:
        form_block = f"<div class='error-msg'>{t('sugges_own', lang)}</div>"
    elif not enabled:
        form_block = f"<div class='error-msg'>{t('sugges_disabled', lang)}</div>"
    else:
        photo_block = f'<label class="custom-file-upload"><input type="file" accept="image/*" onchange="handleSuggImage(this)"> 📷 {t("choose_file",lang)} <span class="file-name" style="font-size:12px;color:#aaa;margin-left:4px;"></span></label><img id="sugg-img-preview" class="img-preview" style="display:none;">' if photo_enabled else ""
        form_block = f"""
        <form data-nickname="{esc(nickname)}" onsubmit="submitSuggestion(event)" style="display:flex;flex-direction:column;gap:12px;">
            <div class="form-group">
                <label>{t('sugges_name',lang)}</label>
                <input type="text" name="sugg_name" required maxlength="60" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:12px 16px;border-radius:8px;font-size:16px;width:100%;">
            </div>
            <div class="form-group">
                <label>{t('sugges_content',lang)}</label>
                <textarea name="content" required maxlength="5000" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:12px 16px;border-radius:8px;font-size:16px;width:100%;min-height:150px;resize:vertical;"></textarea>
            </div>
            {photo_block}
            <button type="submit" class="btn btn-primary" id="sugg-submit-btn">{t('sugges_send',lang)}</button>
        </form>
        """
    rules_block = f'<div style="background:var(--bg-elevated);border-left:4px solid var(--accent);padding:16px;border-radius:8px;margin-bottom:20px;"><b style="display:block;margin-bottom:8px;">{t("rules_title",lang)}</b><div style="white-space:pre-wrap;line-height:1.5;">{esc(rules)}</div></div>' if rules else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('sugges_title',lang)} {esc(nickname)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "feed")}
        <div style="max-width:600px;">
            <h2 style="margin-bottom:20px;">{t('sugges_title',lang)} {esc(nickname)}</h2>
            {rules_block}
            {msg_html}
            {form_block}
            <a href="/{nickname}" class="btn btn-secondary" style="margin-top:20px;">← {t('back_home',lang)}</a>
        </div>
    {footer_close(lang)}
    </body></html>
    """

def stats_html(lang, token, users_count, posts_count, sugg_count, last_update_iso, viewer=""):
    uptime = _uptime_str(lang)
    started = SERVER_START_DT.strftime("%d.%m.%y %H:%M UTC")
    last_upd = format_date(last_update_iso) if last_update_iso else "—"
    contacts_html = "".join(f"<div style='margin-top:6px;'><a href='mailto:{e}' style='color:var(--accent);'>{e}</a></div>" for e in CONTACT_EMAILS)
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('stats_title',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "stats")}
        <div style="max-width:800px;">
            <h2 style="margin-bottom:24px;">{t('stats_title',lang)}</h2>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_users',lang)}</b><span style="font-size:24px;font-weight:bold;color:var(--accent);">{users_count}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_posts',lang)}</b><span style="font-size:24px;font-weight:bold;color:var(--accent);">{posts_count}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_sugges',lang)}</b><span style="font-size:24px;font-weight:bold;color:var(--accent);">{sugg_count}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_started',lang)}</b><span>{started}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_last_update',lang)}</b><span>{last_upd}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <b>{t('stats_uptime',lang)}</b><span style="color:#2a5db0;font-weight:bold;">{uptime}</span>
            </div>
            <div style="background:var(--bg-elevated);border-radius:8px;padding:20px;margin-top:24px;border:1px solid var(--border);">
                <b style="display:block;margin-bottom:8px;">{t('stats_contacts',lang)}</b>
                <div style="color:var(--text-secondary);margin-bottom:8px;">{t('stats_contacts_desc',lang)}</div>
                {contacts_html}
            </div>
            <a href="/feed" class="btn btn-secondary" style="margin-top:24px;">← {t('stats_back',lang)}</a>
        </div>
    {footer_close(lang)}
    </body></html>
    """

def privacy_html(lang, token):
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('privacy_title',lang)} - Solid Link</title>{get_css()}
    </head><body>
    {header_html(lang, "", "privacy")}
        <div style="max-width:800px;">
            <h2 style="margin-bottom:24px;">{t('privacy_title',lang)}</h2>
            <div style="background:var(--bg-elevated);padding:24px;border-radius:8px;line-height:1.6;">{t('privacy_text',lang)}</div>
            <a href="/feed" class="btn btn-secondary" style="margin-top:24px;">← {t('back_home',lang)}</a>
        </div>
    {footer_close(lang)}
    </body></html>
    """

def bugreport_html(username, reports, lang, token, viewer):
    rh = "<div style='text-align:center;padding:40px;color:#aaa;'>Заявок пока нет...</div>" if not reports else ""
    for x in reports:
        rh += f"""
        <div style="background:var(--bg-elevated);border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
                <b>{t('bugreport_title',lang)}</b>
                <span style="background:{'#4da6ff' if x.get('status')=='Принято' else '#f1c40f' if x.get('status')=='В работе' else '#2ecc71' if x.get('status')=='Исправлено' else '#e74c3c'};padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">{esc(x.get('status','Принято'))}</span>
            </div>
            <div style="white-space:pre-wrap;margin-bottom:8px;">{esc(x.get('content',''))}</div>
            <div style="font-size:12px;color:var(--text-secondary);text-align:right;">{format_date(esc(x.get('created_at','')))}</div>
        </div>
        """
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0f0f0f">
    <title>{t('bugreport_title',lang)} - Solid Link</title>{get_css()}{get_js(lang, token, viewer)}
    </head><body>
    {header_html(lang, viewer, "bugreport")}
        <div style="max-width:800px;">
            <h2 style="margin-bottom:24px;">{t('bugreport_title',lang)}</h2>
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:16px;margin-bottom:24px;">
                <input type="hidden" name="csrf_token" value="{token}">
                <div class="form-group">
                    <label>{t('bugreport_name',lang)}</label>
                    <input type="text" name="name" value="{esc(username)}" required>
                </div>
                <div class="form-group">
                    <label>{t('bugreport_desc',lang)}</label>
                    <textarea name="content" required style="min-height:120px;"></textarea>
                </div>
                <button type="submit" class="btn btn-primary">{t('bugreport_send',lang)}</button>
            </form>
            <h3 style="margin-bottom:16px;">{t('bugreport_my',lang)}</h3>
            {rh}
            <a href="/feed" class="btn btn-secondary" style="margin-top:24px;">← {t('back_home',lang)}</a>
        </div>
    {footer_close(lang)}
    </body></html>
    """

# --- ROUTES ---
@app.get("/set_lang/{lang}")
async def set_lang(lang: str, next: str = "/"):
    res = RedirectResponse(next, 303)
    res.set_cookie("lang", lang if lang in ["ru", "en"] else "ru", max_age=31536000)
    return res

@app.get("/", response_class=HTMLResponse)
async def index(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if nickname:
        try:
            rdb = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
            if rdb.data:
                resp = RedirectResponse("/feed", 303); set_csrf_cookie(resp, token, r); return resp
        except Exception: pass
    res = HTMLResponse(auth_html(lang, "", token)); set_csrf_cookie(res, token, r); return res

@app.get("/feed", response_class=HTMLResponse)
async def feed_page(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if not user_data: return RedirectResponse("/", 303)
    posts = await _fetch_all_posts()
    res = HTMLResponse(feed_html(posts, lang, token, nickname))
    set_csrf_cookie(res, token, r); return res

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    try:
        uc, pc, sc, lu = await _stats_data()
    except Exception as e:
        print(f"stats error: {e}")
        uc, pc, sc, lu = 0, 0, 0, None
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
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    if not privacy: return auth_html(lang, t('alert_privacy', lang), token)
    if password != re_pass: return auth_html(lang, t('alert_pass_mismatch', lang), token)
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
        if x.data: return auth_html(lang, t('alert_nick_taken', lang), token)
        await asyncio.to_thread(lambda: sb.table('users').insert({"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}).execute())
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
    resp = RedirectResponse("/feed", 303)
    secure = r.url.scheme == "https"
    resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
    set_csrf_cookie(resp, token, r); return resp

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
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
            resp = RedirectResponse("/feed", 303)
            secure = r.url.scheme == "https"
            resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
            set_csrf_cookie(resp, token, r); return resp
        _login_fail(ip)
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
    return auth_html(lang, t('alert_bad_login', lang), token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data, p_data, sugg_count = await asyncio.gather(
        _fetch_user(nickname),
        _fetch_posts(nickname),
        _fetch_suggestions_count(nickname)
    )
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(cabinet_html(nickname, user_data, po, sugg_count, lang, token, nickname))
    set_csrf_cookie(res, token, r); return res

@app.get("/cabinet/suggestions", response_class=HTMLResponse)
async def cabinet_suggestions(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    s_data = await _fetch_suggestions(nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(suggestions_html(nickname, s_data, lang, token, nickname))
    set_csrf_cookie(res, token, r); return res

@app.get("/{nickname}/sugges", response_class=HTMLResponse)
async def sugges_form(nickname: str, r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    user_data = await _fetch_user(nickname)
    if not user_data: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
    rules = user_data.get('sugges_rules', '') or ''
    enabled = user_sugges_enabled(user_data)
    photo_enabled = user_sugges_photo_enabled(user_data)
    res = HTMLResponse(sugges_form_html(nickname, lang, token, viewer=viewer, rules=rules, enabled=enabled, photo_enabled=photo_enabled))
    set_csrf_cookie(res, token, r); return res

@app.post("/rpc")
async def rpc_endpoint(req: RPCRequest, r: Request, nickname: str = Cookie(None)):
    if not check_csrf(r): raise HTTPException(status_code=403, detail="CSRF Error")
    if req.method == "submit_suggestion":
        target = req.params.get("target_nickname", "").strip()
        sugg_name = req.params.get("sugg_name", "").strip()[:60]
        content = req.params.get("content", "").strip()[:MAX_POST_LEN]
        image_data = valid_b64(req.params.get("image_data", ""))
        if not target or not sugg_name or not content: raise HTTPException(400, "Missing fields")
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
            content = req.params.get("content", "")
            client_id = req.params.get("client_id")
            image_data = valid_b64(req.params.get("image_data", ""))
            if len(content) > MAX_POST_LEN: raise HTTPException(400, "Too long")
            i = client_id or str(uuid.uuid4())
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
            np = {"id": i, "user_nickname": nickname, "content": sugg.get('content', ''), "is_pinned": False, "created_at": n, "suggested_by": sugg.get('suggested_by_name', ''), "image_data": sugg.get('image_data', '') or ''}
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
async def edit(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(edit_profile_html(nickname, user_data, lang, token, nickname))
    set_csrf_cookie(res, token, r); return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), sugges_enabled: str = Form(None), sugges_photo_enabled: str = Form(None), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
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
    viewer = nickname or ""
    res = HTMLResponse(bugreport_html(u, rp, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
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
        if not u.data: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
        if not x.data: return HTMLResponse(f"<h2>{t('no_posts', lang)}</h2>", 404)
        u_data = u.data[0]; rec = x.data[0]
    except Exception:
        return HTMLResponse(f"<h2>DB Error</h2>", 500)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    res = HTMLResponse(single_post_html(nickname, u_data, rec, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/feed'>OK</a></h2>", 404)
    viewer = r.cookies.get("nickname") or ""
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(profile_html(nickname, user_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
