from fastapi import FastAPI, Form, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from supabase import create_client, Client
import uvicorn
import html
import hashlib
from datetime import datetime

app = FastAPI()

# --- ОБРАБОТЧИК ОШИБОК ВАЛИДАЦИИ (чтобы не было сырого JSON) ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    lang = request.cookies.get("lang", "ru")
    error_msg = "Заполните все обязательные поля!" if lang == "ru" else "Please fill all required fields!"
    return HTMLResponse(content=auth_html(lang, error_msg), status_code=422)

# --- НАСТРОЙКИ SUPABASE ---
SUPABASE_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- ПЕРЕВОДЫ ---
LOCALES = {
    "ru": {
        "reg": "Регистрация", "login": "Вход", "username": "юзернейм", "nickname": "никнейм",
        "password": "пароль", "re_pass": "повтор пароля", "captcha": "Я не робот",
        "register_btn": "Зарегистрироваться!", "login_btn": "Войти", "profile": "ПРОФИЛЬ",
        "total_posts": "Всего постов", "logout": "Выйти", "edit_profile": "Редактировать профиль",
        "save_changes": "Сохранить изменения", "description": "Описание", 
        "desc_placeholder": "Расскажите о себе (до 300 символов)...",
        "create_post_btn": "Создать пост", "create_post_placeholder": "Напишите что-нибудь...",
        "my_posts": "МОИ ПОСТЫ", "user_posts": "ПОСТЫ ПОЛЬЗОВАТЕЛЯ", "no_posts": "Постов пока нет...",
        "pin": "Закрепить", "unpin": "Открепить", "delete": "Удалить", "confirm_delete": "Удалить пост?",
        "created_by": "Создано:", "hosting": "Хостинг:", "back_home": "На главную",
        "user_not_found": "Пользователь не найден.", "alert_captcha": "Подтвердите, что вы не робот!",
        "alert_pass_mismatch": "Пароли не совпадают!", "alert_nick_taken": "Такой никнейм уже занят!",
        "alert_bad_login": "Неверный никнейм или пароль!", "alert_desc_long": "Описание не должно превышать 300 символов!",
        "link_profile": "(Ссылка)", "cancel": "Отмена",
        "username_label": "Имя пользователя", "nickname_label": "Никнейм",
        "bugreport_title": "Баг-репорт", "bugreport_name": "Ваше имя", "bugreport_desc": "Описание проблемы",
        "bugreport_send": "Отправить", "bugreport_my": "Мои заявки",
        "status_accepted": "Принято", "status_working": "В работе", "status_fixed": "Исправлено", "status_rejected": "Отклонено",
        "privacy_title": "Политика конфиденциальности",
        "privacy_text": "1. Сбор информации. Мы собираем только те данные, которые вы добровольно предоставляете при регистрации (имя пользователя, никнейм).<br><br>2. Использование данных. Ваши данные используются исключительно для обеспечения работы сайта и аутентификации.<br><br>3. Безопасность. Мы принимаем необходимые меры для защиты ваших данных от несанкционированного доступа.<br><br>4. Cookies. Сайт использует cookies для сохранения сессии входа и выбранного языка интерфейса.<br><br>5. Ваши права. Вы можете в любой момент изменить или удалить свои данные в профиле.",
        "privacy_agree": "Я согласен с",
        "privacy_link": "Политикой конфиденциальности",
        "alert_privacy": "Вы должны принять политику конфиденциальности!"
    },
    "en": {
        "reg": "Registration", "login": "Login", "username": "username", "nickname": "nickname",
        "password": "password", "re_pass": "re enter pass", "captcha": "I am not a robot",
        "register_btn": "Register!", "login_btn": "Login", "profile": "PROFILE",
        "total_posts": "Total posts", "logout": "Logout", "edit_profile": "Edit Profile",
        "save_changes": "Save changes", "description": "Description", 
        "desc_placeholder": "Tell about yourself (max 300 chars)...",
        "create_post_btn": "Create post", "create_post_placeholder": "Write something...",
        "my_posts": "MY POSTS", "user_posts": "USER POSTS", "no_posts": "No posts yet...",
        "pin": "Pin", "unpin": "Unpin", "delete": "Delete", "confirm_delete": "Delete post?",
        "created_by": "Created by:", "hosting": "Hosting:", "back_home": "Back to home",
        "user_not_found": "User not found.", "alert_captcha": "Please confirm you are not a robot!",
        "alert_pass_mismatch": "Passwords do not match!", "alert_nick_taken": "Nickname is already taken!",
        "alert_bad_login": "Invalid nickname or password!", "alert_desc_long": "Description must not exceed 300 characters!",
        "link_profile": "(Link)", "cancel": "Cancel",
        "username_label": "Username", "nickname_label": "Nickname",
        "bugreport_title": "Bug Report", "bugreport_name": "Your Name", "bugreport_desc": "Issue Description",
        "bugreport_send": "Send", "bugreport_my": "My Reports",
        "status_accepted": "Accepted", "status_working": "In Progress", "status_fixed": "Fixed", "status_rejected": "Rejected",
        "privacy_title": "Privacy Policy",
        "privacy_text": "1. Information Collection. We only collect data you voluntarily provide during registration (username, nickname).<br><br>2. Data Usage. Your data is used solely to ensure the site's operation and authentication.<br><br>3. Security. We take necessary measures to protect your data from unauthorized access.<br><br>4. Cookies. The site uses cookies to maintain your login session and chosen interface language.<br><br>5. Your Rights. You can change or delete your data in your profile at any time.",
        "privacy_agree": "I agree to the",
        "privacy_link": "Privacy Policy",
        "alert_privacy": "You must accept the Privacy Policy!"
    }
}

