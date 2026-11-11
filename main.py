from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext
import uuid
import base64
from typing import List, Optional

app = FastAPI(title="sol.id")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ==========================================
# БАЗА ДАННЫХ В ОПЕРАТИВНОЙ ПАМЯТИ
# ==========================================
users_db = {} 
sessions = {} 
posts_db = [] 

# Создаем дефолтного админа для входа
users_db["admin"] = {
    "username": "admin",
    "password": pwd_context.hash("admin"),
    "display_name": "Administrator",
    "avatar": None,
    "banner": None
}

# ==========================================
# SVG ИКОНКИ
# ==========================================
SVG_LOGO = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM11 7H13V13H11V7ZM11 15H13V17H11V15Z" fill="#8cc84b"/></svg>"""
SVG_FEED = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>"""
SVG_PLUS = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>"""
SVG_USER = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
SVG_EYE = """<svg id="eye-open" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>"""
SVG_EYE_OFF = """<svg id="eye-closed" style="display:none;" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>"""
SVG_BACK = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>"""
SVG_IMAGE = """<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>"""

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        username = sessions[session_token]
        return users_db.get(username)
    return None

async def image_to_base64(file: UploadFile):
    if not file or not file.filename: return None
    contents = await file.read()
    return f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"

# ==========================================
# CSS СТИЛИ (CSS GRID + PIXEL FONTS)
# ==========================================
CSS_STYLES = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
    :root {
        --bg-color: #0f0f0f; --card-bg: #1c1c1c; --text-main: #f3f3f3; --text-muted: #888;
        --accent-color: #8cc84b; --border-color: #2a2a2a;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Pixelify Sans', sans-serif; }
    body { background-color: var(--bg-color); color: var(--text-main); display: flex; flex-direction: column; min-height: 100vh; }
    a { color: var(--accent-color); text-decoration: none; }
    
    /* Layout Grid */
    .app-layout {
        display: grid;
        grid-template-columns: 200px 1fr;
        grid-template-rows: 60px 1fr;
        height: 100vh;
        width: 100%;
    }
    
    /* Topbar */
    .topbar {
        grid-column: 1 / -1;
        display: flex; justify-content: space-between; align-items: center;
        padding: 0 20px; border-bottom: 1px solid var(--border-color);
        background-color: var(--bg-color); z-index: 100;
    }
    .logo { font-size: 20px; font-weight: bold; color: var(--text-main); display: flex; align-items: center; gap: 8px; }
    .btn-primary {
        background-color: var(--accent-color); color: #000; border: none; padding: 8px 16px;
        border-radius: 6px; font-weight: bold; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
        font-size: 14px;
    }
    .btn-primary:hover { opacity: 0.8; }
    .user-nav { display: flex; align-items: center; gap: 15px; font-size: 14px; }
    
    /* Sidebar */
    .sidebar {
        grid-column: 1; grid-row: 2; border-right: 1px solid var(--border-color);
        padding: 20px 10px; display: flex; flex-direction: column; gap: 5px;
        overflow-y: auto;
    }
    .sidebar a {
        color: var(--text-muted); padding: 10px 15px; border-radius: 6px;
        display: flex; align-items: center; gap: 12px; font-size: 16px;
    }
    .sidebar a:hover, .sidebar a.active { color: var(--text-main); background-color: var(--card-bg); }
    .sidebar a.active svg { color: var(--accent-color); }
    
    /* Main Content */
    .main-content {
        grid-column: 2; grid-row: 2; padding: 20px; overflow-y: auto; display: flex; flex-direction: column;
    }
    
    /* Auth Forms */
    .auth-container { display: flex; justify-content: center; align-items: center; flex: 1; }
    .auth-form { background-color: var(--card-bg); padding: 30px; border-radius: 12px; width: 100%; max-width: 400px; border: 1px solid var(--border-color); }
    .auth-form h2 { text-align: center; margin-bottom: 20px; font-weight: 500; }
    .input-group { margin-bottom: 15px; position: relative; }
    .input-group input, .input-group textarea {
        width: 100%; padding: 12px; background-color: var(--bg-color); border: 1px solid var(--border-color);
        border-radius: 6px; color: white; font-size: 16px; outline: none;
    }
    .input-group input:focus { border-color: var(--accent-color); }
    .pass-toggle { position: absolute; right: 12px; top: 14px; cursor: pointer; color: var(--text-muted); }
    .checkbox-group { display: flex; gap: 10px; align-items: center; margin-bottom: 20px; font-size: 14px; color: var(--text-muted); }
    .error { color: #ff5555; text-align: center; margin-bottom: 15px; font-size: 14px; }
    
    /* Profile */
    .profile-header { position: relative; margin-bottom: 20px; border-radius: 12px; overflow: hidden; background: var(--card-bg); }
    .profile-banner { width: 100%; height: 200px; background: #2a2a2a; object-fit: cover; display: block; }
    .profile-info { display: flex; gap: 20px; padding: 0 20px 20px 20px; margin-top: -50px; align-items: flex-end; }
    .profile-avatar { width: 100px; height: 100px; border-radius: 50%; border: 4px solid var(--card-bg); object-fit: cover; background: #333; }
    .profile-details { flex: 1; }
    .profile-details h1 { font-size: 24px; margin-bottom: 5px; font-weight: 500; }
    .profile-details p { color: var(--text-muted); font-size: 14px; }
    
    /* Post View */
    .post-view { display: flex; gap: 20px; background: var(--card-bg); border-radius: 12px; padding: 20px; border: 1px solid var(--border-color); flex-wrap: wrap; margin-bottom: 20px; }
    .post-media { flex: 2; min-width: 300px; background: #000; border-radius: 8px; display: flex; align-items: center; justify-content: center; overflow: hidden; position: relative; }
    .post-media img { max-width: 100%; max-height: 70vh; object-fit: contain; }
    .post-details { flex: 1; min-width: 300px; display: flex; flex-direction: column; }
    .post-author { display: flex; align-items: center; gap: 10px; margin-bottom: 15px; }
    .post-author img { width: 40px; height: 40px; border-radius: 50%; }
    .post-title { font-size: 22px; font-weight: 500; margin-bottom: 10px; }
    .post-desc { color: var(--text-muted); font-size: 15px; margin-bottom: 20px; white-space: pre-wrap; }
    .post-actions { display: flex; gap: 15px; margin-bottom: 20px; color: var(--text-muted); font-size: 14px; }
    .comments-section { flex: 1; overflow-y: auto; border-top: 1px solid var(--border-color); padding-top: 15px; }
    
    /* Feed Grid */
    .feed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 15px; }
    .feed-card { background: var(--card-bg); border-radius: 12px; overflow: hidden; border: 1px solid var(--border-color); display: flex; flex-direction: column; }
    .feed-card img { width: 100%; height: 160px; object-fit: cover; }
    .feed-card-info { padding: 12px; }
    .feed-card-title { font-weight: 500; font-size: 16px; margin-bottom: 5px; }
    .feed-card-author { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 5px; }
    
    /* Upload Area */
    .upload-area { border: 2px dashed var(--border-color); border-radius: 12px; padding: 40px; text-align: center; cursor: pointer; margin-bottom: 20px; color: var(--text-muted); display: block; }
    .upload-area:hover { border-color: var(--accent-color); }
    .upload-area input[type="file"] { display: none; }

    /* Mobile Nav */
    .bottom-nav { display: none; position: fixed; bottom: 0; left: 0; width: 100%; background: var(--bg-color); border-top: 1px solid var(--border-color); justify-content: space-around; padding: 10px 0; z-index: 100; }
    .bottom-nav a { display: flex; flex-direction: column; align-items: center; font-size: 10px; color: var(--text-muted); gap: 4px; }
    .bottom-nav a.active { color: var(--accent-color); }
    .bottom-nav .plus-btn { background: var(--accent-color); color: #000; padding: 10px; border-radius: 50%; transform: translateY(-15px); box-shadow: 0 4px 10px rgba(140, 200, 75, 0.4); }

    @media (max-width: 768px) {
        .app-layout { grid-template-columns: 1fr; grid-template-rows: 60px 1fr; }
        .sidebar { display: none; }
        .main-content { grid-column: 1; }
        .bottom-nav { display: flex; }
        .topbar .user-nav span, .topbar .btn-primary span { display: none; }
        .post-view { flex-direction: column; padding: 15px; }
        .profile-banner { height: 120px; }
        .profile-avatar { width: 80px; height: 80px; }
        .main-content { padding-bottom: 80px; }
    }
</style>
<script>
    function togglePassword(id) {
        var input = document.getElementById(id);
        var eyeOpen = document.getElementById('eye-open-' + id);
        var eyeClosed = document.getElementById('eye-closed-' + id);
        if (input.type === "password") {
            input.type = "text";
            eyeOpen.style.display = "none";
            eyeClosed.style.display = "block";
        } else {
            input.type = "password";
            eyeOpen.style.display = "block";
            eyeClosed.style.display = "none";
        }
    }
    function updateFileName(input) {
        if (input.files.length > 0) {
            document.getElementById('file-count').innerText = 'Выбрано файлов: ' + input.files.length;
        }
    }
</script>
"""

