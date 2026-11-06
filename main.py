from fastapi import FastAPI, Form, Cookie, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from supabase import create_client, Client
import uvicorn
import html
import hashlib

app = FastAPI()

# --- НАСТРОЙКИ SUPABASE ---
SUPABASE_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- СЛОВАРИ ПЕРЕВОДА (i18n) ---
LOCALES = {
    "ru": {
        "reg": "Регистрация",
        "login": "Вход",
        "username": "юзернейм",
        "nickname": "никнейм",
        "password": "пароль",
        "re_pass": "повтор пароля",
        "captcha": "Я не робот",
        "register_btn": "Зарегистрироваться!",
        "login_btn": "Войти",
        "profile": "ПРОФИЛЬ",
        "total_posts": "Всего постов",
        "logout": "Выйти",
        "create_post_btn": "Создать пост",
        "create_post_placeholder": "Напишите что-нибудь...",
        "my_posts": "МОИ ПОСТЫ",
        "user_posts": "ПОСТЫ ПОЛЬЗОВАТЕЛЯ",
        "no_posts": "Постов пока нет...",
        "pin": "Закрепить",
        "unpin": "Открепить",
        "delete": "Удалить",
        "confirm_delete": "Удалить пост?",
        "created_by": "Создано:",
        "back_home": "На главную",
        "user_not_found": "Пользователь не найден.",
        "alert_captcha": "Подтвердите, что вы не робот!",
        "alert_pass_mismatch": "Пароли не совпадают!",
        "alert_nick_taken": "Такой никнейм уже занят!",
        "alert_bad_login": "Неверный никнейм или пароль!",
        "lang_name": "Язык",
        "link_profile": "(Ссылка)"
    },
    "en": {
        "reg": "Registration",
        "login": "Login",
        "username": "username",
        "nickname": "nickname",
        "password": "password",
        "re_pass": "re enter pass",
        "captcha": "I am not a robot",
        "register_btn": "Register!",
        "login_btn": "Login",
        "profile": "PROFILE",
        "total_posts": "Total posts",
        "logout": "Logout",
        "create_post_btn": "Create post",
        "create_post_placeholder": "Write something...",
        "my_posts": "MY POSTS",
        "user_posts": "USER POSTS",
        "no_posts": "No posts yet...",
        "pin": "Pin",
        "unpin": "Unpin",
        "delete": "Delete",
        "confirm_delete": "Delete post?",
        "created_by": "Created by:",
        "back_home": "Back to home",
        "user_not_found": "User not found.",
        "alert_captcha": "Please confirm you are not a robot!",
        "alert_pass_mismatch": "Passwords do not match!",
        "alert_nick_taken": "Nickname is already taken!",
        "alert_bad_login": "Invalid nickname or password!",
        "lang_name": "Language",
        "link_profile": "(Link)"
    }
}

def t(key: str, lang: str = "ru") -> str:
    return LOCALES.get(lang, LOCALES["ru"]).get(key, key)