def t(key: str, lang: str = "ru") -> str:
    return LOCALES.get(lang, LOCALES["ru"]).get(key, key)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def format_date(iso_str: str) -> str:
    if not iso_str: return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return iso_str[:10]

# --- SVG ИКОНКИ ---
SVG_EYE = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>"""
SVG_EYE_OFF = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>"""

# --- CSS ---
def get_css():
    return """
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px;
            display: flex; flex-direction: column; align-items: center; min-height: 100vh;
        }
        a { color: black; text-decoration: none; font-weight: bold; }
        a:hover { text-decoration: underline; }
        
        .container {
            background: white; padding: 30px; border: 10px solid #e0e0e0; display: flex; gap: 40px; 
            align-items: flex-start; max-width: 100%; margin-bottom: 20px;
        }
        
        /* Подвал */
        .footer { 
            text-align: center; font-size: 16px; font-weight: bold; color: #555; 
            width: 100%; max-width: 1200px; margin-top: 10px; display: flex; flex-direction: column; gap: 5px;
        }
        .footer a { color: #000; border-bottom: 2px solid #000; }
        .footer-links { font-size: 14px; color: #777; }
        .footer-links a { color: #555; border-bottom: 1px solid #555; font-weight: normal; }

        /* Формы */
        .auth-wrapper { display: flex; gap: 20px; flex-direction: column; width: 340px; }
        .auth-wrapper-inner { display: flex; gap: 20px; align-items: flex-end; width: 100%;}
        .form-box { background-color: black; padding: 5px; display: flex; flex-direction: column; gap: 5px; border: 2px solid #ccc; width: 100%;}
        .form-box form { display: flex; flex-direction: column; gap: 5px; margin: 0; width: 100%;}
        
        .input-group { position: relative; display: flex; align-items: center; width: 100%; }
        
        input[type="text"], input[type="password"], textarea, select {
            background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px;
            font-family: Arial, sans-serif; width: 100%; text-align: center; outline: none;
        }
        textarea { text-align: left; resize: vertical; }
        
        button, .btn {
            background-color: #a9a9a9; border: none; padding: 12px; font-size: 20px;
            font-family: Arial, sans-serif; width: 100%; text-align: center; cursor: pointer;
            color: black; font-weight: bold; display: inline-block; border: 1px solid transparent;
        }
        button:hover, .btn:hover { background-color: #8c8c8c; }
        
        .eye-btn { 
            position: absolute; right: 5px; background: transparent; border: none; cursor: pointer; 
            width: 40px; padding: 5px; display: flex; align-items: center; justify-content: center; 
        }
        .label-text { font-size: 32px; font-weight: normal; margin-bottom: 10px; white-space: nowrap; }
        
        .captcha-container { 
            background-color: #a9a9a9; padding: 10px; display: flex; align-items: center; justify-content: center; 
            gap: 10px; width: 100%; cursor: pointer; font-size: 16px; font-weight: bold; text-align: center;
        }
        .captcha-container input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; flex-shrink: 0;}
        .privacy-link { color: #0000ff; text-decoration: underline; margin-left: 5px;}

        /* Дашборд */
        .dashboard-container { display: flex; gap: 20px; width: 100%; max-width: 1200px; margin: 0 auto; align-items: flex-start; }
        .sidebar { background: black; padding: 10px; width: 350px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; }
        .sidebar h2 { color: white; text-align: center; font-size: 28px; margin: 10px 0; }
        
        .info-card { background: #a9a9a9; padding: 15px; font-size: 18px; text-align: center; word-wrap: break-word; white-space: pre-wrap; }
        .logout-btn { margin-top: 10px; background: #ff4d4d; }
        .logout-btn:hover { background: #cc0000; }
        .edit-btn { background: #4da6ff; margin-top: 5px; color: white;}
        .edit-btn:hover { background: #1a82e2; }
        
        .main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
        
        .create-post-box { background: black; padding: 5px; display: flex; flex-direction: column; gap: 5px; }
        .create-post-box textarea { height: 120px; font-size: 18px; padding: 10px; }
        
        .posts-area { background: black; padding: 20px; min-height: 300px; display: flex; flex-direction: column; gap: 10px; }
        .posts-area h2 { color: white; font-size: 28px; margin: 0 0 10px 0; text-align: center;}
        
        .post-wrapper { position: relative; }
        .post-item { background: #a9a9a9; padding: 15px; font-size: 18px; word-wrap: break-word; border-left: 5px solid transparent; display: flex; flex-direction: column;}
        .post-item.pinned { border-left: 5px solid #ff4d4d; background: #d9d9d9; }
        .post-content { margin-bottom: 10px; }
        .post-date { font-size: 12px; color: #555; text-align: right; border-top: 1px solid #888; padding-top: 5px; }
        
        .post-actions { position: absolute; top: 5px; right: 5px; display: flex; gap: 5px; opacity: 0; transition: opacity 0.2s; z-index: 10; }
        .post-wrapper:hover .post-actions { opacity: 1; }
        .action-btn { background: black; color: white; border: none; padding: 5px 10px; font-size: 14px; cursor: pointer; border-radius: 3px; width: auto; font-weight: normal;}
        .action-btn:hover { background: #ff4d4d; }
        .action-btn.pin-btn:hover { background: #4da6ff; }

        .status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; color: white; margin-left: 10px;}
        .status-Принято, .status-Accepted { background: #4da6ff; }
        .status-В-работе, .status-In-Progress { background: #f1c40f; }
        .status-Исправлено, .status-Fixed { background: #2ecc71; }
        .status-Отклонено, .status-Rejected { background: #e74c3c; }

        /* Языки */
        .lang-switch { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
        .lang-btn { background: transparent; border: 2px solid #a9a9a9; color: #a9a9a9; padding: 8px 15px; width: auto; font-size: 16px; font-weight: bold; cursor: pointer; transition: all 0.2s;}
        .lang-btn:hover { background: #a9a9a9; color: black; }
        .lang-btn.active { background: #4da6ff; border-color: #4da6ff; color: white; }
        .login-lang-wrapper { display: flex; justify-content: flex-end; width: 100%; margin-top: 5px; }
        
        /* Политика конфиденциальности */
        .privacy-content { background: white; color: black; padding: 20px; font-size: 18px; line-height: 1.5; text-align: left; word-wrap: break-word; }

        .error-msg {
            color: #ff4d4d; font-weight: bold; font-size: 18px; text-align: right;
            width: 100%; margin-top: 10px; min-height: 20px;
        }

        #overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.7); z-index: 9999; flex-direction: column;
            justify-content: center; align-items: center;
        }
        .spinner {
            border: 8px solid #fff; border-top: 8px solid transparent; border-radius: 50%;
            width: 60px; height: 60px; animation: spin 1s linear infinite;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

        @media (max-width: 768px) {
            body { padding: 10px; }
            .container { flex-direction: column; padding: 15px; gap: 20px; border-width: 5px; width: 100%; }
            .auth-wrapper { width: 100%; }
            .auth-wrapper-inner { flex-direction: column; gap: 10px; width: 100%; align-items: stretch;}
            .label-text { font-size: 28px; text-align: center; margin: 10px 0 0 0; order: -1; }
            .dashboard-container { flex-direction: column; }
            .sidebar { width: 100%; }
            .posts-area { padding: 10px; }
            .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
            .error-msg { text-align: center; }
            .login-lang-wrapper { justify-content: center; }
        }
    </style>
    """

