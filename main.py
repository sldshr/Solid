from fastapi import FastAPI, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from supabase import create_client, Client
import uvicorn
import html
import hashlib
from datetime import datetime

app = FastAPI()

# --- НАСТРОЙКИ SUPABASE ---
SUPABASE_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- ПЕРЕВОДЫ (i18n) ---
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
        "link_profile": "(Ссылка)", "avatar": "Аватарка", "cancel": "Отмена",
        "username_label": "Имя пользователя", "nickname_label": "Никнейм",
        "loading_init": "Инициализация...", "loading_send": "Отправка запроса...",
        "loading_wait": "Ожидание ответа БД...", "loading_ok": "Успешно!",
        "loading_err": "Ошибка:", "loading_reload": "Перезагрузка страницы...",
        "post_created": "Пост создан", "post_deleted": "Пост удален"
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
        "link_profile": "(Link)", "avatar": "Avatar", "cancel": "Cancel",
        "username_label": "Username", "nickname_label": "Nickname",
        "loading_init": "Initializing...", "loading_send": "Sending request...",
        "loading_wait": "Waiting for DB response...", "loading_ok": "Success!",
        "loading_err": "Error:", "loading_reload": "Reloading page...",
        "post_created": "Post created", "post_deleted": "Post deleted"
    }
}

