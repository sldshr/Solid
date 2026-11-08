from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, httpx, asyncio
from datetime import datetime, timezone
from typing import Optional

app = FastAPI()

APP_VERSION = "0.08"
SERVER_START_DATE = datetime.now().strftime("%d.%m.%y")

S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

deleted_records = set()
pinned_records = {}
pending_records = {}

MAX_B64_LEN = 900000  # ~700KB лимит base64

def esc(val):
    return html.escape(str(val)) if val is not None else ""

def linkify(text):
    if not text: return ""
    safe_text = html.escape(text)
    url_pattern = re.compile(r'(https?://[^\s]+)')
    return url_pattern.sub(r'<a href="#" class="ext-link" data-url="\1" onclick="showLinkWarning(event, this)">\1</a>', safe_text).replace('\n', '<br>')

def valid_b64(s):
    if not s: return ""
    s = str(s)
    if len(s) > MAX_B64_LEN: return ""
    if not s.startswith("data:image/"): return ""
    return s

# --- АСИНХРОННЫЕ ЗАПРОСЫ ---
async def _fetch_user(nickname):
    for sel in ['username,description,sugges_rules,avatar_data', 'username,description,sugges_rules', 'username,description']:
        try:
            res = await asyncio.to_thread(lambda: sb.table('users').select(sel).eq('nickname', nickname).execute())
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

# --- WEBSOCKET ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- PWA ---
@app.get("/manifest.json")
async def manifest():
    return JSONResponse(
        {"name": "Solid Link", "short_name": "SolidLink", "start_url": "/",
         "display": "standalone", "background_color": "#f4f4f4", "theme_color": "#000000",
         "icons": [{"src": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiB2aWV3Qm94PSIwIDAgMjQgMjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xIDExczQtOCAxMS04IDExIDggMTEgOC00IDgtMTEgOC0xMS04LTExLTh6Ij48L3BhdGg+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMSIgcj0iMyI+PC9jaXJjbGU+PC9zdmc+", "sizes": "192x192", "type": "image/svg+xml"}]},
        headers={"Cache-Control": "public, max-age=86400"})

@app.get("/sw.js")
async def sw():
    js = "self.addEventListener('install', (e) => { e.waitUntil(caches.open('solid-link-v1').then((cache) => cache.addAll(['/']))); }); self.addEventListener('fetch', (e) => { if (e.request.method !== 'GET') return; e.respondWith(caches.match(e.request).then((response) => response || fetch(e.request))); });"
    return Response(content=js, media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})

@app.get("/api/og")
async def get_og(url: str):
    if not url.startswith("http://") and not url.startswith("https://"):
        return {"title": "", "description": "", "image": ""}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0, follow_redirects=True)
            html_content = resp.text
            def get_meta(prop):
                m = re.search(fr'<meta[^>]+(?:property|name)=["\']og:{prop}["\'][^>]+content=["\']([^"\']*)["\']', html_content, re.IGNORECASE)
                if not m:
                    m = re.search(fr'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']og:{prop}["\']', html_content, re.IGNORECASE)
                return m.group(1) if m else ""
            title = get_meta("title") or ""
            if not title:
                tm = re.search(r'<title>([^<]*)</title>', html_content, re.IGNORECASE)
                if tm: title = tm.group(1)
            return {"title": title, "description": get_meta("description"), "image": get_meta("image")}
    except Exception:
        return {"title": "", "description": "", "image": ""}

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    try:
        if len(hashed) == 64 and hashlib.sha256(password.encode()).hexdigest() == hashed:
            return True
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except:
        return False

def get_csrf_token(request: Request) -> str:
    return request.cookies.get("csrf_token") or secrets.token_hex(32)

def check_csrf(request: Request, form_token: str = None) -> bool:
    cookie_token = request.cookies.get("csrf_token")
    if not cookie_token: return False
    header_token = request.headers.get("X-CSRF-Token")
    return cookie_token == form_token or cookie_token == header_token

def set_csrf_cookie(response: Response, token: str, request: Request):
    response.set_cookie("csrf_token", token, httponly=True, samesite="lax", max_age=86400*365)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    lang = request.cookies.get("lang", "ru")
    error_msg = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    response = HTMLResponse(content=auth_html(lang, error_msg, token), status_code=422)
    set_csrf_cookie(response, token, request)
    return response

class RPCRequest(BaseModel):
    method: str
    params: dict = {}

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
        "attach_photo": "Прикрепить фото", "attach_avatar": "Аватар (до 300px)", "remove_photo": "Убрать фото",
        "img_compressing": "Сжатие фото...", "img_ready": "Фото готово", "img_error": "Ошибка фото",
        "img_too_big": "Фото слишком большое"
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
        "attach_photo": "Attach photo", "attach_avatar": "Avatar (up to 300px)", "remove_photo": "Remove photo",
        "img_compressing": "Compressing photo...", "img_ready": "Photo ready", "img_error": "Photo error",
        "img_too_big": "Photo is too big"
    }
}

def t(key: str, lang: str = "ru") -> str:
    return LOCALES.get(lang, LOCALES["ru"]).get(key, key)

def format_date(iso_str: str) -> str:
    if not iso_str: return ""
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except:
        return iso_str[:10]

SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""

