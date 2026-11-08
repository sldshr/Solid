from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn, html, bcrypt, secrets, uuid, hashlib, re, random
from datetime import datetime, timezone
from typing import Optional

app = FastAPI()

# --- НАСТРОЙКИ SUPABASE ---
S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

# --- ОПЕРАТИВНАЯ ПАМЯТЬ ---
deleted_records = set()
pinned_records = {}
pending_records = {}

# --- БЕЗОПАСНЫЙ HTML И BB-КОДЫ ---
def esc(val):
    return html.escape(str(val)) if val is not None else ""

def parse_bb(text: str) -> str:
    if not text: return ""
    # 1. Экранируем весь HTML для безопасности
    t = html.escape(text)
    
    # 2. Простые теги
    t = re.sub(r'\[b\](.*?)\[/b\]', r'<b>\1</b>', t, flags=re.IGNORECASE|re.DOTALL)
    t = re.sub(r'\[i\](.*?)\[/i\]', r'<i>\1</i>', t, flags=re.IGNORECASE|re.DOTALL)
    t = re.sub(r'\[u\](.*?)\[/u\]', r'<u>\1</u>', t, flags=re.IGNORECASE|re.DOTALL)
    t = re.sub(r'\[s\](.*?)\[/s\]', r'<s>\1</s>', t, flags=re.IGNORECASE|re.DOTALL)
    
    # 3. Цвет (поддерживаем hex и названия)
    def replace_color(m):
        color = m.group(1)
        if re.match(r'^#[0-9a-fA-F]{3,6}$', color) or re.match(r'^[a-zA-Z]+$', color):
            return f'<span style="color:{color}">' + m.group(2) + '</span>'
        return m.group(0)
    t = re.sub(r'\[color=([^\]]+)\](.*?)\[/color\]', replace_color, t, flags=re.IGNORECASE|re.DOTALL)
    
    # 4. Размер (только цифры)
    def replace_size(m):
        size = m.group(1)
        if size.isdigit():
            return f'<span style="font-size:{size}px">' + m.group(2) + '</span>'
        return m.group(0)
    t = re.sub(r'\[size=([^\]]+)\](.*?)\[/size\]', replace_size, t, flags=re.IGNORECASE|re.DOTALL)
    
    # 5. Свечение (Glow)
    def replace_glow(m):
        color = m.group(1)
        if re.match(r'^#[0-9a-fA-F]{3,6}$', color) or re.match(r'^[a-zA-Z]+$', color):
            return f'<span style="text-shadow: 0 0 5px {color}, 0 0 10px {color}, 0 0 15px {color}">' + m.group(2) + '</span>'
        return m.group(0)
    t = re.sub(r'\[glow=([^\]]+)\](.*?)\[/glow\]', replace_glow, t, flags=re.IGNORECASE|re.DOTALL)
    
    # 6. Ссылки
    def replace_url(m):
        url = m.group(1)
        if url.startswith('http://') or url.startswith('https://'):
            return f'<a href="{url}" target="_blank" style="color:#4da6ff;text-decoration:underline">' + m.group(2) + '</a>'
        return m.group(0)
    t = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', replace_url, t, flags=re.IGNORECASE|re.DOTALL)
    
    # 7. Переносы строк
    t = t.replace('\n', '<br>')
    return t

# --- WEBSOCKET МЕНЕДЖЕР (REAL-TIME) ---
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

# --- БЕЗОПАСНОСТЬ ---
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
    header_token = request.headers.get("X-CSRF-Token")
    return cookie_token and (cookie_token == form_token or cookie_token == header_token)

def set_csrf_cookie(response: Response, token: str, request: Request):
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", token, httponly=True, samesite="lax")

async def auth_middleware(r: Request, nickname: Optional[str] = Cookie(None)):
    if not nickname:
        raise HTTPException(status_code=401)
    try:
        x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
        if not x.data or not isinstance(x.data, list) or len(x.data) == 0:
            raise HTTPException(status_code=401)
    except Exception:
        raise HTTPException(status_code=401)
    return nickname

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    lang = request.cookies.get("lang", "ru")
    error_msg = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    response = HTMLResponse(content=auth_html(lang, error_msg, token), status_code=422)
    set_csrf_cookie(response, token, request)
    return response

# --- RPC МОДЕЛЬ ---
class RPCRequest(BaseModel):
    method: str
    params: dict = {}

# --- ПЕРЕВОДЫ ---
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
        "privacy_text": "1. Сбор информации. Мы собираем только ваш юзернейм, никнейм и хеш пароля. Пароли хранятся в зашифрованном виде (bcrypt).<br><br>2. Использование данных. Данные используются для аутентификации и отображения профиля. Мы не передаем данные третьим лицам.<br><br>3. Контент. Ваши записи и лайки хранятся на серверах Supabase.<br><br>4. Cookies. Сайт использует cookies для сессии и выбранного языка.<br><br>5. Ваши права. Вы можете изменить профиль или удалить записи в любой момент.",
        "privacy_agree": "Я согласен с", "privacy_link": "Политикой конфиденциальности",
        "alert_privacy": "Примите политику!", "cabinet": "ЛИЧНЫЙ КАБИНЕТ",
        "record_page": "Запись", "vote_err": "Вы уже голосовали!", "copy_link": "Ссылка",
        "nickgen_title": "Генератор никнеймов", "nickgen_desc": "Выберите стиль и нажмите кнопку, чтобы сгенерировать красивые никнеймы.",
        "gen_btn": "Сгенерировать", "copy": "Копировать", "bb_help": "Поддерживаются BB-коды: [b]жирный[/b], [i]курсив[/i], [u]подчеркнутый[/u], [s]зачеркнутый[/s], [color=red]цвет[/color], [size=24]размер[/size], [glow=#00ff00]свечение[/glow], [url=http://link]ссылка[/url]"
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
        "privacy_text": "1. Data Collection. We collect only your username, nickname, and hashed password (bcrypt).<br><br>2. Data Usage. Data is used for authentication and profile display. We do not share data with third parties.<br><br>3. Content. Your records and votes are stored on Supabase.<br><br>4. Cookies. The site uses cookies for session and language preferences.<br><br>5. Your Rights. You can edit your profile or delete records at any time.",
        "privacy_agree": "I agree to the", "privacy_link": "Privacy Policy",
        "alert_privacy": "Accept the Privacy Policy!", "cabinet": "PERSONAL CABINET",
        "record_page": "Record", "vote_err": "You already voted!", "copy_link": "Link",
        "nickgen_title": "Nickname Generator", "nickgen_desc": "Choose a style and click the button to generate beautiful nicknames.",
        "gen_btn": "Generate", "copy": "Copy", "bb_help": "Supported BB codes: [b]bold[/b], [i]italic[/i], [u]underline[/u], [s]strike[/s], [color=red]color[/color], [size=24]size[/size], [glow=#00ff00]glow[/glow], [url=http://link]link[/url]"
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

