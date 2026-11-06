from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

# База данных в оперативной памяти (словарь: nickname -> {username, password})
db = {}

# HTML + CSS шаблон
html_content = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Login / Reg</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .main-container {
            display: flex;
            gap: 40px;
            align-items: flex-start;
            background: white;
            padding: 40px;
            border: 10px solid #e0e0e0;
        }
        .form-wrapper {
            display: flex;
            gap: 20px;
        }
        .form-wrapper.login-wrapper {
            align-items: flex-end;
        }
        .form-box {
            background-color: black;
            padding: 5px;
            display: flex;
            flex-direction: column;
            gap: 5px;
            border: 2px solid #ccc;
        }
        .form-box form {
            display: flex;
            flex-direction: column;
            gap: 5px;
            margin: 0;
        }
        input, button {
            background-color: #a9a9a9;
            border: none;
            padding: 12px;
            font-size: 28px;
            font-family: Arial, sans-serif;
            width: 280px;
            text-align: center;
            box-sizing: border-box;
            outline: none;
        }
        button {
            cursor: pointer;
            color: black;
        }
        button:hover {
            background-color: #8c8c8c;
        }
        .label-text {
            font-size: 48px;
            font-weight: normal;
            margin-bottom: 10px;
        }
        .login-label {
            margin-bottom: 10px;
        }
        .result-box {
            position: absolute;
            top: 20px;
            padding: 20px;
            background: white;
            border: 2px solid black;
            font-size: 24px;
        }
    </style>
</head>
<body>

    <div class="main-container">
        <!-- Блок регистрации -->
        <div class="form-wrapper">
            <div class="form-box">
                <form action="/register" method="post">
                    <input type="text" name="username" placeholder="username" required>
                    <input type="text" name="nickname" placeholder="nickname" required>
                    <input type="password" name="password" placeholder="password" required>
                    <input type="password" name="re_pass" placeholder="re enter pass" required>
                    <input type="text" name="captcha" placeholder="captcha" required>
                    <button type="submit">Register!</button>
                </form>
            </div>
            <div class="label-text">reg</div>
        </div>

        <!-- Блок логина -->
        <div class="form-wrapper login-wrapper">
            <div class="form-box">
                <form action="/login" method="post">
                    <input type="text" name="nickname" placeholder="nickname" required>
                    <input type="password" name="password" placeholder="password" required>
                    <input type="text" name="captcha" placeholder="captcha" required>
                    <button type="submit">Login</button>
                </form>
            </div>
            <div class="label-text login-label">Login</div>
        </div>
    </div>

</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return html_content

@app.post("/register", response_class=HTMLResponse)
async def register(
    username: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    re_pass: str = Form(...),
    captcha: str = Form(...)
):
    if password != re_pass:
        return "<div class='result-box'>Пароли не совпадают! <a href='/'>Назад</a></div>"
    
    if nickname in db:
        return "<div class='result-box'>Такой никнейм уже занят! <a href='/'>Назад</a></div>"
    
    # Сохраняем в оперативку
    db[nickname] = {"username": username, "password": password}
    return f"<div class='result-box'>Успешная регистрация, {username}! <a href='/'>Войти</a></div>"

@app.post("/login", response_class=HTMLResponse)
async def login(
    nickname: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(...)
):
    user = db.get(nickname)
    
    if user and user["password"] == password:
        return f"<div class='result-box'>Привет, {user['username']}! Вы вошли. <a href='/'>Назад</a></div>"
    
    return "<div class='result-box'>Неверный никнейм или пароль. <a href='/'>Назад</a></div>"

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
