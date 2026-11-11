from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext
import uuid

app = FastAPI(title="sol.id clone")

# ИСПРАВЛЕНИЕ ОШИБКИ: Используем pbkdf2_sha256 вместо bcrypt, чтобы избежать ошибки 72 байт
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ==========================================
# БАЗА ДАННЫХ В ОПЕРАТИВНОЙ ПАМЯТИ
# ==========================================
# Фейковые посты убраны
posts_db = []

# Добавлен дефолтный пользователь для теста (логин: admin, пароль: admin)
users_db = {
    "admin": {"password": pwd_context.hash("admin"), "name": "Admin"}
}

# Сессии (токен -> username)
sessions = {}

# ==========================================
# SVG ИКОНКИ (Вместо эмодзи)
# ==========================================
SVG_LOGO = """<svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM11 7H13V13H11V7ZM11 15H13V17H11V15Z" fill="#3b82f6"/></svg>"""
SVG_AVATAR = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 12C14.21 12 16 10.21 16 8C16 5.79 14.21 4 12 4C9.79 4 8 5.79 8 8C8 10.21 9.79 12 12 12ZM12 14C9.33 14 4 15.34 4 18V20H20V18C20 15.34 14.67 14 12 14Z" fill="#a1a1aa"/></svg>"""

SVG_FEED = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>"""
SVG_SUBS = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>"""
SVG_GAMES = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="12" x2="10" y2="12"></line><line x1="8" y1="10" x2="8" y2="14"></line><line x1="15" y1="13" x2="15.01" y2="13"></line><line x1="18" y1="11" x2="18.01" y2="11"></line><rect x="2" y="6" width="20" height="12" rx="2"></rect></svg>"""
SVG_APPS = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect></svg>"""
SVG_PLUS = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>"""
SVG_BELL = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>"""
SVG_USER = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
SVG_SEARCH = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>"""

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        return sessions[session_token]
    return None

# ==========================================
# HTML ШАБЛОНЫ И CSS
# ==========================================
CSS_STYLES = """
<style>
    :root {
        --bg-color: #0f0f0f;
        --card-bg: #1c1c1c;
        --text-main: #f3f3f3;
        --text-muted: #888;
        --accent-color: #3b82f6; /* Синий цвет вместо зеленого */
        --border-color: #2a2a2a;
    }
    body {
        background-color: var(--bg-color);
        color: var(--text-main);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        min-height: 100vh;
        padding-bottom: 60px; /* Место для мобильной навигации */
    }
    /* Topbar */
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 20px;
        border-bottom: 1px solid var(--border-color);
        background-color: var(--bg-color);
        position: sticky;
        top: 0;
        z-index: 100;
    }
    .logo { font-size: 22px; font-weight: bold; color: var(--text-main); text-decoration: none; display: flex; align-items: center; gap: 8px;}
    .search-container {
        display: flex;
        align-items: center;
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 0 10px;
        width: 300px;
    }
    .search-container svg { color: var(--text-muted); }
    .search-bar {
        background-color: transparent;
        border: none;
        padding: 8px 10px;
        color: white;
        outline: none;
        width: 100%;
    }
    .btn-primary {
        background-color: var(--accent-color);
        color: #fff;
        border: none;
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: bold;
        cursor: pointer;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .btn-primary:hover { opacity: 0.8; }
    
    /* Main Layout */
    .container { display: flex; flex: 1; }
    
    /* Sidebar (Desktop) */
    .sidebar {
        width: 220px;
        padding: 20px 10px;
        border-right: 1px solid var(--border-color);
        display: flex;
        flex-direction: column;
        gap: 5px;
        position: sticky;
        top: 60px;
        height: calc(100vh - 60px);
    }
    .sidebar a {
        color: var(--text-muted);
        text-decoration: none;
        padding: 12px 15px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 15px;
        font-weight: 500;
    }
    .sidebar a:hover, .sidebar a.active { color: var(--text-main); background-color: var(--card-bg); }
    .sidebar a.active svg { color: var(--accent-color); }
    
    /* Feed */
    .feed {
        flex: 1;
        padding: 20px;
        max-width: 800px; /* Ограничиваем ширину на больших экранах */
        margin: 0 auto;
    }
    .feed-header {
        display: flex;
        gap: 20px;
        margin-bottom: 20px;
        border-bottom: 1px solid var(--border-color);
        padding-bottom: 10px;
    }
    .feed-header a { color: var(--text-muted); text-decoration: none; font-size: 16px; font-weight: 500; }
    .feed-header a.active { color: var(--text-main); border-bottom: 2px solid var(--accent-color); padding-bottom: 9px; }
    
    .empty-state {
        text-align: center;
        padding: 50px 20px;
        color: var(--text-muted);
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px dashed var(--border-color);
    }
    .empty-state h3 { color: var(--text-main); margin-bottom: 10px; }

    /* Cards (для будущих постов) */
    .card {
        background-color: var(--card-bg);
        border-radius: 12px;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        border: 1px solid var(--border-color);
        margin-bottom: 15px;
    }
    .card-content { padding: 15px; }
    .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 14px; color: var(--text-muted);}
    .card-title { font-size: 16px; font-weight: bold; margin: 0 0 10px 0; }
    .card-text { font-size: 14px; color: var(--text-muted); }
    
    /* Auth Forms */
    .auth-form {
        background-color: var(--card-bg);
        padding: 30px;
        border-radius: 12px;
        width: 100%;
        max-width: 350px;
        margin: 40px auto;
        border: 1px solid var(--border-color);
        box-sizing: border-box;
    }
    .auth-form h2 { margin-top: 0; text-align: center; color: var(--text-main); }
    .auth-form input {
        width: 100%;
        padding: 12px;
        margin-bottom: 15px;
        background-color: var(--bg-color);
        border: 1px solid var(--border-color);
        border-radius: 6px;
        color: white;
        box-sizing: border-box;
    }
    .auth-form button { width: 100%; justify-content: center; }
    .auth-links { text-align: center; margin-top: 15px; font-size: 14px; color: var(--text-muted); }
    .auth-links a { color: var(--accent-color); text-decoration: none; }
    .error { color: #ff5555; text-align: center; margin-bottom: 15px; font-size: 14px; }

    /* Bottom Navigation (Mobile) */
    .bottom-nav {
        display: none;
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: var(--bg-color);
        border-top: 1px solid var(--border-color);
        justify-content: space-around;
        align-items: center;
        padding: 10px 0;
        z-index: 100;
    }
    .bottom-nav a {
        color: var(--text-muted);
        text-decoration: none;
        display: flex;
        flex-direction: column;
        align-items: center;
        font-size: 10px;
        gap: 4px;
    }
    .bottom-nav a.active { color: var(--accent-color); }
    .bottom-nav .plus-btn {
        background-color: var(--accent-color);
        color: white;
        padding: 10px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transform: translateY(-10px); /* Приподнимаем кнопку */
        box-shadow: 0 4px 10px rgba(59, 130, 246, 0.4);
    }
    .bottom-nav .plus-btn svg { width: 28px; height: 28px; }
    
    /* Media Queries (Телефоны) */
    @media (max-width: 768px) {
        .sidebar { display: none; }
        .bottom-nav { display: flex; }
        .search-container { display: none; /* Скрываем поиск на мобилках */ }
        .topbar { padding: 10px 15px; }
        .feed { padding: 15px; }
        .auth-form { margin: 20px auto; }
        .desktop-btn { display: none; } /* Скрываем кнопку "Новый пост" в топбаре */
    }
</style>
"""

def render_layout(content_html, user, active_page="feed"):
    user_html = ""
    if user:
        user_html = f"""
        <div style="display: flex; align-items: center; gap: 15px;">
            <a href="/post" class="btn-primary desktop-btn">{SVG_PLUS} Новый пост</a>
            <div style="display: flex; align-items: center; gap: 8px;">
                {SVG_AVATAR} <span>{user['name']}</span>
            </div>
            <a href="/logout" style="color:var(--text-muted); text-decoration:none; font-size:14px;">Выйти</a>
        </div>
        """
    else:
        user_html = f"""
        <div style="display: flex; gap: 15px; align-items: center;">
            <a href="/login" style="color:var(--text-main); text-decoration:none; font-weight: 500;">Вход</a>
            <a href="/register" class="btn-primary">Регистрация</a>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>sol.id</title>
        {CSS_STYLES}
    </head>
    <body>
        <div class="topbar">
            <a href="/" class="logo">{SVG_LOGO} sol.id</a>
            <div class="search-container">
                {SVG_SEARCH}
                <input type="text" class="search-bar" placeholder="Поиск">
            </div>
            {user_html}
        </div>
        
        <div class="container">
            <div class="sidebar">
                <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
                <a href="#">{SVG_SUBS} Подписки</a>
                <a href="#">{SVG_GAMES} Игры</a>
                <a href="#">{SVG_APPS} Приложения</a>
            </div>
            <div class="feed">
                {content_html}
            </div>
        </div>

        <!-- Мобильная навигация -->
        <div class="bottom-nav">
            <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
            <a href="#">{SVG_SUBS} Подписки</a>
            <a href="/post" class="plus-btn">{SVG_PLUS}</a>
            <a href="#">{SVG_BELL} Уведомления</a>
            <a href="/login" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} Профиль</a>
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
    
    # Хедер ленты (Все / Подписки)
    feed_header = f"""
    <div class="feed-header">
        <a href="/" class="active">Все</a>
        <a href="#">Подписки</a>
    </div>
    """
    
    if not posts_db:
        # Пустое состояние, если нет постов
        content_html = feed_header + """
        <div class="empty-state">
            <h3>Здесь пока пусто</h3>
            <p>Станьте первым, кто опубликует пост на sol.id!</p>
        </div>
        """
    else:
        # Рендер постов (когда они появятся)
        cards_html = ""
        for post in posts_db:
            cards_html += f"""
            <div class="card">
                <div class="card-content">
                    <div class="card-header">
                        {SVG_AVATAR}
                        <span>{post['author']}</span>
                        <span style="margin-left: auto;">{post['time']}</span>
                    </div>
                    <h3 class="card-title">{post['title']}</h3>
                    <p class="card-text">{post['content']}</p>
                </div>
            </div>
            """
        content_html = feed_header + cards_html
    
    return render_layout(content_html, user)

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    return render_layout("""
        <form class="auth-form" action="/register" method="post">
            <h2>Регистрация на sol.id</h2>
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn-primary">Создать аккаунт</button>
            <div class="auth-links">
                Уже есть аккаунт? <a href="/login">Войти</a>
            </div>
        </form>
    """, None, "profile")