# ==========================================
# LAYOUT
# ==========================================
def render_layout(content_html, user, active_page="feed"):
    avatar_url = user.get('avatar') if user and user.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username'] if user else 'guest'}"
    
    if user:
        nav_html = f"""
        <div class="user-nav">
            <a href="/write" class="btn-primary">{SVG_PLUS} <span>Новый пост</span></a>
            <a href="/@{user['username']}" style="display:flex; align-items:center; gap:8px; color:#fff;">
                <img src="{avatar_url}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;">
                <span>{user['display_name']}</span>
            </a>
            <a href="/logout" style="color:var(--text-muted);">Выйти</a>
        </div>
        """
    else:
        nav_html = f"""
        <div class="user-nav">
            <a href="/login" style="color:var(--text-main);">Вход</a>
            <a href="/register" class="btn-primary">Регистрация</a>
        </div>
        """

    sidebar_html = ""
    if user:
        sidebar_html = f"""
        <div class="sidebar">
            <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
            <a href="/@{user['username']}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} Профиль</a>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>sol.id</title>
        {CSS_STYLES}
    </head>
    <body>
        <div class="app-layout">
            <div class="topbar">
                <a href="/" class="logo">{SVG_LOGO} sol.id</a>
                {nav_html}
            </div>
            {sidebar_html}
            <div class="main-content" style="{'grid-column: 1 / -1;' if not user else ''}">
                {content_html}
            </div>
        </div>
        
        <div class="bottom-nav">
            <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
            <a href="/write" class="plus-btn">{SVG_PLUS}</a>
            <a href="/@{user['username'] if user else 'login'}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} Профиль</a>
        </div>
    </body>
    </html>
    """