def get_js_logic(lang):
    return f"""
    <script>
        function showOverlay() {{
            document.getElementById('overlay').style.display = 'flex';
        }}
        function hideOverlay() {{
            document.getElementById('overlay').style.display = 'none';
        }}

        async function handleCreatePost(event) {{
            event.preventDefault();
            showOverlay();
            const form = event.target;
            const formData = new FormData(form);
            try {{
                const res = await fetch('/create_post', {{ method: 'POST', body: formData }});
                if (!res.ok) throw new Error("HTTP " + res.status);
                window.location.reload();
            }} catch (e) {{
                alert("Error: " + e.message);
                hideOverlay();
            }}
        }}

        async function handleDeletePost(postId) {{
            if (!confirm("{t('confirm_delete', lang)}")) return;
            showOverlay();
            try {{
                const res = await fetch('/delete_post/' + postId, {{ method: 'POST' }});
                if (!res.ok) throw new Error("HTTP " + res.status);
                window.location.reload();
            }} catch (e) {{
                alert("Error: " + e.message);
                hideOverlay();
            }}
        }}

        async function handlePinPost(postId) {{
            showOverlay();
            try {{
                const res = await fetch('/pin_post/' + postId, {{ method: 'POST' }});
                if (!res.ok) throw new Error("HTTP " + res.status);
                window.location.reload();
            }} catch (e) {{
                alert("Error: " + e.message);
                hideOverlay();
            }}
        }}

        function togglePassword(inputId, btn) {{
            const input = document.getElementById(inputId);
            if (input.type === "password") {{
                input.type = "text";
                btn.innerHTML = `{SVG_EYE_OFF}`;
            }} else {{
                input.type = "password";
                btn.innerHTML = `{SVG_EYE}`;
            }}
        }}

        function updateCounter(el) {{
            document.getElementById('char-count').innerText = el.value.length + ' / 300';
        }}
    </script>
    """