_CSS_CACHE = None
def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        _CSS_CACHE = """
        <style>
            * { box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
            a { color: black; text-decoration: none; font-weight: bold; }
            a:hover { text-decoration: underline; }
            .container { background: white; padding: 30px; border: 10px solid #e0e0e0; display: flex; gap: 40px; align-items: flex-start; max-width: 100%; margin-bottom: 20px; }
            .footer { text-align: center; font-size: 16px; font-weight: bold; color: #555; width: 100%; max-width: 1200px; margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }
            .footer a { color: #000; border-bottom: 2px solid #000; }
            .footer-links { font-size: 14px; color: #777; }
            .footer-links a { color: #555; border-bottom: 1px solid #555; font-weight: normal; }
            .auth-wrapper { display: flex; gap: 20px; flex-direction: column; width: 340px; }
            .auth-wrapper-inner { display: flex; gap: 20px; align-items: flex-end; width: 100%;}
            .form-box { background-color: black; padding: 5px; display: flex; flex-direction: column; gap: 5px; border: 2px solid #ccc; width: 100%;}
            .form-box form { display: flex; flex-direction: column; gap: 5px; margin: 0; width: 100%;}
            .input-group { position: relative; display: flex; align-items: center; width: 100%; }
            input[type="text"], input[type="password"], textarea, select { background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px; font-family: Arial, sans-serif; width: 100%; text-align: center; outline: none; }
            textarea { text-align: left; resize: vertical; }
            input[type="file"] { background-color: #a9a9a9; border: none; padding: 10px; font-size: 15px; width: 100%; cursor: pointer; }
            button, .btn { background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px; font-family: Arial, sans-serif; width: 100%; text-align: center; cursor: pointer; color: black; font-weight: bold; display: inline-block; border: 1px solid transparent; }
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
            .avatar { width: 120px; height: 120px; border-radius: 50%; object-fit: cover; display: block; margin: 0 auto 10px auto; border: 3px solid #a9a9a9; background: #333; }
            .logout-btn { margin-top: 10px; background: #ff4d4d; }
            .logout-btn:hover { background: #cc0000; }
            .edit-btn { background: #4da6ff; margin-top: 5px; color: white;}
            .edit-btn:hover { background: #1a82e2; }
            .sugges-btn { background: #f1c40f; color: black; margin-top: 5px; }
            .sugges-btn:hover { background: #d4ac0d; }
            .main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
            .create-post-box { background: black; padding: 10px; display: flex; flex-direction: column; gap: 10px; border-radius: 5px; }
            .create-post-box textarea { height: 100px; font-size: 16px; padding: 10px; border-radius: 3px; }
            .create-post-box label { color: #fff; font-size: 14px; font-weight: bold; display: block; margin-top: 5px;}
            .img-preview { max-width: 100%; max-height: 200px; border-radius: 5px; margin-top: 8px; display: block; margin-left: auto; margin-right: auto;}
            .post-item { background: #a9a9a9; padding: 15px; font-size: 16px; word-wrap: break-word; border-left: 5px solid transparent; display: flex; flex-direction: column; border-radius: 3px;}
            .post-item.pinned { border-left: 5px solid #ff4d4d; background: #d9d9d9; }
            .post-content { margin-bottom: 10px; font-size: 18px; text-align: center; }
            .post-content a.ext-link { color: #0000ff; text-decoration: underline; word-break: break-all; }
            .post-image { max-width: 100%; max-height: 500px; object-fit: contain; border-radius: 5px; margin: 10px auto; display: block; }
            .post-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; border-top: 1px solid #888; padding-top: 5px; flex-wrap: wrap; gap: 10px; }
            .post-date { font-size: 12px; color: #555; margin-left: auto; }
            .post-suggested { font-size: 13px; color: #1e8449; font-weight: bold; }
            .posts-area { background: black; padding: 10px; border-radius: 5px; display: flex; flex-direction: column; gap: 10px; min-height: 300px;}
            .posts-area h2 { color: white; font-size: 24px; margin: 0 0 10px 0; text-align: center;}
            .post-wrapper { position: relative; transition: opacity 0.3s ease; }
            .post-actions { position: absolute; top: 5px; right: 5px; display: flex; gap: 5px; opacity: 0; transition: opacity 0.2s; z-index: 10; }
            .post-wrapper:hover .post-actions { opacity: 1; }
            .action-btn { background: black; color: white; border: none; padding: 5px 10px; font-size: 12px; cursor: pointer; border-radius: 3px; width: auto; font-weight: normal;}
            .action-btn:hover { background: #ff4d4d; }
            .action-btn.pin-btn:hover { background: #4da6ff; }
            .action-btn.link-btn:hover { background: #f1c40f; color: black; }
            .suggestion-card { background: #a9a9a9; padding: 15px; border-radius: 5px; border-left: 5px solid #f1c40f; margin-bottom: 10px; }
            .sugg-author { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #888; flex-wrap: wrap;}
            .sugg-name { font-weight: bold; color: #333; font-size: 14px; }
            .sugg-date { font-size: 12px; color: #666; }
            .sugg-content { font-size: 16px; margin-bottom: 10px; text-align: center; }
            .sugg-actions { display: flex; gap: 10px; }
            .sugg-approve { background: #2ecc71; color: white; padding: 8px; }
            .sugg-approve:hover { background: #27ae60; }
            .sugg-reject { background: #e74c3c; color: white; padding: 8px; }
            .sugg-reject:hover { background: #c0392b; }
            .rules-box { background: #fff9e6; border-left: 5px solid #f1c40f; padding: 15px; border-radius: 5px; margin-bottom: 15px; color: #000; }
            .rules-box b { display: block; margin-bottom: 8px; font-size: 15px; }
            .rules-content { font-size: 14px; white-space: pre-wrap; line-height: 1.4; }
            .status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; color: white; margin-left: 10px;}
            .status-Принято, .status-Accepted { background: #4da6ff; }
            .status-В-работе, .status-In-Progress { background: #f1c40f; }
            .status-Исправлено, .status-Fixed { background: #2ecc71; }
            .status-Отклонено, .status-Rejected { background: #e74c3c; }
            .lang-switch { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
            .lang-btn { background: transparent; border: 2px solid #a9a9a9; color: #a9a9a9; padding: 8px 15px; width: auto; font-size: 16px; font-weight: bold; cursor: pointer; transition: all 0.2s;}
            .lang-btn:hover { background: #a9a9a9; color: black; }
            .lang-btn.active { background: #4da6ff; border-color: #4da6ff; color: white; }
            .login-lang-wrapper { display: flex; justify-content: flex-end; width: 100%; margin-top: 5px; }
            .privacy-content { background: white; color: black; padding: 20px; font-size: 18px; line-height: 1.5; text-align: left; word-wrap: break-word; border-radius: 3px;}
            .error-msg { color: #ff4d4d; font-weight: bold; font-size: 18px; text-align: right; width: 100%; margin-top: 10px; min-height: 20px; }
            #toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #333; color: white; padding: 12px 24px; border-radius: 5px; opacity: 0; transition: opacity 0.3s; z-index: 9999; font-weight: bold; pointer-events: none; text-align: center; max-width: 90%; }
            #toast.show { opacity: 1; }
            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; justify-content: center; align-items: center; padding: 15px; }
            .modal-overlay.show { display: flex; }
            .modal-box { background: white; padding: 30px; border-radius: 5px; max-width: 400px; width: 100%; text-align: center; border: 5px solid #000; }
            .modal-actions { display: flex; gap: 10px; margin-top: 20px; }
            .btn-danger { background: #ff4d4d; color: white; }
            .btn-danger:hover { background: #cc0000; }
            .og-box { margin: 15px 0; padding: 10px; background: #f9f9f9; border-radius: 5px; border: 1px solid #ddd; text-align: left;}
            .og-img { max-width: 100%; max-height: 200px; border-radius: 5px; margin-bottom: 10px; object-fit: cover; }
            .og-title { margin: 0 0 5px 0; font-size: 16px; color: #000; font-weight: bold;}
            .og-desc { margin: 0; font-size: 14px; color: #555; }
            @media (max-width: 768px) {
                body { padding: 8px; }
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
                .post-item { padding: 10px; }
                .post-footer { flex-direction: column; align-items: flex-start; gap: 5px; }
                .post-date { margin-left: 0; }
                input[type="text"], input[type="password"], textarea, select { font-size: 16px; padding: 12px; }
                button, .btn { font-size: 16px; padding: 14px; }
                .post-content { font-size: 16px; }
                .sidebar h2 { font-size: 20px; }
                .avatar { width: 100px; height: 100px; }
                .post-image { max-height: 400px; }
                .sugg-actions { flex-direction: column; }
                .action-btn { padding: 8px 12px; font-size: 13px; }
                .modal-box { padding: 20px; }
            }
            @media (max-width: 400px) {
                .post-actions { gap: 3px; }
                .action-btn { padding: 6px 8px; font-size: 12px; }
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
            d: "__DEL__", p: "__PIN__", u: "__UNPIN__",
            c: "__CONFIRM__", n: "__NOPOSTS__", cl: "__COPYLINK__",
            sf: "__SUGG_FILL__", ss: "__SUGG_SELF__", su: "__SUGG_SUCCESS__",
            ic: "__IMG_COMPRESSING__", ir: "__IMG_READY__", ie: "__IMG_ERROR__", ib: "__IMG_BIG__"
        };
        
        // ============ СЖАТИЕ ИЗОБРАЖЕНИЙ ============
        async function compressImage(file, maxWidth = 1000, quality = 0.75) {
            return new Promise((resolve, reject) => {
                if (!file.type.startsWith('image/')) return reject('Not an image');
                const reader = new FileReader();
                reader.onload = (e) => {
                    const img = new Image();
                    img.onload = () => {
                        try {
                            const canvas = document.createElement('canvas');
                            let w = img.width, h = img.height;
                            if (w > maxWidth) { h = Math.round(h * maxWidth / w); w = maxWidth; }
                            canvas.width = w; canvas.height = h;
                            const ctx = canvas.getContext('2d');
                            ctx.fillStyle = '#fff';
                            ctx.fillRect(0, 0, w, h);
                            ctx.drawImage(img, 0, 0, w, h);
                            let b64 = canvas.toDataURL('image/jpeg', quality);
                            // Если всё ещё слишком большое - сжимаем сильнее
                            let q = quality;
                            while (b64.length > 800000 && q > 0.3) {
                                q -= 0.1;
                                b64 = canvas.toDataURL('image/jpeg', q);
                            }
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
        
        // Кэш base64 для постов/предложек/аватаров
        window.postImageCache = "";
        window.suggImageCache = "";
        
        async function handlePostImage(input) {
            const file = input.files[0];
            const preview = document.getElementById('post-img-preview');
            const btn = document.getElementById('create-post-btn');
            if (!file) { window.postImageCache = ""; if(preview) preview.style.display='none'; return; }
            showToast(L.ic);
            btn.disabled = true;
            try {
                const b64 = await compressImage(file, 1000, 0.75);
                window.postImageCache = b64;
                if (preview) { preview.src = b64; preview.style.display = 'block'; }
                showToast(L.ir);
            } catch (e) {
                window.postImageCache = "";
                showToast(e === 'Image too big' ? L.ib : L.ie);
                input.value = '';
                if(preview) preview.style.display='none';
            } finally {
                btn.disabled = false;
            }
        }
        
        async function handleSuggImage(input) {
            const file = input.files[0];
            const preview = document.getElementById('sugg-img-preview');
            const btn = document.getElementById('sugg-submit-btn');
            if (!file) { window.suggImageCache = ""; if(preview) preview.style.display='none'; return; }
            showToast(L.ic);
            if(btn) btn.disabled = true;
            try {
                const b64 = await compressImage(file, 1000, 0.75);
                window.suggImageCache = b64;
                if (preview) { preview.src = b64; preview.style.display = 'block'; }
                showToast(L.ir);
            } catch (e) {
                window.suggImageCache = "";
                showToast(e === 'Image too big' ? L.ib : L.ie);
                input.value = '';
                if(preview) preview.style.display='none';
            } finally {
                if(btn) btn.disabled = false;
            }
        }
        
        async function handleAvatarChange(input) {
            const file = input.files[0];
            const hidden = document.getElementById('avatar-data');
            const preview = document.getElementById('avatar-preview');
            if (!file) { hidden.value = ""; return; }
            showToast(L.ic);
            try {
                const b64 = await compressImage(file, 300, 0.8);
                hidden.value = b64;
                if (preview) { preview.src = b64; preview.style.display = 'block'; }
                showToast(L.ir);
            } catch (e) {
                showToast(e === 'Image too big' ? L.ib : L.ie);
                input.value = '';
            }
        }
        
        // ============ ОБЩИЕ ФУНКЦИИ ============
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW failed', err));
            });
        }
        let ws;
        function connectWS() {
            const proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            ws = new WebSocket(proto + window.location.host + '/ws');
            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                if (d.type === 'delete_record') {
                    const p = document.getElementById('post-' + d.post_id);
                    if (p) p.remove();
                } else if (d.type === 'new_record') {
                    showToast("New record added!");
                }
            };
            ws.onclose = () => setTimeout(connectWS, 3000);
        }
        connectWS();
        function copyLink(user, rid, btn) {
            if (!user) return;
            const url = window.location.origin + '/' + user + '/' + rid;
            navigator.clipboard.writeText(url).then(() => showToast("Link copied!")).catch(() => showToast("Failed to copy"));
        }
        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 3000);
        }
        function showConfirm(msg, cb) {
            const m = document.getElementById('modal-overlay');
            document.getElementById('modal-text').innerText = msg;
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
        let pendingUrl = "";
        async function showLinkWarning(e, el) {
            e.preventDefault();
            pendingUrl = el.getAttribute('data-url');
            if (!pendingUrl) return;
            document.getElementById('link-modal-confirm').href = pendingUrl;
            const ogBox = document.getElementById('og-preview');
            ogBox.innerHTML = `<p style="margin:0; font-size:14px; color:#666;">__EXT_LOADING__</p>`;
            document.getElementById('link-modal').classList.add('show');
            try {
                const res = await fetch('/api/og?url=' + encodeURIComponent(pendingUrl));
                const data = await res.json();
                if (data.title || data.description || data.image) {
                    let html = '';
                    if (data.image) html += `<img src="${data.image}" class="og-img">`;
                    if (data.title) html += `<h4 class="og-title">${data.title}</h4>`;
                    if (data.description) html += `<p class="og-desc">${data.description}</p>`;
                    ogBox.innerHTML = html;
                } else {
                    ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#666;">No preview available.</p>';
                }
            } catch (err) {
                ogBox.innerHTML = '<p style="margin:0; font-size:14px; color:#666;">Failed to load preview.</p>';
            }
        }
        function closeLinkModal() {
            document.getElementById('link-modal').classList.remove('show');
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
        function tp(i, b) {
            const x = document.getElementById(i);
            if (x.type === 'password') { x.type = 'text'; b.innerHTML = `__SVG_EYE_OFF__`; }
            else { x.type = 'password'; b.innerHTML = `__SVG_EYE__`; }
        }
        function uc(e) { document.getElementById('char-count').innerText = e.value.length + ' / 300'; }
        function ucRules(e) { document.getElementById('rules-count').innerText = e.value.length + ' / 1000'; }
        
        async function hc(e) {
            e.preventDefault();
            const f = e.target, c = f.querySelector('textarea').value.trim();
            if (!c) return;
            const i = crypto.randomUUID(), n = new Date();
            const d = n.toLocaleDateString('ru-RU') + ' ' + n.toLocaleTimeString('ru-RU', {hour: '2-digit', minute:'2-digit'});
            const img = window.postImageCache || "";
            const a = document.querySelector('#my-records-container');
            const m = a.querySelector('.empty-state');
            if (m) m.remove();
            const w = document.createElement('div');
            w.className = 'post-wrapper'; w.id = 'post-' + i;
            w.innerHTML = `
                <div class="post-actions">
                    <button onclick="copyLink('${ME}','${i}',this)" class="action-btn link-btn">${L.cl}</button>
                    <button onclick="hp('${i}',this)" class="action-btn pin-btn">${L.p}</button>
                    <button onclick="hd('${i}',this)" class="action-btn">${L.d}</button>
                </div>
                <div class="post-item">
                    <div class="post-content">${c.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>
                    ${img ? `<img class="post-image" src="${img}">` : ''}
                    <div class="post-footer"><div class="post-date">${d}</div></div>
                </div>`;
            let inserted = false;
            const wrappers = a.querySelectorAll('.post-wrapper');
            for (let ww of wrappers) {
                if (!ww.querySelector('.pinned')) { a.insertBefore(w, ww); inserted = true; break; }
            }
            if (!inserted) a.appendChild(w);
            f.reset();
            window.postImageCache = "";
            const preview = document.getElementById('post-img-preview');
            if (preview) preview.style.display = 'none';
            try {
                await rpc('create_record', { content: c, client_id: i, image_data: img });
            } catch (x) {
                w.remove(); showToast('Failed: ' + x.message);
            }
        }
        function hd(i) {
            showConfirm(L.c, async (yes) => {
                if (!yes) return;
                const w = document.getElementById('post-' + i);
                w.style.opacity = '0'; setTimeout(() => w.style.display = 'none', 300);
                try {
                    await rpc('delete_record', { post_id: i });
                    w.remove();
                } catch (x) {
                    w.style.opacity = '1'; w.style.display = 'block'; showToast('Failed: ' + x.message);
                }
            });
        }
        async function hp(i, b) {
            const w = document.getElementById('post-' + i), p = w.querySelector('.post-item'), s = p.classList.contains('pinned');
            if (s) { p.classList.remove('pinned'); b.innerText = L.p; }
            else { p.classList.add('pinned'); b.innerText = L.u; const a = w.parentNode; a.insertBefore(w, a.children[1]); }
            try { await rpc('pin_record', { post_id: i }); }
            catch (x) {
                if (s) { p.classList.add('pinned'); b.innerText = L.u; }
                else { p.classList.remove('pinned'); b.innerText = L.p; }
                showToast('Failed: ' + x.message);
            }
        }
        async function submitSuggestion(event) {
            event.preventDefault();
            const f = event.target;
            const target = f.dataset.nickname;
            const name = f.querySelector('input[name="sugg_name"]').value.trim();
            const content = f.querySelector('textarea[name="content"]').value.trim();
            if (!name || !content) { showToast(L.sf); return; }
            if (ME && target === ME) { showToast(L.ss); return; }
            const btn = f.querySelector('button[type="submit"]');
            const img = window.suggImageCache || "";
            btn.disabled = true;
            try {
                await rpc('submit_suggestion', { target_nickname: target, sugg_name: name, content: content, image_data: img });
                showToast(L.su);
                f.reset();
                window.suggImageCache = "";
                const preview = document.getElementById('sugg-img-preview');
                if (preview) preview.style.display = 'none';
            } catch (x) {
                showToast('Error: ' + x.message);
            } finally { btn.disabled = false; }
        }
        async function approveSugg(suggId) {
            try {
                await rpc('approve_suggestion', { suggestion_id: suggId });
                const card = document.getElementById('sugg-' + suggId);
                if (card) card.remove();
                showToast("Approved!");
            } catch (x) { showToast('Failed: ' + x.message); }
        }
        async function rejectSugg(suggId) {
            try {
                await rpc('reject_suggestion', { suggestion_id: suggId });
                const card = document.getElementById('sugg-' + suggId);
                if (card) card.remove();
                showToast("Rejected!");
            } catch (x) { showToast('Failed: ' + x.message); }
        }
    </script>
    """
    js = js.replace("__TOKEN__", token)
    js = js.replace("__ME__", current_user)
    js = js.replace("__DEL__", t('delete', lang))
    js = js.replace("__PIN__", t('pin', lang))
    js = js.replace("__UNPIN__", t('unpin', lang))
    js = js.replace("__CONFIRM__", t('confirm_delete', lang))
    js = js.replace("__NOPOSTS__", t('no_posts', lang))
    js = js.replace("__COPYLINK__", t('copy_link', lang))
    js = js.replace("__EXT_LOADING__", t('ext_loading', lang))
    js = js.replace("__SUGG_FILL__", t('sugges_error_fill', lang))
    js = js.replace("__SUGG_SELF__", t('sugges_error_self', lang))
    js = js.replace("__SUGG_SUCCESS__", t('sugges_success', lang))
    js = js.replace("__IMG_COMPRESSING__", t('img_compressing', lang))
    js = js.replace("__IMG_READY__", t('img_ready', lang))
    js = js.replace("__IMG_ERROR__", t('img_error', lang))
    js = js.replace("__IMG_BIG__", t('img_too_big', lang))
    js = js.replace("__SVG_EYE_OFF__", SVG_EYE_OFF)
    js = js.replace("__SVG_EYE__", SVG_EYE)
    return js