# ==========================================
# МАРШРУТЫ
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def read_feed(request: Request):
    user = get_current_user(request)
    
    if not posts_db:
        content = """
        <div style="text-align:center; padding: 60px 20px; color: var(--text-muted);">
            <h3 style="font-size: 24px; color: #fff; margin-bottom: 10px;">Здесь пока пусто</h3>
            <p>Станьте первым, кто опубликует пост!</p>
        </div>
        """
    else:
        cards = ""
        for post in posts_db:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="height:160px; background:#222; display:flex; align-items:center; justify-content:center;">{SVG_IMAGE}</div>'
            
            cards += f"""
            <a href="/post/{post['id']}" class="feed-card">
                {img_html}
                <div class="feed-card-info">
                    <div class="feed-card-title">{post['title']}</div>
                    <div class="feed-card-author"><img src="{ava}" style="width:20px;height:20px;border-radius:50%;"> @{post['author']}</div>
                </div>
            </a>
            """
        content = f'<div class="feed-grid">{cards}</div>'
        
    # Принудительно отдаем HTMLResponse
    return HTMLResponse(content=render_layout(content, user, "feed"))

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    content = f"""
    <div class="auth-container">
        <form class="auth-form" action="/register" method="post">
            <h2>Регистрация</h2>
            <div class="input-group"><input type="text" name="username" placeholder="Логин (для /@login)" required></div>
            <div class="input-group"><input type="text" name="display_name" placeholder="Отображаемое имя" required></div>
            <div class="input-group">
                <input type="password" id="pass1" name="password" placeholder="Пароль" required>
                <span class="pass-toggle" onclick="togglePassword('pass1')">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <div class="input-group">
                <input type="password" id="pass2" name="confirm_password" placeholder="Подтвердите пароль" required>
                <span class="pass-toggle" onclick="togglePassword('pass2')">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <div class="checkbox-group">
                <input type="checkbox" id="privacy" name="privacy" required>
                <label for="privacy">Я согласен с <a href="#">политикой конфиденциальности</a>.</label>
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center;">Создать аккаунт</button>
            <div style="text-align:center; margin-top:15px; font-size:14px;">Уже есть аккаунт? <a href="/login">Войти</a></div>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, None))

@app.post("/register")
async def register_user(username: str = Form(...), display_name: str = Form(...), password: str = Form(...), confirm_password: str = Form(...)):
    if username in users_db:
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Пользователь уже существует</div><a href="/register" class="btn-primary">Назад</a></div></div>', None))
    if password != confirm_password:
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Пароли не совпадают</div><a href="/register" class="btn-primary">Назад</a></div></div>', None))
    
    users_db[username] = {
        "username": username,
        "password": pwd_context.hash(password),
        "display_name": display_name,
        "avatar": None,
        "banner": None
    }
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = f"""
    <div class="auth-container">
        <form class="auth-form" action="/login" method="post">
            <h2>Вход</h2>
            <div class="input-group"><input type="text" name="username" placeholder="Логин" required></div>
            <div class="input-group">
                <input type="password" id="pass1" name="password" placeholder="Пароль" required>
                <span class="pass-toggle" onclick="togglePassword('pass1')">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center;">Войти</button>
            <div style="text-align:center; margin-top:15px; font-size:14px;">Нет аккаунта? <a href="/register">Создать</a></div>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, None))

