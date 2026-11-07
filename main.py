from fastapi import FastAPI, Form, Cookie, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from supabase import create_client, Client
import uvicorn
import html
import bcrypt
import secrets
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional

app = FastAPI()

# --- НАСТРОЙКИ SUPABASE ---
S_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb: Client = create_client(S_URL, S_KEY)

# --- ОПЕРАТИВНАЯ ПАМЯТЬ ---
pending_records = {}
deleted_records = set()
pinned_records = {}

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

def check_csrf(request: Request, form_token: str) -> bool:
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token")
    return cookie_token and (cookie_token == form_token or cookie_token == header_token)

def set_csrf_cookie(response: Response, token: str, request: Request):
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", token, httponly=True, samesite="lax")

# --- МИДДЛВАРЬ / ЗАВИСИМОСТЬ ---
async def auth_middleware(r: Request, nickname: Optional[str] = Cookie(None)):
    if not nickname:
        raise HTTPException(status_code=401)
    x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
    if not x.data:
        raise HTTPException(status_code=401)
    return nickname

# --- ОБРАБОТЧИК ОШИБОК ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    lang = request.cookies.get("lang", "ru")
    error_msg = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    token = get_csrf_token(request)
    response = HTMLResponse(content=auth_html(lang, error_msg, token), status_code=422)
    set_csrf_cookie(response, token, request)
    return response

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
        "my_posts": "МОИ ЗАПИСИ", "user_posts": "ЗАПИСИ ПОЛЬЗОВАТЕЛЯ", "feed": "ОБЩАЯ ЛЕНТА", 
        "no_posts": "Записей пока нет...", "pin": "Закрепить", "unpin": "Открепить", "delete": "Удалить", 
        "confirm_delete": "Удалить запись?", "created_by": "Создано:", "hosting": "Хостинг:", 
        "back_home": "На главную", "user_not_found": "Пользователь не найден.", 
        "alert_captcha": "Подтвердите, что вы не робот!", "alert_pass_mismatch": "Пароли не совпадают!", 
        "alert_nick_taken": "Такой никнейм уже занят!", "alert_bad_login": "Неверный никнейм или пароль!", 
        "alert_desc_long": "Описание > 300 символов!", "link_profile": "(Ссылка)", "cancel": "Отмена", 
        "username_label": "Имя", "nickname_label": "Никнейм", "bugreport_title": "Баг-репорт", 
        "bugreport_name": "Ваше имя", "bugreport_desc": "Описание проблемы", "bugreport_send": "Отправить", 
        "bugreport_my": "Мои заявки", "privacy_title": "Политика конфиденциальности",
        "privacy_text": "1. Сбор информации. Собираем только данные при регистрации.<br><br>2. Использование. Данные нужны для работы сайта.<br><br>3. Безопасность. Используем шифрование (bcrypt).<br><br>4. Cookies. Сайт использует cookies для сессии.<br><br>5. Ваши права. Вы можете изменить данные в профиле.",
        "privacy_agree": "Я согласен с", "privacy_link": "Политикой конфиденциальности",
        "alert_privacy": "Примите политику!", "cabinet": "ЛИЧНЫЙ КАБИНЕТ",
        "hidden_record": "Скрытая", "hidden_label": "Скрытая запись", "record_page": "Запись", 
        "vote_err": "Вы уже голосовали!"
    },
    "en": {
        "reg": "Registration", "login": "Login", "username": "username", "nickname": "nickname",
        "password": "password", "re_pass": "re enter pass", "captcha": "I am not a robot",
        "register_btn": "Register!", "login_btn": "Login", "profile": "PROFILE",
        "total_posts": "Total records", "logout": "Logout", "edit_profile": "Edit Profile",
        "save_changes": "Save changes", "description": "Description", 
        "desc_placeholder": "Tell about yourself...",
        "create_post_btn": "Create record", "create_post_placeholder": "Write something...",
        "my_posts": "MY RECORDS", "user_posts": "USER RECORDS", "feed": "GLOBAL FEED", 
        "no_posts": "No records yet...", "pin": "Pin", "unpin": "Unpin", "delete": "Delete", 
        "confirm_delete": "Delete record?", "created_by": "Created by:", "hosting": "Hosting:", 
        "back_home": "Back to home", "user_not_found": "User not found.", 
        "alert_captcha": "Confirm you are not a robot!", "alert_pass_mismatch": "Passwords do not match!", 
        "alert_nick_taken": "Nickname is taken!", "alert_bad_login": "Invalid login!", 
        "alert_desc_long": "Description > 300 chars!", "link_profile": "(Link)", "cancel": "Cancel", 
        "username_label": "Name", "nickname_label": "Nickname", "bugreport_title": "Bug Report", 
        "bugreport_name": "Your Name", "bugreport_desc": "Issue Description", "bugreport_send": "Send", 
        "bugreport_my": "My Reports", "privacy_title": "Privacy Policy",
        "privacy_text": "1. We collect data you provide.<br><br>2. Used for site operation.<br><br>3. We use bcrypt.<br><br>4. Site uses cookies.<br><br>5. You can change data anytime.",
        "privacy_agree": "I agree to the", "privacy_link": "Privacy Policy",
        "alert_privacy": "Accept the Privacy Policy!", "cabinet": "PERSONAL CABINET",
        "hidden_record": "Hidden", "hidden_label": "Make hidden", "record_page": "Record", 
        "vote_err": "You already voted!"
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
        
        .main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
        
        .create-post-box { background: black; padding: 10px; display: flex; flex-direction: column; gap: 10px; border-radius: 5px; }
        .create-post-box textarea { height: 100px; font-size: 16px; padding: 10px; border-radius: 3px; }

        /* --- СТИЛИ ДЛЯ ВКЛАДОК --- */
        .tabs-container { background: black; padding: 10px; border-radius: 5px; display: flex; flex-direction: column; gap: 10px; }
        .tabs-header { display: flex; gap: 5px; }
        .tab-btn { background: #555; border: none; padding: 10px; cursor: pointer; font-weight: bold; font-size: 16px; color: white; border-radius: 5px 5px 0 0; flex: 1; transition: 0.2s; }
        .tab-btn:hover { background: #777; }
        .tab-btn.active { background: #4da6ff; color: white; }
        .tab-content { display: none; flex-direction: column; gap: 10px; min-height: 300px; padding-top: 10px; }
        .tab-content.active { display: flex; }

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
        .vote-btn.liked { background: #2ecc71; }
        .vote-btn.disliked { background: #e74c3c; }

        .post-actions { position: absolute; top: 5px; right: 5px; display: flex; gap: 5px; opacity: 0; transition: opacity 0.2s; z-index: 10; }
        .post-wrapper:hover .post-actions { opacity: 1; }
        .action-btn { background: black; color: white; border: none; padding: 5px 10px; font-size: 12px; cursor: pointer; border-radius: 3px; width: auto; font-weight: normal;}
        .action-btn:hover { background: #ff4d4d; }
        .action-btn.pin-btn:hover { background: #4da6ff; }

        .status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; color: white; margin-left: 10px;}
        .status-Принято, .status-Accepted { background: #4da6ff; }
        .status-В-работе, .status-In-Progress { background: #f1c40f; }
        .status-Исправлено, .status-Fixed { background: #2ecc71; }
        .status-Отклонено, .status-Rejected { background: #e74c3c; }
        .hidden-badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 12px; font-weight: bold; background: #555; color: #fff; margin-left: 10px;}

        .lang-switch { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
        .lang-btn { background: transparent; border: 2px solid #a9a9a9; color: #a9a9a9; padding: 8px 15px; width: auto; font-size: 16px; font-weight: bold; cursor: pointer; transition: all 0.2s;}
        .lang-btn:hover { background: #a9a9a9; color: black; }
        .lang-btn.active { background: #4da6ff; border-color: #4da6ff; color: white; }
        .login-lang-wrapper { display: flex; justify-content: flex-end; width: 100%; margin-top: 5px; }
        
        .privacy-content { background: white; color: black; padding: 20px; font-size: 18px; line-height: 1.5; text-align: left; word-wrap: break-word; border-radius: 3px;}

        .error-msg { color: #ff4d4d; font-weight: bold; font-size: 18px; text-align: right; width: 100%; margin-top: 10px; min-height: 20px; }

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
            .tab-btn { font-size: 14px; padding: 8px; }
            .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
            .error-msg { text-align: center; }
            .login-lang-wrapper { justify-content: center; }
            .create-post-box { padding: 10px; }
            .post-item { padding: 10px; }
            .post-footer { flex-direction: column; align-items: flex-start; gap: 10px; }
            .vote-btns { width: 100%; justify-content: space-between; }
            .vote-btn { width: 48%; justify-content: center; }
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
            c: "{t('confirm_delete', lang)}", n: "{t('no_posts', lang)}", h: "{t('hidden_record', lang)}",
            ve: "{t('vote_err', lang)}"
        }};

        function switchTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            if (tab === 'my') {{
                document.getElementById('btn-my').classList.add('active');
                document.getElementById('tab-my').classList.add('active');
            }} else {{
                document.getElementById('btn-feed').classList.add('active');
                document.getElementById('tab-feed').classList.add('active');
            }}
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
            const hid = f.querySelector('input[name=is_hidden]').checked;
            const a = document.querySelector('#my-records-container');
            const m = a.querySelector('.post-item:not(.post-wrapper)');
            if (m) m.remove();

            const w = document.createElement('div');
            w.className = 'post-wrapper'; w.id = 'post-' + i;
            w.innerHTML = `
                <div class="post-actions">
                    <button onclick="hp('${{i}}',this)" class="action-btn pin-btn">${{L.p}}</button>
                    <button onclick="hd('${{i}}',this)" class="action-btn">${{L.d}}</button>
                </div>
                <div class="post-item">
                    <div class="post-content">${{c.replace(/</g,'&lt;').replace(/>/g,'&gt;')}} ${{hid ? `<span class="hidden-badge">${{L.h}}</span>` : ''}}</div>
                    <div class="post-footer"><div class="post-date">${{d}}</div></div>
                </div>`;
            a.insertBefore(w, a.children[1]);
            f.reset();

            const fd = new FormData(f);
            fd.append('content', c); fd.append('client_id', i); fd.append('is_hidden', hid ? 'true' : 'false'); fd.append('csrf_token', T);

            try {{
                const r = await fetch('/create_record', {{ method: 'POST', body: fd, headers: {{ 'X-CSRF-Token': T }} }});
                if (!r.ok) throw new Error('Server Error');
            }} catch (x) {{
                w.remove(); alert('Failed: ' + x.message);
            }}
        }}

        async function hd(i) {{
            if (!confirm(L.c)) return;
            const w = document.getElementById('post-' + i);
            w.style.opacity = '0'; setTimeout(() => w.style.display = 'none', 300);
            const fd = new FormData(); fd.append('csrf_token', T);
            try {{
                const r = await fetch('/delete_record/' + i, {{ method: 'POST', body: fd, headers: {{ 'X-CSRF-Token': T }} }});
                if (!r.ok) throw new Error('Server Error');
                w.remove();
            }} catch (x) {{
                w.style.opacity = '1'; w.style.display = 'block'; alert('Failed: ' + x.message);
            }}
        }}

        async function hp(i, b) {{
            const w = document.getElementById('post-' + i), p = w.querySelector('.post-item'), s = p.classList.contains('pinned');
            if (s) {{ p.classList.remove('pinned'); b.innerText = L.p; }}
            else {{
                p.classList.add('pinned'); b.innerText = L.u;
                const a = w.parentNode; a.insertBefore(w, a.children[1]);
            }}
            const fd = new FormData(); fd.append('csrf_token', T);
            try {{
                const r = await fetch('/pin_record/' + i, {{ method: 'POST', body: fd, headers: {{ 'X-CSRF-Token': T }} }});
                if (!r.ok) throw new Error('Server Error');
            }} catch (x) {{
                if (s) {{ p.classList.add('pinned'); b.innerText = L.u; }}
                else {{ p.classList.remove('pinned'); b.innerText = L.p; }}
            }}
        }}

        async function hv(i, t, b) {{
            const fd = new FormData(); fd.append('csrf_token', T); fd.append('vote_type', t);
            try {{
                const r = await fetch('/vote/' + i, {{ method: 'POST', body: fd, headers: {{ 'X-CSRF-Token': T }} }});
                const d = await r.json();
                if (!r.ok) throw new Error(d.e || 'Err');
                const p = b.parentNode.querySelectorAll('.vote-btn');
                p.forEach(x => x.classList.remove('liked', 'disliked'));
                if (t == 1) b.classList.add('liked'); else b.classList.add('disliked');
                b.parentNode.querySelector('.v-l').innerText = d.l;
                b.parentNode.querySelector('.v-d').innerText = d.d;
            }} catch (x) {{
                alert(x.message);
            }}
        }}
    </script>
    """

# --- ФУТЕР ---
def get_footer(lang):
    return f"""
    <div class="footer">
        <div>{t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a></div>
        <div class="footer-links">
            <a href="/privacy">{t('privacy_title', lang)}</a> | <a href="/bugreport">{t('bugreport_title', lang)}</a>
        </div>
    </div>
    """

# --- HTML ГЕНЕРАТОРЫ ---
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
    </div>{get_footer(lang)}</body></html>"""

def render_records(records, lang, own=False, feed=False, uid=None):
    if not records: return f"<div class='post-item'>{t('no_posts', lang)}</div>"
    out = ""
    for x in records:
        rid, pinned, hidden = x.get('id', ''), x.get('is_pinned', False), x.get('is_hidden', False)
        content = html.escape(x.get('content', '')).replace('\n', '<br>')
        date = format_date(x.get('created_at', ''))
        pc = "pinned" if pinned else ""
        likes, dislikes = x.get('likes', 0), x.get('dislikes', 0)
        hb = f"<span class='hidden-badge'>{t('hidden_record', lang)}</span>" if hidden else ""
        
        acts = f"<div class='post-actions'><button onclick='hp(\"{rid}\",this)' class='action-btn pin-btn'>{t('unpin', lang) if pinned else t('pin', lang)}</button><button onclick='hd(\"{rid}\",this)' class='action-btn'>{t('delete', lang)}</button></div>" if own else ""
        
        vb = ""
        if feed and uid:
            vb = f"<div class='vote-btns'><button onclick='hv(\"{rid}\",1,this)' class='vote-btn'>{SVG_LIKE} <span class='v-l'>{likes}</span></button><button onclick='hv(\"{rid}\",-1,this)' class='vote-btn'>{SVG_DISLIKE} <span class='v-d'>{dislikes}</span></button></div>"
        elif feed:
            vb = f"<div class='vote-btns'><span style='color:green;font-weight:bold'>{SVG_LIKE} {likes}</span> <span style='color:red;font-weight:bold'>{SVG_DISLIKE} {dislikes}</span></div>"
            
        head = ""
        if feed:
            head = f"<div class='post-header'><span><b><a href='/{x.get('user_nickname','')}'>{html.escape(x.get('user_nickname',''))}</a></b></span><span>{date}</span></div>"
            date = "" 
            
        out += f"""
        <div class="post-wrapper" id="post-{rid}">{acts}
            <div class="post-item {pc}">
                {head}
                <div class="post-content">{content} {hb}</div>
                <div class="post-footer">{vb}<div class="post-date">{date}</div></div>
            </div>
        </div>"""
    return out

def merge_memory(db_records, nickname, is_owner=False):
    f = [x for x in db_records if x['id'] not in deleted_records and (is_owner or not x.get('is_hidden', False))]
    for x in f:
        if x['id'] in pinned_records: x['is_pinned'] = pinned_records[x['id']]
    for rid, x in pending_records.items():
        if x['user_nickname'] == nickname and (is_owner or not x.get('is_hidden', False)): f.append(x)
    f.sort(key=lambda x: (not x.get('is_pinned', False), x.get('created_at', '')), reverse=True)
    return f

def dashboard_html(nickname, user, my_p, feed_p, lang, token):
    rh_my = render_records(my_p, lang, True, False)
    rh_feed = render_records(feed_p, lang, False, True, nickname)
    desc = user.get('description', '')
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{html.escape(desc)}</div>" if desc else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('cabinet', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('cabinet', lang)}</h2>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{html.escape(user['username'])}</div>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br><a href="/{nickname}" target="_blank">{html.escape(nickname)} {t('link_profile', lang)}</a></div>{db}
        <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(my_p)}</div>
        <a href="/cabinet/edit" class="btn edit-btn">{t('edit_profile', lang)}</a>
        <form action="/logout" method="get" style="margin: 0; width: 100%;"><button type="submit" class="logout-btn">{t('logout', lang)}</button></form>
        <div class="lang-switch"><a href="/set_lang/ru?next=/cabinet" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/cabinet" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div>
    <div class="main-content">
        <div class="create-post-box"><form id="create-form" onsubmit="hc(event)">
            <textarea name="content" placeholder="{t('create_post_placeholder', lang)}" required maxlength="500"></textarea>
            <label style="color:#fff;display:flex;align-items:center;gap:10px;margin-bottom:5px;font-weight:bold"><input type="checkbox" name="is_hidden"> {t('hidden_label', lang)}</label>
            <button type="submit">{t('create_post_btn', lang)}</button>
        </form></div>
        
        <div class="tabs-container">
            <div class="tabs-header">
                <button id="btn-my" class="tab-btn active" onclick="switchTab('my')">{t('my_posts', lang)}</button>
                <button id="btn-feed" class="tab-btn" onclick="switchTab('feed')">{t('feed', lang)}</button>
            </div>
            <div id="tab-my" class="tab-content active">
                <div class="posts-area" id="my-records-container">{rh_my}</div>
            </div>
            <div id="tab-feed" class="tab-content">
                <div class="posts-area">{rh_feed}</div>
            </div>
        </div>
    </div></div>{get_footer(lang)}</body></html>"""

def edit_html(nickname, user, lang, token):
    desc = user.get('description', '')
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('edit_profile', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container" style="justify-content:center"><div class="main-content" style="max-width:600px"><div class="tabs-container" style="padding:20px">
        <h2 style="color:#fff;text-align:center">{t('edit_profile', lang)}</h2>
        <form action="/cabinet/edit" method="post" style="display:flex;flex-direction:column;gap:10px">
            <input type="hidden" name="csrf_token" value="{token}">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">{t('username_label', lang)}</div>
            <input type="text" name="username" value="{html.escape(user['username'])}" required style="background:#a9a9a9;padding:12px;font-size:18px">
            <div style="color:#fff;font-size:18px;margin-bottom:-5px">{t('description', lang)}</div>
            <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder', lang)}" oninput="uc(this)" style="background:#a9a9a9;height:150px;padding:12px;font-size:18px">{html.escape(desc)}</textarea>
            <div id="char-count" style="color:#fff;text-align:right;font-size:14px">{len(desc)} / 300</div>
            <button type="submit" style="background:#4da6ff;color:#fff;margin-top:10px">{t('save_changes', lang)}</button>
            <a href="/cabinet" class="btn" style="background:#a9a9a9">{t('cancel', lang)}</a>
        </form>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/cabinet/edit" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/cabinet/edit" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div></div></div>{get_footer(lang)}</body></html>"""

def public_html(nickname, user, records, lang, token):
    rh = render_records(records, lang, False, True, nickname)
    desc = user.get('description', '')
    db = f"<div class='info-card'><b>{t('description', lang)}:</b><br>{html.escape(desc)}</div>" if desc else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('profile', lang)} {html.escape(nickname)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('profile', lang)}</h2>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{html.escape(user['username'])}</div>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br>{html.escape(nickname)}</div>{db}
        <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(records)}</div>
        <div class="lang-switch"><a href="/set_lang/ru?next=/{nickname}" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/{nickname}" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
        <a href="/" class="btn" style="margin-top:auto;background:#a9a9a9">{t('back_home', lang)}</a>
    </div><div class="main-content"><div class="tabs-container"><div class="posts-area" style="min-height:500px"><h2>{t('user_posts', lang)}</h2>{rh}</div></div></div></div>{get_footer(lang)}</body></html>"""

def record_page_html(nickname, user, record, lang, token):
    c = html.escape(record.get('content', '')).replace('\n', '<br>')
    d = format_date(record.get('created_at', ''))
    hb = f"<span class='hidden-badge'>{t('hidden_record', lang)}</span>" if record.get('is_hidden') else ""
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('record_page', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar">
        <h2>{t('profile', lang)}</h2>
        <div class="info-card"><b>{t('nickname_label', lang)}:</b><br><a href="/{nickname}">{html.escape(nickname)}</a></div>
        <div class="info-card"><b>{t('username_label', lang)}:</b><br>{html.escape(user['username'])}</div>
        <a href="/{nickname}" class="btn" style="margin-top:auto;background:#a9a9a9">{t('back_home', lang)}</a>
    </div><div class="main-content"><div class="tabs-container"><div class="posts-area"><h2>{t('record_page', lang)}</h2>
        <div class="post-wrapper"><div class="post-item {'pinned' if record.get('is_pinned') else ''}">
            <div class="post-content" style="font-size:20px">{c} {hb}</div><div class="post-date">{d}</div>
        </div></div>
    </div></div></div></div>{get_footer(lang)}</body></html>"""

def bugreport_html(username, reports, lang, token):
    rh = "<div class='post-item'>Заявок пока нет...</div>" if not reports else "".join([f"""
        <div class="post-item" style="border-left-color:transparent">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <b>{t('bugreport_title', lang)}</b><span class="status-badge status-{x.get('status','Принято').replace(' ','-')}">{x.get('status','Принято')}</span>
            </div>
            <div class="post-content">{html.escape(x.get('content',''))}</div>
            <div class="post-date">{format_date(x.get('created_at',''))}</div>
        </div>""" for x in reports])
    return f"""
    <!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{t('bugreport_title', lang)}</title>{get_css()}{get_js(lang, token)}</head><body>
    <div class="dashboard-container"><div class="sidebar" style="display:none"></div>
    <div class="main-content" style="max-width:800px;margin:0 auto">
        <div class="create-post-box"><h2 style="color:#fff;text-align:center;margin:10px 0">{t('bugreport_title', lang)}</h2>
            <form action="/bugreport" method="post" style="display:flex;flex-direction:column;gap:5px">
                <input type="hidden" name="csrf_token" value="{token}">
                <input type="text" name="name" value="{username}" placeholder="{t('bugreport_name', lang)}" required style="background:#a9a9a9;padding:12px;margin-bottom:5px">
                <textarea name="content" placeholder="{t('bugreport_desc', lang)}" required style="background:#a9a9a9;height:150px;padding:12px;margin-bottom:5px"></textarea>
                <button type="submit" style="background:#f1c40f;color:#000">{t('bugreport_send', lang)}</button>
            </form>
        </div>
        <div class="tabs-container"><div class="posts-area"><h2>{t('bugreport_my', lang)}</h2>{rh}</div></div>
        <a href="/cabinet" class="btn" style="background:#a9a9a9;margin-top:10px">{t('cancel', lang)}</a>
        <div class="lang-switch" style="margin-top:20px"><a href="/set_lang/ru?next=/bugreport" class="btn lang-btn {'active' if lang=='ru' else ''}">RU</a><a href="/set_lang/en?next=/bugreport" class="btn lang-btn {'active' if lang=='en' else ''}">EN</a></div>
    </div></div>{get_footer(lang)}</body></html>"""

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
        x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
        if x.data: return RedirectResponse("/cabinet", 303)
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
    
    x = sb.table('users').select('nickname').eq('nickname', nickname).execute()
    if x.data: return auth_html(lang, t('alert_nick_taken', lang), token)
    
    try:
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
    
    x = sb.table('users').select('password').eq('nickname', nickname).execute()
    user = x.data[0] if x.data else None
    if user and verify_password(password, user["password"]):
        if len(user["password"]) == 64:
            sb.table('users').update({"password": hash_password(password)}).eq('nickname', nickname).execute()
        res = RedirectResponse("/cabinet", 303)
        res.set_cookie("nickname", nickname, httponly=True, samesite="lax")
        return res
        
    return auth_html(lang, t('alert_bad_login', lang), token)

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(r: Request, user: str = Depends(auth_middleware), lang: str = Cookie("ru")):
    u = sb.table('users').select('username,description').eq('nickname', user).execute()
    p = sb.table('posts').select('*').eq('user_nickname', user).execute()
    f = sb.table('posts').select('*').eq('is_hidden', False).order('created_at', desc=True).limit(50).execute()
    
    po = merge_memory(p.data, user, True)
    pf = merge_memory(f.data, user, False)
    
    token = get_csrf_token(r)
    res = HTMLResponse(dashboard_html(user, u.data[0], po, pf, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/create_record")
async def create_record(r: Request, user: str = Depends(auth_middleware), content: str = Form(...), client_id: str = Form(None), is_hidden: str = Form(None), csrf_token: str = Form(None)):
    if not check_csrf(r, csrf_token): return JSONResponse({"e": "CSRF"}, 403)
    if not content.strip(): return JSONResponse({"e": "Empty"}, 400)
    
    i = client_id or str(uuid.uuid4())
    n = datetime.now(timezone.utc).isoformat()
    hidden_bool = (is_hidden == 'true' or is_hidden == 'on')
    
    pd = {"id": i, "user_nickname": user, "content": content.strip(), "is_pinned": False, "is_hidden": hidden_bool, "created_at": n, "likes": 0, "dislikes": 0}
    pending_records[i] = pd
    
    try:
        sb.table('posts').insert(pd).execute()
    except Exception as e:
        print(f"DB Create Error: {e}")
    finally:
        pending_records.pop(i, None)
        
    return JSONResponse({"s": "ok", "id": i})

@app.post("/delete_record/{rid}")
async def delete_record(rid: str, r: Request, user: str = Depends(auth_middleware), csrf_token: str = Form(None)):
    if not check_csrf(r, csrf_token): return JSONResponse({"e": "CSRF"}, 403)
    
    deleted_records.add(rid)
    try:
        sb.table('posts').delete().eq('id', rid).eq('user_nickname', user).execute()
    except Exception as e:
        print(f"DB Delete Error: {e}")
    finally:
        deleted_records.discard(rid)
        
    return JSONResponse({"s": "ok"})

@app.post("/pin_record/{rid}")
async def pin_record(rid: str, r: Request, user: str = Depends(auth_middleware), csrf_token: str = Form(None)):
    if not check_csrf(r, csrf_token): return JSONResponse({"e": "CSRF"}, 403)
    
    c = pinned_records.get(rid)
    if c is None:
        x = sb.table('posts').select('is_pinned').eq('id', rid).eq('user_nickname', user).execute()
        if x.data: c = x.data[0]['is_pinned']
    if c is None: return JSONResponse({"e": "Not found"}, 404)
    
    ns = not c
    pinned_records[rid] = ns
    
    try:
        sb.table('posts').update({"is_pinned": ns}).eq('id', rid).eq('user_nickname', user).execute()
    except Exception as e:
        print(f"DB Pin Error: {e}")
    finally:
        pinned_records.pop(rid, None)
        
    return JSONResponse({"s": "ok"})

@app.post("/vote/{rid}")
async def vote(r: Request, rid: str, user: str = Depends(auth_middleware), vote_type: int = Form(...), csrf_token: str = Form(None)):
    if not check_csrf(r, csrf_token): return JSONResponse({"e": "CSRF"}, 403)
    if vote_type not in [1, -1]: return JSONResponse({"e": "Bad type"}, 400)
    
    ex = sb.table('post_votes').select('vote_type').eq('post_id', rid).eq('user_nickname', user).execute()
    p = sb.table('posts').select('likes,dislikes').eq('id', rid).execute()
    if not p.data: return JSONResponse({"e": "Not found"}, 404)
    
    likes, dislikes = p.data[0]['likes'], p.data[0]['dislikes']
    
    if ex.data:
        old = ex.data[0]['vote_type']
        if old == vote_type:
            return JSONResponse({"e": t('vote_err', r.cookies.get('lang', 'ru')), "l": likes, "d": dislikes}, 400)
        sb.table('post_votes').update({"vote_type": vote_type}).eq('post_id', rid).eq('user_nickname', user).execute()
        if vote_type == 1: likes += 1; dislikes = max(0, dislikes - 1)
        else: dislikes += 1; likes = max(0, likes - 1)
    else:
        sb.table('post_votes').insert({"post_id": rid, "user_nickname": user, "vote_type": vote_type}).execute()
        if vote_type == 1: likes += 1
        else: dislikes += 1
        
    sb.table('posts').update({"likes": likes, "dislikes": dislikes}).eq('id', rid).execute()
    return JSONResponse({"s": "ok", "l": likes, "d": dislikes})

@app.get("/cabinet/edit", response_class=HTMLResponse)
async def edit(r: Request, user: str = Depends(auth_middleware), lang: str = Cookie("ru")):
    u = sb.table('users').select('username,description').eq('nickname', user).execute()
    if not u.data: return RedirectResponse("/", 303)
    token = get_csrf_token(r)
    res = HTMLResponse(edit_html(user, u.data[0], lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/cabinet/edit", response_class=HTMLResponse)
async def edit_action(r: Request, res: Response, user: str = Depends(auth_middleware), username: str = Form(...), description: str = Form(""), csrf_token: str = Form(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>alert('CSRF Error');window.history.back()</script>")
    if len(description) > 300: return HTMLResponse(f"<script>alert('{t('alert_desc_long', lang)}');window.history.back()</script>")
    
    sb.table('users').update({"username": username, "description": description}).eq('nickname', user).execute()
    return RedirectResponse("/cabinet", 303)

@app.get("/bugreport", response_class=HTMLResponse)
async def bugreport(r: Request, nickname: str = Cookie(None), lang: str = Cookie("ru")):
    u = ""
    rp = []
    if nickname:
        x = sb.table('users').select('username').eq('nickname', nickname).execute()
        if x.data: u = x.data[0]['username']
        y = sb.table('bug_reports').select('*').eq('user_nickname', nickname).order('created_at', desc=True).execute()
        rp = y.data
    token = get_csrf_token(r)
    res = HTMLResponse(bugreport_html(u, rp, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.post("/bugreport", response_class=HTMLResponse)
async def bugreport_submit(r: Request, res: Response, name: str = Form(...), content: str = Form(...), csrf_token: str = Form(None), nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not check_csrf(r, csrf_token): return HTMLResponse("<script>alert('CSRF Error');window.history.back()</script>")
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
    u = sb.table('users').select('username').eq('nickname', nickname).execute()
    if not u.data: return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
    x = sb.table('posts').select('*').eq('id', rid).eq('user_nickname', nickname).execute()
    if not x.data: return HTMLResponse(f"<h2>{t('no_posts', lang)}</h2>", 404)
    rec = x.data[0]
    if rec.get('is_hidden') and r.cookies.get("nickname") != nickname:
        return HTMLResponse(f"<h2>{t('user_not_found', lang)}</h2>", 404)
    token = get_csrf_token(r)
    res = HTMLResponse(record_page_html(nickname, u.data[0], rec, lang, token))
    set_csrf_cookie(res, token, r)
    return res

@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str, r: Request, lang: str = Cookie("ru")):
    u = sb.table('users').select('username,description').eq('nickname', nickname).execute()
    if not u.data: return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/'>OK</a></h2>", 404)
    
    is_owner = (r.cookies.get("nickname") == nickname)
    p = sb.table('posts').select('*').eq('user_nickname', nickname).execute()
    po = merge_memory(p.data, nickname, is_owner)
    
    token = get_csrf_token(r)
    res = HTMLResponse(public_html(nickname, u.data[0], po, lang, token))
    set_csrf_cookie(res, token, r)
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