def get_overlay_html():
    return """
    <div id="overlay">
        <div class="spinner"></div>
    </div>
    """

# --- ФУТЕР ---
def get_footer(lang):
    return f"""
    <div class="footer">
        <div>{t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a></div>
        <div class="footer-links"><a href="/privacy">{t('privacy_title', lang)}</a></div>
    </div>
    """

# --- HTML ГЕНЕРАТОРЫ ---

def auth_html(lang: str, error_msg: str = ""):
    error_block = f'<div class="error-msg">{error_msg}</div>' if error_msg else '<div class="error-msg"></div>'
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('login', lang)} / {t('reg', lang)}</title>
        {get_css()}
        {get_js_logic(lang)}
    </head>
    <body>
        <div class="container">
            <div class="auth-wrapper">
                <div class="label-text">{t('reg', lang)}</div>
                <div class="form-box">
                    <form action="/register" method="post">
                        <input type="text" name="username" placeholder="{t('username', lang)}" required>
                        <input type="text" name="nickname" placeholder="{t('nickname', lang)}" required>
                        <div class="input-group">
                            <input type="password" name="password" id="reg-pass" placeholder="{t('password', lang)}" required>
                            <button type="button" class="eye-btn" onclick="togglePassword('reg-pass', this)">{SVG_EYE}</button>
                        </div>
                        <div class="input-group">
                            <input type="password" name="re_pass" id="reg-repass" placeholder="{t('re_pass', lang)}" required>
                            <button type="button" class="eye-btn" onclick="togglePassword('reg-repass', this)">{SVG_EYE}</button>
                        </div>
                        <label class="captcha-container">
                            <input type="checkbox" name="captcha" required> {t('captcha', lang)}
                        </label>
                        <label class="captcha-container" style="background: #8c8c8c; margin-top:2px;">
                            <input type="checkbox" name="privacy" required> 
                            <span>{t('privacy_agree', lang)} <a href="/privacy" target="_blank" class="privacy-link">{t('privacy_link', lang)}</a></span>
                        </label>
                        <button type="submit">{t('register_btn', lang)}</button>
                    </form>
                </div>
            </div>

            <div class="auth-wrapper">
                <div class="auth-wrapper-inner">
                    <div class="form-box">
                        <form action="/login" method="post">
                            <input type="text" name="nickname" placeholder="{t('nickname', lang)}" required>
                            <div class="input-group">
                                <input type="password" name="password" id="log-pass" placeholder="{t('password', lang)}" required>
                                <button type="button" class="eye-btn" onclick="togglePassword('log-pass', this)">{SVG_EYE}</button>
                            </div>
                            <label class="captcha-container">
                                <input type="checkbox" name="captcha" required> {t('captcha', lang)}
                            </label>
                            <button type="submit">{t('login_btn', lang)}</button>
                        </form>
                    </div>
                    <div class="label-text">{t('login', lang)}</div>
                </div>
                <div class="login-lang-wrapper">
                    <div class="lang-switch">
                        <a href="/set_lang/ru?next=/" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                        <a href="/set_lang/en?next=/" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                    </div>
                </div>
                {error_block}
            </div>
        </div>

        {get_footer(lang)}
        {get_overlay_html()}
    </body>
    </html>
    """

def render_posts(posts_list, lang, show_actions=False, viewer_is_owner=False):
    if not posts_list:
        return f"<div class='post-item'>{t('no_posts', lang)}</div>"
    
    html_out = ""
    for post in posts_list:
        post_id = post.get('id', '')
        is_pinned = post.get('is_pinned', False)
        content = html.escape(post.get('content', '')).replace('\n', '<br>')
        post_date = format_date(post.get('created_at', ''))
        
        pinned_class = "pinned" if is_pinned else ""
        pin_text = t('unpin', lang) if is_pinned else t('pin', lang)
        
        actions = ""
        if show_actions and viewer_is_owner:
            actions = f'''
            <div class="post-actions">
                <button onclick="handlePinPost('{post_id}')" class="action-btn pin-btn">{pin_text}</button>
                <button onclick="handleDeletePost('{post_id}')" class="action-btn">{t('delete', lang)}</button>
            </div>
            '''
            
        html_out += f'''
        <div class="post-wrapper">
            {actions}
            <div class="post-item {pinned_class}">
                <div class="post-content">{content}</div>
                <div class="post-date">{post_date}</div>
            </div>
        </div>
        '''
    return html_out

def dashboard_html(user_nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=True, viewer_is_owner=True)
    desc = user_data.get('description', '')
    desc_block = f'<div class="info-card"><b>{t("description", lang)}:</b><br>{html.escape(desc)}</div>' if desc else ''
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('profile', lang)}</title>
        {get_css()}
        {get_js_logic(lang)}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>{t('profile', lang)}</h2>
                <div class="info-card"><b>{t('username_label', lang)}:</b><br>{html.escape(user_data['username'])}</div>
                <div class="info-card"><b>{t('nickname_label', lang)}:</b><br><a href="/{user_nickname}" target="_blank">{html.escape(user_nickname)} {t('link_profile', lang)}</a></div>
                {desc_block}
                <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(posts)}</div>
                
                <a href="/dashboard/edit" class="btn edit-btn">{t('edit_profile', lang)}</a>
                <a href="/bugreport" class="btn" style="background: #f1c40f; color: black;">{t('bugreport_title', lang)}</a>
                <form action="/logout" method="get" style="margin: 0; width: 100%;">
                    <button type="submit" class="logout-btn">{t('logout', lang)}</button>
                </form>
                
                <div class="lang-switch">
                    <a href="/set_lang/ru?next=/dashboard" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                    <a href="/set_lang/en?next=/dashboard" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                </div>
            </div>

            <div class="main-content">
                <div class="create-post-box">
                    <form id="create-form" onsubmit="handleCreatePost(event)">
                        <textarea name="content" placeholder="{t('create_post_placeholder', lang)}" required maxlength="500" style="margin-bottom: 5px;"></textarea>
                        <button type="submit">{t('create_post_btn', lang)}</button>
                    </form>
                </div>

                <div class="posts-area">
                    <h2>{t('my_posts', lang)}</h2>
                    {posts_html}
                </div>
            </div>
        </div>
        
        {get_footer(lang)}
        {get_overlay_html()}
    </body>
    </html>
    """