def get_overlay(lang):
    html = """
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay">
        <div class="modal-box">
            <p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p>
            <div class="modal-actions">
                <button id="modal-cancel" class="btn" style="background:#aaa;color:black;">__CANCEL__</button>
                <button id="modal-confirm" class="btn btn-danger">OK</button>
            </div>
        </div>
    </div>
    <div id="link-modal" class="modal-overlay">
        <div class="modal-box" style="text-align: left;">
            <h3 style="margin-top:0;">__EXT_TITLE__</h3>
            <p style="font-size:14px; color:#555; margin-bottom:10px;">__EXT_DESC__</p>
            <div id="og-preview" class="og-box"><p style="margin:0; font-size:14px; color:#666;">__EXT_LOADING__</p></div>
            <div class="modal-actions">
                <button onclick="closeLinkModal()" class="btn" style="background:#aaa;color:black;">__CANCEL__</button>
                <a id="link-modal-confirm" href="#" target="_blank" class="btn btn-danger" style="text-decoration: none; display: flex; align-items: center; justify-content: center;">__EXT_CONTINUE__</a>
            </div>
        </div>
    </div>
    """
    html = html.replace("__CANCEL__", t('cancel', lang))
    html = html.replace("__EXT_TITLE__", t('ext_title', lang))
    html = html.replace("__EXT_DESC__", t('ext_desc', lang))
    html = html.replace("__EXT_LOADING__", t('ext_loading', lang))
    html = html.replace("__EXT_CONTINUE__", t('ext_continue', lang))
    return html