@app.post("/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    if username in users_db:
        return render_layout("""
            <form class="auth-form" action="/register" method="post">
                <h2>Регистрация на sol.id</h2>
                <div class="error">Пользователь уже существует</div>
                <input type="text" name="username" placeholder="Логин" required>
                <input type="password" name="password" placeholder="Пароль" required>
                <button type="submit" class="btn-primary">Создать аккаунт</button>
            </form>
        """, None, "profile")
    
    # Хешируем пароль безопасным алгоритмом pbkdf2_sha256
    users_db[username] = {
        "password": pwd_context.hash(password),
        "name": username
    }
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_layout("""
        <form class="auth-form" action="/login" method="post">
            <h2>Вход в sol.id</h2>
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn-primary">Войти</button>
            <div class="auth-links">
                Нет аккаунта? <a href="/register">Зарегистрироваться</a>
            </div>
        </form>
    """, None, "profile")

@app.post("/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users_db.get(username)
    if not user or not pwd_context.verify(password, user["password"]):
        return render_layout("""
            <form class="auth-form" action="/login" method="post">
                <h2>Вход в sol.id</h2>
                <div class="error">Неверный логин или пароль</div>
                <input type="text" name="username" placeholder="Логин" required>
                <input type="password" name="password" placeholder="Пароль" required>
                <button type="submit" class="btn-primary">Войти</button>
            </form>
        """, None, "profile")

    session_token = str(uuid.uuid4())
    sessions[session_token] = username
    
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="session_token", value=session_token, httponly=True)
    return response

@app.get("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token in sessions:
        del sessions[session_token]
    
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

@app.get("/post", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    return render_layout("""
        <form class="auth-form" action="/post" method="post">
            <h2>Новый пост</h2>
            <input type="text" name="title" placeholder="Заголовок" required>
            <input type="text" name="content" placeholder="Текст поста" required>
            <button type="submit" class="btn-primary">Опубликовать</button>
        </form>
    """, user, "profile")

@app.post("/post")
async def create_post(request: Request, title: str = Form(...), content: str = Form(...)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    new_post = {
        "id": str(len(posts_db) + 1),
        "author": user["name"],
        "title": title,
        "content": content,
        "time": "Только что"
    }
    # Добавляем в начало списка
    posts_db.insert(0, new_post)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