def edit_profile_html(user_nickname: str, user_data: dict, lang: str):
    desc = user_data.get('description', '')
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('edit_profile', lang)}</title>
        {get_css()}
        {get_js_logic(lang)}
    </head>
    <body>
        <div class="dashboard-container" style="justify-content: center;">
            <div class="main-content" style="max-width: 600px;">
                <div class="posts-area">
                    <h2>{t('edit_profile', lang)}</h2>
                    <form action="/dashboard/edit" method="post" style="display: flex; flex-direction: column; gap: 10px;">
                        
                        <div style="color: white; font-size: 18px; margin-bottom: -5px;">{t('username_label', lang)}</div>
                        <input type="text" name="username" value="{html.escape(user_data['username'])}" required style="background: #a9a9a9; padding: 12px; font-size: 18px;">
                        
                        <div style="color: white; font-size: 18px; margin-bottom: -5px;">{t('description', lang)}</div>
                        <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder', lang)}" oninput="updateCounter(this)" style="background: #a9a9a9; height: 150px; padding: 12px; font-size: 18px;">{html.escape(desc)}</textarea>
                        <div id="char-count" style="color: white; text-align: right; font-size: 14px;">{len(desc)} / 300</div>
                        
                        <button type="submit" style="background: #4da6ff; color: white; margin-top: 10px;">{t('save_changes', lang)}</button>
                        <a href="/dashboard" class="btn" style="background: #a9a9a9;">{t('cancel', lang)}</a>
                    </form>
                    
                    <div class="lang-switch" style="margin-top: 20px;">
                        <a href="/set_lang/ru?next=/dashboard/edit" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                        <a href="/set_lang/en?next=/dashboard/edit" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                    </div>
                </div>
            </div>
        </div>
        {get_footer(lang)}
        {get_overlay_html()}
    </body>
    </html>
    """

def public_profile_html(nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=False)
    desc = user_data.get('description', '')
    desc_block = f'<div class="info-card"><b>{t("description", lang)}:</b><br>{html.escape(desc)}</div>' if desc else ''
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('profile', lang)} {html.escape(nickname)}</title>
        {get_css()}
        {get_js_logic(lang)}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>{t('profile', lang)}</h2>
                <div class="info-card"><b>{t('username_label', lang)}:</b><br>{html.escape(user_data['username'])}</div>
                <div class="info-card"><b>{t('nickname_label', lang)}:</b><br>{html.escape(nickname)}</div>
                {desc_block}
                <div class="info-card"><b>{t('total_posts', lang)}:</b><br>{len(posts)}</div>
                
                <div class="lang-switch">
                    <a href="/set_lang/ru?next=/{nickname}" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                    <a href="/set_lang/en?next=/{nickname}" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                </div>
                <a href="/" class="btn" style="margin-top: auto; background: #a9a9a9;">{t('back_home', lang)}</a>
            </div>

            <div class="main-content">
                <div class="posts-area" style="min-height: 500px;">
                    <h2>{t('user_posts', lang)}</h2>
                    {posts_html}
                </div>
            </div>
        </div>

        {get_footer(lang)}
        {get_overlay_html()}
    </body>
    </html>
    """

