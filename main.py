from fastapi import FastAPI, Form, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import html
import uuid

app = FastAPI()

# База данных в оперативке
# Структура: { "nickname": { "username": "...", "password": "...", "posts": [ {"id": "...", "text": "...", "pinned": False} ] } }
db = {}

# --- CSS СТИЛИ ---
common_css = """
<style>
    * { box-sizing: border-box; }
    body {
        font-family: Arial, sans-serif;
        background-color: #f4f4f4;
        margin: 0;
        padding: 20px;
        display: flex;
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
    }
    
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
        font-size: 24px;
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
        font-size: 20px;
        cursor: pointer;
        width: auto;
        padding: 5px;
        user-select: none;
    }
    .label-text { font-size: 48px; font-weight: normal; margin-bottom: 10px; }
    
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
        font-size: 20px;
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
    .sidebar h2 { color: white; text-align: center; font-size: 32px; margin: 10px 0; }
    .info-card {
        background: #a9a9a9;
        padding: 20px;
        font-size: 20px;
        text-align: center;
        word-wrap: break-word;
    }
    .logout-btn { margin-top: auto; background: #ff4d4d; }
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
    .posts-area h2 { color: white; font-size: 32px; margin: 0 0 10px 0; text-align: center;}
    
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
    .post-author { font-size: 14px; font-weight: bold; margin-bottom: 5px; color: #333; }
    
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
    }
    .action-btn:hover { background: #ff4d4d; }
    .action-btn.pin-btn:hover { background: #4da6ff; }

    /* --- Мобильная адаптация --- */
    @media (max-width: 768px) {
        body { padding: 10px; }
        .container {
            flex-direction: column;
            padding: 15px;
            gap: 20px;
            border-width: 5px;
        }
        .auth-wrapper { flex-direction: column; gap: 10px; width: 100%; }
        .auth-wrapper.login-wrapper { align-items: flex-start; }
        .input-group { width: 100%; }
        .label-text { font-size: 32px; text-align: center; margin: 10px 0 0 0; order: -1; }
        .form-box { width: 100%; }
        
        .dashboard-container { flex-direction: column; }
        .sidebar { width: 100%; }
        .posts-area { padding: 10px; }
        .post-actions { opacity: 1; position: relative; margin-top: 10px; justify-content: flex-end; top: 0; right: 0;}
    }
</style>
"""

# --- HTML ШАБЛОНЫ ---

auth_html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login / Reg</title>
    {common_css}
    <script>
        function togglePassword(inputId) {{
            const input = document.getElementById(inputId);
            input.type = input.type === "password" ? "text" : "password";
        }}
    </script>
</head>
<body>
    <div class="container">
        <div class="auth-wrapper">
            <div class="label-text">reg</div>
            <div class="form-box">
                <form action="/register" method="post">
                    <input type="text" name="username" placeholder="username" required>
                    <input type="text" name="nickname" placeholder="nickname" required>
                    
                    <div class="input-group">
                        <input type="password" name="password" id="reg-pass" placeholder="password" required>
                        <button type="button" class="eye-btn" onclick="togglePassword('reg-pass')">👁</button>
                    </div>
                    
                    <div class="input-group">
                        <input type="password" name="re_pass" id="reg-repass" placeholder="re enter pass" required>
                        <button type="button" class="eye-btn" onclick="togglePassword('reg-repass')">👁</button>
                    </div>
                    
                    <label class="captcha-container">
                        <input type="checkbox" name="captcha" required> Я не робот
                    </label>
                    <button type="submit">Register!</button>
                </form>
            </div>
        </div>

        <div class="auth-wrapper login-wrapper">
            <div class="form-box">
                <form action="/login" method="post">
                    <input type="text" name="nickname" placeholder="nickname" required>
                    
                    <div class="input-group">
                        <input type="password" name="password" id="log-pass" placeholder="password" required>
                        <button type="button" class="eye-btn" onclick="togglePassword('log-pass')">👁</button>
                    </div>
                    
                    <label class="captcha-container">
                        <input type="checkbox" name="captcha" required> Я не робот
                    </label>
                    <button type="submit">Login</button>
                </form>
            </div>
            <div class="label-text">Login</div>
        </div>
    </div>
</body>
</html>
"""

def render_posts(posts_list, show_actions=False, viewer_is_owner=False):
    if not posts_list:
        return "<div class='post-item'>Постов пока нет...</div>"
    
    # Сортировка: сначала закрепленные, потом остальные (новые сверху)
    sorted_posts = sorted(posts_list, key=lambda x: (not x['pinned'], x.get('created_at', 0)), reverse=True)
    
    html_out = ""
    for post in sorted_posts:
        pinned_class = "pinned" if post['pinned'] else ""
        safe_text = html.escape(post['text']).replace('\n', '<br>')
        
        actions = ""
        if show_actions and viewer_is_owner:
            pin_text = "Открепить" if post['pinned'] else "Закрепить"
            actions = f"""
            <div class="post-actions">
                <form action="/pin_post/{post['id']}" method="post" style="margin:0;">
                    <button type="submit" class="action-btn pin-btn">{pin_text}</button>
                </form>
                <form action="/delete_post/{post['id']}" method="post" style="margin:0;" onsubmit="return confirm('Удалить пост?');">
                    <button type="submit" class="action-btn">Удалить</button>
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

