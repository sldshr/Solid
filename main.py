from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, httpx, asyncio, time as time_module, traceback
from datetime import datetime, timezone
from typing import Optional

app = FastAPI()

APP_VERSION = "0.13"
SERVER_START_DT = datetime.now(timezone.utc)
SERVER_START_DATE = SERVER_START_DT.strftime("%d.%m.%y")
CONTACT_EMAILS = ["sldshr.confirmation@gmail.com", "sldshr.confirm@yandex.ru"]

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

deleted_records, pinned_records, pending_records = set(), {}, {}
MAX_B64_LEN = 900000

BANNERS = {
    "default": "linear-gradient(135deg, #1d9bf0 0%, #7856ff 100%)",
    "sunset":  "linear-gradient(135deg, #ff6b6b 0%, #ffe66d 100%)",
    "ocean":   "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    "forest":  "linear-gradient(135deg, #11998e 0%, #38ef7d 100%)",
    "midnight":"linear-gradient(135deg, #232526 0%, #414345 100%)",
    "fire":    "linear-gradient(135deg, #f12711 0%, #f5af19 100%)",
    "candy":   "linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%)",
    "neon":    "linear-gradient(135deg, #00c6ff 0%, #0072ff 100%)",
    "grape":   "linear-gradient(135deg, #8e2de2 0%, #4a00e0 100%)",
    "gold":    "linear-gradient(135deg, #f7971e 0%, #ffd200 100%)",
    "rose":    "linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%)",
    "mint":    "linear-gradient(135deg, #00b09b 0%, #96c93d 100%)",
}

def get_banner_css(banner_id):
    return BANNERS.get(banner_id or "default", BANNERS["default"])

# --- RATE LIMITING ---
_RATE_BUCKETS = {}
_LOGIN_FAILS = {}

def _rate_ok(key, limit=60, window=60):
    now = time_module.time()
    lst = _RATE_BUCKETS.setdefault(key, [])
    lst[:] = [t for t in lst if now - t < window]
    if len(lst) >= limit: return False
    lst.append(now); return True

def _login_fails(ip):
    now = time_module.time(); lst = _LOGIN_FAILS.get(ip, [])
    return len([t for t in lst if now - t < 300])

def _login_fail(ip):
    now = time_module.time(); lst = _LOGIN_FAILS.setdefault(ip, [])
    lst[:] = [t for t in lst if now - t < 300]; lst.append(now)

def _login_clear(ip): _LOGIN_FAILS.pop(ip, None)

# --- MIDDLEWARE ---
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
    except Exception:
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

def sanitize_q(q):
    if not q: return ""
    return q.strip()[:100].replace("\\", "").replace("%", "").replace("_", "")

def _uptime_str(lang="ru"):
    delta = datetime.now(timezone.utc) - SERVER_START_DT
    sec = int(delta.total_seconds())
    d, rem = divmod(sec, 86400); h, rem = divmod(rem, 3600); m, s = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}д" if lang == "ru" else f"{d}d")
    parts.append(f"{h:02d}:{m:02d}:{s:02d}")
    return " ".join(parts)

def _safe_zoom(v):
    try:
        f = float(v)
        return max(0.5, min(2.0, f))
    except Exception:
        return 1.0

# --- DB ---
async def _fetch_user(nickname):
    tries = [
        'username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled,banner_id,avatar_zoom',
        'username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled,banner_id',
        'username,description,sugges_rules,avatar_data,sugges_enabled,sugges_photo_enabled',
        'username,description,sugges_rules,avatar_data,sugges_enabled',
        'username,description,sugges_rules,avatar_data',
        'username,description,sugges_rules',
        'username,description',
    ]
    for sel in tries:
        try:
            res = await asyncio.to_thread(lambda s=sel: sb.table('users').select(s).eq('nickname', nickname).execute())
            return res.data[0] if res.data else None
        except Exception:
            continue
    return None

async def _fetch_posts(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('posts').select('*').eq('user_nickname', nickname).execute())
        return res.data or []
    except Exception:
        return []

async def _fetch_suggestions(nickname):
    try:
        res = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('author_nickname', nickname).eq('status', 'pending').order('created_at', desc=True).execute())
        return res.data or []
    except Exception:
        return []

async def _stats_data():
    u_c, p_c, s_c, lu = 0, 0, 0, None
    try:
        u = await asyncio.to_thread(lambda: sb.table('users').select('nickname', count='exact').execute())
        u_c = u.count if getattr(u, 'count', None) is not None else len(u.data or [])
    except Exception: pass
    try:
        p = await asyncio.to_thread(lambda: sb.table('posts').select('id', count='exact').execute())
        p_c = p.count if getattr(p, 'count', None) is not None else len(p.data or [])
    except Exception: pass
    try:
        s = await asyncio.to_thread(lambda: sb.table('suggestions').select('id', count='exact').execute())
        s_c = s.count if getattr(s, 'count', None) is not None else len(s.data or [])
    except Exception: pass
    try:
        r = await asyncio.to_thread(lambda: sb.table('posts').select('created_at').order('created_at', desc=True).limit(1).execute())
        if r.data: lu = r.data[0].get('created_at')
    except Exception: pass
    return u_c, p_c, s_c, lu

def user_sugges_enabled(u): return bool(u) and u.get('sugges_enabled') is not False
def user_sugges_photo_enabled(u): return bool(u) and u.get('sugges_photo_enabled') is not False