# --- ХЕШИРОВАНИЕ ПАРОЛЕЙ ---
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# --- CSS СТИЛИ ---
def get_css():
    return """
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        a { color: black; text-decoration: none; font-weight: bold; }
        a:hover { text-decoration: underline; }
        
        /* --- Общие контейнеры --- */
        .container {
            background: white;
            padding: 30px;
            border: 10px solid #e0e0e0;
            display: flex;
            gap: 40px;
            align-items: flex-start;
            max-width: 100%;
            margin-bottom: 20px;
        }
        
        /* Футер */
        .footer {
            text-align: center;
            font-size: 18px;
            font-weight: bold;
            color: #555;
            width: 100%;
            max-width: 1200px;
            margin-top: 10px;
        }
        .footer a { color: #000; border-bottom: 2px solid #000; }

        /* --- Логин/Регистрация --- */
        .auth-wrapper { display: flex; gap: 20px; }
        .auth-wrapper.login-wrapper { align-items: flex-end; }
        .form-box {
            background-color: black;
            padding: 5px;
            display: flex;
            flex-direction: column;
            gap: 5px;
            border: 2px solid #ccc;
        }
        .form-box form { display: flex; flex-direction: column; gap: 5px; margin: 0; }
        .input-group { position: relative; display: flex; align-items: center; width: 280px; }
        
        input[type="text"], input[type="password"], textarea {
            background-color: #a9a9a9;
            border: none;
            padding: 12px;
            font-size: 20px;
            font-family: Arial, sans-serif;
            width: 100%;
            text-align: center;
            outline: none;
        }
        
        button, .btn {
            background-color: #a9a9a9;
            border: none;
            padding: 12px;
            font-size: 20px;
            font-family: Arial, sans-serif;
            width: 100%;
            text-align: center;
            cursor: pointer;
            color: black;
            font-weight: bold;
            display: inline-block;
        }
        button:hover, .btn:hover { background-color: #8c8c8c; }
        
        .eye-btn {
            position: absolute;
            right: 5px;
            background: transparent;
            border: none;
            font-size: 24px;
            cursor: pointer;
            width: auto;
            padding: 5px;
            user-select: none;
        }
        .label-text { font-size: 32px; font-weight: normal; margin-bottom: 10px; white-space: nowrap; }
        
        /* Капча-чекбокс */
        .captcha-container {
            background-color: #a9a9a9;
            padding: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
            cursor: pointer;
            font-size: 18px;
            font-weight: bold;
        }
        .captcha-container input[type="checkbox"] {
            width: 20px;
            height: 20px;
            cursor: pointer;
        }

        /* --- Личный кабинет --- */
        .dashboard-container {
            display: flex;
            gap: 20px;
            width: 100%;
            max-width: 1200px;
            margin: 0 auto;
            align-items: flex-start;
        }
        .sidebar {
            background: black;
            padding: 10px;
            width: 350px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            flex-shrink: 0;
        }
        .sidebar h2 { color: white; text-align: center; font-size: 28px; margin: 10px 0; }
        .info-card {
            background: #a9a9a9;
            padding: 15px;
            font-size: 18px;
            text-align: center;
            word-wrap: break-word;
        }
        .logout-btn { margin-top: 10px; background: #ff4d4d; }
        .logout-btn:hover { background: #cc0000; }
        
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
            width: 100%;
        }
        .create-post-box {
            background: black;
            padding: 5px;
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .create-post-box textarea {
            height: 120px;
            resize: vertical;
            text-align: left;
            font-size: 18px;
            padding: 10px;
        }
        
        .posts-area {
            background: black;
            padding: 20px;
            min-height: 300px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .posts-area h2 { color: white; font-size: 28px; margin: 0 0 10px 0; text-align: center;}
        
        /* Посты */
        .post-wrapper { position: relative; }
        .post-item {
            background: #a9a9a9;
            padding: 15px;
            font-size: 18px;
            word-wrap: break-word;
            border-left: 5px solid transparent;
        }
        .post-item.pinned {
            border-left: 5px solid #ff4d4d;
            background: #d9d9d9;
        }
        
        /* Кнопки при наведении */
        .post-actions {
            position: absolute;
            top: 5px;
            right: 5px;
            display: flex;
            gap: 5px;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .post-wrapper:hover .post-actions { opacity: 1; }
        .action-btn {
            background: black;
            color: white;
            border: none;
            padding: 5px 10px;
            font-size: 14px;
            cursor: pointer;
            border-radius: 3px;
            width: auto;
        }
        .action-btn:hover { background: #ff4d4d; }
        .action-btn.pin-btn:hover { background: #4da6ff; }

        /* Переключатель языка */
        .lang-switch {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-top: 10px;
        }
        .lang-btn {
            background: transparent;
            border: 2px solid white;
            color: white;
            padding: 5px 10px;
            width: auto;
            font-size: 16px;
        }
        .lang-btn.active { background: white; color: black; }
        .lang-btn.auth-lang { border-color: black; color: black; }
        .lang-btn.auth-lang.active { background: black; color: white; }

        /* --- Мобильная адаптация --- */
        @media (max-width: 768px) {
            body { padding: 10px; }
            .container {
                flex-direction: column;
                padding: 15px;
                gap: 20px;
                border-width: 5px;
                width: 100%;
            }
            .auth-wrapper { flex-direction: column; gap: 10px; width: 100%; }
            .auth-wrapper.login-wrapper { align-items: flex-start; }
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

# --- ГЕНЕРАТОРЫ HTML ---

def auth_html(lang: str):
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('login', lang)} / {t('reg', lang)}</title>
        {get_css()}
        <script>
            function togglePassword(inputId, btn) {{
                const input = document.getElementById(inputId);
                if (input.type === "password") {{
                    input.type = "text";
                    btn.innerHTML = "🙈";
                }} else {{
                    input.type = "password";
                    btn.innerHTML = "👁";
                }}
            }}
        </script>
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
                            <button type="button" class="eye-btn" onclick="togglePassword('reg-pass', this)">👁</button>
                        </div>
                        
                        <div class="input-group">
                            <input type="password" name="re_pass" id="reg-repass" placeholder="{t('re_pass', lang)}" required>
                            <button type="button" class="eye-btn" onclick="togglePassword('reg-repass', this)">👁</button>
                        </div>
                        
                        <label class="captcha-container">
                            <input type="checkbox" name="captcha" required> {t('captcha', lang)}
                        </label>
                        <button type="submit">{t('register_btn', lang)}</button>
                    </form>
                </div>
            </div>

            <div class="auth-wrapper login-wrapper">
                <div class="form-box">
                    <form action="/login" method="post">
                        <input type="text" name="nickname" placeholder="{t('nickname', lang)}" required>
                        
                        <div class="input-group">
                            <input type="password" name="password" id="log-pass" placeholder="{t('password', lang)}" required>
                            <button type="button" class="eye-btn" onclick="togglePassword('log-pass', this)">👁</button>
                        </div>
                        
                        <label class="captcha-container">
                            <input type="checkbox" name="captcha" required> {t('captcha', lang)}
                        </label>
                        <button type="submit">{t('login_btn', lang)}</button>
                    </form>
                </div>
                <div class="label-text">{t('login', lang)}</div>
            </div>
        </div>

        <!-- Переключатель языка и футер -->
        <div class="lang-switch">
            <a href="/set_lang/ru?next=/" class="btn lang-btn auth-lang {'active' if lang == 'ru' else ''}">RU</a>
            <a href="/set_lang/en?next=/" class="btn lang-btn auth-lang {'active' if lang == 'en' else ''}">EN</a>
        </div>

        <div class="footer">
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a>
        </div>
    </body>
    </html>
    """