def t(key: str, lang: str = "ru") -> str:
    return LOCALES.get(lang, LOCALES["ru"]).get(key, key)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def format_date(iso_str: str) -> str:
    if not iso_str: return ""
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
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
        
        .footer { text-align: center; font-size: 16px; font-weight: bold; color: #555; width: 100%; max-width: 1200px; margin-top: 10px; }
        .footer a { color: #000; border-bottom: 2px solid #000; }

        .auth-wrapper { display: flex; gap: 20px; flex-direction: column; }
        .auth-wrapper-inner { display: flex; gap: 20px; align-items: flex-end; }
        .form-box { background-color: black; padding: 5px; display: flex; flex-direction: column; gap: 5px; border: 2px solid #ccc; }
        .form-box form { display: flex; flex-direction: column; gap: 5px; margin: 0; }
        .input-group { position: relative; display: flex; align-items: center; width: 280px; }
        
        input[type="text"], input[type="password"], input[type="file"], textarea {
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
        
        .eye-btn { position: absolute; right: 5px; background: transparent; border: none; cursor: pointer; width: 40px; padding: 5px; display: flex; align-items: center; justify-content: center; }
        .label-text { font-size: 32px; font-weight: normal; margin-bottom: 10px; white-space: nowrap; }
        
        .captcha-container { background-color: #a9a9a9; padding: 10px; display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; cursor: pointer; font-size: 18px; font-weight: bold; }
        .captcha-container input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }

        .dashboard-container { display: flex; gap: 20px; width: 100%; max-width: 1200px; margin: 0 auto; align-items: flex-start; }
        .sidebar { background: black; padding: 10px; width: 350px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; }
        .sidebar h2 { color: white; text-align: center; font-size: 28px; margin: 10px 0; }
        
        .profile-avatar { width: 150px; height: 150px; object-fit: cover; display: block; margin: 0 auto; border: 3px solid #a9a9a9; }
        
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

        /* Улучшенные кнопки языков */
        .lang-switch { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
        .lang-btn { 
            background: transparent; 
            border: 2px solid #a9a9a9; 
            color: #a9a9a9; 
            padding: 8px 15px; 
            width: auto; 
            font-size: 16px; 
            font-weight: bold; 
            cursor: pointer; 
            transition: all 0.2s;
        }
        .lang-btn:hover { background: #a9a9a9; color: black; }
        .lang-btn.active { background: #4da6ff; border-color: #4da6ff; color: white; }
        .login-lang-wrapper { display: flex; justify-content: flex-end; width: 100%; margin-top: 5px; }

        /* Оверлей загрузки */
        #overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.85); z-index: 9999; flex-direction: column;
            justify-content: center; align-items: center; color: #00ff00; font-family: monospace;
        }
        .spinner {
            border: 8px solid #333; border-top: 8px solid #00ff00; border-radius: 50%;
            width: 60px; height: 60px; animation: spin 1s linear infinite; margin-bottom: 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        #log-box {
            text-align: left; width: 80%; max-width: 500px; height: 150px; overflow-y: auto;
            background: #111; padding: 15px; border: 1px solid #333; white-space: pre-wrap;
            font-size: 14px; line-height: 1.4;
        }

        @media (max-width: 768px) {
            body { padding: 10px; }
            .container { flex-direction: column; padding: 15px; gap: 20px; border-width: 5px; width: 100%; }
            .auth-wrapper-inner { flex-direction: column; gap: 10px; width: 100%; align-items: stretch;}
            .input-group { width: 100%; }
            .label-text { font-size: 28px; text-align: center; margin: 10px 0 0 0; order: -1; }
            .form-box { width: 100%; }
            .dashboard-container { flex-direction: column; }
            .sidebar { width: 100%; }
            .posts-area { padding: 10px; }
            .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
        }
    </style>
    """

# --- JS ДЛЯ AJAX И ЛОГОВ ---
def get_js_logic(lang):
    return f"""
    <script>
        const msgInit = "{t('loading_init', lang)}";
        const msgSend = "{t('loading_send', lang)}";
        const msgWait = "{t('loading_wait', lang)}";
        const msgOk = "{t('loading_ok', lang)}";
        const msgErr = "{t('loading_err', lang)}";
        const msgReload = "{t('loading_reload', lang)}";

        function log(text, isError = false) {{
            const box = document.getElementById('log-box');
            const color = isError ? '#ff4d4d' : '#00ff00';
            box.innerHTML += `<span style="color: ${{color}}">> ${{text}}</span><br>`;
            box.scrollTop = box.scrollHeight;
        }}

        function showOverlay() {{
            document.getElementById('overlay').style.display = 'flex';
            document.getElementById('log-box').innerHTML = '';
        }}

        async function handleCreatePost(event) {{
            event.preventDefault();
            showOverlay();
            log(msgInit);
            
            const form = event.target;
            const formData = new FormData(form);
            
            try {{
                log(msgSend + " POST /create_post");
                const res = await fetch('/create_post', {{ method: 'POST', body: formData }});
                log(msgWait);
                
                if (!res.ok) throw new Error("HTTP " + res.status);
                
                const data = await res.json();
                log(msgOk + " ID: " + data.id);
                log(msgReload);
                setTimeout(() => window.location.reload(), 800);
            }} catch (e) {{
                log(msgErr + " " + e.message, true);
                setTimeout(() => document.getElementById('overlay').style.display = 'none', 3000);
            }}
        }}

        async function handleDeletePost(postId, btn) {{
            if (!confirm("{t('confirm_delete', lang)}")) return;
            showOverlay();
            log(msgInit);
            
            try {{
                log(msgSend + " POST /delete_post/" + postId);
                const res = await fetch('/delete_post/' + postId, {{ method: 'POST' }});
                log(msgWait);
                
                if (!res.ok) throw new Error("HTTP " + res.status);
                
                log(msgOk + " " + "{t('post_deleted', lang)}");
                log(msgReload);
                setTimeout(() => window.location.reload(), 800);
            }} catch (e) {{
                log(msgErr + " " + e.message, true);
                setTimeout(() => document.getElementById('overlay').style.display = 'none', 3000);
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
        <div id="log-box"></div>
    </div>
    """

# --- HTML ГЕНЕРАТОРЫ ---

def auth_html(lang: str):
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
            </div>
        </div>

        <div class="footer">
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | 
            {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a>
        </div>
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

def get_avatar_html(user_data):
    avatar_url = user_data.get('avatar_url', '')
    if avatar_url:
        return f'<img src="{avatar_url}" class="profile-avatar">'
    return ''

def dashboard_html(user_nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=True, viewer_is_owner=True)
    desc = user_data.get('description', '')
    avatar_html = get_avatar_html(user_data)
    
    desc_block = f'<div class="info-card"><b>{t("description", lang)}:</b><br>{html.escape(desc)}</div>' if desc else ''
    
    # Добавляем JS для закрепления постов (чтобы не делать форму)
    js_pin = f"""
    <script>
        async function handlePinPost(postId) {{
            showOverlay();
            log(msgInit);
            try {{
                log(msgSend + " POST /pin_post/" + postId);
                const res = await fetch('/pin_post/' + postId, {{ method: 'POST' }});
                log(msgWait);
                if (!res.ok) throw new Error("HTTP " + res.status);
                log(msgOk + " Pinned status toggled");
                log(msgReload);
                setTimeout(() => window.location.reload(), 800);
            }} catch (e) {{
                log(msgErr + " " + e.message, true);
                setTimeout(() => document.getElementById('overlay').style.display = 'none', 3000);
            }}
        }}
    </script>
    """
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('profile', lang)}</title>
        {get_css()}
        {get_js_logic(lang)}
        {js_pin}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>{t('profile', lang)}</h2>
                {avatar_html}
                <div class="info-card">
                    <b>{t('username_label', lang)}:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>{t('nickname_label', lang)}:</b><br><a href="/{user_nickname}" target="_blank">{html.escape(user_nickname)} {t('link_profile', lang)}</a>
                </div>
                {desc_block}
                <div class="info-card">
                    <b>{t('total_posts', lang)}:</b><br>{len(posts)}
                </div>
                
                <a href="/dashboard/edit" class="btn edit-btn">{t('edit_profile', lang)}</a>
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
        
        <div class="footer">
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | 
            {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a>
        </div>
        {get_overlay_html()}
    </body>
    </html>
    """

def edit_profile_html(user_nickname: str, user_data: dict, lang: str):
    desc = user_data.get('description', '')
    avatar_html = get_avatar_html(user_data)
    
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
                    <form action="/dashboard/edit" method="post" enctype="multipart/form-data" style="display: flex; flex-direction: column; gap: 10px;">
                        
                        {avatar_html}
                        
                        <div style="color: white; font-size: 18px; margin-bottom: -5px;">{t('avatar', lang)}</div>
                        <input type="file" name="avatar" accept="image/*" style="background: #a9a9a9; padding: 10px; font-size: 16px;">
                        
                        <div style="color: white; font-size: 18px; margin-bottom: -5px;">{t('username_label', lang)}</div>
                        <input type="text" name="username" value="{html.escape(user_data['username'])}" required style="background: #a9a9a9; padding: 12px; font-size: 18px;">
                        
                        <div style="color: white; font-size: 18px; margin-bottom: -5px;">{t('description', lang)}</div>
                        <textarea name="description" maxlength="300" placeholder="{t('desc_placeholder', lang)}" oninput="updateCounter(this)" style="background: #a9a9a9; height: 150px; padding: 12px; font-size: 18px;">{html.escape(desc)}</textarea>
                        
                        <div id="char-count" style="color: white; text-align: right; font-size: 14px;">{len(desc)} / 300</div>
                        
                        <button type="submit" style="background: #4da6ff; color: white; margin-top: 10px;">{t('save_changes', lang)}</button>
                        <a href="/dashboard" class="btn" style="background: #a9a9a9;">{t('cancel', lang)}</a>
                    </form>
                </div>
            </div>
        </div>
        <div class="footer">
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | 
            {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a>
        </div>
        {get_overlay_html()}
    </body>
    </html>
    """

def public_profile_html(nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=False)
    desc = user_data.get('description', '')
    avatar_html = get_avatar_html(user_data)
    
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
                {avatar_html}
                <div class="info-card">
                    <b>{t('username_label', lang)}:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>{t('nickname_label', lang)}:</b><br>{html.escape(nickname)}
                </div>
                {desc_block}
                <div class="info-card">
                    <b>{t('total_posts', lang)}:</b><br>{len(posts)}
                </div>
                
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

        <div class="footer">
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a> | 
            {t('hosting', lang)} <a href="https://fastapicloud.com" target="_blank">FastAPICloud</a>
        </div>
        {get_overlay_html()}
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

@app.post("/register")
def register(
    username: str = Form(...), nickname: str = Form(...), password: str = Form(...),
    re_pass: str = Form(...), captcha: str = Form(None), lang: str = Cookie("ru")
):
    if not captcha: 
        return HTMLResponse(f"<script>alert('{t('alert_captcha', lang)}'); window.history.back();</script>")
    if password != re_pass: 
        return HTMLResponse(f"<script>alert('{t('alert_pass_mismatch', lang)}'); window.history.back();</script>")
    
    res = supabase.table('users').select('nickname').eq('nickname', nickname).execute()
    if res.data: 
        return HTMLResponse(f"<script>alert('{t('alert_nick_taken', lang)}'); window.history.back();</script>")
    
    try:
        supabase.table('users').insert({
            "username": username, "nickname": nickname, "password": hash_password(password),
            "description": "", "avatar_url": ""
        }).execute()
    except Exception as e:
        return HTMLResponse(f"<script>alert('DB Error: {str(e)}'); window.history.back();</script>")
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="nickname", value=nickname, httponly=True)
    return response

@app.post("/login")
def login(nickname: str = Form(...), password: str = Form(...), captcha: str = Form(None), lang: str = Cookie("ru")):
    if not captcha: 
        return HTMLResponse(f"<script>alert('{t('alert_captcha', lang)}'); window.history.back();</script>")
    
    res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    user = res.data[0] if res.data else None
    
    if user and user["password"] == hash_password(password):
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="nickname", value=nickname, httponly=True)
        return response
    
    return HTMLResponse(f"<script>alert('{t('alert_bad_login', lang)}'); window.history.back();</script>")

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

@app.post("/dashboard/edit")
async def edit_profile_action(
    username: str = Form(...), description: str = Form(""),
    avatar: UploadFile = File(None),
    nickname: str = Cookie(None), lang: str = Cookie("ru")
):
    if not nickname: return RedirectResponse(url="/", status_code=303)
    if len(description) > 300: 
        return HTMLResponse(f"<script>alert('{t('alert_desc_long', lang)}'); window.history.back();</script>")

    update_data = {"username": username, "description": description}

    if avatar and avatar.filename:
        try:
            file_bytes = await avatar.read()
            ext = avatar.filename.split(".")[-1]
            file_path = f"{nickname}.{ext}"
            
            supabase.storage.from_("avatars").upload(
                path=file_path, file=file_bytes,
                file_options={"content-type": avatar.content_type, "upsert": "true"}
            )
            public_url = supabase.storage.from_("avatars").get_public_url(file_path)
            update_data["avatar_url"] = public_url
        except Exception as e:
            print(f"Upload error: {e}")

    supabase.table('users').update(update_data).eq('nickname', nickname).execute()
    return RedirectResponse(url="/dashboard", status_code=303)

# --- AJAX МАРШРУТЫ (ВОЗВРАЩАЮТ JSON, А НЕ REDIRECT) ---
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