# --- WS ---
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
    return JSONResponse({
        "name": "Solid", "short_name": "Solid", "start_url": "/",
        "display": "standalone", "display_override": ["standalone", "minimal-ui"],
        "background_color": "#000000", "theme_color": "#000000",
        "orientation": "portrait-primary", "scope": "/",
        "icons": [
            {"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFkOWJmMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xMiAyTDIgN2wxMCA1IDEwLTV6Ii8+PHBhdGggZD0iTTIgMTdsMTAgNSAxMC01Ii8+PHBhdGggZD0iTTIgMTJsMTAgNSAxMC01Ii8+PC9zdmc+", "sizes": "192x192", "type": "image/svg+xml", "purpose": "any"},
            {"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI1MTIiIGhlaWdodD0iNTEyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFkOWJmMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xMiAyTDIgN2wxMCA1IDEwLTV6Ii8+PHBhdGggZD0iTTIgMTdsMTAgNSAxMC01Ii8+PHBhdGggZD0iTTIgMTJsMTAgNSAxMC01Ii8+PC9zdmc+", "sizes": "512x512", "type": "image/svg+xml", "purpose": "any"},
            {"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9IiMwMDAiPjxyZWN0IHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgZmlsbD0iIzAwMCIvPjxwYXRoIGQ9Ik0xMiAyTDIgN2wxMCA1IDEwLTV6IiBmaWxsPSJub25lIiBzdHJva2U9IiMxZDliZjAiIHN0cm9rZS13aWR0aD0iMiIvPjwvc3ZnPg==", "sizes": "192x192", "type": "image/svg+xml", "purpose": "maskable"}
        ]
    }, headers={"Cache-Control": "public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = """
const CACHE = 'solid-v3';
const PRECACHE = ['/', '/manifest.json', '/privacy'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.origin !== location.origin) return;
  if (url.pathname === '/ws' || url.pathname.startsWith('/api/')) return;
  if (url.pathname === '/sw.js') return;
  e.respondWith(
    fetch(e.request).then(res => {
      if (res && res.status === 200 && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('/')))
  );
});
"""
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
    except Exception:
        return {"title": "", "description": "", "image": ""}

def hash_password(p): return bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(p, h):
    try:
        if len(h) == 64 and hashlib.sha256(p.encode()).hexdigest() == h: return True
        return bcrypt.checkpw(p.encode('utf-8'), h.encode('utf-8'))
    except Exception:
        return False

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
    lang = request.cookies.get("lang", "ru")
    em = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    res = HTMLResponse(content=auth_html(lang, em, token), status_code=422)
    set_csrf_cookie(res, token, request)
    return res

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

# --- ICONS ---
SVG_HOME = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>'
SVG_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
SVG_CHART = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>'
SVG_USER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
SVG_BELL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'
SVG_PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'
SVG_SETTINGS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
SVG_LOGOUT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>'
SVG_ARROW_LEFT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>'
SVG_IMAGE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'
SVG_LOGO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>'
SVG_CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'

SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""

# --- LOCALES ---
LOCALES = {
    "ru": {
        "reg": "Регистрация", "login": "Вход", "username": "юзернейм", "nickname": "никнейм",
        "password": "пароль", "re_pass": "повтор пароля", "captcha": "Я не робот",
        "register_btn": "Зарегистрироваться", "login_btn": "Войти", "profile": "ПРОФИЛЬ",
        "total_posts": "Всего записей", "logout": "Выйти", "edit_profile": "Редактировать профиль",
        "save_changes": "Сохранить", "description": "Описание", 
        "desc_placeholder": "Расскажите о себе...",
        "create_post_btn": "Опубликовать", "create_post_placeholder": "Что происходит?",
        "my_posts": "МОИ ЗАПИСИ", "user_posts": "ЗАПИСИ", 
        "no_posts": "Записей пока нет...", "pin": "Закрепить", "unpin": "Открепить", "delete": "Удалить", 
        "confirm_delete": "Удалить запись?", "created_by": "Создано:", "hosting": "Хостинг:", 
        "back_home": "На главную", "user_not_found": "Пользователь не найден.", 
        "alert_captcha": "Подтвердите, что вы не робот!", "alert_pass_mismatch": "Пароли не совпадают!", 
        "alert_nick_taken": "Такой никнейм уже занят!", "alert_bad_login": "Неверный никнейм или пароль!", 
        "alert_desc_long": "Описание > 300 символов!", "link_profile": "(Ссылка)", "cancel": "Отмена", 
        "username_label": "Имя", "nickname_label": "Никнейм", "bugreport_title": "Баг-репорт", 
        "bugreport_name": "Ваше имя", "bugreport_desc": "Описание проблемы", "bugreport_send": "Отправить", 
        "bugreport_my": "Мои заявки", "privacy_title": "Политика конфиденциальности",
        "privacy_text": "1. Сбор информации. Мы собираем только ваш юзернейм, никнейм и хеш пароля.\n\n2. Использование данных. Данные используются для аутентификации.\n\n3. Контент. Ваши записи хранятся на серверах Supabase.\n\n4. Cookies. Сайт использует cookies для сессии и языка.\n\n5. Ваши права. Вы можете изменить профиль или удалить записи.",
        "privacy_agree": "Я согласен с", "privacy_link": "Политикой конфиденциальности",
        "alert_privacy": "Примите политику!", "cabinet": "Solid",
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
        "attach_photo": "Прикрепить фото", "attach_avatar": "Аватар", "remove_photo": "Убрать фото",
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
        "search_title": "ПОИСК", "search_placeholder": "Введите запрос...",
        "search_type_all": "Всё", "search_type_authors": "Авторы", "search_type_records": "Записи",
        "search_author_filter": "Фильтр по автору",
        "search_btn": "Найти", "search_no_results": "Ничего не найдено",
        "search_found_authors": "Найденные авторы", "search_found_records": "Найденные записи",
        "search_link": "Поиск", "stats_link": "Статистика",
        "stats_title": "СТАТИСТИКА", "stats_users": "Пользователей", "stats_posts": "Записей",
        "stats_sugges": "Предложек", "stats_started": "Сервер запущен", "stats_last_update": "Последнее обновление",
        "stats_uptime": "Аптайм", "stats_contacts": "Связь с администрацией",
        "stats_contacts_desc": "По любым вопросам и предложениям:", "stats_back": "На главную",
        "home": "Главная", "feed": "Лента", "back": "Назад", "sign_in": "Войти",
        "composer_hint": "Что нового?", "post": "Опубликовать", "photo": "Фото",
        "profile_posts": "записей", "loading": "Загрузка...",
        "settings": "Настройки", "settings_title": "Настройки",
        "appearance": "Оформление", "banner": "Баннер профиля",
        "avatar_zoom": "Приближение аватара", "avatar_hint": "Нажмите на аватар или перетащите файл",
        "account": "Аккаунт", "language": "Язык", "save": "Сохранить", "saved": "Сохранено!",
        "suggestions_section": "Предложка", "privacy_section": "Приватность",
        "post_created": "Опубликовано!", "compose": "Создать запись",
        "compose_title": "Создать запись", "drag_drop": "Перетащите файл сюда",
        "posts_count": "записей",
    },
    "en": {
        "reg": "Sign up", "login": "Sign in", "username": "username", "nickname": "nickname",
        "password": "password", "re_pass": "repeat password", "captcha": "I'm not a robot",
        "register_btn": "Create account", "login_btn": "Sign in", "profile": "PROFILE",
        "total_posts": "Total records", "logout": "Logout", "edit_profile": "Edit profile",
        "save_changes": "Save changes", "description": "Bio", 
        "desc_placeholder": "Tell about yourself...",
        "create_post_btn": "Post", "create_post_placeholder": "What's happening?",
        "my_posts": "MY RECORDS", "user_posts": "RECORDS", 
        "no_posts": "No records yet...", "pin": "Pin", "unpin": "Unpin", "delete": "Delete", 
        "confirm_delete": "Delete record?", "created_by": "Created by:", "hosting": "Hosting:", 
        "back_home": "Back to home", "user_not_found": "User not found.", 
        "alert_captcha": "Confirm you are not a robot!", "alert_pass_mismatch": "Passwords do not match!", 
        "alert_nick_taken": "Nickname is taken!", "alert_bad_login": "Invalid login!", 
        "alert_desc_long": "Bio > 300 chars!", "link_profile": "(Link)", "cancel": "Cancel", 
        "username_label": "Name", "nickname_label": "Nickname", "bugreport_title": "Bug report", 
        "bugreport_name": "Your name", "bugreport_desc": "Issue description", "bugreport_send": "Send", 
        "bugreport_my": "My reports", "privacy_title": "Privacy Policy",
        "privacy_text": "1. Data Collection. We collect only your username, nickname, and hashed password.\n\n2. Data Usage. Data is used for authentication.\n\n3. Content. Your records are stored on Supabase.\n\n4. Cookies. The site uses cookies for session and language.\n\n5. Your Rights. You can edit your profile or delete records.",
        "privacy_agree": "I agree to the", "privacy_link": "Privacy Policy",
        "alert_privacy": "Accept the Privacy Policy!", "cabinet": "Solid",
        "record_page": "Post", "copy_link": "Link", 
        "ext_title": "Leaving site", "ext_desc": "You are leaving our site and going to:", 
        "ext_continue": "Continue", "ext_loading": "Loading preview...",
        "suggestions_title": "SUGGESTIONS", "suggestions_btn": "Suggest a post",
        "sugges_title": "Suggest a post for", "sugges_name": "Your name",
        "sugges_content": "Post text", "sugges_send": "Send",
        "sugges_success": "Suggestion sent! Thank you!",
        "sugges_empty": "No suggestions yet...",
        "sugges_approve": "Approve", "sugges_reject": "Reject",
        "suggested_by": "Suggested by:", "sugges_own": "You can't suggest to yourself.",
        "sugges_error_fill": "Fill all fields!", "sugges_error_self": "Can't suggest to yourself",
        "rules_title": "Suggestion rules", "rules_placeholder": "Write rules for people who suggest posts...",
        "rules_edit_label": "Suggestion rules (max 1000 chars)", "rules_alert_long": "Rules > 1000 chars!",
        "rules_none": "No rules set",
        "attach_photo": "Attach photo", "attach_avatar": "Avatar", "remove_photo": "Remove photo",
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
        "search_title": "SEARCH", "search_placeholder": "Enter query...",
        "search_type_all": "All", "search_type_authors": "Authors", "search_type_records": "Records",
        "search_author_filter": "Filter by author",
        "search_btn": "Search", "search_no_results": "Nothing found",
        "search_found_authors": "Found authors", "search_found_records": "Found records",
        "search_link": "Search", "stats_link": "Stats",
        "stats_title": "STATISTICS", "stats_users": "Users", "stats_posts": "Records",
        "stats_sugges": "Suggestions", "stats_started": "Server started", "stats_last_update": "Last update",
        "stats_uptime": "Uptime", "stats_contacts": "Contact administration",
        "stats_contacts_desc": "For questions and suggestions:", "stats_back": "Back to home",
        "home": "Home", "feed": "Feed", "back": "Back", "sign_in": "Sign in",
        "composer_hint": "What's happening?", "post": "Post", "photo": "Photo",
        "profile_posts": "posts", "loading": "Loading...",
        "settings": "Settings", "settings_title": "Settings",
        "appearance": "Appearance", "banner": "Profile banner",
        "avatar_zoom": "Avatar zoom", "avatar_hint": "Click avatar or drag file",
        "account": "Account", "language": "Language", "save": "Save", "saved": "Saved!",
        "suggestions_section": "Suggestions", "privacy_section": "Privacy",
        "post_created": "Posted!", "compose": "Compose",
        "compose_title": "Create post", "drag_drop": "Drop file here",
        "posts_count": "posts",
    }
}

def t(k, l="ru"): return LOCALES.get(l, LOCALES["ru"]).get(k, k)

def format_date(iso):
    if not iso: return ""
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except Exception: return iso[:10]

# --- CSS ---
_CSS_CACHE = None
def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        _CSS_CACHE = """
        <style>
            :root{
                --bg:#000;--bg-elev:#16181c;--bg-hover:#1d1f23;--bg-hover2:#222528;
                --border:#2f3336;--border-light:#3f4348;
                --text:#e7e9ea;--text-2:#71767b;--text-3:#536471;
                --accent:#1d9bf0;--accent-h:#1a8cd8;--accent-sub:rgba(29,155,240,.12);
                --success:#00ba7c;--success-h:#00a06b;--danger:#f4212e;--danger-h:#dc1a26;
                --warning:#ffd400;--purple:#7856ff;
                --r-sm:8px;--r-md:12px;--r-lg:16px;--r-xl:24px;--r-pill:9999px;
                --nav-w:275px;--main-w:600px;--side-w:300px;
            }
            *{box-sizing:border-box;margin:0;padding:0}
            html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
            body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
                background:var(--bg);color:var(--text);font-size:15px;line-height:1.4;
                min-height:100vh;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
                overflow-x:hidden}
            a{color:var(--accent);text-decoration:none}
            a:hover{text-decoration:underline}
            img{max-width:100%;display:block}
            @view-transition{navigation:auto}
            ::selection{background:var(--accent-sub);color:var(--text)}

            /* App Shell — 3 columns on desktop */
            .app-shell{display:grid;grid-template-columns:var(--nav-w) minmax(0,var(--main-w)) var(--side-w);
                gap:0;max-width:calc(var(--nav-w) + var(--main-w) + var(--side-w));margin:0 auto;min-height:100vh}
            @media(max-width:1180px){.app-shell{grid-template-columns:88px minmax(0,1fr) 280px}}
            @media(max-width:1000px){.app-shell{grid-template-columns:88px minmax(0,1fr);max-width:1000px}}
            @media(max-width:768px){.app-shell{grid-template-columns:1fr;max-width:100%}}

            /* Nav rail */
            .nav-rail{position:sticky;top:0;height:100vh;overflow-y:auto;padding:8px 12px;
                border-right:1px solid var(--border);display:flex;flex-direction:column;
                scrollbar-width:thin;scrollbar-color:var(--border) transparent;z-index:100}
            .nav-rail::-webkit-scrollbar{width:6px}
            .nav-rail::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
            .nav-rail-inner{display:flex;flex-direction:column;flex:1;gap:2px}
            .nav-logo{padding:14px 12px;display:flex;align-items:center;gap:12px;font-size:22px;
                font-weight:900;color:var(--text);text-decoration:none;border-radius:var(--r-pill);
                margin-bottom:6px;transition:background .15s;letter-spacing:-.5px}
            .nav-logo:hover{background:var(--bg-hover);text-decoration:none}
            .nav-logo svg{width:30px;height:30px;color:var(--accent);flex-shrink:0}
            .nav-item{display:flex;align-items:center;gap:18px;padding:12px;border-radius:var(--r-pill);
                color:var(--text);font-size:20px;font-weight:400;text-decoration:none;cursor:pointer;
                transition:background .15s;background:transparent;border:none;font-family:inherit;
                width:100%;text-align:left}
            .nav-item:hover{background:var(--bg-hover);text-decoration:none}
            .nav-item.active{font-weight:700}
            .nav-item.active svg{stroke-width:2.5}
            .nav-item svg{width:26px;height:26px;flex-shrink:0}
            .nav-item .nav-badge{background:var(--accent);color:white;font-size:12px;padding:2px 8px;
                border-radius:var(--r-pill);margin-left:auto;font-weight:700}
            .nav-primary{margin:12px 0;padding:14px;background:var(--accent);color:white;border:none;
                border-radius:var(--r-pill);font-size:16px;font-weight:700;cursor:pointer;
                transition:background .2s;font-family:inherit;width:100%}
            .nav-primary:hover{background:var(--accent-h)}

            /* User pill at bottom */
            .nav-user-wrap{margin-top:auto;display:flex;flex-direction:column;gap:6px;padding-top:8px}
            .nav-user{display:flex;align-items:center;gap:10px;padding:8px;border-radius:var(--r-pill);
                cursor:pointer;transition:background .15s;text-decoration:none;color:var(--text)}
            .nav-user:hover{background:var(--bg-hover);text-decoration:none}
            .nav-user-avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;
                background:var(--bg-elev);border:1px solid var(--border);flex-shrink:0;overflow:hidden}
            .nav-user-avatar img{width:100%;height:100%;object-fit:cover}
            .nav-user-placeholder{width:40px;height:40px;border-radius:50%;
                background:var(--bg-elev);border:1px solid var(--border);
                display:flex;align-items:center;justify-content:center;
                color:var(--text-2);flex-shrink:0}
            .nav-user-placeholder svg{width:22px;height:22px}
            .nav-user-info{min-width:0;flex:1;overflow:hidden}
            .nav-user-name{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
            .nav-user-handle{color:var(--text-2);font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

            /* Main column */
            .main-col{border-right:1px solid var(--border);min-height:100vh;display:flex;flex-direction:column}
            .main-header{position:sticky;top:0;z-index:50;background:rgba(0,0,0,.75);
                backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
                border-bottom:1px solid var(--border);padding:14px 16px;
                display:flex;align-items:center;gap:12px;min-height:54px}
            .main-header h1{font-size:20px;font-weight:800;letter-spacing:-.3px}
            .main-header-sub{font-size:12px;color:var(--text-2);margin-top:2px}
            .back-btn{background:transparent;border:none;color:var(--text);width:36px;height:36px;
                border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;
                transition:background .15s;padding:0;flex-shrink:0}
            .back-btn:hover{background:var(--bg-hover);text-decoration:none}
            .back-btn svg{width:22px;height:22px}

            /* Side column (footer on right) */
            .side-col{padding:20px 16px 20px 24px;display:flex;flex-direction:column;gap:16px}
            .side-card{background:var(--bg-elev);border:1px solid var(--border);
                border-radius:var(--r-lg);padding:16px;font-size:13px;color:var(--text-2)}
            .side-card h3{font-size:16px;color:var(--text);font-weight:800;margin-bottom:10px}
            .side-card .side-link{display:flex;justify-content:space-between;padding:8px 0;
                color:var(--text);text-decoration:none;font-size:14px;font-weight:500;
                border-bottom:1px solid var(--border)}
            .side-card .side-link:last-child{border-bottom:none}
            .side-card .side-link:hover{color:var(--accent);text-decoration:none}
            .side-card .side-link span{color:var(--text-2);font-size:12px}
            .side-contacts{line-height:1.8;word-break:break-all}
            .side-contacts a{color:var(--accent);font-size:12px}
            .side-version{font-size:11px;color:var(--text-3);text-align:center;padding-top:8px}
            .side-version a{color:var(--text-2)}

            /* Mobile footer only */
            .mobile-footer{display:none;padding:20px 16px;border-top:1px solid var(--border);
                font-size:12px;color:var(--text-2);text-align:center;line-height:1.8}
            .mobile-footer a{color:var(--text-2)}
            .mobile-footer .mlinks{display:flex;justify-content:center;flex-wrap:wrap;gap:4px 16px;margin-bottom:8px}
            .mobile-footer .mcontacts{font-size:11px;word-break:break-all}
            .mobile-footer .mcontacts a{color:var(--accent)}
            .mobile-footer .mversion{font-size:11px;color:var(--text-3);margin-top:6px}

            /* Composer (inline) */
            .composer{padding:14px 16px;border-bottom:1px solid var(--border)}
            .composer-form{display:flex;flex-direction:column;gap:10px}
            .composer-row{display:flex;gap:12px;align-items:flex-start}
            .composer-avatar{width:44px;height:44px;border-radius:50%;object-fit:cover;
                background:var(--bg-elev);border:1px solid var(--border);flex-shrink:0;overflow:hidden;
                display:flex;align-items:center;justify-content:center;color:var(--text-2)}
            .composer-avatar img{width:100%;height:100%;object-fit:cover}
            .composer-avatar svg{width:22px;height:22px}
            .composer textarea{width:100%;background:transparent;border:none;color:var(--text);
                font-size:20px;font-family:inherit;resize:none;min-height:56px;outline:none;padding:8px 0;
                line-height:1.4}
            .composer textarea::placeholder{color:var(--text-3)}
            .composer-toolbar{display:flex;align-items:center;justify-content:space-between;
                gap:12px;padding-top:10px;border-top:1px solid var(--border)}
            .composer-tools{display:flex;gap:4px}
            .composer-tool{background:transparent;border:none;color:var(--accent);width:38px;height:38px;
                border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;
                transition:background .15s;padding:0;position:relative}
            .composer-tool:hover{background:var(--accent-sub)}
            .composer-tool svg{width:20px;height:20px}
            .composer-tool input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer}
            .composer-submit{background:var(--accent);color:white;border:none;
                padding:8px 22px;border-radius:var(--r-pill);font-size:15px;font-weight:700;
                cursor:pointer;transition:background .2s;font-family:inherit}
            .composer-submit:hover{background:var(--accent-h)}
            .composer-submit:disabled{opacity:.5;cursor:not-allowed}
            .composer-img-preview{max-height:320px;width:auto;border-radius:var(--r-lg);
                margin-top:10px;display:none;cursor:zoom-in;border:1px solid var(--border)}

            /* Posts */
            .feed{display:flex;flex-direction:column}
            .post-wrapper{position:relative}
            .post-wrapper:hover .post-actions{opacity:1}
            .post-item{padding:14px 16px;border-bottom:1px solid var(--border);
                transition:background .15s;position:relative}
            .post-item:hover{background:rgba(255,255,255,.02)}
            .post-item.pinned{background:rgba(255,212,0,.03)}
            .post-item.pinned::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
                background:var(--warning)}
            .post-content{font-size:15px;line-height:1.55;word-wrap:break-word;
                white-space:pre-wrap;color:var(--text);margin-bottom:8px}
            .post-content .ext-link{color:var(--accent)}
            .post-content .ext-link:hover{text-decoration:underline}
            .post-image{width:100%;max-height:500px;object-fit:cover;
                border-radius:var(--r-lg);border:1px solid var(--border);
                margin:8px 0;cursor:zoom-in}
            .post-footer{display:flex;justify-content:space-between;align-items:center;
                gap:12px;flex-wrap:wrap;font-size:13px;color:var(--text-2)}
            .post-suggested{color:var(--success);font-size:12px;font-weight:600}
            .post-date{font-size:13px;color:var(--text-2)}
            .post-actions{position:absolute;top:8px;right:8px;display:flex;gap:4px;z-index:10;
                opacity:0;transition:opacity .2s}
            .action-btn{background:rgba(22,24,28,.9);backdrop-filter:blur(8px);
                color:var(--text-2);border:1px solid var(--border);padding:5px 10px;
                border-radius:var(--r-pill);font-size:11px;font-weight:600;cursor:pointer;
                transition:all .15s;font-family:inherit;width:auto}
            .action-btn:hover{background:var(--bg-hover);color:var(--text)}
            .action-btn.link-btn:hover{color:var(--accent);border-color:var(--accent)}
            .action-btn.pin-btn:hover{color:var(--warning);border-color:var(--warning)}
            .action-btn.del-btn:hover{color:var(--danger);border-color:var(--danger)}
            .empty-state{padding:48px 24px;text-align:center;color:var(--text-2);
                font-size:15px;border-bottom:1px solid var(--border)}

            /* Buttons */
            .btn,button{background:var(--accent);color:white;border:none;padding:10px 20px;
                border-radius:var(--r-pill);font-size:15px;font-weight:700;cursor:pointer;
                transition:background .15s;font-family:inherit;display:inline-flex;
                align-items:center;justify-content:center;text-decoration:none}
            .btn:hover{background:var(--accent-h);text-decoration:none}
            .btn:disabled{opacity:.5;cursor:not-allowed}
            .btn-secondary{background:transparent;color:var(--text);border:1px solid var(--border)}
            .btn-secondary:hover{background:var(--bg-hover)}
            .btn-danger{background:var(--danger)}
            .btn-danger:hover{background:var(--danger-h)}
            .btn-success{background:var(--success)}
            .btn-success:hover{background:var(--success-h)}

            /* Inputs */
            input[type=text],input[type=password],input[type=email],textarea,select{
                background:var(--bg);color:var(--text);border:1px solid var(--border);
                border-radius:var(--r-sm);padding:12px 16px;font-size:15px;font-family:inherit;
                width:100%;outline:none;transition:border-color .15s,box-shadow .15s}
            input:focus,textarea:focus,select:focus{border-color:var(--accent);
                box-shadow:0 0 0 1px var(--accent)}
            input[type=file]{background:transparent;color:var(--text-2);padding:8px;
                cursor:pointer;font-size:14px;border:1px dashed var(--border);
                border-radius:var(--r-sm);width:100%}
            input[type=file]::file-selector-button{background:var(--accent);color:white;
                border:none;padding:8px 14px;border-radius:var(--r-pill);
                font-family:inherit;font-weight:700;font-size:13px;cursor:pointer;
                margin-right:10px;transition:background .15s}
            input[type=file]::file-selector-button:hover{background:var(--accent-h)}
            input[type=checkbox]{accent-color:var(--accent)}
            input[type=range]{accent-color:var(--accent);width:100%}

            /* Auth */
            .auth-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;
                padding:24px 16px;flex-direction:column;gap:20px}
            .auth-card{background:var(--bg-elev);border:1px solid var(--border);
                border-radius:var(--r-xl);padding:40px;width:100%;max-width:440px;
                box-shadow:0 8px 40px rgba(0,0,0,.4)}
            .auth-logo-wrap{display:flex;justify-content:center;margin-bottom:16px}
            .auth-logo-wrap svg{width:48px;height:48px;color:var(--accent)}
            .auth-card h1{font-size:32px;font-weight:900;margin-bottom:6px;
                text-align:center;letter-spacing:-1px}
            .auth-sub{color:var(--text-2);text-align:center;margin-bottom:24px;font-size:15px}
            .auth-tabs{display:flex;background:var(--bg);border-radius:var(--r-pill);
                padding:4px;margin-bottom:20px;border:1px solid var(--border)}
            .auth-tab{flex:1;padding:10px;text-align:center;border-radius:var(--r-pill);
                cursor:pointer;font-weight:700;color:var(--text-2);transition:all .15s;
                font-size:15px;background:transparent;border:none;font-family:inherit}
            .auth-tab.active{background:var(--bg-elev);color:var(--text)}
            .auth-panel{display:flex;flex-direction:column;gap:12px}
            .auth-input-wrap{position:relative}
            .auth-input-wrap input{padding-right:48px}
            .captcha-row{display:flex;align-items:center;gap:10px;padding:12px 16px;
                background:var(--bg);border:1px solid var(--border);
                border-radius:var(--r-sm);cursor:pointer;font-size:14px;color:var(--text-2)}
            .captcha-row input[type=checkbox]{width:18px;height:18px;cursor:pointer;
                flex-shrink:0;accent-color:var(--accent)}
            .captcha-row a{color:var(--accent)}
            .eye-btn{position:absolute;right:8px;top:50%;transform:translateY(-50%);
                background:transparent;border:none;color:var(--text-2);cursor:pointer;
                width:34px;height:34px;padding:6px;display:flex;align-items:center;
                justify-content:center;border-radius:50%}
            .eye-btn:hover{background:var(--bg-hover);color:var(--text)}

            .error-msg{color:#ff8a95;font-size:14px;padding:12px 16px;
                background:rgba(244,33,46,.12);border:1px solid rgba(244,33,46,.3);
                border-radius:var(--r-sm);margin-bottom:12px;text-align:center}
            .error-msg:empty{display:none}

            /* Lang switch */
            .lang-switch{display:flex;justify-content:center;gap:6px;margin-top:16px}
            .lang-btn{background:transparent;border:1px solid var(--border);color:var(--text-2);
                padding:6px 16px;border-radius:var(--r-pill);font-size:13px;font-weight:700;
                cursor:pointer;text-decoration:none;transition:all .15s;width:auto;
                display:inline-flex;align-items:center;justify-content:center}
            .lang-btn:hover{background:var(--bg-hover);color:var(--text);text-decoration:none}
            .lang-btn.active{background:var(--accent);border-color:var(--accent);color:white}

            /* Profile */
            .profile-banner{height:180px;position:relative;overflow:hidden}
            .profile-banner.has-img{background-size:cover;background-position:center}
            .profile-head{padding:16px 20px 20px;position:relative}
            .profile-avatar-wrap{margin-top:-70px;margin-bottom:12px;display:inline-block;position:relative}
            .profile-avatar-clip{width:120px;height:120px;border-radius:50%;
                border:4px solid var(--bg);overflow:hidden;background:var(--bg-elev);
                display:flex;align-items:center;justify-content:center;cursor:pointer;
                transition:transform .15s;position:relative}
            .profile-avatar-clip:hover{transform:scale(1.02)}
            .profile-avatar-clip img{width:100%;height:100%;object-fit:cover;
                transition:transform .2s;transform-origin:center}
            .profile-avatar-clip svg{width:48px;height:48px;color:var(--text-2)}
            .profile-name{font-size:22px;font-weight:900;margin-bottom:2px;letter-spacing:-.3px}
            .profile-handle{color:var(--text-2);font-size:15px;margin-bottom:14px}
            .profile-bio{font-size:15px;line-height:1.55;margin-bottom:14px;
                white-space:pre-wrap;word-wrap:break-word;color:var(--text)}
            .profile-meta{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px;
                font-size:14px;color:var(--text-2)}
            .profile-meta b{color:var(--text);font-weight:700}
            .profile-actions{display:flex;gap:8px;flex-wrap:wrap}
            .profile-actions .btn{padding:9px 20px;font-size:14px}
            .back-link{color:var(--accent);font-size:14px;display:inline-flex;align-items:center;gap:6px}
            .back-link svg{width:16px;height:16px}

            /* Settings */
            .settings-body{padding:20px 16px 40px;max-width:640px;width:100%;margin:0 auto;
                display:flex;flex-direction:column;gap:20px}
            .settings-section{background:var(--bg-elev);border:1px solid var(--border);
                border-radius:var(--r-lg);padding:20px}
            .settings-section h2{font-size:16px;font-weight:800;margin-bottom:16px;
                text-transform:uppercase;letter-spacing:.5px;color:var(--text-2);font-size:13px}
            .settings-field{margin-bottom:16px}
            .settings-field:last-child{margin-bottom:0}
            .settings-field label{display:block;font-size:13px;color:var(--text-2);
                margin-bottom:8px;font-weight:500}
            .settings-save{position:sticky;bottom:20px;background:var(--accent);
                color:white;border:none;padding:14px;border-radius:var(--r-pill);
                font-size:16px;font-weight:700;cursor:pointer;font-family:inherit;
                box-shadow:0 4px 20px rgba(29,155,240,.35);transition:background .15s;
                margin-top:20px}
            .settings-save:hover{background:var(--accent-h)}

            /* Banner swatches */
            .banner-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(60px,1fr));gap:8px}
            .banner-swatch{aspect-ratio:1;border-radius:var(--r-sm);cursor:pointer;
                border:2px solid transparent;transition:all .15s;position:relative;overflow:hidden}
            .banner-swatch:hover{transform:scale(1.05)}
            .banner-swatch.active{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-sub)}
            .banner-swatch::after{content:'';position:absolute;inset:0;
                background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.15),transparent 60%)}
            .banner-preview{height:80px;border-radius:var(--r-md);margin-bottom:12px;
                background:var(--accent);position:relative;overflow:hidden}

            /* Avatar upload in settings */
            .avatar-upload-wrap{display:flex;flex-direction:column;align-items:center;gap:12px}
            .avatar-preview-wrap{position:relative;width:120px;height:120px;border-radius:50%;
                overflow:hidden;background:var(--bg);border:3px solid var(--border);
                cursor:pointer;transition:border-color .15s}
            .avatar-preview-wrap:hover{border-color:var(--accent)}
            .avatar-preview-wrap.dragover{border-color:var(--accent);background:var(--accent-sub)}
            .avatar-preview-wrap img{width:100%;height:100%;object-fit:cover;
                transform-origin:center;transition:transform .15s}
            .avatar-preview-wrap .placeholder{width:100%;height:100%;display:flex;
                align-items:center;justify-content:center;color:var(--text-2)}
            .avatar-preview-wrap .placeholder svg{width:48px;height:48px}
            .avatar-hint{font-size:12px;color:var(--text-2);text-align:center}
            .zoom-row{display:flex;align-items:center;gap:10px;width:100%;max-width:280px}
            .zoom-row input[type=range]{flex:1}
            .zoom-val{font-size:13px;color:var(--text-2);font-variant-numeric:tabular-nums;
                min-width:44px;text-align:right}

            /* Toggle */
            .toggle-row{display:flex;align-items:center;justify-content:space-between;
                gap:12px;padding:14px 16px;background:var(--bg);border:1px solid var(--border);
                border-radius:var(--r-md);cursor:pointer;font-size:15px;font-weight:500;
                transition:border-color .15s}
            .toggle-row:hover{border-color:var(--border-light)}
            .toggle-row input[type=checkbox]{width:20px;height:20px;cursor:pointer;
                flex-shrink:0;accent-color:var(--accent)}

            /* Suggestions */
            .suggestion-card{padding:16px;border-bottom:1px solid var(--border);
                transition:background .15s}
            .suggestion-card:hover{background:rgba(255,255,255,.02)}
            .sugg-author{display:flex;justify-content:space-between;align-items:center;
                gap:12px;margin-bottom:10px;flex-wrap:wrap}
            .sugg-name{font-weight:700;font-size:15px}
            .sugg-date{font-size:13px;color:var(--text-2)}
            .sugg-content{font-size:15px;line-height:1.55;margin-bottom:12px;
                white-space:pre-wrap;word-wrap:break-word}
            .sugg-actions{display:flex;gap:8px}
            .sugg-actions .btn{padding:8px 16px;font-size:14px}
            .rules-box{background:var(--accent-sub);border:1px solid rgba(29,155,240,.3);
                border-left:3px solid var(--accent);border-radius:var(--r-md);
                padding:14px 16px;margin-bottom:16px}
            .rules-box b{display:block;margin-bottom:8px;font-size:14px;color:var(--accent)}
            .rules-content{font-size:14px;white-space:pre-wrap;line-height:1.55;color:var(--text)}

            /* Status */
            .status-badge{display:inline-block;padding:4px 10px;border-radius:var(--r-pill);
                font-size:12px;font-weight:700;color:white}
            .status-Принято,.status-Accepted{background:var(--accent)}
            .status-В-работе,.status-In-Progress{background:var(--warning);color:#000}
            .status-Исправлено,.status-Fixed{background:var(--success)}
            .status-Отклонено,.status-Rejected{background:var(--danger)}

            /* Toast */
            #toast{position:fixed;bottom:88px;left:50%;transform:translateX(-50%) translateY(20px);
                background:var(--accent);color:white;padding:12px 22px;
                border-radius:var(--r-pill);font-weight:600;font-size:14px;
                opacity:0;pointer-events:none;transition:opacity .3s,transform .3s;
                z-index:9999;text-align:center;max-width:90vw;word-break:break-word;
                box-shadow:0 4px 16px rgba(29,155,240,.35)}
            #toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

            /* Modals */
            .modal-overlay{display:none;position:fixed;inset:0;background:rgba(91,112,131,.4);
                backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);
                z-index:10000;justify-content:center;align-items:center;padding:16px;
                animation:fadeIn .15s ease}
            .modal-overlay.show{display:flex}
            @keyframes fadeIn{from{opacity:0}to{opacity:1}}
            .modal-box{background:var(--bg);border:1px solid var(--border);
                border-radius:var(--r-xl);padding:24px;max-width:440px;width:100%;
                box-shadow:0 8px 32px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto;
                animation:scaleIn .15s ease}
            @keyframes scaleIn{from{transform:scale(.95);opacity:0}to{transform:scale(1);opacity:1}}
            .modal-box h3{font-size:20px;margin-bottom:12px}
            .modal-text{font-size:16px;color:var(--text-2);margin-bottom:20px}
            .modal-actions{display:flex;gap:8px;margin-top:20px;justify-content:flex-end;flex-wrap:wrap}
            .modal-close{position:absolute;top:16px;right:16px;background:transparent;
                border:none;color:var(--text-2);width:36px;height:36px;border-radius:50%;
                cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
            .modal-close:hover{background:var(--bg-hover);color:var(--text)}

            /* Compose modal */
            .compose-modal-box{max-width:560px;position:relative}
            .compose-modal-header{display:flex;justify-content:space-between;align-items:center;
                margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid var(--border)}
            .compose-modal-header h3{font-size:18px;font-weight:800}
            .compose-modal-form{display:flex;flex-direction:column;gap:12px}
            .compose-modal-form textarea{background:transparent;border:none;color:var(--text);
                font-size:20px;padding:8px 0;min-height:120px;resize:none;font-family:inherit}
            .compose-modal-form textarea::placeholder{color:var(--text-3)}
            .compose-modal-form .composer-img-preview{display:none}
            .compose-modal-footer{display:flex;justify-content:space-between;align-items:center;
                padding-top:12px;border-top:1px solid var(--border);gap:12px}

            /* OG preview */
            .og-box{margin:16px 0;border:1px solid var(--border);border-radius:var(--r-md);
                overflow:hidden;background:var(--bg-elev)}
            .og-img{width:100%;max-height:220px;object-fit:cover}
            .og-title{padding:12px 16px 4px;font-size:15px;font-weight:700;margin:0}
            .og-desc{padding:0 16px 14px;font-size:14px;color:var(--text-2);margin:0}

            /* Image viewer */
            #img-viewer{position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:20000;
                display:none;justify-content:center;align-items:center;
                cursor:zoom-out;padding:20px}
            #img-viewer.show{display:flex}
            #img-viewer-img{max-width:95vw;max-height:95vh;object-fit:contain;
                border-radius:var(--r-md)}
            .img-viewer-close{position:absolute;top:20px;right:20px;
                background:rgba(255,255,255,.1);color:white;border:none;
                width:44px;height:44px;border-radius:50%;font-size:24px;cursor:pointer;
                display:flex;align-items:center;justify-content:center}
            .img-viewer-close:hover{background:rgba(255,255,255,.2)}

            /* Search */
            .search-form{padding:16px;border-bottom:1px solid var(--border);
                display:flex;flex-direction:column;gap:10px}
            .search-form-row{display:flex;gap:8px;flex-wrap:wrap}
            .search-form-row>*{flex:1;min-width:130px}
            .search-result{padding:14px 16px;border-bottom:1px solid var(--border);
                transition:background .15s}
            .search-result:hover{background:rgba(255,255,255,.02)}
            .search-result a{color:var(--text)}
            .search-result a:hover{color:var(--accent);text-decoration:none}
            .search-avatar{width:44px;height:44px;border-radius:50%;
                object-fit:cover;float:left;margin-right:12px;border:1px solid var(--border)}
            .search-empty{color:var(--text-2);text-align:center;padding:48px 20px;font-size:15px}
            .search-h{font-size:18px;font-weight:800;padding:16px 20px 10px;color:var(--text)}

            /* Stats */
            .stat-row{display:flex;justify-content:space-between;align-items:center;
                gap:12px;padding:16px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap}
            .stat-row b{font-size:15px;color:var(--text-2);font-weight:400}
            .stat-val{font-weight:800;color:var(--text);font-size:22px}
            .contacts-box{background:var(--bg-elev);border:1px solid var(--border);
                border-radius:var(--r-lg);padding:20px;margin:20px}
            .contacts-box b{display:block;margin-bottom:8px;font-size:16px}
            .contacts-box a{color:var(--accent);word-break:break-all}

            /* Privacy */
            .privacy-body{padding:20px;font-size:15px;line-height:1.75;
                color:var(--text);white-space:pre-wrap;word-wrap:break-word;max-width:760px;margin:0 auto}

            /* Mobile bottom nav */
            .mobile-nav{display:none;position:fixed;bottom:0;left:0;right:0;
                background:rgba(0,0,0,.88);backdrop-filter:blur(16px);
                -webkit-backdrop-filter:blur(16px);border-top:1px solid var(--border);
                z-index:1000;padding:6px 0 calc(6px + env(safe-area-inset-bottom,0))}
            .mobile-nav-inner{display:flex;justify-content:space-around;align-items:center;
                max-width:520px;margin:0 auto}
            .mobile-nav-item{display:flex;flex-direction:column;align-items:center;gap:3px;
                padding:8px 14px;color:var(--text-2);text-decoration:none;
                font-size:11px;font-weight:500;transition:color .15s;background:transparent;
                border:none;cursor:pointer;font-family:inherit}
            .mobile-nav-item:hover{text-decoration:none}
            .mobile-nav-item.active{color:var(--text)}
            .mobile-nav-item.active svg{stroke-width:2.5}
            .mobile-nav-item svg{width:24px;height:24px}
            .mobile-compose{background:var(--accent);color:white;width:48px;height:48px;
                border-radius:50%;display:flex;align-items:center;justify-content:center;
                padding:0;box-shadow:0 4px 12px rgba(29,155,240,.4);margin:0 4px}
            .mobile-compose:hover{background:var(--accent-h)}
            .mobile-compose svg{width:22px;height:22px}

            /* Responsive */
            @media(max-width:1180px){
                .nav-rail{padding:8px}
                .nav-logo{padding:14px 0;justify-content:center}
                .nav-logo span{display:none}
                .nav-item{justify-content:center;padding:12px;gap:0}
                .nav-item span{display:none}
                .nav-item .nav-badge{display:none}
                .nav-primary{padding:0;height:52px;display:flex;align-items:center;justify-content:center}
                .nav-primary span{display:none}
                .nav-primary::before{content:'+';font-size:28px;font-weight:300;line-height:1}
                .nav-user{padding:6px;justify-content:center}
                .nav-user-info{display:none}
                .nav-user-wrap{display:flex;flex-direction:column;align-items:center}
                .nav-user-wrap .logout-btn{width:44px;height:44px;padding:0}
                .nav-user-wrap .logout-btn span{display:none}
            }
            @media(max-width:1000px){
                .side-col{display:none}
                .mobile-footer{display:block}
            }
            @media(max-width:768px){
                body{padding-bottom:72px}
                .nav-rail{display:none}
                .main-col{border-right:none}
                .mobile-nav{display:block}
                .main-header{padding:12px 14px;min-height:50px}
                .main-header h1{font-size:18px}
                .composer{padding:12px 14px}
                .composer textarea{font-size:18px;min-height:50px}
                .post-item{padding:12px 14px}
                .post-content{font-size:15px}
                .post-actions{opacity:1}
                .action-btn{padding:4px 8px;font-size:10px}
                .auth-card{padding:24px 20px;border-radius:var(--r-lg)}
                .auth-card h1{font-size:26px}
                .auth-wrap{padding:16px}
                .profile-banner{height:120px}
                .profile-avatar-clip{width:92px;height:92px}
                .profile-avatar-wrap{margin-top:-56px}
                .profile-name{font-size:20px}
                .profile-avatar-clip svg{width:36px;height:36px}
                .settings-body{padding:16px 12px 40px}
                .settings-section{padding:16px}
                .modal-box{padding:20px;border-radius:var(--r-lg)}
                /* Bottom sheet for compose on mobile */
                .compose-modal-overlay{align-items:flex-end;padding:0}
                .compose-modal-box{border-radius:var(--r-xl) var(--r-xl) 0 0;
                    max-height:90vh;padding-bottom:calc(24px + env(safe-area-inset-bottom,0))}
                .avatar-preview-wrap{width:100px;height:100px}
                .side-card{display:none}
            }
            @media(max-width:400px){
                .mobile-nav-item{padding:6px 10px;font-size:10px}
                .mobile-nav-item svg{width:22px;height:22px}
                .mobile-compose{width:44px;height:44px}
            }
            /* Reduced motion */
            @media(prefers-reduced-motion:reduce){
                *,*::before,*::after{animation-duration:.01ms!important;
                    animation-iteration-count:1!important;transition-duration:.01ms!important}
            }
        </style>
        """
    return _CSS_CACHE

def get_js(lang, token, current_user="", current_avatar=""):
    js = """
    <script>
        const T = "__TOKEN__";
        const ME = "__ME__";
        const L = {
            d:"__DEL__",p:"__PIN__",u:"__UNPIN__",c:"__CONFIRM__",
            n:"__NOPOSTS__",cl:"__COPYLINK__",sf:"__SUGG_FILL__",ss:"__SUGG_SELF__",su:"__SUGG_SUCCESS__",
            ic:"__IMG_COMPRESSING__",ir:"__IMG_READY__",ie:"__IMG_ERROR__",ib:"__IMG_BIG__",
            tn:"__TOAST_NEW__",tl:"__TOAST_LINK__",tc:"__TOAST_COPY_FAIL__",
            tar:"__TOAST_APPROVED_REMOVED__",trr:"__TOAST_REJECTED_REMOVED__",tf:"__TOAST_FAILED__",
            saved:"__SAVED__",pc:"__POST_CREATED__",drag:"__DRAG_DROP__"
        };
        // ---- Core utilities ----
        function $(id){return document.getElementById(id)}
        function viewImage(src){if(!src)return;$('img-viewer-img').src=src;$('img-viewer').classList.add('show');document.body.style.overflow='hidden'}
        function closeImgViewer(){$('img-viewer').classList.remove('show');document.body.style.overflow=''}
        document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeImgViewer();closeLinkModal();closeCompose()}});

        function showToast(msg){const t=$('toast');if(!t)return;t.innerText=msg;t.classList.add('show');clearTimeout(window.__tt);window.__tt=setTimeout(()=>t.classList.remove('show'),3000)}
        function showConfirm(msg,cb){const m=$('modal-overlay');$('modal-text').innerText=msg;m.classList.add('show');
            const cBtn=$('modal-confirm'),xBtn=$('modal-cancel');
            const nC=cBtn.cloneNode(true),nX=xBtn.cloneNode(true);
            cBtn.parentNode.replaceChild(nC,cBtn);xBtn.parentNode.replaceChild(nX,xBtn);
            nC.onclick=()=>{m.classList.remove('show');cb(true)};nX.onclick=()=>{m.classList.remove('show');cb(false)}}

        // ---- Image compression ----
        async function compressImage(file,maxWidth=1000,quality=0.75){
            return new Promise((res,rej)=>{
                if(!file.type.startsWith('image/'))return rej('Not an image');
                const r=new FileReader();
                r.onload=e=>{const img=new Image();img.onload=()=>{
                    try{const c=document.createElement('canvas');
                        let w=img.width,h=img.height;
                        if(w>maxWidth){h=Math.round(h*maxWidth/w);w=maxWidth}
                        c.width=w;c.height=h;const ctx=c.getContext('2d');
                        ctx.fillStyle='#000';ctx.fillRect(0,0,w,h);
                        ctx.drawImage(img,0,0,w,h);
                        let b64=c.toDataURL('image/jpeg',quality);let q=quality;
                        while(b64.length>800000&&q>0.3){q-=0.1;b64=c.toDataURL('image/jpeg',q)}
                        if(b64.length>850000)return rej('Image too big');
                        res(b64)}catch(err){rej(err)}};
                    img.onerror=()=>rej('Load error');img.src=e.target.result};
                r.onerror=()=>rej('Read error');r.readAsDataURL(file)})}

        // ---- Service worker ----
        if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(()=>{})})}

        // ---- Prefetch on hover (SPA-like speed) ----
        const prefetched=new Set();
        document.addEventListener('mouseover',e=>{
            const a=e.target.closest('a[href]');if(!a)return;
            if(a.target==='_blank'||a.href.startsWith('mailto:'))return;
            try{const u=new URL(a.href);if(u.origin!==location.origin)return;
                if(prefetched.has(u.pathname))return;prefetched.add(u.pathname);
                const l=document.createElement('link');l.rel='prefetch';l.href=a.href;
                l.as='document';document.head.appendChild(l)}catch(_){}});

        // ---- WebSocket ----
        let ws;
        function connectWS(){try{
            const proto=location.protocol==='https:'?'wss://':'ws://';
            ws=new WebSocket(proto+location.host+'/ws');
            ws.onmessage=e=>{try{const d=JSON.parse(e.data);
                if(d.type==='delete_record'){const p=$('post-'+d.post_id);if(p)p.remove()}
                else if(d.type==='new_record'){showToast(L.tn)}}catch(_){}};
            ws.onclose=()=>setTimeout(connectWS,5000);
        }catch(_){}}
        connectWS();

        // ---- RPC ----
        async function rpc(method,params){
            const res=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':T},
                body:JSON.stringify({method,params})});
            const data=await res.json();
            if(!res.ok)throw new Error(data.detail||data.error||'RPC Error');
            return data}

        // ---- Auth / password toggle ----
        function tp(i,b){const x=$(i);if(!x)return;
            if(x.type==='password'){x.type='text';b.innerHTML=`__SVG_EYE_OFF__`}
            else{x.type='password';b.innerHTML=`__SVG_EYE__`}}
        function showAuthTab(name){
            document.querySelectorAll('.auth-tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
            document.querySelectorAll('.auth-panel').forEach(p=>p.style.display=(p.dataset.tab===name?'flex':'none'));
            document.querySelectorAll('.error-msg').forEach(e=>{if(e.parentElement.classList.contains('auth-card'))e.style.display='none'})}

        // ---- Copy link ----
        function copyLink(user,rid){if(!user)return;
            const url=location.origin+'/'+user+'/'+rid;
            navigator.clipboard.writeText(url).then(()=>showToast(L.tl)).catch(()=>showToast(L.tc))}

        // ---- Post image handling ----
        window.postImageCache="";window.composeImageCache="";window.suggImageCache="";
        async function handlePostImage(input){
            const file=input.files[0];const preview=$('post-img-preview');const btn=$('create-post-btn');
            if(!file){window.postImageCache="";if(preview)preview.style.display='none';return}
            showToast(L.ic);if(btn)btn.disabled=true;
            try{const b64=await compressImage(file,1000,0.75);window.postImageCache=b64;
                if(preview){preview.src=b64;preview.style.display='block';preview.onclick=()=>viewImage(b64)}
                showToast(L.ir)}
            catch(e){window.postImageCache="";showToast(e==='Image too big'?L.ib:L.ie);input.value='';
                if(preview)preview.style.display='none'}
            finally{if(btn)btn.disabled=false}}
        async function handleComposeImage(input){
            const file=input.files[0];const preview=$('compose-img-preview');const btn=$('compose-submit-btn');
            if(!file){window.composeImageCache="";if(preview)preview.style.display='none';return}
            showToast(L.ic);if(btn)btn.disabled=true;
            try{const b64=await compressImage(file,1000,0.75);window.composeImageCache=b64;
                if(preview){preview.src=b64;preview.style.display='block';preview.onclick=()=>viewImage(b64)}
                showToast(L.ir)}
            catch(e){window.composeImageCache="";showToast(e==='Image too big'?L.ib:L.ie);input.value='';
                if(preview)preview.style.display='none'}
            finally{if(btn)btn.disabled=false}}
        async function handleSuggImage(input){
            const file=input.files[0];const preview=$('sugg-img-preview');const btn=$('sugg-submit-btn');
            if(!file){window.suggImageCache="";if(preview)preview.style.display='none';return}
            showToast(L.ic);if(btn)btn.disabled=true;
            try{const b64=await compressImage(file,1000,0.75);window.suggImageCache=b64;
                if(preview){preview.src=b64;preview.style.display='block';preview.onclick=()=>viewImage(b64)}
                showToast(L.ir)}
            catch(e){window.suggImageCache="";showToast(e==='Image too big'?L.ib:L.ie);input.value='';
                if(preview)preview.style.display='none'}
            finally{if(btn)btn.disabled=false}}

        // ---- Avatar handling (settings) ----
        window.avatarB64="";window.avatarZoom=1.0;
        async function handleAvatarFile(file){
            const hidden=$('avatar-data');const preview=$('avatar-preview-img');
            const placeholder=$('avatar-placeholder');const zoomRow=$('avatar-zoom-row');
            if(!file)return;
            if(!file.type.startsWith('image/')){showToast(L.ie);return}
            showToast(L.ic);
            try{const b64=await compressImage(file,500,0.85);
                window.avatarB64=b64;
                if(hidden)hidden.value=b64;
                if(preview){preview.src=b64;preview.style.display='block';preview.style.transform='scale('+window.avatarZoom+')'}
                if(placeholder)placeholder.style.display='none';
                if(zoomRow)zoomRow.style.display='flex';
                showToast(L.ir)}
            catch(e){showToast(e==='Image too big'?L.ib:L.ie)}}
        function handleAvatarInput(input){handleAvatarFile(input.files[0])}
        function handleAvatarDrop(e){e.preventDefault();
            const wrap=$('avatar-preview-wrap');if(wrap)wrap.classList.remove('dragover');
            const f=e.dataTransfer.files[0];if(f)handleAvatarFile(f)}
        function handleAvatarDragOver(e){e.preventDefault();
            const wrap=$('avatar-preview-wrap');if(wrap)wrap.classList.add('dragover')}
        function handleAvatarDragLeave(e){
            const wrap=$('avatar-preview-wrap');if(wrap)wrap.classList.remove('dragover')}
        function updateAvatarZoom(v){window.avatarZoom=parseFloat(v);
            const preview=$('avatar-preview-img');const val=$('avatar-zoom-val');
            if(preview)preview.style.transform='scale('+window.avatarZoom+')';
            if(val)val.innerText=Math.round(window.avatarZoom*100)+'%'}

        // ---- Banner selection ----
        window.selectedBanner="";
        function selectBanner(id){
            window.selectedBanner=id;
            document.querySelectorAll('.banner-swatch').forEach(s=>s.classList.toggle('active',s.dataset.banner===id));
            const prev=$('banner-preview');if(prev){
                const css=BANNERS_MAP[id]||BANNERS_MAP['default'];
                prev.style.background=css}
            const hidden=$('banner-id');if(hidden)hidden.value=id}
        const BANNERS_MAP=__BANNERS_JSON__;

        // ---- Compose modal/sheet ----
        function openCompose(){
            const m=$('compose-modal');if(!m)return;
            m.classList.add('show');document.body.style.overflow='hidden';
            setTimeout(()=>{const ta=$('compose-textarea');if(ta)ta.focus()},100)}
        function closeCompose(){
            const m=$('compose-modal');if(!m)return;
            m.classList.remove('show');document.body.style.overflow='';
            const ta=$('compose-textarea');if(ta)ta.value='';
            const preview=$('compose-img-preview');if(preview){preview.style.display='none';preview.src=''}
            window.composeImageCache=""}
        async function submitCompose(e){
            e.preventDefault();
            const ta=$('compose-textarea');const c=(ta.value||'').trim();
            if(!c)return;
            const btn=$('compose-submit-btn');if(btn)btn.disabled=true;
            const i=crypto.randomUUID();
            const img=window.composeImageCache||"";
            try{
                await rpc('create_record',{content:c,client_id:i,image_data:img});
                // Add to feed if present
                const feed=$('my-records-container');
                if(feed){
                    const empty=feed.querySelector('.empty-state');if(empty)empty.remove();
                    const now=new Date();
                    const dateStr=now.toLocaleDateString('ru-RU')+' '+now.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
                    const w=document.createElement('div');w.className='post-wrapper';w.id='post-'+i;
                    w.innerHTML='<div class="post-actions"><button onclick="copyLink(\''+ME+'\',\''+i+'\')" class="action-btn link-btn">'+L.cl+'</button><button onclick="hp(\''+i+'\',this)" class="action-btn pin-btn">'+L.p+'</button><button onclick="hd(\''+i+'\',this)" class="action-btn del-btn">'+L.d+'</button></div><div class="post-item"><div class="post-content">'+c.replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div>'+(img?'<img class="post-image" src="'+img+'" onclick="viewImage(this.src)">':'')+'<div class="post-footer"><div class="post-date">'+dateStr+'</div></div></div>';
                    let inserted=false;
                    for(const ww of feed.querySelectorAll('.post-wrapper')){
                        if(!ww.querySelector('.pinned')){feed.insertBefore(w,ww);inserted=true;break}}
                    if(!inserted)feed.appendChild(w);
                } else {
                    // No feed - redirect to /cabinet
                    window.location.href='/cabinet';
                    return;
                }
                closeCompose();
                showToast(L.pc);
            }catch(x){showToast(L.tf+' '+x.message)}
            finally{if(btn)btn.disabled=false}}

        // ---- Inline composer ----
        function goCompose(){
            const ta=document.querySelector('.composer textarea');
            if(ta){ta.focus();ta.scrollIntoView({behavior:'smooth',block:'center'})}
            else if($('compose-modal')){openCompose()}
            else{window.location.href='/cabinet'}}

        // ---- Create post (inline form) ----
        async function hc(e){
            e.preventDefault();
            const f=e.target,c=f.querySelector('textarea').value.trim();
            if(!c)return;
            const i=crypto.randomUUID();
            const n=new Date();
            const d=n.toLocaleDateString('ru-RU')+' '+n.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
            const img=window.postImageCache||"";
            const a=$('my-records-container');
            if(!a){return}
            const m=a.querySelector('.empty-state');if(m)m.remove();
            const w=document.createElement('div');w.className='post-wrapper';w.id='post-'+i;
            w.innerHTML='<div class="post-actions"><button onclick="copyLink(\''+ME+'\',\''+i+'\')" class="action-btn link-btn">'+L.cl+'</button><button onclick="hp(\''+i+'\',this)" class="action-btn pin-btn">'+L.p+'</button><button onclick="hd(\''+i+'\',this)" class="action-btn del-btn">'+L.d+'</button></div><div class="post-item"><div class="post-content">'+c.replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div>'+(img?'<img class="post-image" src="'+img+'" onclick="viewImage(this.src)">':'')+'<div class="post-footer"><div class="post-date">'+d+'</div></div></div>';
            let inserted=false;
            const wrappers=a.querySelectorAll('.post-wrapper');
            for(const ww of wrappers){
                if(!ww.querySelector('.pinned')){a.insertBefore(w,ww);inserted=true;break}}
            if(!inserted)a.appendChild(w);
            f.reset();
            window.postImageCache="";
            const preview=$('post-img-preview');if(preview)preview.style.display='none';
            try{await rpc('create_record',{content:c,client_id:i,image_data:img})}
            catch(x){w.remove();showToast(L.tf+' '+x.message)}}

        // ---- Delete post ----
        function hd(i){showConfirm(L.c,async(yes)=>{
            if(!yes)return;
            const w=$('post-'+i);if(!w)return;
            w.style.opacity='.3';
            setTimeout(()=>{w.style.display='none'},250);
            try{await rpc('delete_record',{post_id:i});w.remove()}
            catch(x){w.style.opacity='1';w.style.display='block';showToast(L.tf+' '+x.message)}})}

        // ---- Pin post ----
        async function hp(i,b){
            const w=$('post-'+i);if(!w)return;
            const p=w.querySelector('.post-item'),s=p.classList.contains('pinned');
            if(s){p.classList.remove('pinned');b.innerText=L.p}
            else{
                document.querySelectorAll('.post-item.pinned').forEach(el=>{
                    el.classList.remove('pinned');
                    const ww=el.closest('.post-wrapper');
                    if(ww){const btn=ww.querySelector('.pin-btn');if(btn)btn.innerText=L.p}});
                p.classList.add('pinned');b.innerText=L.u;
                const a=w.parentNode;a.insertBefore(w,a.firstChild)}
            try{await rpc('pin_record',{post_id:i})}
            catch(x){
                if(s){p.classList.add('pinned');b.innerText=L.u}
                else{p.classList.remove('pinned');b.innerText=L.p}
                showToast(L.tf+' '+x.message)}}

        // ---- Suggestions ----
        async function submitSuggestion(event){
            event.preventDefault();
            const f=event.target;const target=f.dataset.nickname;
            const name=f.querySelector('input[name="sugg_name"]').value.trim();
            const content=f.querySelector('textarea[name="content"]').value.trim();
            if(!name||!content){showToast(L.sf);return}
            if(ME&&target===ME){showToast(L.ss);return}
            const btn=f.querySelector('button[type=submit]');const img=window.suggImageCache||"";
            btn.disabled=true;
            try{await rpc('submit_suggestion',{target_nickname:target,sugg_name:name,content,image_data:img});
                showToast(L.su);f.reset();window.suggImageCache="";
                const preview=$('sugg-img-preview');if(preview)preview.style.display='none'}
            catch(x){showToast(L.tf+' '+x.message)}
            finally{btn.disabled=false}}
        async function approveSugg(id){try{await rpc('approve_suggestion',{suggestion_id:id});
            const card=$('sugg-'+id);if(card)card.remove();showToast(L.tar)}
            catch(x){showToast(L.tf+' '+x.message)}}
        async function rejectSugg(id){try{await rpc('reject_suggestion',{suggestion_id:id});
            const card=$('sugg-'+id);if(card)card.remove();showToast(L.trr)}
            catch(x){showToast(L.tf+' '+x.message)}}

        // ---- External link warning ----
        let pendingUrl="";
        async function showLinkWarning(e,el){
            e.preventDefault();pendingUrl=el.getAttribute('data-url');if(!pendingUrl)return;
            $('link-modal-confirm').href=pendingUrl;
            const ogBox=$('og-preview');
            ogBox.innerHTML='<p style="margin:0;font-size:14px;color:#71767b;padding:16px;">__EXT_LOADING__</p>';
            $('link-modal').classList.add('show');
            try{const res=await fetch('/api/og?url='+encodeURIComponent(pendingUrl));
                const data=await res.json();
                if(data.title||data.description||data.image){
                    let html='';
                    if(data.image)html+='<img src="'+data.image+'" class="og-img" onerror="this.style.display=\'none\'">';
                    if(data.title)html+='<h4 class="og-title">'+data.title+'</h4>';
                    if(data.description)html+='<p class="og-desc">'+data.description+'</p>';
                    ogBox.innerHTML=html}
                else{ogBox.innerHTML='<p style="margin:0;font-size:14px;color:#71767b;padding:16px;">No preview</p>'}}
            catch(err){ogBox.innerHTML='<p style="margin:0;font-size:14px;color:#71767b;padding:16px;">Failed to load</p>'}}
        function closeLinkModal(){$('link-modal').classList.remove('show')}

        // ---- Character counts ----
        function uc(e){const el=$('char-count');if(el)el.innerText=e.value.length+' / 300'}
        function ucRules(e){const el=$('rules-count');if(el)el.innerText=e.value.length+' / 1000'}

        // ---- Settings save ----
        async function saveSettings(e){
            e.preventDefault();
            const f=e.target;
            const data=new FormData(f);
            try{
                const res=await fetch('/settings',{method:'POST',body:data,redirect:'manual'});
                showToast(L.saved);
                // Reload to reflect changes
                setTimeout(()=>window.location.reload(),400);
            }catch(err){showToast(L.tf+' '+err.message)}}
    </script>
    """
    banners_json = "{" + ",".join(f'"{k}":"{v}"' for k, v in BANNERS.items()) + "}"
    reps = [("__TOKEN__",token),("__ME__",current_user),("__DEL__",t('delete',lang)),("__PIN__",t('pin',lang)),
        ("__UNPIN__",t('unpin',lang)),("__CONFIRM__",t('confirm_delete',lang)),("__NOPOSTS__",t('no_posts',lang)),
        ("__COPYLINK__",t('copy_link',lang)),("__EXT_LOADING__",t('ext_loading',lang)),
        ("__SUGG_FILL__",t('sugges_error_fill',lang)),("__SUGG_SELF__",t('sugges_error_self',lang)),
        ("__SUGG_SUCCESS__",t('sugges_success',lang)),("__IMG_COMPRESSING__",t('img_compressing',lang)),
        ("__IMG_READY__",t('img_ready',lang)),("__IMG_ERROR__",t('img_error',lang)),
        ("__IMG_BIG__",t('img_too_big',lang)),("__TOAST_NEW__",t('toast_new',lang)),
        ("__TOAST_LINK__",t('toast_link',lang)),("__TOAST_COPY_FAIL__",t('toast_copy_fail',lang)),
        ("__TOAST_APPROVED_REMOVED__",t('toast_approved_removed',lang)),("__TOAST_REJECTED_REMOVED__",t('toast_rejected_removed',lang)),
        ("__TOAST_FAILED__",t('toast_failed',lang)),("__SVG_EYE_OFF__",SVG_EYE_OFF),("__SVG_EYE__",SVG_EYE),
        ("__SAVED__",t('saved',lang)),("__POST_CREATED__",t('post_created',lang)),("__DRAG_DROP__",t('drag_drop',lang)),
        ("__BANNERS_JSON__",banners_json)]
    for k, v in reps: js = js.replace(k, v)
    return js

def get_overlay(lang):
    html_str = """
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay"><div class="modal-box"><p id="modal-text" class="modal-text"></p><div class="modal-actions"><button id="modal-cancel" class="btn btn-secondary">__CANCEL__</button><button id="modal-confirm" class="btn btn-danger">OK</button></div></div></div>
    <div id="compose-modal" class="modal-overlay compose-modal-overlay"><div class="modal-box compose-modal-box">
        <div class="compose-modal-header"><h3>__COMPOSE_TITLE__</h3><button type="button" class="modal-close" onclick="closeCompose()">__SVG_CLOSE__</button></div>
        <form class="compose-modal-form" onsubmit="submitCompose(event)">
            <textarea id="compose-textarea" placeholder="__COMPOSE_HINT__" required maxlength="500"></textarea>
            <img id="compose-img-preview" class="composer-img-preview">
            <div class="compose-modal-footer">
                <label class="composer-tool" style="cursor:pointer;" title="__PHOTO__">__SVG_IMAGE__<input type="file" accept="image/*" onchange="handleComposeImage(this)"></label>
                <button type="submit" id="compose-submit-btn" class="composer-submit">__POST_BTN__</button>
            </div>
        </form>
    </div></div>
    <div id="link-modal" class="modal-overlay"><div class="modal-box" style="position:relative;"><button class="modal-close" onclick="closeLinkModal()">__SVG_CLOSE__</button><h3>__EXT_TITLE__</h3><p class="modal-text" style="font-size:14px;">__EXT_DESC__</p><div id="og-preview" class="og-box"><p style="margin:0;font-size:14px;color:#71767b;padding:16px;">__EXT_LOADING__</p></div><div class="modal-actions"><button onclick="closeLinkModal()" class="btn btn-secondary">__CANCEL__</button><a id="link-modal-confirm" href="#" target="_blank" rel="noopener noreferrer" class="btn btn-danger">__EXT_CONTINUE__</a></div></div></div>
    <div id="img-viewer" onclick="if(event.target===this)closeImgViewer()"><button class="img-viewer-close" onclick="closeImgViewer()">&times;</button><img id="img-viewer-img" src="" alt=""></div>
    """
    for k, v in [("__CANCEL__", t('cancel',lang)),("__EXT_TITLE__", t('ext_title',lang)),("__EXT_DESC__", t('ext_desc',lang)),
        ("__EXT_LOADING__", t('ext_loading',lang)),("__EXT_CONTINUE__", t('ext_continue',lang)),
        ("__COMPOSE_TITLE__", t('compose_title',lang)),("__COMPOSE_HINT__", t('composer_hint',lang)),
        ("__PHOTO__", t('photo',lang)),("__POST_BTN__", t('post',lang)),
        ("__SVG_IMAGE__", SVG_IMAGE),("__SVG_CLOSE__", SVG_CLOSE)]:
        html_str = html_str.replace(k, v)
    return html_str

def side_footer(lang):
    contacts = "".join(f"<div class='side-contacts'><a href='mailto:{e}'>{e}</a></div>" for e in CONTACT_EMAILS)
    return f"""
    <aside class="side-card">
        <h3>Solid</h3>
        <a class="side-link" href="/search">{t('search_link',lang)} <span>→</span></a>
        <a class="side-link" href="/stats">{t('stats_link',lang)} <span>→</span></a>
        <a class="side-link" href="/privacy">{t('privacy_title',lang)} <span>→</span></a>
        <a class="side-link" href="/bugreport">{t('bugreport_title',lang)} <span>→</span></a>
    </aside>
    <aside class="side-card">
        <h3>{t('stats_contacts',lang)}</h3>
        {contacts}
    </aside>
    <div class="side-version">v{APP_VERSION} · {SERVER_START_DATE}<br><a href="http://solid-link.ddns.net" target="_blank" rel="noopener">Solid Link</a> · <a href="https://fastapicloud.com" target="_blank" rel="noopener">FastAPICloud</a></div>
    """

def mobile_footer(lang):
    contacts = "".join(f"<a href='mailto:{e}'>{e}</a> " for e in CONTACT_EMAILS)
    return f"""
    <div class="mobile-footer">
        <div class="mlinks">
            <a href="/privacy">{t('privacy_title',lang)}</a>
            <a href="/bugreport">{t('bugreport_title',lang)}</a>
            <a href="/search">{t('search_link',lang)}</a>
            <a href="/stats">{t('stats_link',lang)}</a>
        </div>
        <div class="mcontacts">{contacts}</div>
        <div class="mversion">v{APP_VERSION} · {SERVER_START_DATE} · <a href="http://solid-link.ddns.net" target="_blank" rel="noopener">Solid Link</a></div>
    </div>
    """

def mobile_nav(lang, active="home", logged_in=False, nickname="", avatar=""):
    home_href = "/cabinet" if logged_in else "/"
    profile_href = f"/{nickname}" if logged_in else "/"
    def item(key, href, label, icon, action=None):
        cls = "mobile-nav-item active" if key == active else "mobile-nav-item"
        if action:
            return f'<button class="{cls}" onclick="{action}" aria-label="{label}">{icon}<span>{label}</span></button>'
        return f'<a href="{href}" class="{cls}">{icon}<span>{label}</span></a>'
    html = '<nav class="mobile-nav"><div class="mobile-nav-inner">'
    html += item("search", "/search", t('search_link', lang), SVG_SEARCH)
    html += item("suggestions", "/cabinet/suggestions" if logged_in else "/", t('suggestions_title', lang).title(), SVG_BELL)
    html += f'<button class="mobile-nav-item mobile-compose" onclick="openCompose()" aria-label="Compose">{SVG_PLUS}</button>'
    html += item("profile", profile_href, t('profile', lang), SVG_USER)
    html += item("settings", "/settings" if logged_in else "/", t('settings', lang), SVG_SETTINGS)
    html += '</div></nav>'
    return html

def nav_rail(lang, active="home", nickname="", user=None, current_avatar=""):
    # Avatar resolution - prioritize passed user data, fallback to current_avatar
    avatar = ""
    if user:
        avatar = esc(user.get('avatar_data', '') or '')
    if not avatar:
        avatar = current_avatar or ""
    username = esc(user.get('username', '')) if user else ""
    zoom = _safe_zoom(user.get('avatar_zoom', 1.0)) if user else 1.0

    if avatar:
        user_avatar = f'<div class="nav-user-avatar"><img src="{avatar}" alt="avatar" style="transform:scale({zoom})"></div>'
    else:
        user_avatar = f'<div class="nav-user-placeholder">{SVG_USER}</div>'

    html = '<aside class="nav-rail"><div class="nav-rail-inner">'
    html += f'<a href="/cabinet" class="nav-logo">{SVG_LOGO}<span>Solid</span></a>'
    html += f'<a href="/cabinet" class="nav-item {"active" if active=="home" else ""}">{SVG_HOME}<span>{t("home",lang)}</span></a>'
    html += f'<a href="/cabinet/suggestions" class="nav-item {"active" if active=="suggestions" else ""}">{SVG_BELL}<span>{t("suggestions_title",lang).title()}</span></a>'
    html += f'<a href="/search" class="nav-item {"active" if active=="search" else ""}">{SVG_SEARCH}<span>{t("search_link",lang)}</span></a>'
    html += f'<a href="/settings" class="nav-item {"active" if active=="settings" else ""}">{SVG_SETTINGS}<span>{t("settings",lang)}</span></a>'
    html += f'<button class="nav-primary" onclick="openCompose()"><span>{t("post",lang)}</span></button>'
    html += '<div class="nav-user-wrap">'
    html += f'<a href="/{esc(nickname)}" class="nav-user">{user_avatar}<div class="nav-user-info"><div class="nav-user-name">{username or nickname}</div><div class="nav-user-handle">@{esc(nickname)}</div></div></a>'
    html += f'<form action="/logout" method="get" style="margin:0"><button type="submit" class="nav-item logout-btn" style="justify-content:center;padding:10px;">{SVG_LOGOUT}<span>{t("logout",lang)}</span></button></form>'
    html += '</div>'
    html += '</div></aside>'
    return html

def auth_html(lang, error_msg="", token="", active_tab="login"):
    eb = f"<div class='error-msg'>{error_msg}</div>" if error_msg else ""
    login_active = "active" if active_tab == "login" else ""
    register_active = "active" if active_tab == "register" else ""
    login_display = "flex" if active_tab == "login" else "none"
    register_display = "flex" if active_tab == "register" else "none"
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Solid"><meta name="mobile-web-app-capable" content="yes">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>Solid</title>__CSS____JS__</head><body>
    <div class="auth-wrap">
        <div class="auth-card">
            <div class="auth-logo-wrap">__LOGO__</div>
            <h1>Solid</h1>
            <p class="auth-sub">__SUB__</p>
            <div class="auth-tabs">
                <button type="button" class="auth-tab __LOGIN_ACTIVE__" data-tab="login" onclick="showAuthTab('login')">__LOGIN__</button>
                <button type="button" class="auth-tab __REG_ACTIVE__" data-tab="register" onclick="showAuthTab('register')">__REG__</button>
            </div>
            __ERROR__
            <div class="auth-panel" data-tab="login" style="display:__LOGIN_DISPLAY__">
                <form action="/login" method="post" class="auth-panel" style="display:flex;">
                    <input type="hidden" name="csrf_token" value="__TOKEN__">
                    <input type="text" name="nickname" placeholder="__NICKNAME__" required autocomplete="username">
                    <div class="auth-input-wrap">
                        <input type="password" name="password" id="lp" placeholder="__PASSWORD__" required autocomplete="current-password">
                        <button type="button" class="eye-btn" onclick="tp('lp',this)">__SVG_EYE__</button>
                    </div>
                    <label class="captcha-row"><input type="checkbox" name="captcha" required><span>__CAPTCHA__</span></label>
                    <button type="submit" style="margin-top:6px;">__LOGIN_BTN__</button>
                </form>
            </div>
            <div class="auth-panel" data-tab="register" style="display:__REG_DISPLAY__">
                <form action="/register" method="post" class="auth-panel" style="display:flex;">
                    <input type="hidden" name="csrf_token" value="__TOKEN__">
                    <input type="text" name="username" placeholder="__USERNAME__" required autocomplete="name">
                    <input type="text" name="nickname" placeholder="__NICKNAME__" required autocomplete="username">
                    <div class="auth-input-wrap">
                        <input type="password" name="password" id="rp" placeholder="__PASSWORD__" required autocomplete="new-password">
                        <button type="button" class="eye-btn" onclick="tp('rp',this)">__SVG_EYE__</button>
                    </div>
                    <div class="auth-input-wrap">
                        <input type="password" name="re_pass" id="rr" placeholder="__REPASS__" required autocomplete="new-password">
                        <button type="button" class="eye-btn" onclick="tp('rr',this)">__SVG_EYE__</button>
                    </div>
                    <label class="captcha-row"><input type="checkbox" name="captcha" required><span>__CAPTCHA__</span></label>
                    <label class="captcha-row"><input type="checkbox" name="privacy" required><span>__PRIVACY_AGREE__ <a href="/privacy" target="_blank">__PRIVACY_LINK__</a></span></label>
                    <button type="submit" style="margin-top:6px;">__REG_BTN__</button>
                </form>
            </div>
            <div class="lang-switch"><a href="/set_lang/ru?next=/" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
        </div>
    </div>
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),
        ("__LOGO__",SVG_LOGO),("__SUB__","Добро пожаловать в Solid" if lang=="ru" else "Welcome to Solid"),
        ("__LOGIN__",t('login',lang)),("__REG__",t('reg',lang)),
        ("__LOGIN_ACTIVE__",login_active),("__REG_ACTIVE__",register_active),
        ("__LOGIN_DISPLAY__",login_display),("__REG_DISPLAY__",register_display),
        ("__USERNAME__",t('username',lang)),("__NICKNAME__",t('nickname',lang)),
        ("__PASSWORD__",t('password',lang)),("__REPASS__",t('re_pass',lang)),
        ("__CAPTCHA__",t('captcha',lang)),("__PRIVACY_AGREE__",t('privacy_agree',lang)),
        ("__PRIVACY_LINK__",t('privacy_link',lang)),("__REG_BTN__",t('register_btn',lang)),
        ("__LOGIN_BTN__",t('login_btn',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),
        ("__EN_ACTIVE__","active" if lang=='en' else ""),("__ERROR__",eb),
        ("__OVERLAY__",get_overlay(lang)),("__SVG_EYE__",SVG_EYE)]:
        html_str = html_str.replace(k, v)
    return html_str

def render_records(records, lang, own=False, uid=None):
    if not records or not isinstance(records, list):
        return f"<div class='post-item empty-state'>{t('no_posts', lang)}</div>"
    out = ""
    for x in records:
        if not isinstance(x, dict): continue
        rid = esc(x.get('id'))
        if not rid: continue
        pinned = bool(x.get('is_pinned', False))
        content = linkify(x.get('content'))
        date = format_date(esc(x.get('created_at')))
        sugg_by = esc(x.get('suggested_by', ''))
        img = esc(x.get('image_data', ''))
        pc = "pinned" if pinned else ""
        acts = "<div class='post-actions'>"
        if uid: acts += f"<button onclick='copyLink(\"{x.get('user_nickname','')}\",\"{rid}\")' class='action-btn link-btn'>{t('copy_link', lang)}</button>"
        if own:
            acts += f"<button onclick='hp(\"{rid}\",this)' class='action-btn pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button>"
            acts += f"<button onclick='hd(\"{rid}\",this)' class='action-btn del-btn'>{t('delete', lang)}</button>"
        acts += "</div>"
        sugg_html = f"<div class='post-suggested'>{t('suggested_by', lang)} {sugg_by}</div>" if sugg_by else ""
        img_html = f'<img class="post-image" src="{img}" alt="" loading="lazy" onclick="viewImage(this.src)">' if img else ""
        item = f"<div class='post-wrapper' id='post-{rid}'>{acts}<div class='post-item {pc}'><div class='post-content'>{content}</div>{img_html}<div class='post-footer'>{sugg_html}<div class='post-date'>{date}</div></div></div></div>"
        out += item
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

def composer_form(lang, avatar_html, form_id="create-form"):
    return f"""
    <section class="composer">
        <form id="{form_id}" onsubmit="hc(event)" class="composer-form">
            <div class="composer-row">{avatar_html}<textarea name="content" placeholder="{t('composer_hint',lang)}" required maxlength="500" rows="2"></textarea></div>
            <img id="post-img-preview" class="composer-img-preview">
            <div class="composer-toolbar">
                <div class="composer-tools">
                    <label class="composer-tool" title="{t('photo',lang)}">{SVG_IMAGE}<input type="file" accept="image/*" onchange="handlePostImage(this)"></label>
                </div>
                <button type="submit" id="create-post-btn" class="composer-submit">{t('post',lang)}</button>
            </div>
        </form>
    </section>
    """

def dashboard_html(nickname, user, my_p, lang, token, viewer):
    rh_my = render_records(my_p, lang, own=True, uid=viewer)
    user_avatar = esc(user.get('avatar_data', ''))
    zoom = _safe_zoom(user.get('avatar_zoom', 1.0))
    if user_avatar:
        composer_avatar = f'<div class="composer-avatar"><img src="{user_avatar}" style="transform:scale({zoom})" alt=""></div>'
    else:
        composer_avatar = f'<div class="composer-avatar">{SVG_USER}</div>'
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Solid"><meta name="mobile-web-app-capable" content="yes">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><h1>Solid</h1></header>
            __COMPOSER__
            <div id="my-records-container" class="feed">__RECORDS_HTML__</div>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer, user_avatar)),
        ("__NAV_RAIL__",nav_rail(lang, "home", nickname, user)),
        ("__COMPOSER__",composer_form(lang, composer_avatar)),
        ("__RECORDS_HTML__",rh_my),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),
        ("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mobile_nav(lang, "home", True, nickname, user_avatar)),
        ("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def settings_html(nickname, user, lang, token):
    desc = esc(user.get('description') or '')
    rules = esc(user.get('sugges_rules') or '')
    avatar = esc(user.get('avatar_data') or '')
    username = esc(user.get('username') or '')
    banner_id = user.get('banner_id') or 'default'
    zoom = _safe_zoom(user.get('avatar_zoom', 1.0))
    sugges_checked = "checked" if user_sugges_enabled(user) else ""
    photo_checked = "checked" if user_sugges_photo_enabled(user) else ""

    # Banner swatches
    swatches = ""
    for bid, css in BANNERS.items():
        active = "active" if bid == banner_id else ""
        swatches += f'<div class="banner-swatch {active}" data-banner="{bid}" style="background:{css}" onclick="selectBanner(\'{bid}\')"></div>'

    # Avatar preview
    if avatar:
        avatar_preview = f'<img id="avatar-preview-img" src="{avatar}" style="transform:scale({zoom})" alt="">'
        zoom_row_style = "flex"
        placeholder_style = "none"
    else:
        avatar_preview = '<img id="avatar-preview-img" style="display:none" alt="">'
        zoom_row_style = "none"
        placeholder_style = "flex"

    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Solid"><meta name="mobile-web-app-capable" content="yes">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><a href="/cabinet" class="back-btn">__BACK_ICON__</a><h1>__TITLE__</h1></header>
            <form action="/settings" method="post" onsubmit="saveSettings(event)" class="settings-body">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <input type="hidden" name="avatar_data" id="avatar-data" value="">
                <input type="hidden" name="banner_id" id="banner-id" value="__BANNER_ID__">
                <input type="hidden" name="avatar_zoom" id="avatar-zoom-input" value="__ZOOM__">

                <div class="settings-section">
                    <h2>__APPEARANCE__</h2>
                    <div class="settings-field">
                        <label>__BANNER__</label>
                        <div class="banner-preview" id="banner-preview" style="background:__BANNER_CSS__"></div>
                        <div class="banner-grid">__SWATCHES__</div>
                    </div>
                    <div class="settings-field">
                        <label>__AVATAR__</label>
                        <div class="avatar-upload-wrap">
                            <div class="avatar-preview-wrap" id="avatar-preview-wrap"
                                onclick="document.getElementById('avatar-file-input').click()"
                                ondragover="handleAvatarDragOver(event)"
                                ondragleave="handleAvatarDragLeave(event)"
                                ondrop="handleAvatarDrop(event)">
                                <div class="placeholder" id="avatar-placeholder" style="display:__PLACEHOLDER_STYLE__">__SVG_USER__</div>
                                __AVATAR_PREVIEW__
                            </div>
                            <input type="file" id="avatar-file-input" accept="image/*" onchange="handleAvatarInput(this)" style="display:none">
                            <div class="avatar-hint">__AVATAR_HINT__</div>
                            <div class="zoom-row" id="avatar-zoom-row" style="display:__ZOOM_ROW_STYLE__">
                                <span style="font-size:13px;color:var(--text-2)">__AVATAR_ZOOM__</span>
                                <input type="range" min="0.5" max="2" step="0.05" value="__ZOOM__" oninput="updateAvatarZoom(this.value);document.getElementById('avatar-zoom-input').value=this.value">
                                <span class="zoom-val" id="avatar-zoom-val">__ZOOM_PCT__%</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="settings-section">
                    <h2>__ACCOUNT__</h2>
                    <div class="settings-field">
                        <label>__USERNAME_LABEL__</label>
                        <input type="text" name="username" value="__USERNAME__" required>
                    </div>
                    <div class="settings-field">
                        <label>__NICKNAME_LABEL__</label>
                        <input type="text" value="@__NICKNAME__" disabled style="opacity:.6;cursor:not-allowed">
                    </div>
                    <div class="settings-field">
                        <label>__DESCRIPTION__</label>
                        <textarea name="description" maxlength="300" placeholder="__DESC_PLACEHOLDER__" oninput="uc(this)" style="min-height:100px">__DESC__</textarea>
                        <div id="char-count" style="text-align:right;font-size:12px;color:var(--text-2);margin-top:4px">__DESC_LEN__ / 300</div>
                    </div>
                </div>

                <div class="settings-section">
                    <h2>__SUGGESTIONS_SECTION__</h2>
                    <div class="settings-field">
                        <label class="toggle-row"><span>__SUGGES_ENABLE_LABEL__</span><input type="checkbox" name="sugges_enabled" __SUGGES_CHECKED__></label>
                    </div>
                    <div class="settings-field">
                        <label class="toggle-row"><span>__SUGGES_PHOTO_ENABLE_LABEL__</span><input type="checkbox" name="sugges_photo_enabled" __PHOTO_CHECKED__></label>
                    </div>
                    <div class="settings-field">
                        <label>__RULES_LABEL__</label>
                        <textarea name="sugges_rules" maxlength="1000" placeholder="__RULES_PLACEHOLDER__" oninput="ucRules(this)" style="min-height:100px">__RULES__</textarea>
                        <div id="rules-count" style="text-align:right;font-size:12px;color:var(--text-2);margin-top:4px">__RULES_LEN__ / 1000</div>
                    </div>
                </div>

                <div class="settings-section">
                    <h2>__LANGUAGE__</h2>
                    <div class="lang-switch" style="justify-content:flex-start;margin-top:0">
                        <a href="/set_lang/ru?next=/settings" class="btn lang-btn __RU_ACTIVE__">Русский</a>
                        <a href="/set_lang/en?next=/settings" class="btn lang-btn __EN_ACTIVE__">English</a>
                    </div>
                </div>

                <button type="submit" class="settings-save">__SAVE__</button>
            </form>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    reps = [("__LANG__",lang),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname, avatar)),
        ("__NAV_RAIL__",nav_rail(lang, "settings", nickname, user)),
        ("__BACK_ICON__",SVG_ARROW_LEFT),("__TITLE__",t('settings_title',lang)),
        ("__APPEARANCE__",t('appearance',lang)),("__BANNER__",t('banner',lang)),
        ("__AVATAR__",t('attach_avatar',lang)),("__AVATAR_HINT__",t('avatar_hint',lang)),
        ("__AVATAR_ZOOM__",t('avatar_zoom',lang)),("__ACCOUNT__",t('account',lang)),
        ("__USERNAME_LABEL__",t('username_label',lang)),("__NICKNAME_LABEL__",t('nickname_label',lang)),
        ("__NICKNAME__",esc(nickname)),("__USERNAME__",username),("__DESCRIPTION__",t('description',lang)),
        ("__DESC_PLACEHOLDER__",t('desc_placeholder',lang)),("__DESC__",desc),("__DESC_LEN__",str(len(desc))),
        ("__SUGGESTIONS_SECTION__",t('suggestions_section',lang)),
        ("__SUGGES_ENABLE_LABEL__",t('sugges_enable_label',lang)),("__SUGGES_CHECKED__",sugges_checked),
        ("__SUGGES_PHOTO_ENABLE_LABEL__",t('sugges_photo_enable_label',lang)),("__PHOTO_CHECKED__",photo_checked),
        ("__RULES_LABEL__",t('rules_edit_label',lang)),("__RULES_PLACEHOLDER__",t('rules_placeholder',lang)),
        ("__RULES__",rules),("__RULES_LEN__",str(len(rules))),
        ("__LANGUAGE__",t('language',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),
        ("__EN_ACTIVE__","active" if lang=='en' else ""),("__SAVE__",t('save',lang)),
        ("__BANNER_ID__",banner_id),("__BANNER_CSS__",get_banner_css(banner_id)),
        ("__SWATCHES__",swatches),("__AVATAR_PREVIEW__",avatar_preview),
        ("__PLACEHOLDER_STYLE__",placeholder_style),("__ZOOM_ROW_STYLE__",zoom_row_style),
        ("__ZOOM__",str(zoom)),("__ZOOM_PCT__",str(int(round(zoom*100)))),
        ("__SVG_USER__",SVG_USER),("__TOKEN__",token),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mobile_nav(lang, "settings", True, nickname, avatar)),
        ("__OVERLAY__",get_overlay(lang))]
    for k, v in reps: html_str = html_str.replace(k, v)
    return html_str

def suggestions_page_html(nickname, suggestions, lang, token):
    if not suggestions:
        rh = f"<div class='post-item empty-state'>{t('sugges_empty', lang)}</div>"
    else:
        rh = ""
        for s in suggestions:
            sid = esc(s.get('id'))
            sugg_by = esc(s.get('suggested_by_name'))
            content = linkify(s.get('content'))
            date = format_date(esc(s.get('created_at')))
            img = esc(s.get('image_data', ''))
            img_html = f'<img class="post-image" src="{img}" alt="" loading="lazy" onclick="viewImage(this.src)">' if img else ""
            card = f"<div class='suggestion-card' id='sugg-{sid}'><div class='sugg-author'><span class='sugg-name'>{sugg_by}</span><span class='sugg-date'>{date}</span></div><div class='sugg-content'>{content}</div>{img_html}<div class='sugg-actions'><button class='btn btn-success' onclick=\"approveSugg('{sid}')\">{t('sugges_approve',lang)}</button><button class='btn btn-danger' onclick=\"rejectSugg('{sid}')\">{t('sugges_reject',lang)}</button></div></div>"
            rh += card
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Solid">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><a href="/cabinet" class="back-btn">__BACK_ICON__</a><h1>__TITLE__</h1></header>
            <div class="feed">__SUGGESTIONS_HTML__</div>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('suggestions_title',lang).title()),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, nickname)),("__BACK_ICON__",SVG_ARROW_LEFT),
        ("__NAV_RAIL__",nav_rail(lang, "suggestions", nickname)),
        ("__SUGGESTIONS_HTML__",rh),("__MOBILE_FOOTER__",mobile_footer(lang)),
        ("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mobile_nav(lang, "suggestions", True, nickname)),
        ("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def sugges_form_html(nickname, lang, token, error="", viewer="", rules="", enabled=True, photo_enabled=True):
    msg_html = f"<div class='error-msg'>{error}</div>" if error else ""
    is_own = (viewer == nickname)
    if is_own:
        form_block = f"<div class='error-msg'>{t('sugges_own', lang)}</div>"
    elif not enabled:
        form_block = f"<div class='error-msg'>{t('sugges_disabled', lang)}</div>"
    else:
        photo_block = f"<label class='toggle-row' style='cursor:pointer;'><span>{t('attach_photo', lang)}</span><input type='file' accept='image/*' onchange='handleSuggImage(this)'></label><img id='sugg-img-preview' class='composer-img-preview'>" if photo_enabled else ""
        form_block = f"<form data-nickname='{esc(nickname)}' onsubmit='submitSuggestion(event)' style='display:flex;flex-direction:column;gap:12px'><input type='text' name='sugg_name' placeholder='{t('sugges_name',lang)}' required maxlength='60'><textarea name='content' placeholder='{t('sugges_content',lang)}' required maxlength='500' style='min-height:150px;'></textarea>{photo_block}<button type='submit' id='sugg-submit-btn' class='btn btn-success'>{t('sugges_send',lang)}</button></form>"
    rules_block = f"<div class='rules-box'><b>{t('rules_title',lang)}</b><div class='rules-content'>{esc(rules)}</div></div>" if rules else ""
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · @__NICKNAME__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        <main class="main-col" style="max-width:100%">
            <header class="main-header"><a href="/__NICKNAME__" class="back-btn">__BACK_ICON__</a><h1>__TITLE__</h1></header>
            <div class="settings-body" style="max-width:560px">
                <div class="side-card" style="background:var(--bg-elev);color:var(--text)"><b>@__NICKNAME__</b></div>
                __RULES_BLOCK____MSG____FORM_BLOCK__
            </div>
            __MOBILE_FOOTER__
        </main>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('sugges_title',lang)),("__NICKNAME__",esc(nickname)),
        ("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),("__BACK_ICON__",SVG_ARROW_LEFT),
        ("__RULES_BLOCK__",rules_block),("__MSG__",msg_html),("__FORM_BLOCK__",form_block),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),
        ("__MOBILE_NAV__",mobile_nav(lang, "profile", bool(viewer), viewer)),
        ("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    rh = render_records(records, lang, own=is_owner, uid=viewer)
    username = esc(user.get('username') or '')
    desc = esc(user.get('description') or '')
    avatar = esc(user.get('avatar_data') or '')
    banner_id = user.get('banner_id') or 'default'
    zoom = _safe_zoom(user.get('avatar_zoom', 1.0))
    banner_css = get_banner_css(banner_id)
    if avatar:
        avatar_html = f'<div class="profile-avatar-clip" onclick="viewImage(this.querySelector(\'img\').src)"><img src="{avatar}" style="transform:scale({zoom})" alt="avatar"></div>'
    else:
        avatar_html = f'<div class="profile-avatar-clip">{SVG_USER}</div>'
    bio_html = f"<div class='profile-bio'>{desc}</div>" if desc else ""
    sugg_btn = "" if is_owner or not user_sugges_enabled(user) else f"<a href='/{esc(nickname)}/sugges' class='btn btn-success'>{t('suggestions_btn', lang)}</a>"
    edit_btn = f"<a href='/settings' class='btn btn-secondary'>{t('settings',lang)}</a>" if is_owner else ""

    # Composer only on own profile
    if is_owner:
        if avatar:
            composer_av = f'<div class="composer-avatar"><img src="{avatar}" style="transform:scale({zoom})" alt=""></div>'
        else:
            composer_av = f'<div class="composer-avatar">{SVG_USER}</div>'
        composer = composer_form(lang, composer_av, "profile-create-form")
    else:
        composer = ""

    nav_user = user if is_owner else None
    nav = nav_rail(lang, "profile", viewer, nav_user) if viewer else ""
    mob = mobile_nav(lang, "profile", bool(viewer), viewer)

    header_title = "Solid" if is_owner else username

    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Solid">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>@__NICKNAME__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header">
                <a href="__HOME_LINK__" class="back-btn">__BACK_ICON__</a>
                <div><div style="font-weight:800;font-size:17px;">__HEADER_TITLE__</div><div class="main-header-sub">__POST_COUNT__ __POSTS_LABEL__</div></div>
            </header>
            <div class="profile-banner" style="background:__BANNER_CSS__"></div>
            <div class="profile-head">
                <div class="profile-avatar-wrap">__AVATAR__</div>
                <div class="profile-name">__USERNAME__</div>
                <div class="profile-handle">@__NICKNAME__</div>
                __BIO_HTML__
                <div class="profile-actions">__EDIT_BTN____SUGG_BTN__</div>
            </div>
            __COMPOSER__
            <div class="feed" id="my-records-container">__RECORDS_HTML__</div>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    home_link = "/cabinet" if viewer else "/"
    for k, v in [("__LANG__",lang),("__NICKNAME__",esc(nickname)),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, viewer or "")),("__NAV_RAIL__",nav),
        ("__BACK_ICON__",SVG_ARROW_LEFT),("__HOME_LINK__",home_link),
        ("__HEADER_TITLE__",esc(header_title)),
        ("__AVATAR__",avatar_html),("__USERNAME__",username),("__BIO_HTML__",bio_html),
        ("__BANNER_CSS__",banner_css),
        ("__POST_COUNT__",str(len(records))),("__POSTS_LABEL__",t('profile_posts',lang)),
        ("__EDIT_BTN__",edit_btn),("__SUGG_BTN__",sugg_btn),
        ("__COMPOSER__",composer),
        ("__RECORDS_HTML__",rh),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mob),("__OVERLAY__",get_overlay(lang)),("__SVG_USER__",SVG_USER)]:
        html_str = html_str.replace(k, v)
    return html_str

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, uid=viewer)
    avatar = esc(user.get('avatar_data') or '')
    zoom = _safe_zoom(user.get('avatar_zoom', 1.0))
    banner_css = get_banner_css(user.get('banner_id') or 'default')
    sugg_btn = "" if (viewer == nickname) or not user_sugges_enabled(user) else f"<a href='/{esc(nickname)}/sugges' class='btn btn-success'>{t('suggestions_btn', lang)}</a>"
    if avatar:
        avatar_html = f'<div class="profile-avatar-clip" onclick="viewImage(this.querySelector(\'img\').src)"><img src="{avatar}" style="transform:scale({zoom})" alt=""></div>'
    else:
        avatar_html = f'<div class="profile-avatar-clip">{SVG_USER}</div>'
    nav_user = user if viewer == nickname else None
    nav = nav_rail(lang, "profile", viewer, nav_user) if viewer else ""
    mob = mobile_nav(lang, "profile", bool(viewer), viewer)
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Solid">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__RECORD_PAGE__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><a href="/__NICKNAME__" class="back-btn">__BACK_ICON__</a><h1>__RECORD_PAGE__</h1></header>
            <div class="profile-banner" style="height:100px;background:__BANNER_CSS__"></div>
            <div class="profile-head">
                <div class="profile-avatar-wrap">__AVATAR__</div>
                <div class="profile-name">__USERNAME__</div>
                <div class="profile-handle">@__NICKNAME__</div>
                <div class="profile-actions">__SUGG_BTN__</div>
            </div>
            <div class="feed">__RECORDS_HTML__</div>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__RECORD_PAGE__",t('record_page',lang)),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, viewer or "")),("__NAV_RAIL__",nav),
        ("__BACK_ICON__",SVG_ARROW_LEFT),("__NICKNAME__",esc(nickname)),
        ("__USERNAME__",esc(user.get('username'))),("__AVATAR__",avatar_html),
        ("__BANNER_CSS__",banner_css),("__SUGG_BTN__",sugg_btn),("__RECORDS_HTML__",rh),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mob),("__OVERLAY__",get_overlay(lang)),("__SVG_USER__",SVG_USER)]:
        html_str = html_str.replace(k, v)
    return html_str

def bugreport_html(username, reports, lang, token):
    rh = "<div class='post-item empty-state'>" + ("Заявок пока нет..." if lang=="ru" else "No reports yet...") + "</div>" if not reports else ""
    for x in reports:
        st = esc(x.get('status','Принято')).replace(' ','-')
        rh += f"<div class='post-item'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;'><b>{t('bugreport_title',lang)}</b><span class='status-badge status-{st}'>{esc(x.get('status','Принято'))}</span></div><div class='post-content' style='text-align:left;'>{esc(x.get('content'))}</div><div class='post-date'>{format_date(esc(x.get('created_at')))}</div></div>"
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        <main class="main-col" style="max-width:100%">
            <header class="main-header"><a href="/cabinet" class="back-btn">__BACK_ICON__</a><h1>__TITLE__</h1></header>
            <div class="settings-body">
                <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:10px;">
                    <input type="hidden" name="csrf_token" value="__TOKEN__">
                    <input type="text" name="name" value="__USERNAME__" placeholder="__BUGREPORT_NAME__" required>
                    <textarea name="content" placeholder="__BUGREPORT_DESC__" required style="min-height:150px;"></textarea>
                    <button type="submit" style="background:var(--warning);color:#000;">__BUGREPORT_SEND__</button>
                </form>
            </div>
            <h2 style="font-size:18px;font-weight:800;padding:16px 20px 10px;border-top:1px solid var(--border)">__BUGREPORT_MY__</h2>
            <div class="feed">__REPORTS_HTML__</div>
            __MOBILE_FOOTER__
        </main>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('bugreport_title',lang)),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, "")),("__TOKEN__",token),("__USERNAME__",esc(username)),
        ("__BACK_ICON__",SVG_ARROW_LEFT),
        ("__BUGREPORT_NAME__",t('bugreport_name',lang)),("__BUGREPORT_DESC__",t('bugreport_desc',lang)),
        ("__BUGREPORT_SEND__",t('bugreport_send',lang)),("__BUGREPORT_MY__",t('bugreport_my',lang)),
        ("__REPORTS_HTML__",rh),("__MOBILE_FOOTER__",mobile_footer(lang)),
        ("__MOBILE_NAV__",mobile_nav(lang, "home", False)),
        ("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def privacy_html(lang, token):
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · Solid</title>__CSS__</head><body>
    <div class="app-shell">
        <main class="main-col" style="max-width:100%">
            <header class="main-header"><a href="/" class="back-btn">__BACK_ICON__</a><h1>__TITLE__</h1></header>
            <div class="privacy-body">__TEXT__</div>
            __MOBILE_FOOTER__
        </main>
    </div>
    __OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('privacy_title',lang)),("__CSS__",get_css()),
        ("__BACK_ICON__",SVG_ARROW_LEFT),("__TEXT__",t('privacy_text',lang).replace('\n','<br><br>')),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def search_html(lang, token, q="", stype="all", author="", authors=None, posts=None, viewer=""):
    authors = authors or []; posts = posts or []
    authors_html = ""
    for a in authors:
        parts = [f"<div class='search-result'><a href='/{esc(a.get('nickname',''))}'>"]
        if a.get('avatar_data'):
            parts.append(f"<img class='search-avatar' src='{esc(a.get('avatar_data'))}' alt=''>")
        parts.append(f"<b>{esc(a.get('nickname',''))}</b> <span style='color:var(--text-2);font-size:13px;'>@{esc(a.get('username',''))}</span></a>")
        if a.get('description'):
            parts.append(f"<div style='margin-top:6px;font-size:13px;color:var(--text-2);'>{esc(a.get('description'))[:140]}</div>")
        parts.append("<div style='clear:both'></div></div>")
        authors_html += "".join(parts)
    records_html = ""
    for p in posts:
        nick = esc(p.get('user_nickname',''))
        c = linkify(p.get('content',''))
        d = format_date(esc(p.get('created_at','')))
        img = esc(p.get('image_data',''))
        img_html = f'<img class="post-image" src="{img}" loading="lazy" onclick="viewImage(this.src)" style="max-height:300px;margin-top:8px;">' if img else ""
        records_html += f"<div class='search-result'><div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;'><a href='/{nick}'><b>@{nick}</b></a><span style='font-size:12px;color:var(--text-2);'>{d}</span></div><div style='margin-top:8px;'>{c}</div>{img_html}</div>"
    if not q: content = f"<div class='search-empty'>{t('search_placeholder', lang)}</div>"
    elif not authors and not posts: content = f"<div class='search-empty'>{t('search_no_results', lang)}</div>"
    else:
        content = ""
        if authors: content += f"<h3 class='search-h'>{t('search_found_authors', lang)} ({len(authors)})</h3>{authors_html}"
        if posts: content += f"<h3 class='search-h'>{t('search_found_records', lang)} ({len(posts)})</h3>{records_html}"
    sel_all = "selected" if stype == "all" else ""
    sel_a = "selected" if stype == "authors" else ""
    sel_r = "selected" if stype == "records" else ""
    nav = nav_rail(lang, "search", viewer) if viewer else ""
    mob = mobile_nav(lang, "search", bool(viewer), viewer)
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Solid">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><h1>__TITLE__</h1></header>
            <form method="get" action="/search" class="search-form">
                <input type="text" name="q" value="__Q__" placeholder="__SEARCH_PLACEHOLDER__">
                <div class="search-form-row">
                    <select name="stype">
                        <option value="all" __SEL_ALL__>__TYPE_ALL__</option>
                        <option value="authors" __SEL_A__>__TYPE_A__</option>
                        <option value="records" __SEL_R__>__TYPE_R__</option>
                    </select>
                    <input type="text" name="author" value="__AUTHOR__" placeholder="__AUTHOR_FILTER__">
                </div>
                <button type="submit" style="background:var(--success)">__SEARCH_BTN__</button>
            </form>
            __CONTENT__
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('search_title',lang).title()),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, viewer)),("__NAV_RAIL__",nav),
        ("__Q__",esc(q)),("__SEARCH_PLACEHOLDER__",t('search_placeholder',lang)),
        ("__SEL_ALL__",sel_all),("__SEL_A__",sel_a),("__SEL_R__",sel_r),
        ("__TYPE_ALL__",t('search_type_all',lang)),("__TYPE_A__",t('search_type_authors',lang)),
        ("__TYPE_R__",t('search_type_records',lang)),("__AUTHOR__",esc(author)),
        ("__AUTHOR_FILTER__",t('search_author_filter',lang)),("__SEARCH_BTN__",t('search_btn',lang)),
        ("__CONTENT__",content),("__MOBILE_FOOTER__",mobile_footer(lang)),
        ("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mob),("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

def stats_html(lang, token, users_count, posts_count, sugg_count, last_update_iso, viewer=""):
    uptime = _uptime_str(lang)
    started = SERVER_START_DT.strftime("%d.%m.%y %H:%M UTC")
    last_upd = format_date(last_update_iso) if last_update_iso else "—"
    contacts_html = "".join(f"<div style='margin-top:6px;'><a href='mailto:{e}'>{e}</a></div>" for e in CONTACT_EMAILS)
    nav = nav_rail(lang, "stats", viewer) if viewer else ""
    mob = mobile_nav(lang, "stats", bool(viewer), viewer)
    html_str = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">
    <meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Solid">
    <link rel="manifest" href="/manifest.json"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231d9bf0' stroke-width='2'%3E%3Cpath d='M12 2L2 7l10 5 10-5-10-5z'/%3E%3C/svg%3E">
    <title>__TITLE__ · Solid</title>__CSS____JS__</head><body>
    <div class="app-shell">
        __NAV_RAIL__
        <main class="main-col">
            <header class="main-header"><h1>__TITLE__</h1></header>
            <div class="stat-row"><b>__STATS_USERS__</b><span class="stat-val">__USERS_COUNT__</span></div>
            <div class="stat-row"><b>__STATS_POSTS__</b><span class="stat-val">__POSTS_COUNT__</span></div>
            <div class="stat-row"><b>__STATS_SUGGES__</b><span class="stat-val">__SUGG_COUNT__</span></div>
            <div class="stat-row"><b>__STATS_STARTED__</b><span style="font-size:15px;color:var(--text-2)">__STARTED__</span></div>
            <div class="stat-row"><b>__STATS_LAST_UPDATE__</b><span style="font-size:15px;color:var(--text-2)">__LAST_UPDATE__</span></div>
            <div class="stat-row"><b>__STATS_UPTIME__</b><span class="stat-val" style="color:var(--accent)">__UPTIME__</span></div>
            <div class="contacts-box">
                <b>__STATS_CONTACTS__</b>
                <div style="color:var(--text-2);font-size:14px;margin-bottom:8px">__STATS_CONTACTS_DESC__</div>
                __CONTACTS_HTML__
            </div>
            __MOBILE_FOOTER__
        </main>
        <div class="side-col">__SIDE_FOOTER__</div>
    </div>
    __MOBILE_NAV____OVERLAY__
    </body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('stats_title',lang).title()),("__CSS__",get_css()),
        ("__JS__",get_js(lang, token, viewer)),("__NAV_RAIL__",nav),
        ("__STATS_USERS__",t('stats_users',lang)),("__STATS_POSTS__",t('stats_posts',lang)),
        ("__STATS_SUGGES__",t('stats_sugges',lang)),("__STATS_STARTED__",t('stats_started',lang)),
        ("__STATS_LAST_UPDATE__",t('stats_last_update',lang)),("__STATS_UPTIME__",t('stats_uptime',lang)),
        ("__STATS_CONTACTS__",t('stats_contacts',lang)),("__STATS_CONTACTS_DESC__",t('stats_contacts_desc',lang)),
        ("__CONTACTS_HTML__",contacts_html),("__USERS_COUNT__",str(users_count)),
        ("__POSTS_COUNT__",str(posts_count)),("__SUGG_COUNT__",str(sugg_count)),
        ("__STARTED__",started),("__LAST_UPDATE__",last_upd),("__UPTIME__",uptime),
        ("__MOBILE_FOOTER__",mobile_footer(lang)),("__SIDE_FOOTER__",side_footer(lang)),
        ("__MOBILE_NAV__",mob),("__OVERLAY__",get_overlay(lang))]:
        html_str = html_str.replace(k, v)
    return html_str

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
                resp = RedirectResponse("/cabinet", 303); set_csrf_cookie(resp, token, r); return resp
        except Exception: pass
    res = HTMLResponse(auth_html(lang, "", token)); set_csrf_cookie(res, token, r); return res

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    try: uc, pc, sc, lu = await _stats_data()
    except Exception: uc, pc, sc, lu = 0, 0, 0, None
    res = HTMLResponse(stats_html(lang, token, uc, pc, sc, lu, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/search", response_class=HTMLResponse)
async def search_page(r: Request, q: str = "", stype: str = "all", author: str = "", lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    q = (q or "").strip()[:100]
    authors, posts = [], []
    if q:
        sq = sanitize_q(q)
        if sq:
            if stype in ("all", "authors"):
                try:
                    r1 = await asyncio.to_thread(lambda: sb.table('users').select('username,nickname,description,avatar_data').ilike('nickname', f'%{sq}%').limit(30).execute())
                    authors = r1.data or []
                except Exception: pass
                try:
                    r2 = await asyncio.to_thread(lambda: sb.table('users').select('username,nickname,description').ilike('username', f'%{sq}%').limit(30).execute())
                    existing = {a.get('nickname') for a in authors}
                    for u in (r2.data or []):
                        if u.get('nickname') not in existing: authors.append(u)
                except Exception: pass
            if stype in ("all", "records"):
                try:
                    if author.strip():
                        r3 = await asyncio.to_thread(lambda: sb.table('posts').select('id,user_nickname,content,image_data,created_at').ilike('content', f'%{sq}%').eq('user_nickname', author.strip()).order('created_at', desc=True).limit(50).execute())
                    else:
                        r3 = await asyncio.to_thread(lambda: sb.table('posts').select('id,user_nickname,content,image_data,created_at').ilike('content', f'%{sq}%').order('created_at', desc=True).limit(50).execute())
                    posts = r3.data or []
                except Exception:
                    try:
                        if author.strip():
                            r4 = await asyncio.to_thread(lambda: sb.table('posts').select('id,user_nickname,content,created_at').ilike('content', f'%{sq}%').eq('user_nickname', author.strip()).order('created_at', desc=True).limit(50).execute())
                        else:
                            r4 = await asyncio.to_thread(lambda: sb.table('posts').select('id,user_nickname,content,created_at').ilike('content', f'%{sq}%').order('created_at', desc=True).limit(50).execute())
                        posts = r4.data or []
                    except Exception: pass
    try: rh = search_html(lang, token, q=q, stype=stype, author=author, authors=authors, posts=posts, viewer=viewer)
    except Exception:
        traceback.print_exc()
        rh = f"<h2 style='color:red;padding:40px'>Search error</h2><a href='/' style='padding:40px'>OK</a>"
    res = HTMLResponse(rh); set_csrf_cookie(res, token, r); return res

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    res = HTMLResponse(privacy_html(lang, token)); set_csrf_cookie(res, token, r); return res

@app.post("/register", response_class=HTMLResponse)
async def register(r: Request, res: Response, username: str = Form(...), nickname: str = Form(...), password: str = Form(...), re_pass: str = Form(...), captcha: str = Form(None), privacy: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token, "register")); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token, "register")
    if not privacy: return auth_html(lang, t('alert_privacy', lang), token, "register")
    if password != re_pass: return auth_html(lang, t('alert_pass_mismatch', lang), token, "register")
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
        if x.data: return auth_html(lang, t('alert_nick_taken', lang), token, "register")
        await asyncio.to_thread(lambda: sb.table('users').insert({"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}).execute())
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token, "register")
    resp = RedirectResponse("/cabinet", 303)
    secure = r.url.scheme == "https"
    resp.set_cookie("nickname", nickname, httponly=True, samesite="lax", secure=secure)
    set_csrf_cookie(resp, token, r); return resp

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    ip = r.client.host if r.client else "0.0.0.0"
    if not check_csrf(r, csrf_token):
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token, "login")); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token, "login")
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
        return auth_html(lang, f"DB Error: {str(e)}", token, "login")
    return auth_html(lang, t('alert_bad_login', lang), token, "login")

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
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

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data = await _fetch_user(nickname)
    if not user_data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(settings_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r); return res

@app.post("/settings", response_class=HTMLResponse)
async def settings_post(r: Request, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), banner_id: str = Form("default"), avatar_zoom: str = Form("1.0"), sugges_enabled: str = Form(None), sugges_photo_enabled: str = Form(None), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token):
        return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
    if len(description) > 300: return HTMLResponse(f"<script>showToast('{t('alert_desc_long', lang)}');window.history.back()</script>")
    if len(sugges_rules) > 1000: return HTMLResponse(f"<script>showToast('{t('rules_alert_long', lang)}');window.history.back()</script>")

    # Validate banner
    if banner_id not in BANNERS: banner_id = "default"
    zoom_val = _safe_zoom(avatar_zoom)

    update = {
        "username": username,
        "description": description,
        "sugges_rules": sugges_rules,
        "sugges_enabled": bool(sugges_enabled),
        "sugges_photo_enabled": bool(sugges_photo_enabled),
        "banner_id": banner_id,
        "avatar_zoom": zoom_val,
    }
    av = valid_b64(avatar_data)
    if av: update["avatar_data"] = av

    # Try progressively smaller update payloads
    try:
        await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
    except Exception:
        for drop in ["banner_id", "avatar_zoom", "avatar_data", "sugges_photo_enabled", "sugges_enabled"]:
            update.pop(drop, None)
            try:
                await asyncio.to_thread(lambda u=update: sb.table('users').update(u).eq('nickname', nickname).execute())
                break
            except Exception:
                continue
    return RedirectResponse("/settings", 303)

# Legacy redirect
@app.get("/cabinet/edit")
async def edit_redirect():
    return RedirectResponse("/settings", 307)

@app.get("/cabinet/edit/")
async def edit_redirect2():
    return RedirectResponse("/settings", 307)

@app.get("/{nickname}/sugges", response_class=HTMLResponse)
async def sugges_form(nickname: str, r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    user_data = await _fetch_user(nickname)
    if not user_data: return HTMLResponse(f"<h2 style='padding:40px;text-align:center'>{t('user_not_found', lang)}</h2><p style='text-align:center'><a href='/'>OK</a></p>", 404)
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
        content = req.params.get("content", "").strip()[:500]
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
    res = HTMLResponse(bugreport_html(u, rp, lang, token)); set_csrf_cookie(res, token, r); return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
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
            asyncio.to_thread(lambda: sb.table('users').select('username,avatar_data,sugges_enabled,sugges_photo_enabled,banner_id,avatar_zoom').eq('nickname', nickname).execute()),
            asyncio.to_thread(lambda: sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute())
        )
        if not u.data: return HTMLResponse(f"<h2 style='padding:40px;text-align:center'>{t('user_not_found', lang)}</h2><p style='text-align:center'><a href='/'>OK</a></p>", 404)
        if not x.data: return HTMLResponse(f"<h2 style='padding:40px;text-align:center'>{t('no_posts', lang)}</h2><p style='text-align:center'><a href='/{nickname}'>OK</a></p>", 404)
        u_data = u.data[0]; rec = x.data[0]
    except Exception:
        return HTMLResponse(f"<h2 style='padding:40px;text-align:center'>DB Error</h2><p style='text-align:center'><a href='/'>OK</a></p>", 500)
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    res = HTMLResponse(record_page_html(nickname, u_data, rec, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        return HTMLResponse(f"<h2 style='padding:40px;text-align:center'>{t('user_not_found', lang)}</h2><p style='text-align:center'><a href='/'>OK</a></p>", 404)
    viewer = r.cookies.get("nickname") or ""
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, user_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r); return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