@app.post("/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users_db.get(username)
    if not user or not pwd_context.verify(password, user["password"]):
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Неверный логин или пароль</div><a href="/login" class="btn-primary">Назад</a></div></div>', None))

    session_token = str(uuid.uuid4())
    sessions[session_token] = username
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="session_token", value=session_token, httponly=True)
    return response

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token in sessions: del sessions[token]
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

@app.get("/write", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    content = f"""
    <div style="max-width: 800px; margin: 0 auto; width: 100%;">
        <h2 style="margin-bottom: 20px; font-weight: 500;">Новый пост</h2>
        <form action="/write" method="post" enctype="multipart/form-data" style="display:flex; gap:20px; flex-wrap:wrap;">
            <div style="flex:1; min-width:300px;">
                <label class="upload-area" for="file-upload">
                    {SVG_IMAGE}
                    <div style="margin-top:15px; font-weight:500; color:#fff;">Перетащите файлы сюда</div>
                    <div style="font-size:14px; margin-top:5px;">JPEG, PNG, GIF до 5 штук</div>
                    <div id="file-count" style="margin-top:15px; color:var(--accent-color); font-weight:bold;"></div>
                    <input id="file-upload" type="file" name="images" multiple accept="image/*" onchange="updateFileName(this)">
                </label>
            </div>
            <div style="flex:1; min-width:300px; background:var(--card-bg); padding:20px; border-radius:12px; border:1px solid var(--border-color);">
                <div class="input-group">
                    <label style="font-size:14px; color:var(--text-muted); margin-bottom:5px; display:block;">Название *</label>
                    <input type="text" name="title" placeholder="Как назовёте пост" required>
                </div>
                <div class="input-group">
                    <label style="font-size:14px; color:var(--text-muted); margin-bottom:5px; display:block;">Описание</label>
                    <textarea name="content" placeholder="Пара слов о том, что тут, можно с #тегами" style="min-height:150px; resize:vertical;"></textarea>
                </div>
                <button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:12px;">Опубликовать</button>
            </div>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "feed"))

@app.post("/write")
async def create_post(request: Request, title: str = Form(...), content: str = Form(...), images: List[UploadFile] = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    img_b64_list = []
    if images and images[0].filename:
        for img in images[:5]: 
            b64 = await image_to_base64(img)
            if b64: img_b64_list.append(b64)
            
    new_post = {
        "id": str(uuid.uuid4())[:8],
        "author": user["username"],
        "title": title,
        "content": content,
        "images": img_b64_list,
        "likes": 0,
        "comments": []
    }
    posts_db.insert(0, new_post)
    return RedirectResponse(url=f"/post/{new_post['id']}", status_code=status.HTTP_302_FOUND)

@app.get("/post/{post_id}", response_class=HTMLResponse)
async def view_post(request: Request, post_id: str):
    user = get_current_user(request)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post:
        raise HTTPException(404, "Post not found")
        
    author = users_db.get(post['author'])
    ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
    
    if post['images']:
        media_html = "".join([f'<img src="{img}" style="max-width:100%; max-height:70vh; object-fit:contain; display:{"" if i==0 else "none"};" class="carousel-img">' for i, img in enumerate(post['images'])])
        if len(post['images']) > 1:
            media_html += f"""
            <div style="position:absolute; bottom:15px; left:0; width:100%; display:flex; justify-content:center; gap:10px;">
                <button onclick="prevImg()" class="btn-primary" style="padding:5px 15px;">&lt;</button>
                <button onclick="nextImg()" class="btn-primary" style="padding:5px 15px;">&gt;</button>
            </div>
            <script>
                let currentImg = 0; let imgs = document.querySelectorAll('.carousel-img');
                function showImg(idx) {{ imgs.forEach((img, i) => img.style.display = i === idx ? 'block' : 'none'); }}
                function nextImg() {{ currentImg = (currentImg + 1) % imgs.length; showImg(currentImg); }}
                function prevImg() {{ currentImg = (currentImg - 1 + imgs.length) % imgs.length; showImg(currentImg); }}
            </script>
            """
    else:
        media_html = SVG_IMAGE

    content = f"""
    <div style="margin-bottom:20px;">
        <a href="/" style="display:flex; align-items:center; gap:10px; color:var(--text-muted);">{SVG_BACK} Назад в ленту</a>
    </div>
    <div class="post-view">
        <div class="post-media">
            {media_html}
        </div>
        <div class="post-details">
            <div class="post-author">
                <img src="{ava}">
                <div>
                    <div style="font-weight:500;">{author['display_name'] if author else post['author']}</div>
                    <div style="font-size:12px; color:var(--text-muted);">@{post['author']}</div>
                </div>
            </div>
            <div class="post-title">{post['title']}</div>
            <div class="post-desc">{post['content']}</div>
            
            <div class="post-actions">
                <span style="display:flex; align-items:center; gap:5px;">♥ {post['likes']}</span>
                <span style="display:flex; align-items:center; gap:5px;">💬 {len(post['comments'])}</span>
            </div>
            
            <div class="comments-section">
                <h3 style="margin-bottom:15px; font-weight:500;">Комментарии</h3>
                <div style="background:var(--bg-color); padding:10px; border-radius:6px; margin-bottom:20px; border: 1px solid var(--border-color);">
                    <input type="text" placeholder="Напишите комментарий..." style="width:100%; background:transparent; border:none; color:#fff; outline:none; font-size:14px;">
                </div>
                <div style="font-size:14px; color:var(--text-muted);">Пока нет комментариев.</div>
            </div>
        </div>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "feed"))

