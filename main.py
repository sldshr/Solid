from fastapi import FastAPI, Form, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import html

app = FastAPI()

# База данных в оперативке
# Структура: { "nickname": { "username": "...", "password": "...", "posts": ["post1", "post2"] } }
db = {}

# --- CSS СТИЛИ (ОБЩИЕ) ---
common_css = """
<style>
    body {
        font-family: Arial, sans-serif;
        background-color: #f4f4f4;
        margin: 0;
        padding: 20px;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        box-sizing: border-box;
    }
    .container {
        background: white;
        padding: 40px;
        border: 10px solid #e0e0e0;
        display: flex;
        gap: 40px;
        align-items: flex-start;
    }
    /* Стили для логина/регистрации */
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
    input, button, textarea {
        background-color: #a9a9a9;
        border: none;
        padding: 12px;
        font-size: 24px;
        font-family: Arial, sans-serif;
        width: 100%;
        text-align: center;
        box-sizing: border-box;
        outline: none;
    }
    button { cursor: pointer; color: black; font-weight: bold; }
    button:hover { background-color: #8c8c8c; }
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
    
    /* Стили для личного кабинета */
    .dashboard-container {
        display: flex;
        gap: 20px;
        width: 100%;
        max-width: 1200px;
        margin: 0 auto;
    }
    .sidebar {
        background: black;
        padding: 10px;
        width: 350px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .sidebar h2 { color: white; text-align: center; font-size: 32px; margin: 10px 0; }
    .info-card {
        background: #a9a9a9;
        padding: 20px;
        font-size: 24px;
        text-align: center;
        word-wrap: break-word;
    }
    .logout-btn { margin-top: auto; background: #ff4d4d; padding: 15px; font-size: 24px;}
    .logout-btn:hover { background: #cc0000; }
    
    .main-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 20px;
    }
    .create-post-box {
        background: black;
        padding: 5px;
        display: flex;
        flex-direction: column;
        gap: 5px;
        height: 200px;
    }
    .create-post-box textarea {
        height: 100%;
        resize: none;
        text-align: left;
        font-size: 18px;
        padding: 10px;
    }
    .create-post-box button { height: 60px; font-size: 24px; }
    
    .posts-area {
        background: black;
        padding: 20px;
        min-height: 300px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .posts-area h2 { color: white; font-size: 32px; margin: 0 0 10px 0; text-align: center;}
    .post-item {
        background: #a9a9a9;
        padding: 15px;
        font-size: 20px;
        word-wrap: break-word;
    }
    .error-msg { color: red; font-size: 20px; text-align: center; margin-top: 10px;}
</style>
"""

# --- HTML ШАБЛОНЫ ---

auth_html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Login / Reg</title>
    {common_css}
    <script>
        function togglePassword(inputId) {{
            const input = document.getElementById(inputId);
            if (input.type === "password") {{
                input.type = "text";
            }} else {{
                input.type = "password";
            }}
        }}
    </script>
</head>
<body>
    <div class="container">
        <div class="auth-wrapper">
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
                    
                    <input type="text" name="captcha" placeholder="captcha" required>
                    <button type="submit">Register!</button>
                </form>
            </div>
            <div class="label-text">reg</div>
        </div>

        <div class="auth-wrapper login-wrapper">
            <div class="form-box">
                <form action="/login" method="post">
                    <input type="text" name="nickname" placeholder="nickname" required>
                    
                    <div class="input-group">
                        <input type="password" name="password" id="log-pass" placeholder="password" required>
                        <button type="button" class="eye-btn" onclick="togglePassword('log-pass')">👁</button>
                    </div>
                    
                    <input type="text" name="captcha" placeholder="captcha" required>
                    <button type="submit">Login</button>
                </form>
            </div>
            <div class="label-text">Login</div>
        </div>
    </div>
</body>
</html>
"""

def get_dashboard_html(user_nickname: str, user_data: dict):
    posts_html = ""
    if not user_data["posts"]:
        posts_html = "<div class='post-item'>У вас пока нет постов...</div>"
    else:
        for post in reversed(user_data["posts"]): # Новые сверху
            safe_post = html.escape(post)
            posts_html += f"<div class='post-item'>{safe_post}</div>"

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Личный кабинет</title>
        {common_css}
    </head>
    <body>
        <div class="dashboard-container">
            <!-- Левая панель: Информация -->
            <div class="sidebar">
                <h2>ПРОФИЛЬ</h2>
                <div class="info-card">
                    <b>Username:</b><br>{html.escape(user_data['username'])}
                </div>
                <div class="info-card">
                    <b>Nickname:</b><br>{html.escape(user_nickname)}
                </div>
                <div class="info-card">
                    <b>Всего постов:</b><br>{len(user_data['posts'])}
                </div>
                <form action="/logout" method="get" style="margin: 0; width: 100%;">
                    <button type="submit" class="logout-btn">Выйти</button>
                </form>
            </div>

            <!-- Правая панель: Посты -->
            <div class="main-content">
                <!-- Создание поста -->
                <div class="create-post-box">
                    <form action="/create_post" method="post" style="height: 100%; display: flex; flex-direction: column;">
                        <textarea name="content" placeholder="Напишите что-нибудь..." required maxlength="500"></textarea>
                        <button type="submit">Создать пост</button>
                    </form>
                </div>

                <!-- Список постов -->
                <div class="posts-area">
                    <h2>МОИ ПОСТЫ</h2>
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
    # Если уже залогинен, редирект в кабинет
    if nickname and nickname in db:
        return RedirectResponse(url="/dashboard", status_code=303)
    return auth_html

@app.post("/register")
async def register(
    username: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    re_pass: str = Form(...),
    captcha: str = Form(...)
):
    if password != re_pass:
        return HTMLResponse("<script>alert('Пароли не совпадают!'); window.history.back();</script>")
    
    if nickname in db:
        return HTMLResponse("<script>alert('Такой никнейм уже занят!'); window.history.back();</script>")
    
    # Сохраняем в оперативку и добавляем пустой список постов
    db[nickname] = {"username": username, "password": password, "posts": []}
    
    # Устанавливаем куки и редиректим
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="nickname", value=nickname, httponly=True)
    return response

@app.post("/login")
async def login(
    nickname: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(...)
):
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
    
    user_data = db[nickname]
    return get_dashboard_html(nickname, user_data)

@app.post("/create_post")
async def create_post(content: str = Form(...), nickname: str = Cookie(None)):
    if not nickname or nickname not in db:
        return RedirectResponse(url="/", status_code=303)
    
    # Сохраняем пост
    if content.strip():
        db[nickname]["posts"].append(content.strip())
        
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("nickname")
    return response

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
