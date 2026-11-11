from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext
import uuid
from datetime import datetime

app = FastAPI(title="sol.id clone")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ==========================================
# БАЗА ДАННЫХ В ОПЕРАТИВНОЙ ПАМЯТИ
# ==========================================
users_db = {
    "admin": {"password": pwd_context.hash("admin"), "avatar": "👽", "name": "Admin"},
    "guest": {"password": pwd_context.hash("guest"), "avatar": "👾", "name": "Guest"}
}

# Сессии (токен -> username)
sessions = {}

# Посты (сгенерированы на основе скриншота)
posts_db = [
    {
        "id": "1", "author": "MIRRONAKE", "avatar": "😡",
        "title": "ОБНОВЛЕНИЕ: РЕДИЗАЙН САЙТА И ПЛАТНЫЕ ПРЕДЛОЖКИ",
        "content": "Сайт переехал на новый дизайн. Переделали почти всё...",
        "image_css": "background: linear-gradient(135deg, #1e1e1e, #2a2a2a);", # Заглушка вместо картинки
        "likes": 118, "comments": 97, "views": "3k", "time": "4 дня назад", "tag": "Текст"
    },
    {
        "id": "2", "author": "warshavskaya", "avatar": "👩",
        "title": "чаттерино W",
        "content": "#эдит на выходных внезапно пришла идея сделать чт...",
        "image_css": "background: linear-gradient(135deg, #4b0082, #8a2be2);",
        "likes": 14, "comments": 8, "views": "131", "time": "вчера в 21:54", "tag": "Видео"
    },
    {
        "id": "3", "author": "JP_1337_322", "avatar": "🕵️",
        "title": "Легендарные файлы #526",
        "content": "France meme's",
        "image_css": "background: url('https://images.unsplash.com/photo-1502602898657-3e91760cbb34?q=80&w=400&auto=format&fit=crop') center/cover;",
        "likes": 11, "comments": 0, "views": "100", "time": "вчера в 21:39", "tag": "Видео"
    },
    {
        "id": "4", "author": "vandal_k", "avatar": "🐶",
        "title": "как будет играть в гта 6",
        "content": "Ну и графика конечно...",
        "image_css": "background: linear-gradient(135deg, #333, #555);",
        "likes": 42, "comments": 12, "views": "1.2k", "time": "2 часа назад", "tag": "Видео"
    },
    {
        "id": "5", "author": "abc_894", "avatar": "🚔",
        "title": "С праздником, дорогие сотрудники",
        "content": "10 НОЯБРЯ. ДЕНЬ СОТРУДНИКА ОРГАНОВ ВНУТРЕННИХ ДЕЛ РОССИЙСКОЙ ФЕДЕРАЦИИ",
        "image_css": "background: linear-gradient(135deg, #0033cc, #ffffff, #cc0000);",
        "likes": 5, "comments": 1, "views": "500", "time": "3 часа назад", "tag": "Текст"
    },
    {
        "id": "6", "author": "Monyxoff", "avatar": "💻",
        "title": "Новый игровой компьютер",
        "content": "Потянет даже ГТА 6",
        "image_css": "background: linear-gradient(135deg, #ff00cc, #333399);",
        "likes": 88, "comments": 24, "views": "2.5k", "time": "10 минут назад", "tag": "Видео"
    }
]

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        return sessions[session_token]
    return None

# ==========================================
# HTML ШАБЛОНЫ (ВСТРОЕННЫЕ)
# ==========================================
CSS_STYLES = """
<style>
    :root {
        --bg-color: #141414;
        --card-bg: #1e1e1e;
        --text-main: #e0e0e0;
        --text-muted: #888;
        --accent-color: #8cc84b;
        --border-color: #333;
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
    .logo { font-size: 24px; font-weight: bold; color: var(--accent-color); text-decoration: none; display: flex; align-items: center; gap: 10px;}
    .search-bar {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 8px 15px;
        color: white;
        width: 400px;
        outline: none;
    }
    .btn-green {
        background-color: var(--accent-color);
        color: #000;
        border: none;
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: bold;
        cursor: pointer;
        text-decoration: none;
    }
    .btn-green:hover { opacity: 0.8; }
    .user-profile { display: flex; align-items: center; gap: 15px; }
    
    /* Main Layout */
    .container { display: flex; flex: 1; }
    .sidebar {
        width: 200px;
        padding: 20px 10px;
        border-right: 1px solid var(--border-color);
        display: flex;
        flex-direction: column;
        gap: 15px;
    }
    .sidebar a {
        color: var(--text-muted);
        text-decoration: none;
        padding: 10px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .sidebar a:hover, .sidebar a.active { color: var(--text-main); background-color: var(--card-bg); }
    
    /* Feed */
    .feed {
        flex: 1;
        padding: 20px;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 20px;
        align-content: start;
    }
    .card {
        background-color: var(--card-bg);
        border-radius: 12px;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        border: 1px solid var(--border-color);
        transition: transform 0.2s;
    }
    .card:hover { transform: translateY(-2px); }
    .card-img { height: 180px; position: relative; }
    .card-tag {
        position: absolute;
        bottom: 10px;
        right: 10px;
        background: rgba(0,0,0,0.7);
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
    .card-content { padding: 15px; display: flex; flex-direction: column; flex: 1; }
    .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 14px; color: var(--text-muted);}
    .card-title { font-size: 16px; font-weight: bold; margin: 0 0 10px 0; line-height: 1.3; }
    .card-text { font-size: 14px; color: var(--text-muted); margin-bottom: 15px; flex: 1; }
    .card-footer { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); border-top: 1px solid var(--border-color); padding-top: 10px; }
    
    /* Auth Forms */
    .auth-form {
        background-color: var(--card-bg);
        padding: 30px;
        border-radius: 12px;
        width: 300px;
        margin: 50px auto;
        border: 1px solid var(--border-color);
    }
    .auth-form h2 { margin-top: 0; text-align: center; color: var(--accent-color); }
    .auth-form input {
        width: 100%;
        padding: 10px;
        margin-bottom: 15px;
        background-color: var(--bg-color);
        border: 1px solid var(--border-color);
        border-radius: 6px;
        color: white;
        box-sizing: border-box;
    }
    .auth-form button { width: 100%; }
    .auth-links { text-align: center; margin-top: 15px; font-size: 14px; }
    .auth-links a { color: var(--accent-color); text-decoration: none; }
    .error { color: #ff5555; text-align: center; margin-bottom: 10px; font-size: 14px; }
</style>
"""