def render_posts(posts_list, lang, show_actions=False, viewer_is_owner=False):
    if not posts_list:
        return f"<div class='post-item'>{t('no_posts', lang)}</div>"
    
    html_out = ""
    for post in posts_list:
        pinned_class = "pinned" if post['is_pinned'] else ""
        safe_text = html.escape(post['content']).replace('\n', '<br>')
        
        actions = ""
        if show_actions and viewer_is_owner:
            pin_text = t('unpin', lang) if post['is_pinned'] else t('pin', lang)
            actions = f"""
            <div class="post-actions">
                <form action="/pin_post/{post['id']}" method="post" style="margin:0;">
                    <button type="submit" class="action-btn pin-btn">{pin_text}</button>
                </form>
                <form action="/delete_post/{post['id']}" method="post" style="margin:0;" onsubmit="return confirm('{t('confirm_delete', lang)}');">
                    <button type="submit" class="action-btn">{t('delete', lang)}</button>
                </form>
            </div>
            """
            
        html_out += f"""
        <div class="post-wrapper">
            {actions}
            <div class="post-item {pinned_class}">
                {safe_text}
            </div>
        </div>
        """
    return html_out

def dashboard_html(user_nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=True, viewer_is_owner=True)
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('profile', lang)}</title>
        {get_css()}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>{t('profile', lang)}</h2>
                <div class="info-card">
                    <b>Username:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>Nickname:</b><br><a href="/{user_nickname}" target="_blank">{html.escape(user_nickname)} {t('link_profile', lang)}</a>
                </div>
                <div class="info-card">
                    <b>{t('total_posts', lang)}:</b><br>{len(posts)}
                </div>
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
                    <form action="/create_post" method="post" style="display: flex; flex-direction: column; gap: 5px;">
                        <textarea name="content" placeholder="{t('create_post_placeholder', lang)}" required maxlength="500"></textarea>
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
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a>
        </div>
    </body>
    </html>
    """

def public_profile_html(nickname: str, user_data: dict, posts: list, lang: str):
    posts_html = render_posts(posts, lang, show_actions=False)
    
    return f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t('profile', lang)} {html.escape(nickname)}</title>
        {get_css()}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>{t('profile', lang)}</h2>
                <div class="info-card">
                    <b>Username:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>Nickname:</b><br>{html.escape(nickname)}
                </div>
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
            {t('created_by', lang)} <a href="http://solid-link.ddns.net" target="_blank">Solid Link</a>
        </div>
    </body>
    </html>
    """