# --- SVG ИКОНКИ ---
SVG_EYE = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"""
SVG_LIKE = """<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='green' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3'></path></svg>"""
SVG_DISLIKE = """<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='red' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-2'></path></svg>"""

# --- CSS ---
def get_css():
    return """
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
        button, .btn { background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px; font-family: Arial, sans-serif; width: 100%; text-align: center; cursor: pointer; color: black; font-weight: bold; display: inline-block; border: 1px solid transparent; }
        button:hover, .btn:hover { background-color: #8c8c8c; }
        
        .eye-btn { position: absolute; right: 5px; background: transparent; border: none; cursor: pointer; width: 40px; padding: 5px; display: flex; align-items: center; justify-content: center; }
        .label-text { font-size: 32px; font-weight: normal; margin-bottom: 10px; white-space: nowrap; }
        
        .captcha-container { background-color: #a9a9a9; padding: 10px; display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; cursor: pointer; font-size: 16px; font-weight: bold; text-align: center;}
        .captcha-container input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; flex-shrink: 0;}
        .privacy-link { color: #0000ff; text-decoration: underline; margin-left: 5px;}

        .dashboard-container { display: flex; gap: 20px; width: 100%; max-width: 1200px; margin: 0 auto; align-items: flex-start; }
        .sidebar { background: black; padding: 10px; width: 350px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; }
        .sidebar h2 { color: white; text-align: center; font-size: 24px; margin: 10px 0; }
        
        .info-card { background: #a9a9a9; padding: 15px; font-size: 18px; text-align: center; word-wrap: break-word; white-space: pre-wrap; }
        .logout-btn { margin-top: 10px; background: #ff4d4d; }
        .logout-btn:hover { background: #cc0000; }
        .edit-btn { background: #4da6ff; margin-top: 5px; color: white;}
        .edit-btn:hover { background: #1a82e2; }
        .gen-btn { background: #9b59b6; color: white; margin-top: 5px; }
        .gen-btn:hover { background: #8e44ad; }
        
        .main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
        
        .create-post-box { background: black; padding: 10px; display: flex; flex-direction: column; gap: 10px; border-radius: 5px; }
        .create-post-box textarea { height: 100px; font-size: 16px; padding: 10px; border-radius: 3px; }

        .tabs-container { background: black; padding: 10px; border-radius: 5px; display: flex; flex-direction: column; gap: 10px; }

        .posts-area { padding: 0; display: flex; flex-direction: column; gap: 10px; }
        .posts-area h2 { color: white; font-size: 24px; margin: 0 0 10px 0; text-align: center;}
        
        .post-wrapper { position: relative; transition: opacity 0.3s ease; }
        .post-item { background: #a9a9a9; padding: 15px; font-size: 16px; word-wrap: break-word; border-left: 5px solid transparent; display: flex; flex-direction: column; border-radius: 3px;}
        .post-item.pinned { border-left: 5px solid #ff4d4d; background: #d9d9d9; }
        
        .post-header { display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 14px; color: #333; border-bottom: 1px solid #888; padding-bottom: 5px; flex-wrap: wrap; gap: 5px; }
        .post-content { margin-bottom: 10px; font-size: 18px; }
        .post-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; border-top: 1px solid #888; padding-top: 5px; flex-wrap: wrap; gap: 10px; }
        .post-date { font-size: 12px; color: #555; }
        
        .vote-btns { display: flex; gap: 10px; }
        .vote-btn { background: #888; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 5px; font-weight: bold; font-size: 14px; }
        .vote-btn:hover { background: #666; }
        .vote-btn.active { background: #4da6ff !important; }
        .vote-btn.like.active { background: #2ecc71 !important; }
        .vote-btn.dislike.active { background: #e74c3c !important; }

        .post-actions { position: absolute; top: 5px; right: 5px; display: flex; gap: 5px; opacity: 0; transition: opacity 0.2s; z-index: 10; }
        .post-wrapper:hover .post-actions { opacity: 1; }
        .action-btn { background: black; color: white; border: none; padding: 5px 10px; font-size: 12px; cursor: pointer; border-radius: 3px; width: auto; font-weight: normal;}
        .action-btn:hover { background: #ff4d4d; }
        .action-btn.pin-btn:hover { background: #4da6ff; }
        .action-btn.link-btn:hover { background: #f1c40f; color: black; }

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

        #toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #333; color: white; padding: 12px 24px; border-radius: 5px; opacity: 0; transition: opacity 0.3s; z-index: 9999; font-weight: bold; pointer-events: none; text-align: center; }
        #toast.show { opacity: 1; }
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; justify-content: center; align-items: center; }
        .modal-overlay.show { display: flex; }
        .modal-box { background: white; padding: 30px; border-radius: 5px; max-width: 400px; width: 90%; text-align: center; border: 5px solid #000; }
        .modal-actions { display: flex; gap: 10px; margin-top: 20px; }
        .btn-danger { background: #ff4d4d; color: white; }
        .btn-danger:hover { background: #cc0000; }

        /* Nickname Generator Styles */
        .nickgen-container { background: black; padding: 20px; border-radius: 5px; color: white; text-align: center; }
        .nickgen-title { font-size: 28px; margin-bottom: 10px; color: #9b59b6; text-shadow: 0 0 10px #9b59b6; }
        .nickgen-desc { font-size: 16px; margin-bottom: 20px; color: #ccc; }
        .nickgen-styles { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
        .style-btn { background: #333; color: white; border: 2px solid #555; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.2s; width: auto; }
        .style-btn.active { background: #9b59b6; border-color: #9b59b6; }
        .style-btn:hover { border-color: #9b59b6; }
        .nickgen-output { display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }
        .nick-item { display: flex; justify-content: space-between; align-items: center; background: #222; padding: 15px; border-radius: 5px; border-left: 5px solid #9b59b6; font-family: monospace; font-size: 20px; }
        .copy-nick-btn { background: #4da6ff; color: white; border: none; padding: 8px 15px; border-radius: 3px; cursor: pointer; font-weight: bold; width: auto; }
        .copy-nick-btn:hover { background: #1a82e2; }

        @media (max-width: 768px) {
            body { padding: 10px; }
            .container { flex-direction: column; padding: 15px; gap: 20px; border-width: 5px; width: 100%; }
            .auth-wrapper { width: 100%; }
            .auth-wrapper-inner { flex-direction: column; gap: 10px; width: 100%; align-items: stretch;}
            .label-text { font-size: 28px; text-align: center; margin: 10px 0 0 0; order: -1; }
            .dashboard-container { flex-direction: column; gap: 15px; }
            .sidebar { width: 100%; }
            .main-content { width: 100%; }
            .tabs-container { padding: 10px; }
            .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
            .error-msg { text-align: center; }
            .login-lang-wrapper { justify-content: center; }
            .create-post-box { padding: 10px; }
            .post-item { padding: 10px; }
            .post-footer { flex-direction: column; align-items: flex-start; gap: 10px; }
            .vote-btns { width: 100%; justify-content: space-between; }
            .vote-btn { width: 48%; justify-content: center; }
            .nick-item { flex-direction: column; gap: 10px; text-align: center; }
            .copy-nick-btn { width: 100%; }
        }
    </style>
    """