def bugreport_html(username: str, reports: list, lang: str):
    reports_html = ""
    if not reports:
        reports_html = "<div class='post-item'>Заявок пока нет...</div>"
    else:
        for r in reports:
            status_class = f"status-{r.get('status', 'Принято').replace(' ', '-')}"
            status_text = r.get('status', 'Принято')
            date_str = format_date(r.get('created_at', ''))
            content = html.escape(r.get('content', ''))
            reports_html += f"""
            <div class="post-item" style="border-left-color: transparent;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <b>{t('bugreport_title', lang)}</b>
                    <span class="status-badge {status_class}">{status_text}</span>
                </div>
                <div class="post-content">{content}</div>
                <div class="post-date">{date_str}</div>
            </div>
            """
            
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('bugreport_title', lang)}</title>
        {get_css()}
        {get_js_logic(lang)}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar" style="display: none;"></div>
            
            <div class="main-content" style="max-width: 800px; margin: 0 auto;">
                <div class="create-post-box">
                    <h2 style="color: white; text-align: center; margin: 10px 0;">{t('bugreport_title', lang)}</h2>
                    <form action="/bugreport" method="post" style="display: flex; flex-direction: column; gap: 5px;">
                        <input type="text" name="name" value="{username}" placeholder="{t('bugreport_name', lang)}" required style="background: #a9a9a9; padding: 12px; margin-bottom: 5px;">
                        <textarea name="content" placeholder="{t('bugreport_desc', lang)}" required style="background: #a9a9a9; height: 150px; padding: 12px; margin-bottom: 5px;"></textarea>
                        <button type="submit" style="background: #f1c40f; color: black;">{t('bugreport_send', lang)}</button>
                    </form>
                </div>

                <div class="posts-area">
                    <h2>{t('bugreport_my', lang)}</h2>
                    {reports_html}
                </div>
                
                <a href="/dashboard" class="btn" style="background: #a9a9a9; margin-top: 10px;">{t('cancel', lang)}</a>
                
                <div class="lang-switch" style="margin-top: 20px;">
                    <a href="/set_lang/ru?next=/bugreport" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                    <a href="/set_lang/en?next=/bugreport" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                </div>
            </div>
        </div>

        {get_footer(lang)}
        {get_overlay_html()}
    </body>
    </html>
    """

def privacy_html(lang: str):
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('privacy_title', lang)}</title>
        {get_css()}
    </head>
    <body>
        <div class="dashboard-container" style="justify-content: center;">
            <div class="main-content" style="max-width: 800px;">
                <div class="posts-area">
                    <h2 style="color: white; text-align: center; margin-bottom: 20px;">{t('privacy_title', lang)}</h2>
                    <div class="privacy-content">
                        {t('privacy_text', lang)}
                    </div>
                    <a href="/" class="btn" style="background: #a9a9a9; margin-top: 20px;">{t('back_home', lang)}</a>
                    
                    <div class="lang-switch" style="margin-top: 20px;">
                        <a href="/set_lang/ru?next=/privacy" class="btn lang-btn {'active' if lang == 'ru' else ''}">RU</a>
                        <a href="/set_lang/en?next=/privacy" class="btn lang-btn {'active' if lang == 'en' else ''}">EN</a>
                    </div>
                </div>
            </div>
        </div>
        {get_footer(lang)}
    </body>
    </html>
    """