@app.get("/@{username}", response_class=HTMLResponse)
async def view_profile(request: Request, username: str):
    current_user = get_current_user(request)
    profile_user = users_db.get(username)
    if not profile_user:
        raise HTTPException(404, "User not found")
        
    ava = profile_user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
    banner = profile_user.get('banner') or "https://images.unsplash.com/photo-1579546929518-9e396f3cc809?q=80&w=1000&auto=format&fit=crop"
    
    user_posts = [p for p in posts_db if p['author'] == username]
    posts_html = ""
    for post in user_posts:
        img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="height:160px; background:#222; display:flex; align-items:center; justify-content:center;">{SVG_IMAGE}</div>'
        posts_html += f"""
        <a href="/post/{post['id']}" class="feed-card">
            {img_html}
            <div class="feed-card-info">
                <div class="feed-card-title">{post['title']}</div>
            </div>
        </a>
        """
        
    if not posts_html:
        posts_html = '<div style="color:var(--text-muted);">Пока нет постов.</div>'

    edit_btn = f'<a href="/edit_profile" class="btn-primary" style="background:#333; color:#fff;">Редактировать профиль</a>' if current_user and current_user['username'] == username else ''

    content = f"""
    <div class="profile-header">
        <img src="{banner}" class="profile-banner">
        <div class="profile-info">
            <img src="{ava}" class="profile-avatar">
            <div class="profile-details">
                <h1>{profile_user['display_name']}</h1>
                <p>@{username}</p>
                <p style="margin-top:5px; font-size:12px;">{len(user_posts)} постов</p>
            </div>
            <div>{edit_btn}</div>
        </div>
    </div>
    
    <div style="border-bottom: 1px solid var(--border-color); margin-bottom: 20px; display:flex; gap:20px;">
        <a href="#" style="color:#fff; padding-bottom:10px; border-bottom:2px solid var(--accent-color); font-size:16px;">Посты</a>
    </div>
    
    <div class="feed-grid">
        {posts_html}
    </div>
    """
    return HTMLResponse(content=render_layout(content, current_user, "profile"))