# --- JS ---
def get_js(lang, token):
    return f"""
    <script>
        const T = "{token}";
        const L = {{
            d: "{t('delete', lang)}", p: "{t('pin', lang)}", u: "{t('unpin', lang)}",
            c: "{t('confirm_delete', lang)}", n: "{t('no_posts', lang)}",
            ve: "{t('vote_err', lang)}", copy: "{t('copy', lang)}"
        }};

        let ws;
        function connectWS() {{
            const proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            ws = new WebSocket(proto + window.location.host + '/ws');
            ws.onmessage = (e) => {{
                const d = JSON.parse(e.data);
                if (d.type === 'vote') {{
                    const p = document.getElementById('post-' + d.post_id);
                    if (p && p.dataset.pendingVote !== "true") {{
                        const likeSpan = p.querySelector('.v-l');
                        const dislikeSpan = p.querySelector('.v-d');
                        if (likeSpan) likeSpan.innerText = d.likes;
                        if (dislikeSpan) dislikeSpan.innerText = d.dislikes;
                    }}
                }} else if (d.type === 'delete_record') {{
                    const p = document.getElementById('post-' + d.post_id);
                    if (p) p.remove();
                }}
            }};
            ws.onclose = () => setTimeout(connectWS, 3000);
        }}
        connectWS();

        function copyLink(user, rid, btn) {{
            if (!user) return;
            const url = window.location.origin + '/' + user + '/' + rid;
            navigator.clipboard.writeText(url).then(() => {{
                showToast("Link copied!");
            }}).catch(() => {{
                showToast("Failed to copy");
            }});
        }}

        function showToast(msg) {{
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 3000);
        }}

        function showConfirm(msg, cb) {{
            const m = document.getElementById('modal-overlay');
            document.getElementById('modal-text').innerText = msg;
            m.classList.add('show');
            
            const cBtn = document.getElementById('modal-confirm');
            const xBtn = document.getElementById('modal-cancel');
            
            const nC = cBtn.cloneNode(true);
            const nX = xBtn.cloneNode(true);
            cBtn.parentNode.replaceChild(nC, cBtn);
            xBtn.parentNode.replaceChild(nX, xBtn);
            
            nC.onclick = () => {{ m.classList.remove('show'); cb(true); }};
            nX.onclick = () => {{ m.classList.remove('show'); cb(false); }};
        }}

        async function rpc(method, params) {{
            const res = await fetch('/rpc', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': T }},
                body: JSON.stringify({{ method, params }})
            }});
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || data.error || 'RPC Error');
            return data;
        }}

        function tp(i, b) {{
            const x = document.getElementById(i);
            if (x.type === 'password') {{ x.type = 'text'; b.innerHTML = `{SVG_EYE_OFF}`; }}
            else {{ x.type = 'password'; b.innerHTML = `{SVG_EYE}`; }}
        }}

        function uc(e) {{ document.getElementById('char-count').innerText = e.value.length + ' / 300'; }}

        async function hc(e) {{
            e.preventDefault();
            const f = e.target, c = f.querySelector('textarea').value.trim();
            if (!c) return;
            const i = crypto.randomUUID(), n = new Date();
            const d = n.toLocaleDateString('ru-RU') + ' ' + n.toLocaleTimeString('ru-RU', {{hour: '2-digit', minute:'2-digit'}});
            const a = document.querySelector('#my-records-container');
            const m = a.querySelector('.post-item:not(.post-wrapper)');
            if (m) m.remove();

            // Временно выводим сырой текст (без BB), сервер отрендерит при перезагрузке
            const w = document.createElement('div');
            w.className = 'post-wrapper'; w.id = 'post-' + i;
            w.innerHTML = `
                <div class="post-actions">
                    <button onclick="hp('${{i}}',this)" class="action-btn pin-btn">${{L.p}}</button>
                    <button onclick="hd('${{i}}',this)" class="action-btn">${{L.d}}</button>
                </div>
                <div class="post-item">
                    <div class="post-content">${{c.replace(/</g,'&lt;').replace(/>/g,'&gt;')}}</div>
                    <div class="post-footer">
                        <div class="vote-btns">
                            <button onclick="toggleVote('${{i}}',1,this)" class="vote-btn like">{SVG_LIKE} <span class="v-l">0</span></button>
                            <button onclick="toggleVote('${{i}}',-1,this)" class="vote-btn dislike">{SVG_DISLIKE} <span class="v-d">0</span></button>
                        </div>
                        <div class="post-date">${{d}}</div>
                    </div>
                </div>`;
            a.insertBefore(w, a.children[1]);
            f.reset();

            try {{
                await rpc('create_record', {{ content: c, client_id: i }});
                setTimeout(() => window.location.reload(), 500); // Перезагрузка для отображения BB-кодов
            }} catch (x) {{
                w.remove(); showToast('Failed: ' + x.message);
            }}
        }}

        function hd(i) {{
            showConfirm(L.c, async (yes) => {{
                if (!yes) return;
                const w = document.getElementById('post-' + i);
                w.style.opacity = '0'; setTimeout(() => w.style.display = 'none', 300);
                try {{
                    await rpc('delete_record', {{ post_id: i }});
                    w.remove();
                }} catch (x) {{
                    w.style.opacity = '1'; w.style.display = 'block'; showToast('Failed: ' + x.message);
                }}
            }});
        }}

        async function hp(i, b) {{
            const w = document.getElementById('post-' + i), p = w.querySelector('.post-item'), s = p.classList.contains('pinned');
            if (s) {{ p.classList.remove('pinned'); b.innerText = L.p; }}
            else {{
                p.classList.add('pinned'); b.innerText = L.u;
                const a = w.parentNode; a.insertBefore(w, a.children[1]);
            }}
            try {{
                await rpc('pin_record', {{ post_id: i }});
            }} catch (x) {{
                if (s) {{ p.classList.add('pinned'); b.innerText = L.u; }}
                else {{ p.classList.remove('pinned'); b.innerText = L.p; }}
                showToast('Failed: ' + x.message);
            }}
        }}

        const voteTimers = {{}};
        async function toggleVote(postId, type, btn) {{
            const wrapper = document.getElementById('post-' + postId);
            if (!wrapper) return;
            
            const likeBtn = wrapper.querySelector('.vote-btn.like');
            const dislikeBtn = wrapper.querySelector('.vote-btn.dislike');
            const likeSpan = wrapper.querySelector('.v-l');
            const dislikeSpan = wrapper.querySelector('.v-d');
            
            if (!likeSpan || !dislikeSpan || !likeBtn || !dislikeBtn) return;

            wrapper.dataset.pendingVote = "true";

            let likes = parseInt(likeSpan.innerText) || 0;
            let dislikes = parseInt(dislikeSpan.innerText) || 0;
            
            const isLiked = likeBtn.classList.contains('active');
            const isDisliked = dislikeBtn.classList.contains('active');
            
            if (type === 1) {{
                if (isLiked) {{
                    likeBtn.classList.remove('active');
                    likes = Math.max(0, likes - 1);
                }} else {{
                    likeBtn.classList.add('active');
                    likes += 1;
                    if (isDisliked) {{
                        dislikeBtn.classList.remove('active');
                        dislikes = Math.max(0, dislikes - 1);
                    }}
                }}
            }} else {{
                if (isDisliked) {{
                    dislikeBtn.classList.remove('active');
                    dislikes = Math.max(0, dislikes - 1);
                }} else {{
                    dislikeBtn.classList.add('active');
                    dislikes += 1;
                    if (isLiked) {{
                        likeBtn.classList.remove('active');
                        likes = Math.max(0, likes - 1);
                    }}
                }}
            }}
            
            likeSpan.innerText = likes;
            dislikeSpan.innerText = dislikes;
            
            if (voteTimers[postId]) clearTimeout(voteTimers[postId]);
            
            voteTimers[postId] = setTimeout(async () => {{
                const finalLiked = likeBtn.classList.contains('active');
                const finalDisliked = dislikeBtn.classList.contains('active');
                
                let voteType = 0;
                if (finalLiked) voteType = 1;
                if (finalDisliked) voteType = -1;
                
                try {{
                    const res = await rpc('vote', {{ post_id: postId, vote_type: voteType }});
                    likeSpan.innerText = res.likes;
                    dislikeSpan.innerText = res.dislikes;
                }} catch (e) {{
                    showToast(e.message);
                }} finally {{
                    wrapper.dataset.pendingVote = "false";
                }}
            }}, 600);
        }}

        // --- NICKNAME GENERATOR ---
        const nickData = {{
            anime: {{
                pre: ["Dark", "Light", "Kawaii", "Shadow", "Neon", "Sakura", "Zero", "Shinobi"],
                root: ["Sword", "Soul", "Spirit", "Blade", "Fox", "Cat", "Kitsune", "Oni"],
                suf: ["Chan", "Kun", "Senpai", "Sama", "Desu", "San"]
            }},
            cyber: {{
                pre: ["Cyber", "Neon", "Glitch", "Tech", "Data", "Hex", "Net", "Synth"],
                root: ["Runner", "Punk", "Hacker", "Ghost", "City", "Wave", "Core", "Drive"],
                suf: ["77", "2077", "X", "Zero", "Prime", "Protocol"]
            }},
            fantasy: {{
                pre: ["Dark", "Blood", "Iron", "Storm", "Shadow", "Fire", "Ice", "Frost"],
                root: ["Lord", "Knight", "Mage", "Rogue", "Hunter", "Slayer", "King", "Dragon"],
                suf: ["I", "II", "III", "The Great", "The Brave", "The Wise"]
            }},
            cute: {{
                pre: ["Sweet", "Little", "Fluffy", "Bunny", "Honey", "Star", "Moon", "Berry"],
                root: ["Bear", "Cat", "Fox", "Cloud", "Dream", "Sparkle", "Pie", "Cake"],
                suf: ["Chan", "Bear", "Nya", "Meow", "Sama", "Kawaii"]
            }}
        }};
        let currentStyle = 'anime';

        function setStyle(style, btn) {{
            currentStyle = style;
            document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            generateNicks();
        }}

        function generateNicks() {{
            const out = document.getElementById('nick-output');
            out.innerHTML = '';
            const data = nickData[currentStyle];
            
            for (let i = 0; i < 5; i++) {{
                const p = data.pre[Math.floor(Math.random() * data.pre.length)];
                const r = data.root[Math.floor(Math.random() * data.root.length)];
                const s = data.suf[Math.floor(Math.random() * data.suf.length)];
                
                // Иногда добавляем BB-код для красоты
                let nick = p + r + s;
                if (Math.random() > 0.7) nick = `[color=#9b59b6]${{nick}}[/color]`;
                if (Math.random() > 0.8) nick = `[b]${{nick}}[/b]`;
                
                const item = document.createElement('div');
                item.className = 'nick-item';
                item.innerHTML = `<span>${{nick}}</span><button class="copy-nick-btn" onclick="copyNick('${{nick}}')">${{L.copy}}</button>`;
                out.appendChild(item);
            }}
        }}

        function copyNick(nick) {{
            // Убираем BB-коды при копировании
            const clean = nick.replace(/\\[[^\\]]+\\]/g, '');
            navigator.clipboard.writeText(clean).then(() => showToast("Copied!"));
        }}
        
        // Инициализация генератора, если мы на его странице
        if (document.getElementById('nick-output')) {{
            generateNicks();
        }}
    </script>
    """