# --- МАРШРУТЫ ---

@app.get("/set_lang/{lang}")
def set_lang(lang: str, next: str = "/"):
    if lang not in ["ru", "en"]: lang = "ru"
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(key="lang", value=lang, max_age=31536000)
    return response

@app.get("/", response_class=HTMLResponse)
def index(nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if nickname:
        res = supabase.table('users').select('nickname').eq('nickname', nickname).execute()
        if res.data:
            return RedirectResponse(url="/dashboard", status_code=303)
    return auth_html(lang)

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(lang: str = Cookie("ru")):
    return privacy_html(lang)

# ОБРАТИТЕ ВНИМАНИЕ НА response_class=HTMLResponse
@app.post("/register", response_class=HTMLResponse)
def register(
    username: str = Form(...), nickname: str = Form(...), password: str = Form(...),
    re_pass: str = Form(...), captcha: str = Form(None), privacy: str = Form(None), lang: str = Cookie("ru")
):
    if not captcha: 
        return auth_html(lang, t('alert_captcha', lang))
    if not privacy: 
        return auth_html(lang, t('alert_privacy', lang))
    if password != re_pass: 
        return auth_html(lang, t('alert_pass_mismatch', lang))
    
    res = supabase.table('users').select('nickname').eq('nickname', nickname).execute()
    if res.data: 
        return auth_html(lang, t('alert_nick_taken', lang))
    
    try:
        supabase.table('users').insert({
            "username": username, "nickname": nickname, "password": hash_password(password),
            "description": ""
        }).execute()
    except Exception as e:
        return auth_html(lang, f"DB Error: {str(e)}")
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="nickname", value=nickname, httponly=True)
    return response