def render_layout(content_html, user):
    user_html = ""
    if user:
        user_html = f"""
        <div class="user-profile">
            <a href="/post" class="btn-green">+ Новый пост</a>
            <span>{user['avatar']} {user['name']}</span>
            <a href="/logout" style="color:var(--text-muted); text-decoration:none; font-size:14px;">Выйти</a>
        </div>
        """
    else:
        user_html = f"""
        <div class="user-profile">
            <a href="/login" style="color:white; text-decoration:none;">Вход</a>
            <a href="/register" class="btn-green">Регистрация</a>
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
        <div class="topbar">
            <a href="/" class="logo">👽 sol.id</a>
            <input type="text" class="search-bar" placeholder="Поиск">
            {user_html}
        </div>
        <div class="container">
            <div class="sidebar">
                <a href="/" class="active">🏠 Лента</a>
                <a href="#">📺 Подписки</a>
                <a href="#">🎮 Игры</a>
                <a href="#">📱 Приложения</a>
            </div>
            <div class="feed">
                {content_html}
            </div>
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
    username = user["name"] if user else None
    
    cards_html = ""
    for post in posts_db:
        cards_html += f"""
        <div class="card">
            <div class="card-img" style="{post['image_css']}">
                <span class="card-tag">▶ {post['tag']}</span>
            </div>
            <div class="card-content">
                <div class="card-header">
                    <span>{post['avatar']}</span>
                    <span>{post['author']}</span>
                </div>
                <h3 class="card-title">{post['title']}</h3>
                <p class="card-text">{post['content']}</p>
                <div class="card-footer">
                    <span>👁 {post['views']} ♡ {post['likes']} 💬 {post['comments']}</span>
                    <span>{post['time']}</span>
                </div>
            </div>
        </div>
        """
    
    return render_layout(cards_html, user)

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    return render_layout("""
        <form class="auth-form" action="/register" method="post">
            <h2>Регистрация на sol.id</h2>
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn-green">Создать аккаунт</button>
            <div class="auth-links">
                Уже есть аккаунт? <a href="/login">Войти</a>
            </div>
        </form>
    """, None)

@app.post("/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    if username in users_db:
        return render_layout("""
            <form class="auth-form" action="/register" method="post">
                <h2>Регистрация на sol.id</h2>
                <div class="error">Пользователь уже существует</div>
                <input type="text" name="username" placeholder="Логин" required>
                <input type="password" name="password" placeholder="Пароль" required>
                <button type="submit" class="btn-green">Создать аккаунт</button>
            </form>
        """, None)
    
    users_db[username] = {
        "password": pwd_context.hash(password),
        "avatar": "👤",
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
            <button type="submit" class="btn-green">Войти</button>
            <div class="auth-links">
                Нет аккаунта? <a href="/register">Зарегистрироваться</a>
            </div>
        </form>
    """, None)

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
                <button type="submit" class="btn-green">Войти</button>
            </form>
        """, None)

    # Создаем сессию
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
        <form class="auth-form" action="/post" method="post" style="width: 400px;">
            <h2>Новый пост</h2>
            <input type="text" name="title" placeholder="Заголовок" required>
            <input type="text" name="content" placeholder="Текст поста" required>
            <select name="tag" style="width: 100%; padding: 10px; margin-bottom: 15px; background: var(--bg-color); color: white; border: 1px solid var(--border-color); border-radius: 6px;">
                <option value="Текст">Текст</option>
                <option value="Видео">Видео</option>
                <option value="Картинка">Картинка</option>
            </select>
            <button type="submit" class="btn-green">Опубликовать</button>
        </form>
    """, user)

@app.post("/post")
async def create_post(request: Request, title: str = Form(...), content: str = Form(...), tag: str = Form(...)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    new_post = {
        "id": str(len(posts_db) + 1),
        "author": user["name"],
        "avatar": user["avatar"],
        "title": title,
        "content": content,
        "image_css": "background: linear-gradient(135deg, #222, #444);", # Рандомная заглушка
        "likes": 0, "comments": 0, "views": "0", "time": "Только что", "tag": tag
    }
    # Добавляем в начало списка
    posts_db.insert(0, new_post)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