def get_dashboard_html(user_nickname: str, user_data: dict):
    posts_html = render_posts(user_data["posts"], show_actions=True, viewer_is_owner=True)
    
    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Личный кабинет</title>
        {common_css}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>ПРОФИЛЬ</h2>
                <div class="info-card">
                    <b>Username:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>Nickname:</b><br><a href="/{user_nickname}" target="_blank">{html.escape(user_nickname)} (Ссылка)</a>
                </div>
                <div class="info-card">
                    <b>Всего постов:</b><br>{len(user_data['posts'])}
                </div>
                <form action="/logout" method="get" style="margin: 0; width: 100%;">
                    <button type="submit" class="logout-btn">Выйти</button>
                </form>
            </div>

            <div class="main-content">
                <div class="create-post-box">
                    <form action="/create_post" method="post" style="display: flex; flex-direction: column; gap: 5px;">
                        <textarea name="content" placeholder="Напишите что-нибудь..." required maxlength="500"></textarea>
                        <button type="submit">Создать пост</button>
                    </form>
                </div>

                <div class="posts-area">
                    <h2>МОИ ПОСТЫ</h2>
                    {posts_html}
                </div>
            </div>
        </div>
    </body>
    </html>
    """

def get_public_profile_html(nickname: str, user_data: dict):
    posts_html = render_posts(user_data["posts"], show_actions=False)
    
    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Профиль {html.escape(nickname)}</title>
        {common_css}
    </head>
    <body>
        <div class="dashboard-container">
            <div class="sidebar">
                <h2>ПРОФИЛЬ</h2>
                <div class="info-card">
                    <b>Username:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>Nickname:</b><br>{html.escape(nickname)}
                </div>
                <div class="info-card">
                    <b>Всего постов:</b><br>{len(user_data['posts'])}
                </div>
                <a href="/" class="btn" style="margin-top: auto; background: #a9a9a9;">На главную</a>
            </div>

            <div class="main-content">
                <div class="posts-area" style="min-height: 500px;">
                    <h2>ПОСТЫ ПОЛЬЗОВАТЕЛЯ</h2>
                    {posts_html}
                </div>
            </div>
        </div>
    </body>
    </html>
    """

# --- МАРШРУТЫ ---

@app.get("/", response_class=HTMLResponse)
async def index(nickname: str = Cookie(None)):
    if nickname and nickname in db:
        return RedirectResponse(url="/dashboard", status_code=303)
    return auth_html

@app.post("/register")
async def register(
    username: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    re_pass: str = Form(...),
    captcha: str = Form(None) # Чекбокс
):
    if not captcha:
        return HTMLResponse("<script>alert('Подтвердите, что вы не робот!'); window.history.back();</script>")
    
    if password != re_pass:
        return HTMLResponse("<script>alert('Пароли не совпадают!'); window.history.back();</script>")
    
    if nickname in db:
        return HTMLResponse("<script>alert('Такой никнейм уже занят!'); window.history.back();</script>")
    
    db[nickname] = {"username": username, "password": password, "posts": []}
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="nickname", value=nickname, httponly=True)
    return response

@app.post("/login")
async def login(
    nickname: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(None)
):
    if not captcha:
        return HTMLResponse("<script>alert('Подтвердите, что вы не робот!'); window.history.back();</script>")
        
    user = db.get(nickname)
    if user and user["password"] == password:
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="nickname", value=nickname, httponly=True)
        return response
        
    return HTMLResponse("<script>alert('Неверный никнейм или пароль!'); window.history.back();</script>")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(nickname: str = Cookie(None)):
    if not nickname or nickname not in db:
        return RedirectResponse(url="/", status_code=303)
    return get_dashboard_html(nickname, db[nickname])

@app.post("/create_post")
async def create_post(content: str = Form(...), nickname: str = Cookie(None)):
    if not nickname or nickname not in db:
        return RedirectResponse(url="/", status_code=303)
    
    if content.strip():
        db[nickname]["posts"].append({
            "id": uuid.uuid4().hex[:8],
            "text": content.strip(),
            "pinned": False,
            "created_at": uuid.uuid1().time # Используем время создания для сортировки
        })
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/delete_post/{post_id}")
async def delete_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname or nickname not in db:
        return RedirectResponse(url="/", status_code=303)
    
    user_posts = db[nickname]["posts"]
    db[nickname]["posts"] = [p for p in user_posts if p["id"] != post_id]
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/pin_post/{post_id}")
async def pin_post(post_id: str, nickname: str = Cookie(None)):
    if not nickname or nickname not in db:
        return RedirectResponse(url="/", status_code=303)
    
    for post in db[nickname]["posts"]:
        if post["id"] == post_id:
            post["pinned"] = not post["pinned"]
            break
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("nickname")
    return response

# ВАЖНО: Динамический маршрут должен идти ПОСЛЕ статических (dashboard, logout и т.д.)
@app.get("/{nickname}", response_class=HTMLResponse)
async def public_profile(nickname: str):
    if nickname not in db:
        return HTMLResponse("<h2>Пользователь не найден. <a href='/'>На главную</a></h2>", status_code=404)
    return get_public_profile_html(nickname, db[nickname])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