def get_footer(lang):
    html = """
    <div class="footer">
        <div>__CREATED_BY__ <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | __HOSTING__ <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a></div>
        <div class="footer-links"><a href="/privacy">__PRIVACY_TITLE__</a> | <a href="/bugreport">__BUGREPORT_TITLE__</a></div>
        <div style="font-size: 12px; color: #999; margin-top: 5px;">v__APP_VERSION__ (__SERVER_START_DATE__)</div>
    </div>
    """
    html = html.replace("__CREATED_BY__", t('created_by', lang))
    html = html.replace("__HOSTING__", t('hosting', lang))
    html = html.replace("__PRIVACY_TITLE__", t('privacy_title', lang))
    html = html.replace("__BUGREPORT_TITLE__", t('bugreport_title', lang))
    html = html.replace("__APP_VERSION__", APP_VERSION)
    html = html.replace("__SERVER_START_DATE__", SERVER_START_DATE)
    return html

def auth_html(lang: str, error_msg: str = "", token: str = ""):
    eb = f"<div class='error-msg'>{error_msg}</div>" if error_msg else "<div class='error-msg'></div>"
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__LOGIN__ / __REG__</title>__CSS____JS__</head><body>
    <div class="container">
        <div class="auth-wrapper"><div class="label-text">__REG__</div><div class="form-box"><form action="/register" method="post">
            <input type="hidden" name="csrf_token" value="__TOKEN__">
            <input type="text" name="username" placeholder="__USERNAME__" required>
            <input type="text" name="nickname" placeholder="__NICKNAME__" required>
            <div class="input-group"><input type="password" name="password" id="rp" placeholder="__PASSWORD__" required><button type="button" class="eye-btn" onclick="tp('rp',this)">__SVG_EYE__</button></div>
            <div class="input-group"><input type="password" name="re_pass" id="rr" placeholder="__REPASS__" required><button type="button" class="eye-btn" onclick="tp('rr',this)">__SVG_EYE__</button></div>
            <label class="captcha-container"><input type="checkbox" name="captcha" required> __CAPTCHA__</label>
            <label class="captcha-container" style="background:#8c8c8c;margin-top:2px"><input type="checkbox" name="privacy" required><span>__PRIVACY_AGREE__ <a href="/privacy" target="_blank" class="privacy-link">__PRIVACY_LINK__</a></span></label>
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
    </div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__LOGIN__",t('login',lang)),("__REG__",t('reg',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),("__TOKEN__",token),
                 ("__USERNAME__",t('username',lang)),("__NICKNAME__",t('nickname',lang)),("__PASSWORD__",t('password',lang)),("__REPASS__",t('re_pass',lang)),
                 ("__CAPTCHA__",t('captcha',lang)),("__PRIVACY_AGREE__",t('privacy_agree',lang)),("__PRIVACY_LINK__",t('privacy_link',lang)),
                 ("__REG_BTN__",t('register_btn',lang)),("__LOGIN_BTN__",t('login_btn',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__ERROR__",eb),("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang)),("__SVG_EYE__",SVG_EYE)]:
        html = html.replace(k, v)
    return html