# --- МАРШРУТЫ ---

@app.get("/set_lang/{lang}")
def set_lang(lang: str, next: str = "/"):
    if lang not in ["ru", "en"]:
        lang = "ru"
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(key="lang", value=lang, max_age=31536000) # 1 год
    return response

@app.get("/", response_class=HTMLResponse)
def index(nickname: str = Cookie(None), lang: str = Cookie("ru")):
    if nickname:
        # Проверяем, существует ли пользователь в БД
        res = supabase.table('users').select('nickname').eq('nickname', nickname).execute()
        if res.data:
            return RedirectResponse(url="/dashboard", status_code=303)
            
    return auth_html(lang)

@app.post("/register")
def register(
    username: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    re_pass: str = Form(...),
    captcha: str = Form(None),
    lang: str = Cookie("ru")
):
    if not captcha:
        return HTMLResponse(f"<script>alert('{t('alert_captcha', lang)}'); window.history.back();</script>")
    
    if password != re_pass:
        return HTMLResponse(f"<script>alert('{t('alert_pass_mismatch', lang)}'); window.history.back();</script>")
    
    # Проверка на занятый никнейм
    res = supabase.table('users').select('nickname').eq('nickname', nickname).execute()
    if res.data:
        return HTMLResponse(f"<script>alert('{t('alert_nick_taken', lang)}'); window.history.back();</script>")
    
    # Сохранение в Supabase
    try:
        supabase.table('users').insert({
            "username": username,
            "nickname": nickname,
            "password": hash_password(password)
        }).execute()
    except Exception as e:
        return HTMLResponse(f"<script>alert('DB Error: {str(e)}'); window.history.back();</script>")
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="nickname", value=nickname, httponly=True)
    return response

@app.post("/login")
def login(
    nickname: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(None),
    lang: str = Cookie("ru")
):
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
    if not nickname:
        return RedirectResponse(url="/", status_code=303)
        
    user_res = supabase.table('users').select('*').eq('nickname', nickname).execute()
    if not user_res.data:
        return RedirectResponse(url="/", status_code=303)
        
    user_data = user_res.data[0]
    
    # Получаем посты (сортировка: сначала закрепленные, потом по дате)
    posts_res = supabase.table('posts').select('*').eq('user_nickname', nickname).order('is_pinned', desc=True).order('created_at', desc=True).execute()
    
    return dashboard_html(nickname, user_data, posts_res.data, lang)

@app.post("/create_post")
def create_post(content: str = Form(...), nickname: str = Cookie(None)):
    if not nickname:
        return RedirectResponse(url="/", status_code=303)
    
    if content.strip():
        supabase.table('posts').insert({
            "user_nickname": nickname,
            "content": content.strip(),
            "is_pinned": False
        }).execute()
        
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/delete_post/{post_id}")
def delete_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname:
        return RedirectResponse(url="/", status_code=303)
    
    # Удаляем только если пост принадлежит текущему пользователю
    supabase.table('posts').delete().eq('id', post_id).eq('user_nickname', nickname).execute()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/pin_post/{post_id}")
def pin_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname:
        return RedirectResponse(url="/", status_code=303)
    
    # Получаем текущий статус поста
    res = supabase.table('posts').select('is_pinned').eq('id', post_id).eq('user_nickname', nickname).execute()
    if res.data:
        current_status = res.data[0]['is_pinned']
        # Инвертируем статус
        supabase.table('posts').update({"is_pinned": not current_status}).eq('id', post_id).eq('user_nickname', nickname).execute()
        
    return RedirectResponse(url="/dashboard", status_code=303)

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
        
    user_data = user_res.data[0]
    posts_res = supabase.table('posts').select('*').eq('user_nickname', nickname).order('is_pinned', desc=True).order('created_at', desc=True).execute()
    
    return public_profile_html(nickname, user_data, posts_res.data, lang)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