# ОБРАТИТЕ ВНИМАНИЕ НА response_class=HTMLResponse
@app.post("/login", response_class=HTMLResponse)
def login(nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), lang: str = Cookie("ru")):
    if not captcha: 
        return auth_html(lang, t('alert_captcha', lang))
    
    res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    user = res.data[0] if res.data else None
    
    if user and user["password"] == hash_password(password):
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="nickname", value=nickname, httponly=True)
        return response
    
    return auth_html(lang, t('alert_bad_login', lang))

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse(url="/", status_code=303)
    
    user_res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    if not user_res.data: return RedirectResponse(url="/", status_code=303)
    
    posts_res = supabase.table('posts').select('*').eq('user_nickname', nickname).order('is_pinned', desc=True).order('created_at', desc=True).execute()
    return dashboard_html(nickname, user_res.data[0], posts_res.data, lang)

@app.get("/dashboard/edit", response_class=HTMLResponse)
def edit_profile_page(nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if not nickname: return RedirectResponse(url="/", status_code=303)
    
    user_res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    if not user_res.data: return RedirectResponse(url="/", status_code=303)
    
    return edit_profile_html(nickname, user_res.data[0], lang)

@app.post("/dashboard/edit", response_class=HTMLResponse)
def edit_profile_action(
    username: str = Form(...), description: str = Form(""),
    nickname: str = Cookie(None), lang: str = Cookie("ru")
):
    if not nickname: return RedirectResponse(url="/", status_code=303)
    if len(description) > 300: 
        return HTMLResponse(f"<script>alert('{t('alert_desc_long', lang)}'); window.history.back();</script>")

    supabase.table('users').update({
        "username": username, "description": description
    }).eq('nickname', nickname).execute()
    
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/create_post")
def create_post(content: str = Form(...), nickname: str = Cookie(None)):
    if not nickname: return JSONResponse({"status": "error", "msg": "Unauthorized"}, status_code=401)
    if not content.strip(): return JSONResponse({"status": "error", "msg": "Empty content"}, status_code=400)
    
    res = supabase.table('posts').insert({
        "user_nickname": nickname, "content": content.strip(), "is_pinned": False
    }).execute()
    
    post_id = res.data[0]['id'] if res.data else ""
    return JSONResponse({"status": "ok", "id": post_id})

@app.post("/delete_post/{post_id}")
def delete_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname: return JSONResponse({"status": "error", "msg": "Unauthorized"}, status_code=401)
    supabase.table('posts').delete().eq('id', post_id).eq('user_nickname', nickname).execute()
    return JSONResponse({"status": "ok"})

@app.post("/pin_post/{post_id}")
def pin_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname: return JSONResponse({"status": "error", "msg": "Unauthorized"}, status_code=401)
    res = supabase.table('posts').select('is_pinned').eq('id', post_id).eq('user_nickname', nickname).execute()
    if res.data:
        supabase.table('posts').update({"is_pinned": not res.data[0]['is_pinned']}).eq('id', post_id).eq('user_nickname', nickname).execute()
    return JSONResponse({"status": "ok"})

@app.get("/bugreport", response_class=HTMLResponse)
def bugreport_page(nickname: str = Cookie(None), lang: str = Cookie("ru")):
    username = ""
    reports = []
    
    if nickname:
        res = supabase.table('users').select('username').eq('nickname', nickname).execute()
        if res.data:
            username = res.data[0]['username']
            
        rep_res = supabase.table('bug_reports').select('*').eq('user_nickname', nickname).order('created_at', desc=True).execute()
        reports = rep_res.data
    
    return bugreport_html(username, reports, lang)

@app.post("/bugreport", response_class=HTMLResponse)
def bugreport_submit(
    name: str = Form(...), content: str = Form(...),
    nickname: str = Cookie(None), lang: str = Cookie("ru")
):
    data = {
        "name": name,
        "content": content,
        "status": "Принято" if lang == "ru" else "Accepted"
    }
    if nickname:
        data["user_nickname"] = nickname
        
    supabase.table('bug_reports').insert(data).execute()
    return RedirectResponse(url="/bugreport", status_code=303)

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("nickname")
    return response

@app.get("/{nickname}", response_class=HTMLResponse)
def public_profile(nickname: str, lang: str = Cookie("ru")):
    user_res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    if not user_res.data: 
        return HTMLResponse(f"<h2>{t('user_not_found', lang)} <a href='/'>OK</a></h2>", status_code=404)
    
    posts_res = supabase.table('posts').select('*').eq('user_nickname', nickname).order('is_pinned', desc=True).order('created_at', desc=True).execute()
    return public_profile_html(nickname, user_res.data[0], posts_res.data, lang)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