def render_records(records, lang, own=False, uid=None, avatar=""):
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
        if uid:
            acts += f"<button onclick='copyLink(\"{x.get('user_nickname','')}\",\"{rid}\", this)' class='action-btn link-btn'>{t('copy_link', lang)}</button>"
        if own:
            acts += f"<button onclick='hp(\"{rid}\",this)' class='action-btn pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button>"
            acts += f"<button onclick='hd(\"{rid}\",this)' class='action-btn'>{t('delete', lang)}</button>"
        acts += "</div>"
        sugg_html = f"<div class='post-suggested'>{t('suggested_by', lang)} {sugg_by}</div>" if sugg_by else ""
        img_html = f'<img class="post-image" src="{img}" alt="">' if img else ""
        item_html = """
        <div class="post-wrapper" id="post-__RID__">__ACTS__
            <div class="post-item __PC__">
                <div class="post-content">__CONTENT__</div>
                __IMG__
                <div class="post-footer">__SUGG__<div class="post-date">__DATE__</div></div>
            </div>
        </div>"""
        for k, v in [("__RID__",rid),("__ACTS__",acts),("__PC__",pc),("__CONTENT__",content),("__IMG__",img_html),("__DATE__",date),("__SUGG__",sugg_html)]:
            item_html = item_html.replace(k, v)
        out += item_html
    return out

def merge_memory(db_records, nickname):
    f = []
    if not db_records or not isinstance(db_records, list): db_records = []
    for x in db_records:
        if not isinstance(x, dict): continue
        x_id = x.get('id')
        if not x_id: continue
        if x_id in deleted_records: continue
        if x_id in pinned_records: x['is_pinned'] = pinned_records[x_id]
        f.append(x)
    for rid, x in pending_records.items():
        if not isinstance(x, dict): continue
        if x.get('user_nickname') == nickname: f.append(x)
    try:
        f.sort(key=lambda x: (bool(x.get('is_pinned')), str(x.get('created_at') or '')), reverse=True)
    except Exception: pass
    return f