def get_overlay():
    return """
    <div id="toast"></div>
    <div id="modal-overlay" class="modal-overlay">
        <div class="modal-box">
            <p id="modal-text" style="font-size:18px;margin-bottom:20px;"></p>
            <div class="modal-actions">
                <button id="modal-cancel" class="btn" style="background:#aaa;color:black;">Cancel</button>
                <button id="modal-confirm" class="btn btn-danger">Confirm</button>
            </div>
        </div>
    </div>
    """

def get_footer(lang):
    return f"""
    <div class="footer">
        <div>{t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a></div>
        <div class="footer-links">
            <a href="/privacy">{t('privacy_title', lang)}</a> | <a href="/bugreport">{t('bugreport_title', lang)}</a>
        </div>
    </div>
    """

def auth_html(lang: str, error_msg: str = "", token: str = ""):
    eb = f"<div class='error-msg'>{error_msg}</div>" if error_msg else "<div class='error-msg'></div>"
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('login', lang)} / {t('reg', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="container">
        <div class="auth-wrapper"><div class="label-text">{t('reg', lang)}</div><div class="form-box"><form action="/register" method="post">
            <input type="hidden" name="csrf_token" value="{token}">
            <input type="text" name="username" placeholder="{t('username', lang)}" required>
            <input type="text" name="nickname" placeholder="{t('nickname', lang)}" required>
            <div class="input-group"><input type="password" name="password" id="rp" placeholder="{t('password', lang)}" required><button type="button" class="eye-btn" onclick="tp('rp',this)">{SVG_EYE}</button></div>
            <div class="input-group"><input type="password" name="re_pass" id="rr" placeholder="{t('re_pass', lang)}" required><button type="button" class="eye-btn" onclick="tp('rr',this)">{SVG_EYE}</button></div>
            <label class="captcha-container"><input type="checkbox" name="captcha" required> {t('captcha', lang)}</label>
            <label class="captcha-container" style="background:#8c8c8c;margin-top:2px"><input type="checkbox" name="privacy" required><span>{t('privacy_agree', lang)} <a href="/privacy" target="_blank" class="privacy-link">{t('privacy_link', lang)}</a></span></label>
            <button type="submit">{t('register_btn', lang)}</button>
        </form></div></div>
        <div class="auth-wrapper"><div class="auth-wrapper-inner"><div class="form-box"><form action="/login" method="post">
            <input type="hidden" name="csrf_token" value="{token}">
            <input type="text" name="nickname" placeholder="{t('nickname', lang)}" required>
            <div class="input-group"><input type="password" name="password" id="lp" placeholder="{t('password', lang)}" required><button type="button" class="eye-btn" onclick="tp('lp',this)">{SVG_EYE}</button></div>
            <label class="captcha-container"><input type="checkbox" name="captcha" required> {t('captcha', lang)}</label>
            <button type="submit">{t('login_btn', lang)}</button>
        </form></div><div class="label-text">{t('login', lang)}</div></div>
        <div class="login-lang-wrapper"><div class="lang-switch"><a href="/set_lang/ru?next=/" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div></div>
        {eb}</div>
    </div>{get_footer(lang)}{get_overlay()}</body></html>"""

def render_records(records, lang, own=False, feed=False, uid=None):
    if not records or not isinstance(records, list): 
        return f"<div class='post-item'>{t('no_posts', lang)}</div>"
    out = ""
    for x in records:
        if not isinstance(x, dict): continue
        rid = esc(x.get('id'))
        if not rid: continue
        
        pinned = bool(x.get('is_pinned', False))
        content = parse_bb(x.get('content'))
        date = format_date(esc(x.get('created_at')))
        
        pc = "pinned" if pinned else ""
        likes = x.get('likes') or 0
        dislikes = x.get('dislikes') or 0
        
        acts = "<div class='post-actions'>"
        if uid:
            acts += f"<button onclick='copyLink(\"{x.get('user_nickname','')}\",\"{rid}\", this)' class='action-btn link-btn'>{t('copy_link', lang)}</button>"
        if own:
            acts += f"<button onclick='hp(\"{rid}\",this)' class='action-btn pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button>"
            acts += f"<button onclick='hd(\"{rid}\",this)' class='action-btn'>{t('delete', lang)}</button>"
        acts += "</div>"
        
        vb = "<div class='vote-btns'>"
        if uid:
            vb += f"<button onclick='toggleVote(\"{rid}\",1,this)' class='vote-btn like'>{SVG_LIKE} <span class='v-l'>{likes}</span></button>"
            vb += f"<button onclick='toggleVote(\"{rid}\",-1,this)' class='vote-btn dislike'>{SVG_DISLIKE} <span class='v-d'>{dislikes}</span></button>"
        else:
            vb += f"<span style='color:green;font-weight:bold'>{SVG_LIKE} <span class='v-l'>{likes}</span></span>"
            vb += f"<span style='color:red;font-weight:bold'>{SVG_DISLIKE} <span class='v-d'>{dislikes}</span></span>"
        vb += "</div>"
            
        head = ""
        if feed:
            user_nick = esc(x.get('user_nickname')) # Никнеймы не парсим!
            head = f"<div class='post-header'><span><b><a href='/{user_nick}'>{user_nick}</a></b></span><span>{date}</span></div>"
            date = "" 
            
        out += f"""
        <div class="post-wrapper" id="post-{rid}">{acts}
            <div class="post-item {pc}">
                {head}
                <div class="post-content">{content}</div>
                <div class="post-footer">{vb}<div class="post-date">{date}</div></div>
            </div>
        </div>"""
    return out

def merge_memory(db_records, nickname, is_owner=False):
    f = []
    if not db_records or not isinstance(db_records, list):
        db_records = []
        
    for x in db_records:
        if not isinstance(x, dict):
            continue
        x_id = x.get('id')
        if not x_id:
            continue
        if x_id in deleted_records:
            continue
            
        if x_id in pinned_records:
            x['is_pinned'] = pinned_records[x_id]
        f.append(x)
        
    for rid, x in pending_records.items():
        if not isinstance(x, dict):
            continue
        if x.get('user_nickname') == nickname:
            f.append(x)
            
    def sort_key(x):
        p = x.get('is_pinned')
        c = x.get('created_at')
        return (bool(p), str(c) if c is not None else '')
        
    try:
        f.sort(key=sort_key, reverse=True)
    except Exception:
        pass
    return f

def dashboard_html(nickname, user, my_p, lang, token):
    rh_my = render_records(my_p, lang, own=True, feed=False, uid=nickname)
    user_username = esc(user.get('username'))
    desc = parse_bb(user.get('description')) # Описание с BB-кодами
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('cabinet', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('cabinet', lang)}</h2>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{user_username}</div>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br><a href="/{nickname}" target="_blank">{esc(nickname)} {t('link_profile', lang)}</a></div>{db}
        <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(my_p)}</div>
        <a href="/cabinet/nickgen" class="btn gen-btn">{t('nickgen_title', lang)}</a>
        <a href="/cabinet/edit" class="btn edit-btn">{t('edit_profile', lang)}</a>
        <form action="/logout" method="get" style="margin: 0; width: 100%;"><button type="submit" class="logout-btn">{t('logout', lang)}</button></form>
        <div class="lang-switch"><a href="/set_lang/ru?next=/cabinet" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/cabinet" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div>
    <div class="main-content">
        <div class="create-post-box">
            <div style="color:#a9a9a9; font-size:12px; text-align:left; margin-bottom:5px;">{t('bb_help', lang)}</div>
            <form id="create-form" onsubmit="hc(event)">
                <textarea name="content" placeholder="{t('create_post_placeholder', lang)}" required maxlength="1000"></textarea>
                <button type="submit">{t('create_post_btn', lang)}</button>
            </form>
        </div>
        
        <div class="tabs-container">
            <div class="posts-area" id="my-records-container"><h2>{t('my_posts', lang)}</h2>{rh_my}</div>
        </div>
    </div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def nickgen_html(nickname, user, lang, token):
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('nickgen_title', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('cabinet', lang)}</h2>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br>{esc(nickname)}</div>
        <a href="/cabinet" class="btn" style="margin-top:auto;background:#a9a9a9">{t('back_home', lang)}</a>
    </div><div class="main-content">
        <div class="nickgen-container">
            <div class="nickgen-title">{t('nickgen_title', lang)}</div>
            <div class="nickgen-desc">{t('nickgen_desc', lang)}</div>
            
            <div class="nickgen-styles">
                <button class="style-btn active" onclick="setStyle('anime', this)">Anime</button>
                <button class="style-btn" onclick="setStyle('cyber', this)">Cyberpunk</button>
                <button class="style-btn" onclick="setStyle('fantasy', this)">Fantasy</button>
                <button class="style-btn" onclick="setStyle('cute', this)">Cute</button>
            </div>
            
            <button class="btn" style="background:#9b59b6;color:white;margin-bottom:20px;" onclick="generateNicks()">{t('gen_btn', lang)}</button>
            
            <div id="nick-output" class="nickgen-output"></div>
        </div>
    </div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def edit_html(nickname, user, lang, token):
    desc = esc(user.get('description'))
    user_username = esc(user.get('username'))
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('edit_profile', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px"><div class="tabs-container" style="padding:20px">
        <h2 style="color:#fff;text-align:center">{t('edit_profile', lang)}</h2>
        <div style="color:#a9a9a9; font-size:12px; text-align:left; margin-bottom:5px;">{t('bb_help', lang)}</div>
        <form action="/cabinet/edit" method="post" style="display:flex;flex-direction:column;gap:10px">
            <input type="hidden" name="csrf_token" value="{token}">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">{t('username_label', lang)}</div>
            <input type="text" name="username" value="{user_username}" required style="background:#a9a9a9;padding:12px;font-size:18px">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">{t('description', lang)}</div>
            <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder', lang)}" oninput="uc(this)" style="background:#a9a9a9;height:150px;padding:12px;font-size:18px">{desc}</textarea>
            <div id="char-count" style="color:#fff;text-align:right;font-size:14px">{len(desc)} / 300</div>
            <button type="submit" style="background:#4da6ff;color:#fff;margin-top:10px">{t('save_changes', lang)}</button>
            <a href="/cabinet" class="btn" style="background:#a9a9a9">{t('cancel', lang)}</a>
        </form>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/edit" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/cabinet/edit" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div></div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def public_html(nickname, user, records, lang, token, viewer):
    rh = render_records(records, lang, own=False, feed=True, uid=viewer)
    user_username = esc(user.get('username'))
    desc = parse_bb(user.get('description'))
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{desc}</div>" if desc else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('profile', lang)} {esc(nickname)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('profile', lang)}</h2>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{user_username}</div>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br>{esc(nickname)}</div>{db}
        <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(records)}</div>
        <div class="lang-switch"><a href="/set_lang/ru?next=/{nickname}" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/{nickname}" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
        <a href="/" class="btn" style="margin-top:auto;background:#a9a9a9">{t('back_home', lang)}</a>
    </div><div class="main-content"><div class="tabs-container">
        <div class="posts-area" id="feed-records-container" style="min-height:500px"><h2>{t('user_posts', lang)}</h2>{rh}</div>
    </div></div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def record_page_html(nickname, user, record, lang, token, viewer):
    rh = render_records([record], lang, own=False, feed=True, uid=viewer)
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('record_page', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('profile', lang)}</h2>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br><a href="/{nickname}">{esc(nickname)}</a></div>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{esc(user.get('username'))}</div>
        <a href="/{nickname}" class="btn" style="margin-top:auto;background:#a9a9a9">{t('back_home', lang)}</a>
    </div><div class="main-content"><div class="tabs-container"><div class="posts-area"><h2>{t('record_page', lang)}</h2>
        {rh}
    </div></div></div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def bugreport_html(username, reports, lang, token):
    rh = "<div class='post-item'>Заявок пока нет...</div>" if not reports else "".join([f"""
        <div class="post-item" style="border-left-color:transparent">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <b>{t('bugreport_title', lang)}</b><span class="status-badge status-{esc(x.get('status','Принято')).replace(' ','-')}">{esc(x.get('status','Принято'))}</span>
            </div>
            <div class="post-content">{esc(x.get('content'))}</div>
            <div class="post-date">{format_date(esc(x.get('created_at')))}</div>
        </div>""" for x in reports])
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('bugreport_title', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="create-post-box"><h2 style="color:#fff;text-align:center;margin:10px 0">{t('bugreport_title', lang)}</h2>
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:5px">
                <input type="hidden" name="csrf_token" value="{token}">
                <input type="text" name="name" value="{esc(username)}" placeholder="{t('bugreport_name', lang)}" required style="background:#a9a9a9;padding:12px;margin-bottom:5px">
                <textarea name="content" placeholder="{t('bugreport_desc', lang)}" required style="background:#a9a9a9;height:150px;padding:12px;margin-bottom:5px"></textarea>
                <button type="submit" style="background:#f1c40f;color:#000">{t('bugreport_send', lang)}</button>
            </form>
        </div>
        <div class="tabs-container"><div class="posts-area"><h2>{t('bugreport_my', lang)}</h2>{rh}</div></div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">{t('cancel', lang)}</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/bugreport" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/bugreport" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div></div>{get_footer(lang)}{get_overlay()}</body></html>"""

def privacy_html(lang, token):
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('privacy_title', lang)}</title>{get_css()}</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:800px"><div class="tabs-container" style="padding:20px">
        <h2 style="color:#fff;text-align:center;margin-bottom:20px">{t('privacy_title', lang)}</h2>
        <div class="privacy-content">{t('privacy_text', lang)}</div>
        <a href="/" class="btn" style="background:#a9a9a9;margin-top:20px">{t('back_home', lang)}</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/privacy" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/privacy" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div></div></div>{get_footer(lang)}</body></html>"""

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
            x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
            if x.data: return RedirectResponse("/cabinet", 303)
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
    if not check_csrf(r, csrf_token): return auth_html(lang, "CSRF Error", token)
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    if not privacy: return auth_html(lang, t('alert_privacy', lang), token)
    if password != re_pass: return auth_html(lang, t('alert_pass_mismatch', lang), token)
    
    try:
        x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
        if x.data: return auth_html(lang, t('alert_nick_taken', lang), token)
        sb.table('users').insert({"username": username, "nickname": nickname, "password": hash_password(password), "description": ""}).execute()
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
        
    res = RedirectResponse("/cabinet", 303)
    res.set_cookie("nickname", nickname, httponly=True, samesite="lax")
    return res

@app.post("/login", response_class=HTMLResponse)
async def login(r: Request, res: Response, nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    if not check_csrf(r, csrf_token): return auth_html(lang, "CSRF Error", token)
    if not captcha: return auth_html(lang, t('alert_captcha', lang), token)
    
    try:
        x = sb.table('users').select('password').eq('nickname', nickname).execute()
        user = x.data[0] if x.data else None
        if user and verify_password(password, user.get("password", "")):
            if len(user["password"]) == 64:
                sb.table('users').update({"password": hash_password(password)}).eq('nickname', nickname).execute()
            res = RedirectResponse("/cabinet", 303)
            res.set_cookie("nickname", nickname, httponly=True, samesite="lax")
            return res
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}", token)
        
    return auth_html(lang, t('alert_bad_login', lang), token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, user: str = Depends(auth_middleware), lang: str = Cookie("ru")):
    user_data = {"username": user, "description": ""}
    p_data = []
    
    try:
        u = sb.table('users').select('username,description').eq('nickname', user).execute()
        if u.data and isinstance(u.data, list) and len(u.data) > 0:
            user_data = u.data[0]
    except Exception:
        pass
    
    try:
        p = sb.table('posts').select('*').eq('user_nickname', user).execute()
        if p.data and isinstance(p.data, list):
            p_data = p.data
    except Exception:
        pass
            
    po = merge_memory(p_data, user, True)
    
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(user, user_data, po, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/cabinet/nickgen", response_class=HTMLResponse)
async def nickgen(r: Request, user: str = Depends(auth_middleware), lang: str = Cookie("ru")):
    token = get_csrf_token(r)
    res = HTMLResponse(nickgen_html(user, {}, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/rpc")
async def rpc_endpoint(req: RPCRequest, r: Request, user: str = Depends(auth_middleware)):
    if not check_csrf(r):
        raise HTTPException(status_code=403, detail="CSRF Error")
    
    try:
        if req.method == "create_record":
            content = req.params.get("content", "")
            client_id = req.params.get("client_id")
            
            i = client_id or str(uuid.uuid4())
            n = datetime.now(timezone.utc).isoformat()
            
            pd = {"id": i, "user_nickname": user, "content": content.strip(), "is_pinned": False, "created_at": n, "likes": 0, "dislikes": 0}
            try:
                sb.table('posts').insert(pd).execute()
            except Exception:
                pd.pop("likes", None)
                pd.pop("dislikes", None)
                sb.table('posts').insert(pd).execute()
            
            return {"status": "ok", "id": i}
            
        elif req.method == "delete_record":
            rid = req.params.get("post_id")
            sb.table('posts').delete().eq('id', rid).eq('user_nickname', user).execute()
            await manager.broadcast({"type": "delete_record", "post_id": rid})
            return {"status": "ok"}
            
        elif req.method == "pin_record":
            rid = req.params.get("post_id")
            x = sb.table('posts').select('is_pinned').eq('id', rid).eq('user_nickname', user).execute()
            if not x.data or not isinstance(x.data, list) or len(x.data) == 0: 
                raise HTTPException(404, "Not found")
            
            ns = not x.data[0].get('is_pinned', False)
            sb.table('posts').update({"is_pinned": ns}).eq('id', rid).eq('user_nickname', user).execute()
            return {"status": "ok", "is_pinned": ns}
            
        elif req.method == "vote":
            rid = req.params.get("post_id")
            vote_type = int(req.params.get("vote_type", 0))
            if vote_type not in [-1, 0, 1]: raise HTTPException(400, "Bad type")
            
            try:
                ex = sb.table('post_votes').select('vote_type').eq('post_id', rid).eq('user_nickname', user).execute()
            except Exception:
                ex = type('obj', (object,), {'data': []})
                
            p = sb.table('posts').select('likes,dislikes').eq('id', rid).execute()
            if not p.data or not isinstance(p.data, list) or len(p.data) == 0: 
                raise HTTPException(404, "Not found")
            
            likes = p.data[0].get('likes') or 0
            dislikes = p.data[0].get('dislikes') or 0
            
            if vote_type == 0:
                if ex.data:
                    try: sb.table('post_votes').delete().eq('post_id', rid).eq('user_nickname', user).execute()
                    except Exception: pass
                    if ex.data[0].get('vote_type') == 1: likes = max(0, likes - 1)
                    else: dislikes = max(0, dislikes - 1)
            else:
                if ex.data:
                    old = ex.data[0].get('vote_type')
                    if old == vote_type:
                        try: sb.table('post_votes').delete().eq('post_id', rid).eq('user_nickname', user).execute()
                        except Exception: pass
                        if vote_type == 1: likes = max(0, likes - 1)
                        else: dislikes = max(0, dislikes - 1)
                    else:
                        try: sb.table('post_votes').update({"vote_type": vote_type}).eq('post_id', rid).eq('user_nickname', user).execute()
                        except Exception: pass
                        if vote_type == 1: likes += 1; dislikes = max(0, dislikes - 1)
                        else: dislikes += 1; likes = max(0, likes - 1)
                else:
                    try: sb.table('post_votes').insert({"post_id": rid, "user_nickname": user, "vote_type": vote_type}).execute()
                    except Exception: pass
                    if vote_type == 1: likes += 1
                    else: dislikes += 1
                    
            sb.table('posts').update({"likes": likes, "dislikes": dislikes}).eq('id', rid).execute()
            await manager.broadcast({"type": "vote", "post_id": rid, "likes": likes, "dislikes": dislikes})
            return {"status": "ok", "likes": likes, "dislikes": dislikes}
            
        raise HTTPException(400, "Unknown method")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/cabinet/edit", response_class=HTMLResponse)
async def edit(r: Request, user: str = Depends(auth_middleware), lang: str = Cookie("ru")):
    user_data = {"username": user, "description": ""}
    try:
        u = sb.table('users').select('username,description').eq('nickname', user).execute()
        if u.data and isinstance(u.data, list) and len(u.data) > 0: user_data = u.data[0]
    except Exception: pass
    token = get_csrf_token(r)
    res = HTMLResponse(edit_html(user, user_data, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, user: str = Depends(auth_middleware), username: str = Form(...), description: str = Form(""), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>showToast('CSRF Error');window.history.back()</script>")
    if len(description) > 300: return HTMLResponse(f"<script>showToast('{t('alert_desc_long', lang)}');window.history.back()</script>")
    
    try:
        sb.table('users').update({"username": username, "description": description}).eq('nickname', user).execute()
    except Exception:
        try:
            sb.table('users').update({"username": username}).eq('nickname', user).execute()
        except Exception: pass
    return RedirectResponse("/cabinet", 303)

@app.get("/bugreport", response_class=HTMLResponse)
async def bugreport(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    u = ""
    rp = []
    if nickname:
        try:
            x = sb.table('users').select('username').eq('nickname', nickname).execute()
            if x.data: u = x.data[0].get('username') or ""
            y = sb.table('bug_reports').select('*').eq('user_nickname', nickname).order('created_at', desc=True).execute()
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
    sb.table('bug_reports').insert(d).execute()
    return RedirectResponse("/bugreport", 303)

@app.get("/logout")
async def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("nickname")
    return res

@app.get("/{nickname}/{rid}", response_class=HTMLResponse)
async def record_page(nickname: str, rid: str, r: Request, lang: str = Cookie("ru")):
    u_data = {}
    rec = None
    try:
        u = sb.table('users').select('username').eq('nickname', nickname).execute()
        if u.data: u_data = u.data[0]
        else: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
        
        x = sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute()
        if not x.data: return HTMLResponse(f"<h2>{t('no_posts', lang)}</h2>", 404)
        rec = x.data[0]
    except Exception:
        return HTMLResponse(f"<h2>DB Error</h2>", 500)
        
    token = get_csrf_token(r)
    viewer = r.cookies.get("nickname")
    res = HTMLResponse(record_page_html(nickname, u_data, rec, lang, token, viewer))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    u_data = {}
    p_data = []
    try:
        u = sb.table('users').select('username,description').eq('nickname', nickname).execute()
        if not u.data: return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/'>OK</a></h2>", 404)
        u_data = u.data[0]
        
        p = sb.table('posts').select('*').eq('user_nickname', nickname).execute()
        p_data = p.data or []
    except Exception:
        return HTMLResponse(f"<h2>DB Error</h2>", 500)
    
    viewer = r.cookies.get("nickname")
    po = merge_memory(p_data, nickname, True)
    
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, u_data, po, lang, token, viewer))
    set_csrf_cookie(res, token, r)
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