@app.get("/edit_profile", response_class=HTMLResponse)
async def edit_profile_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    content = f"""
    <div style="max-width: 600px; margin: 0 auto; background: var(--card-bg); padding: 30px; border-radius: 12px; border: 1px solid var(--border-color); width: 100%;">
        <h2 style="margin-bottom:20px; font-weight:500;">Редактор профиля</h2>
        <form action="/edit_profile" method="post" enctype="multipart/form-data">
            <div class="input-group">
                <label style="font-size:14px; color:var(--text-muted); margin-bottom:5px; display:block;">Отображаемое имя</label>
                <input type="text" name="display_name" value="{user['display_name']}" required>
            </div>
            <div class="input-group">
                <label style="font-size:14px; color:var(--text-muted); margin-bottom:5px; display:block;">Аватарка (JPEG/PNG)</label>
                <input type="file" name="avatar" accept="image/*" style="padding: 8px;">
            </div>
            <div class="input-group">
                <label style="font-size:14px; color:var(--text-muted); margin-bottom:5px; display:block;">Баннер (JPEG/PNG)</label>
                <input type="file" name="banner" accept="image/*" style="padding: 8px;">
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; margin-top:10px;">Сохранить</button>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "profile"))

@app.post("/edit_profile")
async def edit_profile(request: Request, display_name: str = Form(...), avatar: UploadFile = File(None), banner: UploadFile = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    users_db[user['username']]['display_name'] = display_name
    
    if avatar and avatar.filename:
        users_db[user['username']]['avatar'] = await image_to_base64(avatar)
    if banner and banner.filename:
        users_db[user['username']]['banner'] = await image_to_base64(banner)
        
    return RedirectResponse(url=f"/@{user['username']}", status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