def dashboard_html(nickname, user, my_p, lang, token, viewer):
    rh_my = render_records(my_p, lang, own=True, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = esc(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar">' if avatar else ""
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__CABINET__</title>__CSS____JS__</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>__CABINET__</h2>
        __AVATAR__
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br><a href="/__NICKNAME__" target="_blank">__NICKNAME__ __LINK_PROFILE__</a></div>__DB__
        <div class="info-card"><b>__TOTAL_POSTS__:</b><br>__POST_COUNT__</div>
        <a href="/cabinet/edit" class="btn edit-btn">__EDIT_PROFILE__</a>
        <a href="/cabinet/suggestions" class="btn sugges-btn">__SUGGESTIONS_TITLE__</a>
        <form action="/logout" method="get" style="margin: 0; width: 100%;"><button type="submit" class="logout-btn">__LOGOUT__</button></form>
        <div class="lang-switch"><a href="/set_lang/ru?next=/cabinet" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div>
    <div class="main-content">
        <div class="create-post-box"><form id="create-form" onsubmit="hc(event)">
            <textarea name="content" placeholder="__CREATE_POST_PLACEHOLDER__" required maxlength="500"></textarea>
            <label>__ATTACH_PHOTO__</label>
            <input type="file" accept="image/*" onchange="handlePostImage(this)">
            <img id="post-img-preview" class="img-preview" style="display:none;">
            <button type="submit" id="create-post-btn">__CREATE_POST_BTN__</button>
        </form></div>
        <div class="posts-area" id="my-records-container"><h2>__MY_POSTS__</h2>__RECORDS_HTML__</div>
    </div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__CABINET__",t('cabinet',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer)),
                 ("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),
                 ("__NICKNAME_LABEL__",t('nickname_label',lang)),("__NICKNAME__",esc(nickname)),("__LINK_PROFILE__",t('link_profile',lang)),
                 ("__DB__",db),("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(my_p))),
                 ("__EDIT_PROFILE__",t('edit_profile',lang)),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__LOGOUT__",t('logout',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__CREATE_POST_PLACEHOLDER__",t('create_post_placeholder',lang)),("__ATTACH_PHOTO__",t('attach_photo',lang)),
                 ("__CREATE_POST_BTN__",t('create_post_btn',lang)),("__MY_POSTS__",t('my_posts',lang)),("__RECORDS_HTML__",rh_my),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def suggestions_page_html(nickname, suggestions, lang, token):
    if not suggestions:
        rh = f"<div class='post-item'>{t('sugges_empty', lang)}</div>"
    else:
        rh = ""
        for s in suggestions:
            sid = esc(s.get('id'))
            sugg_by = esc(s.get('suggested_by_name'))
            content = linkify(s.get('content'))
            date = format_date(esc(s.get('created_at')))
            img = esc(s.get('image_data', ''))
            img_html = f'<img class="post-image" src="{img}" alt="">' if img else ""
            card = """
            <div class="suggestion-card" id="sugg-__SID__">
                <div class="sugg-author"><span class="sugg-name">__NAME__</span><span class="sugg-date">__DATE__</span></div>
                <div class="sugg-content">__CONTENT__</div>
                __IMG__
                <div class="sugg-actions" style="margin-top:10px;">
                    <button class="btn sugg-approve" onclick="approveSugg('__SID__')">__APPROVE__</button>
                    <button class="btn sugg-reject" onclick="rejectSugg('__SID__')">__REJECT__</button>
                </div>
            </div>"""
            for k, v in [("__SID__",sid),("__NAME__",sugg_by),("__DATE__",date),("__CONTENT__",content),("__IMG__",img_html),
                         ("__APPROVE__",t('sugges_approve',lang)),("__REJECT__",t('sugges_reject',lang))]:
                card = card.replace(k, v)
            rh += card
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__SUGGESTIONS_TITLE__</title>__CSS____JS__</head><body>
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="posts-area" style="min-height:300px;padding:20px;"><h2>__SUGGESTIONS_TITLE__</h2>__SUGGESTIONS_HTML__</div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">__BACK__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/suggestions" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/suggestions" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__SUGGESTIONS_TITLE__",t('suggestions_title',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),
                 ("__SUGGESTIONS_HTML__",rh),("__BACK__",t('back_home',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def sugges_form_html(nickname, lang, token, error="", viewer="", rules=""):
    msg_html = f"<div class='error-msg' style='color:#ff4d4d;'>{error}</div>" if error else ""
    is_own = (viewer == nickname)
    if is_own:
        form_block = f"<div class='error-msg' style='color:#ff4d4d;'>{t('sugges_own', lang)}</div>"
    else:
        form_block = """
            <form data-nickname="__NICK_ATTR__" onsubmit="submitSuggestion(event)" style="display:flex;flex-direction:column;gap:10px">
                <input type="text" name="sugg_name" placeholder="__SUGG_NAME__" required maxlength="60" style="background:#a9a9a9;padding:12px;font-size:16px;">
                <textarea name="content" placeholder="__SUGG_CONTENT__" required maxlength="500" style="background:#a9a9a9;height:150px;padding:12px;font-size:16px;"></textarea>
                <label style="color:#fff;font-size:14px;font-weight:bold;">__ATTACH_PHOTO__</label>
                <input type="file" accept="image/*" onchange="handleSuggImage(this)">
                <img id="sugg-img-preview" class="img-preview" style="display:none;">
                <button type="submit" id="sugg-submit-btn" style="background:#2ecc71;color:white;font-size:18px;">__SEND__</button>
            </form>
        """
        for k, v in [("__NICK_ATTR__",esc(nickname)),("__SUGG_NAME__",t('sugges_name',lang)),("__SUGG_CONTENT__",t('sugges_content',lang)),
                     ("__ATTACH_PHOTO__",t('attach_photo',lang)),("__SEND__",t('sugges_send',lang))]:
            form_block = form_block.replace(k, v)
    rules_block = f'<div class="rules-box"><b>{t("rules_title", lang)}</b><div class="rules-content">{esc(rules)}</div></div>' if rules else ""
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__TITLE__ __NICKNAME__</title>__CSS____JS__</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px">
        <div class="posts-area" style="padding:20px;">
            <h2>__TITLE__ __NICKNAME__</h2>
            __RULES_BLOCK____MSG____FORM_BLOCK__
            <a href="/__NICKNAME__" class="btn" style="background:#a9a9a9;margin-top:15px;">__BACK__</a>
            <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/__NICKNAME__/sugges" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/__NICKNAME__/sugges" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
        </div>
    </div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__TITLE__",t('sugges_title',lang)),("__NICKNAME__",esc(nickname)),("__CSS__",get_css()),
                 ("__JS__",get_js(lang, token, viewer)),("__RULES_BLOCK__",rules_block),("__MSG__",msg_html),("__FORM_BLOCK__",form_block),
                 ("__BACK__",t('back_home',lang)),("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def edit_html(nickname, user, lang, token):
    desc = esc(user.get('description'))
    rules = esc(user.get('sugges_rules', ''))
    avatar = esc(user.get('avatar_data', ''))
    avatar_html = f'<img id="avatar-preview" class="avatar" src="{avatar}" alt="avatar">' if avatar else '<img id="avatar-preview" class="avatar" style="display:none;" alt="avatar">'
    user_username = esc(user.get('username'))
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__EDIT_PROFILE__</title>__CSS____JS__</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px"><div class="posts-area" style="padding:20px">
        <h2 style="color:#fff;text-align:center">__EDIT_PROFILE__</h2>
        <form action="/cabinet/edit" method="post" style="display:flex;flex-direction:column;gap:10px">
            <input type="hidden" name="csrf_token" value="__TOKEN__">
            <input type="hidden" name="avatar_data" id="avatar-data" value="">
            __AVATAR_HTML__
            <div style="color:#fff;font-size:16px;margin-bottom:-5px">__ATTACH_AVATAR__</div>
            <input type="file" accept="image/*" onchange="handleAvatarChange(this)">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__USERNAME_LABEL__</div>
            <input type="text" name="username" value="__USERNAME__" required style="background:#a9a9a9;padding:12px;font-size:18px">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__DESCRIPTION__</div>
            <textarea name="description" maxlength="300" placeholder="__DESC_PLACEHOLDER__" oninput="uc(this)" style="background:#a9a9a9;height:120px;padding:12px;font-size:16px">__DESC__</textarea>
            <div id="char-count" style="color:#fff;text-align:right;font-size:14px">__DESC_LEN__ / 300</div>
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">__RULES_LABEL__</div>
            <textarea name="sugges_rules" maxlength="1000" placeholder="__RULES_PLACEHOLDER__" oninput="ucRules(this)" style="background:#a9a9a9;height:120px;padding:12px;font-size:16px">__RULES__</textarea>
            <div id="rules-count" style="color:#fff;text-align:right;font-size:14px">__RULES_LEN__ / 1000</div>
            <button type="submit" style="background:#4da6ff;color:#fff;margin-top:10px">__SAVE_CHANGES__</button>
            <a href="/cabinet" class="btn" style="background:#a9a9a9">__CANCEL__</a>
        </form>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/edit" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/cabinet/edit" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__EDIT_PROFILE__",t('edit_profile',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, nickname)),
                 ("__TOKEN__",token),("__AVATAR_HTML__",avatar_html),("__ATTACH_AVATAR__",t('attach_avatar',lang)),
                 ("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",user_username),("__DESCRIPTION__",t('description',lang)),
                 ("__DESC_PLACEHOLDER__",t('desc_placeholder',lang)),("__DESC__",desc),("__DESC_LEN__",str(len(desc))),
                 ("__RULES_LABEL__",t('rules_edit_label',lang)),("__RULES_PLACEHOLDER__",t('rules_placeholder',lang)),("__RULES__",rules),
                 ("__RULES_LEN__",str(len(rules))),("__SAVE_CHANGES__",t('save_changes',lang)),("__CANCEL__",t('cancel',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def public_html(nickname, user, records, lang, token, viewer):
    is_owner = (viewer == nickname)
    rh = render_records(records, lang, own=is_owner, uid=viewer)
    user_username = esc(user.get('username'))
    desc = esc(user.get('description'))
    avatar = esc(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar">' if avatar else ""
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    sugg_btn = ""
    if not is_owner:
        sugg_btn = f"<a href='/{nickname}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PROFILE__ __NICKNAME__</title>__CSS____JS__</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>__PROFILE__</h2>
        __AVATAR__
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br>__NICKNAME__</div>__DB__
        <div class="info-card"><b>__TOTAL_POSTS__:</b><br>__POST_COUNT__</div>
        __SUGG_BTN__
        <div class="lang-switch"><a href="/set_lang/ru?next=/__NICKNAME__" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/__NICKNAME__" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
        <a href="/" class="btn" style="margin-top:auto;background:#a9a9a9">__BACK_HOME__</a>
    </div><div class="main-content"><div class="posts-area" style="min-height:500px">
        <h2>__USER_POSTS__</h2>__RECORDS_HTML__
    </div></div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__PROFILE__",t('profile',lang)),("__NICKNAME__",esc(nickname)),("__CSS__",get_css()),
                 ("__JS__",get_js(lang, token, viewer or "")),("__AVATAR__",avatar_html),("__USERNAME_LABEL__",t('username_label',lang)),
                 ("__USERNAME__",user_username),("__NICKNAME_LABEL__",t('nickname_label',lang)),("__DB__",db),
                 ("__TOTAL_POSTS__",t('total_posts',lang)),("__POST_COUNT__",str(len(records))),("__SUGG_BTN__",sugg_btn),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__BACK_HOME__",t('back_home',lang)),("__USER_POSTS__",t('user_posts',lang)),("__RECORDS_HTML__",rh),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, uid=viewer)
    avatar = esc(user.get('avatar_data', ''))
    avatar_html = f'<img class="avatar" src="{avatar}" alt="avatar">' if avatar else ""
    sugg_btn = ""
    if not viewer or viewer != nickname:
        sugg_btn = f"<a href='/{nickname}/sugges' class='btn' style='background:#2ecc71;color:white;margin-top:5px;'>{t('suggestions_btn', lang)}</a>"
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__RECORD_PAGE__</title>__CSS____JS__</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>__PROFILE__</h2>
        __AVATAR__
        <div class="info-card"><b>__NICKNAME_LABEL__:</b><br><a href="/__NICKNAME__">__NICKNAME__</a></div>
        <div class="info-card"><b>__USERNAME_LABEL__:</b><br>__USERNAME__</div>
        __SUGG_BTN__
        <a href="/__NICKNAME__" class="btn" style="margin-top:auto;background:#a9a9a9">__BACK_HOME__</a>
    </div><div class="main-content"><div class="posts-area"><h2>__RECORD_PAGE__</h2>__RECORDS_HTML__</div></div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__RECORD_PAGE__",t('record_page',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, viewer or "")),
                 ("__PROFILE__",t('profile',lang)),("__AVATAR__",avatar_html),("__NICKNAME_LABEL__",t('nickname_label',lang)),
                 ("__NICKNAME__",esc(nickname)),("__USERNAME_LABEL__",t('username_label',lang)),("__USERNAME__",esc(user.get('username'))),
                 ("__SUGG_BTN__",sugg_btn),("__BACK_HOME__",t('back_home',lang)),("__RECORDS_HTML__",rh),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def bugreport_html(username, reports, lang, token):
    rh = "<div class='post-item'>Заявок пока нет...</div>" if not reports else ""
    for x in reports:
        item = """
        <div class="post-item" style="border-left-color:transparent">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;">
                <b>__BUGREPORT_TITLE__</b><span class="status-badge status-__STATUS_CLASS__">__STATUS__</span>
            </div>
            <div class="post-content" style="text-align:left;">__CONTENT__</div>
            <div class="post-date">__DATE__</div>
        </div>"""
        for k, v in [("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__STATUS_CLASS__",esc(x.get('status','Принято')).replace(' ','-')),
                     ("__STATUS__",esc(x.get('status','Принято'))),("__CONTENT__",esc(x.get('content'))),
                     ("__DATE__",format_date(esc(x.get('created_at'))))]:
            item = item.replace(k, v)
        rh += item
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__BUGREPORT_TITLE__</title>__CSS____JS__</head><body>
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="create-post-box"><h2 style="color:#fff;text-align:center;margin:10px 0">__BUGREPORT_TITLE__</h2>
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:5px">
                <input type="hidden" name="csrf_token" value="__TOKEN__">
                <input type="text" name="name" value="__USERNAME__" placeholder="__BUGREPORT_NAME__" required style="background:#a9a9a9;padding:12px;margin-bottom:5px">
                <textarea name="content" placeholder="__BUGREPORT_DESC__" required style="background:#a9a9a9;height:150px;padding:12px;margin-bottom:5px"></textarea>
                <button type="submit" style="background:#f1c40f;color:#000">__BUGREPORT_SEND__</button>
            </form>
        </div>
        <div class="posts-area"><h2>__BUGREPORT_MY__</h2>__REPORTS_HTML__</div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">__CANCEL__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/bugreport" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/bugreport" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div>__FOOTER____OVERLAY__</body></html>
    """
    for k, v in [("__LANG__",lang),("__BUGREPORT_TITLE__",t('bugreport_title',lang)),("__CSS__",get_css()),("__JS__",get_js(lang, token, "")),
                 ("__TOKEN__",token),("__USERNAME__",esc(username)),("__BUGREPORT_NAME__",t('bugreport_name',lang)),
                 ("__BUGREPORT_DESC__",t('bugreport_desc',lang)),("__BUGREPORT_SEND__",t('bugreport_send',lang)),
                 ("__BUGREPORT_MY__",t('bugreport_my',lang)),("__REPORTS_HTML__",rh),("__CANCEL__",t('cancel',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__FOOTER__",get_footer(lang)),("__OVERLAY__",get_overlay(lang))]:
        html = html.replace(k, v)
    return html

def privacy_html(lang, token):
    html = """
    <!DOCTYPE html><html lang="__LANG__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#000000">
    <title>__PRIVACY_TITLE__</title>__CSS__</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:800px"><div class="posts-area" style="padding:20px">
        <h2 style="color:#fff;text-align:center;margin-bottom:20px">__PRIVACY_TITLE__</h2>
        <div class="privacy-content">__PRIVACY_TEXT__</div>
        <a href="/" class="btn" style="background:#a9a9a9;margin-top:20px">__BACK_HOME__</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/privacy" class="btn lang-btn __RU_ACTIVE__">RU</a><a href="/set_lang/en?next=/privacy" class="btn lang-btn __EN_ACTIVE__">EN</a></div>
    </div></div></div>__FOOTER__</body></html>
    """
    for k, v in [("__LANG__",lang),("__PRIVACY_TITLE__",t('privacy_title',lang)),("__CSS__",get_css()),
                 ("__PRIVACY_TEXT__",t('privacy_text',lang)),("__BACK_HOME__",t('back_home',lang)),
                 ("__RU_ACTIVE__","active" if lang=='ru' else ""),("__EN_ACTIVE__","active" if lang=='en' else ""),
                 ("__FOOTER__",get_footer(lang))]:
        html = html.replace(k, v)
    return html

# --- МАРШРУТЫ ---
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
            res_db = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', nickname).execute())
            if res_db.data:
                resp = RedirectResponse("/cabinet", 303)
                set_csrf_cookie(resp, token, r)
                return resp
        except Exception: pass
    res = HTMLResponse(auth_html(lang, "", token))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    res = HTMLResponse(privacy_html(lang, token))
    set_csrf_cookie(res, token, r)
    return res

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
    resp = RedirectResponse("/cabinet", 303)
    resp.set_cookie("nickname", nickname, httponly=True, samesite="lax")
    set_csrf_cookie(resp, token, r)
    return resp

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if not check_csrf(r, csrf_token): 
        resp = HTMLResponse(auth_html(lang, "CSRF Error", token)); set_csrf_cookie(resp, token, r); return resp
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    try:
        x = await asyncio.to_thread(lambda: sb.table('users').select('password').eq('nickname', nickname).execute())
        user = x.data[0] if x.data else None
        if user and verify_password(password, user.get("password", "")):
            if len(user["password"]) == 64:
                await asyncio.to_thread(lambda: sb.table('users').update({"password": hash_password(password)}).eq('nickname', nickname).execute())
            resp = RedirectResponse("/cabinet", 303)
            resp.set_cookie("nickname", nickname, httponly=True, samesite="lax")
            set_csrf_cookie(resp, token, r)
            return resp
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
    return auth_html(lang, t('alert_bad_login', lang), token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        resp = RedirectResponse("/", 303); resp.delete_cookie("nickname"); return resp
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(nickname, user_data, po, lang, token, nickname))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/cabinet/suggestions", response_class=HTMLResponse)
async def cabinet_suggestions(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    s_data = await _fetch_suggestions(nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(suggestions_page_html(nickname, s_data, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/{nickname}/sugges", response_class=HTMLResponse)
async def sugges_form(nickname: str, r: Request, lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname") or ""
    user_data = await _fetch_user(nickname)
    if not user_data:
        return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
    rules = user_data.get('sugges_rules', '') or ''
    res = HTMLResponse(sugges_form_html(nickname, lang, token, viewer=viewer, rules=rules))
    set_csrf_cookie(res, token, r)
    return res

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
            u = await asyncio.to_thread(lambda: sb.table('users').select('nickname').eq('nickname', target).execute())
            if not u.data: raise HTTPException(404, "User not found")
        except HTTPException: raise
        except Exception as e: raise HTTPException(500, str(e))
        data = {"author_nickname": target, "suggested_by_name": sugg_name, "content": content, "status": "pending", "image_data": image_data}
        try:
            await asyncio.to_thread(lambda: sb.table('suggestions').insert(data).execute())
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
            try:
                await asyncio.to_thread(lambda: sb.table('posts').insert(pd).execute())
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
            if not x.data or not isinstance(x.data, list) or len(x.data) == 0: raise HTTPException(404, "Not found")
            ns = not x.data[0].get('is_pinned', False)
            await asyncio.to_thread(lambda: sb.table('posts').update({"is_pinned": ns}).eq('id', rid).eq('user_nickname', nickname).execute())
            return {"status": "ok", "is_pinned": ns}
        elif req.method == "approve_suggestion":
            sid = req.params.get("suggestion_id")
            s = await asyncio.to_thread(lambda: sb.table('suggestions').select('*').eq('id', sid).eq('author_nickname', nickname).eq('status', 'pending').execute())
            if not s.data or not isinstance(s.data, list) or len(s.data) == 0: raise HTTPException(404, "Suggestion not found")
            sugg = s.data[0]
            i = str(uuid.uuid4())
            n = datetime.now(timezone.utc).isoformat()
            new_post = {"id": i, "user_nickname": nickname, "content": sugg.get('content', ''), "is_pinned": False, "created_at": n,
                        "suggested_by": sugg.get('suggested_by_name', ''), "image_data": sugg.get('image_data', '') or ''}
            try:
                await asyncio.to_thread(lambda: sb.table('posts').insert(new_post).execute())
            except Exception:
                new_post.pop("suggested_by", None); new_post.pop("image_data", None)
                await asyncio.to_thread(lambda: sb.table('posts').insert(new_post).execute())
            await asyncio.to_thread(lambda: sb.table('suggestions').update({"status": "approved"}).eq('id', sid).execute())
            await manager.broadcast({"type": "new_record", "post_id": i})
            return {"status": "ok", "id": i}
        elif req.method == "reject_suggestion":
            sid = req.params.get("suggestion_id")
            await asyncio.to_thread(lambda: sb.table('suggestions').update({"status": "rejected"}).eq('id', sid).eq('author_nickname', nickname).execute())
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
    res = HTMLResponse(edit_html(nickname, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, username: str = Form(...), description: str = Form(""), sugges_rules: str = Form(""), avatar_data: str = Form(""), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse("/", 303)
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
    if len(description) > 300: return HTMLResponse(f"<script>showToast('{t('alert_desc_long', lang)}');window.history.back()</script>")
    if len(sugges_rules) > 1000: return HTMLResponse(f"<script>showToast('{t('rules_alert_long', lang)}');window.history.back()</script>")
    update = {"username": username, "description": description, "sugges_rules": sugges_rules}
    av = valid_b64(avatar_data)
    if av: update["avatar_data"] = av
    try:
        await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
    except Exception:
        update.pop("avatar_data", None); update.pop("sugges_rules", None)
        try:
            await asyncio.to_thread(lambda: sb.table('users').update(update).eq('nickname', nickname).execute())
        except Exception: pass
    return RedirectResponse("/cabinet", 303)

@app.get("/bugreport", response_class=HTMLResponse)
async def bugreport(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    u = ""
    rp = []
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
    return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
    d = {"name": name, "content": content, "status": "Принято" if lang == "ru" else "Accepted"}
    if nickname: d["user_nickname"] = nickname
    await asyncio.to_thread(lambda: sb.table('bug_reports').insert(d).execute())
    return RedirectResponse("/bugreport", 303)

@app.get("/logout")
async def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("nickname")
    return res

@app.get("/{nickname}/{rid}", response_class=HTMLResponse)
async def record_page(nickname: str, rid: str, r: Request, lang: str = Cookie("ru")):
    try:
        u, x = await asyncio.gather(
            asyncio.to_thread(lambda: sb.table('users').select('username,avatar_data').eq('nickname', nickname).execute()),
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
    return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    user_data, p_data = await asyncio.gather(_fetch_user(nickname), _fetch_posts(nickname))
    if not user_data:
        return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/'>OK</a></h2>", 404)
    viewer = r.cookies.get("nickname") or ""
    po = merge_memory(p_data, nickname)
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, user_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r)
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
