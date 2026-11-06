import uvicorn
from fastapi import FastAPI, Request, Form, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template
from typing import Optional

app = FastAPI()

# ================= БАЗА ДАННЫХ В ОПЕРАТИВКЕ =================
# { "email": {"name": "...", "surname": "...", "password": "...", "status": "..."} }
users_db = {}

# ================= ШАБЛОНЫ =================

BASE_CSS = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        background-color: #f0f0f0;
        font-family: Tahoma, Verdana, Arial, sans-serif;
        font-size: 11px;
        color: #000;
        line-height: 1.4;
        -webkit-font-smoothing: antialiased;
    }
    a { color: #2b587a; text-decoration: none; }
    a:hover { text-decoration: underline; }
    ul { list-style-position: inside; }

    /* ===== ШАПКА ===== */
    .header {
        background: #4e545a;
        height: 44px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 20px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }
    .header-logo {
        display: flex; align-items: center; color: #fff;
        font-size: 20px; font-weight: bold; letter-spacing: -0.5px;
        text-decoration: none;
    }
    .header-logo:hover { text-decoration: none; }
    .header-logo svg { width: 24px; height: 24px; margin-right: 8px; }
    .header-nav { display: flex; gap: 20px; }
    .header-nav a { color: #fff; font-size: 12px; text-decoration: none; }
    .header-nav a:hover { text-decoration: underline; }

    /* ===== ОСНОВНОЙ БЛОК ===== */
    .main-box {
        display: flex; background: #fff;
        border: 1px solid #ccc; border-top: none;
        min-height: 340px;
    }
    .left-col {
        width: 250px; border-right: 1px solid #ccc;
        padding: 15px; flex-shrink: 0;
    }
    .right-col { flex: 1; display: flex; flex-direction: column; }

    /* ===== ФОРМЫ ===== */
    .form-group { margin-bottom: 8px; }
    .form-group label { display: block; color: #666; margin-bottom: 3px; font-size: 11px; }
    .form-group input[type="text"], .form-group input[type="password"], .form-group input[type="email"], .form-group input[type="date"] {
        width: 100%; height: 24px; border: 1px solid #999; padding: 0 5px;
        font-family: inherit; font-size: 11px; outline: none;
    }
    .btn {
        display: block; width: 100%; height: 26px;
        background: linear-gradient(180deg, #a8a8a8 0%, #7a7a7a 100%);
        border: 1px solid #666; color: #fff; font-family: inherit; font-size: 11px;
        font-weight: bold; text-shadow: 0 1px 1px rgba(0,0,0,0.5);
        cursor: pointer; margin-bottom: 10px; border-radius: 2px;
    }
    .btn:hover { background: linear-gradient(180deg, #b8b8b8 0%, #8a8a8a 100%); }
    .btn:active { background: #7a7a7a; box-shadow: inset 0 2px 3px rgba(0,0,0,0.3); }
    .btn-inline { display: inline-block; width: auto; padding: 0 15px; margin: 0 5px; }

    /* ===== РЕГИСТРАЦИЯ (Контент) ===== */
    .welcome-banner { background: #fdf5d0; border-bottom: 1px solid #e3d9a7; padding: 6px 15px; font-weight: bold; font-size: 11px; }
    .welcome-content { padding: 15px; font-size: 11px; line-height: 1.6; }
    .welcome-content p { margin-bottom: 10px; }
    
    .reg-title { font-size: 16px; font-weight: bold; color: #2b587a; margin-bottom: 15px; border-bottom: 1px solid #e3e3e3; padding-bottom: 5px; }
    .reg-header-text { display: flex; align-items: flex-start; margin-bottom: 15px; }
    .reg-icon { width: 32px; height: 32px; background: #4e545a; border-radius: 4px; margin-right: 10px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
    .reg-icon svg { width: 20px; height: 20px; fill: #fff; }
    
    .reg-section-title { font-weight: bold; color: #2b587a; margin: 15px 0 10px 0; border-bottom: 1px solid #e3e3e3; padding-bottom: 3px; }
    
    .reg-form-row { display: flex; align-items: center; margin-bottom: 8px; }
    .reg-form-row label { width: 140px; text-align: right; margin-right: 10px; color: #666; font-size: 11px; }
    .reg-form-row input[type="text"], .reg-form-row input[type="email"], .reg-form-row input[type="password"], .reg-form-row input[type="date"], .reg-form-row select {
        width: 250px; height: 24px; border: 1px solid #ccc; padding: 0 5px; font-family: inherit; font-size: 11px;
    }
    .reg-form-row input:focus, .reg-form-row select:focus { border-color: #999; }
    
    .captcha-box { width: 120px; height: 40px; background: #333; display: flex; align-items: center; justify-content: center; margin-right: 10px; overflow: hidden; position: relative; }
    .captcha-text { color: #ff3333; font-family: 'Courier New', Courier, monospace; font-weight: bold; font-size: 20px; transform: scaleY(1.5) rotate(-5deg); text-shadow: 1px 1px 0 #000; }
    
    /* ===== ПОДВАЛ ===== */
    .footer { text-align: center; padding: 20px 0 40px 0; color: #666; font-size: 11px; line-height: 1.7; }
    .footer a { color: #2b587a; }
    .footer-langs { margin: 5px 0 10px 0; display: flex; justify-content: center; align-items: center; gap: 5px; }
    .flag { display: inline-block; width: 16px; height: 11px; border: 1px solid #ccc; }
    .flag-ru { background: linear-gradient(to bottom, #fff 33%, #0039a6 33%, #0039a6 66%, #d52b1e 66%); }
    .flag-by { background: linear-gradient(to bottom, #c8313e 33%, #fff 33%, #fff 66%, #c8313e 66%); }
    .flag-ua { background: linear-gradient(to bottom, #0057b7 50%, #ffd700 50%); }
    .footer-debian { margin-top: 10px; display: flex; justify-content: center; align-items: center; gap: 5px; color: #d70a53; font-weight: bold; font-size: 16px; }

    /* ===== ЛИЧНЫЙ КАБИНЕТ ===== */
    .vk-container { width: 800px; margin: 15px auto; display: flex; gap: 15px; }
    .vk-sidebar { width: 200px; flex-shrink: 0; }
    .vk-profile-card { background: #fff; border: 1px solid #d3d9de; padding: 10px; margin-bottom: 10px; }
    .vk-avatar { width: 100%; height: 180px; background: #a9bacd; border: 1px solid #b2c1d2; margin-bottom: 10px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='35' r='16' fill='%23fff' fill-opacity='0.7'/%3E%3Cellipse cx='50' cy='96' rx='32' ry='31' fill='%23fff' fill-opacity='0.7'/%3E%3C/svg%3E");
        background-size: cover; background-position: center; }
    .vk-name { font-weight: bold; font-size: 13px; color: #2b587a; margin-bottom: 3px; }
    .vk-status { font-size: 11px; color: #888; font-style: italic; margin-bottom: 5px; }
    .vk-menu { list-style: none; background: #fff; border: 1px solid #d3d9de; }
    .vk-menu li { border-bottom: 1px solid #f0f2f5; }
    .vk-menu li:last-child { border-bottom: none; }
    .vk-menu a { display: block; padding: 8px 12px; font-size: 12px; color: #2b587a; text-decoration: none; }
    .vk-menu a:hover { background: #f0f4f8; }
    .vk-menu li.active a { background: #e5ebf1; font-weight: bold; border-left: 2px solid #4e545a; padding-left: 10px; }
    .vk-menu .count { color: #999; font-size: 11px; }
    .vk-content { flex: 1; min-width: 0; }
    .vk-panel { background: #fff; border: 1px solid #d3d9de; margin-bottom: 15px; }
    .vk-panel-head { background: #f0f2f5; border-bottom: 1px solid #e2e7ec; padding: 8px 15px; font-weight: bold; color: #2b587a; font-size: 12px; }
    .vk-panel-body { padding: 15px; }
    .vk-info-row { display: flex; margin-bottom: 6px; font-size: 12px; }
    .vk-info-row .k { width: 130px; color: #888; }
    .vk-post { display: flex; padding: 15px; border-bottom: 1px solid #f0f2f5; }
    .vk-post:last-child { border-bottom: none; }
    .vk-post-ava { width: 40px; height: 40px; border-radius: 2px; flex-shrink: 0; background-color: #c9d6e3; margin-right: 10px; }
    .vk-post-content { flex: 1; }
    .vk-post-author { font-weight: bold; color: #2b587a; font-size: 12px; margin-bottom: 2px; }
    .vk-post-date { color: #999; font-weight: normal; font-size: 11px; }
    .vk-post-text { font-size: 12px; margin-bottom: 8px; }
    .vk-post-actions { font-size: 11px; color: #888; }
    .vk-post-actions a { color: #2b587a; margin-right: 8px; }
    .vk-post-input { padding: 15px; background: #fafafa; }
    .vk-post-input textarea { width: 100%; height: 50px; border: 1px solid #ccc; padding: 5px; font-family: inherit; font-size: 12px; resize: vertical; margin-bottom: 8px; outline: none; }
    .vk-btn { background: #5e82a8; border: 1px solid #3f6895; color: #fff; padding: 5px 15px; font-size: 11px; cursor: pointer; border-radius: 2px; font-weight: bold; font-family: inherit; }
    .vk-btn:hover { background: #6d92b8; }
    
    .vk-header-bar { background: #4e545a; height: 42px; display: flex; align-items: center; padding: 0 20px; color: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.2); }
    .vk-header-bar .logo { font-size: 18px; font-weight: bold; margin-right: 20px; color: #fff; text-decoration: none; display: flex; align-items: center; }
    .vk-header-bar .logo svg { width: 20px; height: 20px; margin-right: 6px; }
    .vk-header-bar .search { width: 200px; height: 22px; border: 1px solid #3b3f43; padding: 0 5px; font-family: inherit; font-size: 11px; background: #fff; }
    .vk-header-bar .right-menu { margin-left: auto; font-size: 12px; }
    .vk-header-bar .right-menu a { color: #fff; margin-left: 15px; text-decoration: none; }
    
    .error-msg { color: #d00; font-size: 11px; margin-bottom: 10px; background: #ffe6e6; padding: 5px; border: 1px solid #fcc; display: none; }
    .error-msg.show { display: block; }
</style>
"""

HEADER_HTML = """
<div class="header">
    <a href="/" class="header-logo">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="11" fill="#d17128"/>
            <circle cx="12" cy="12" r="8" fill="#fff"/>
            <circle cx="12" cy="12" r="5" fill="#d17128"/>
        </svg>
        OpenVK
    </a>
    <div class="header-nav">
        <a href="/">вход</a>
        <a href="/register">регистрация</a>
        <a href="#" onclick="alert('Раздел помощи в разработке')">помощь</a>
    </div>
</div>
"""

FOOTER_HTML = """
<div class="footer">
    <a href="#">об инстанции</a> &nbsp; <a href="#">правила</a> &nbsp; <a href="#">блог</a> &nbsp; <a href="#">помощь</a> &nbsp; <a href="#">разработчикам</a> &nbsp; <a href="#">приватность</a>
    <div class="footer-langs">
        <span class="flag flag-ru"></span> <span class="flag flag-by"></span> <span class="flag flag-ua"></span> &nbsp; <a href="#">all languages »</a>
    </div>
    <div>OpenVK Altair Preview (839745a-nightly) | PHP: 8.4.27 | DB: 8.0.34-26</div>
    <div>OpenVK является любительской разработкой и никак не связан с ВКонтакте и компанией ООО "ВК"</div>
    <div style="margin-top: 5px;">время подавать напитки и вершить судьбы</div>
    <div style="margin-top: 5px;"><a href="#">Mastodon</a> | <a href="#">Telegram</a> | <a href="#">GitHub</a> | <a href="#">Discord</a> | <a href="#">Email</a></div>
    <div class="footer-debian">
        <svg viewBox="0 0 100 100" width="24" height="24">
            <path d="M46,18 C52,16 60,18 64,24 C68,30 69,38 66,46 C66,46 67,49 68,53 C69,57 68,62 65,65 C61,68 55,67 52,63 C49,59 48,53 49,47 C51,41 55,36 55,30 C55,25 51,21 46,18 Z" fill="#d70a53"/>
            <path d="M50,15 C48,14 45,14 42,16 C35,20 30,30 32,40 C34,50 42,58 52,62 C62,66 73,65 80,60 C87,55 92,45 90,35 C88,25 80,17 70,15 C63,13 55,14 50,15 Z M52,18 C58,18 65,20 70,24 C76,28 80,35 80,42 C80,50 75,57 68,61 C60,65 50,65 43,61 C36,57 30,50 30,42 C30,34 35,26 42,22 C45,19 49,18 52,18 Z" fill="#d70a53"/>
            <path d="M55,35 C58,35 60,38 60,40 C60,43 57,45 55,45 C52,45 50,42 50,40 C50,37 52,35 55,35 Z" fill="#d70a53"/>
        </svg>
        debian <span style="font-size: 10px; color: #666; font-weight: normal; margin-top: 5px;">POWERED</span>
    </div>
    <div style="margin-top: 5px;">Хостинг предоставлен провайдером <a href="#">Senko Digital</a></div>
</div>
"""

# ================= ШАБЛОНЫ СТРАНИЦ =================

LOGIN_PAGE = Template(BASE_CSS + """
<div style="display: flex; flex-direction: column; align-items: center; padding-top: 20px;">
    <div style="width: 780px;">
        """ + HEADER_HTML + """
        <div class="main-box">
            <div class="left-col">
                <form action="/login" method="POST">
                    <div class="error-msg {{ 'show' if error else '' }}">{{ error if error else '' }}</div>
                    <div class="form-group">
                        <label>Электронная почта:</label>
                        <input type="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label>Пароль:</label>
                        <input type="password" name="password" required>
                    </div>
                    <button type="submit" class="btn">Войти</button>
                    <a href="/register" class="btn" style="text-align: center; line-height: 24px; text-decoration: none;">Регистрация</a>
                    <a href="#" onclick="alert('Восстановление пароля в разработке')" style="display: inline-block; margin-top: 5px; color: #2b587a;">Забыли пароль?</a>
                </form>
            </div>
            <div class="right-col">
                <div class="welcome-banner">Добро пожаловать</div>
                <div class="welcome-content">
                    <p><b>OpenVK - универсальное средство поиска коллег основанное на структуре ВКонтакте.</b><br>
                    Мы хотим, чтобы друзья, однокурсники, одноклассники, соседи и коллеги всегда могли быть в контакте.<br>
                    С помощью этого сайта Вы можете:</p>
                    <ul>
                        <li>Найти людей, с которыми Вы когда-либо учились, работали или отдыхали.</li>
                        <li>Узнать больше о людях, которые Вас окружают, и найти новых друзей.</li>
                        <li>Всегда оставаться в контакте с теми, кто Вам дорог.</li>
                        <li>Продвигать своё творчество и/или мнение.</li>
                    </ul>
                    <div style="width: 250px; margin: 10px auto; background: #fdf5d0; border: 1px solid #e3d9a7; text-align: center; padding: 8px;">
                        <b>Экскурсия по сайту</b><br><span style="color: #555; font-size: 10px;">О том, что Вас ждет после регистрации</span>
                    </div>
                </div>
                <div style="text-align: center; padding-bottom: 15px; margin-top: auto;">
                    <a href="/login" class="btn btn-inline" onclick="document.forms[0].submit(); return false;">Войти</a>
                    <a href="/register" class="btn btn-inline" style="text-decoration: none; line-height: 24px;">Регистрация</a>
                </div>
            </div>
        </div>
    </div>
    """ + FOOTER_HTML + """
</div>
""")

REGISTER_PAGE = Template(BASE_CSS + """
<div style="display: flex; flex-direction: column; align-items: center; padding-top: 20px;">
    <div style="width: 780px;">
        """ + HEADER_HTML + """
        <div class="main-box">
            <!-- Левая колонка (как на скрине) -->
            <div class="left-col">
                <form action="/login" method="POST">
                    <div class="form-group">
                        <label>Электронная почта:</label>
                        <input type="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label>Пароль:</label>
                        <input type="password" name="password" required>
                    </div>
                    <button type="submit" class="btn">Войти</button>
                    <a href="/register" class="btn" style="text-align: center; line-height: 24px; text-decoration: none;">Регистрация</a>
                    <a href="#" onclick="alert('Восстановление пароля в разработке')" style="display: inline-block; margin-top: 5px; color: #2b587a;">Забыли пароль?</a>
                </form>
            </div>
            
            <!-- Правая колонка (Форма регистрации) -->
            <div class="right-col">
                <div class="welcome-banner">Регистрация</div>
                <div class="welcome-content">
                    <div class="reg-title">Регистрация</div>
                    
                    <div class="reg-header-text">
                        <div class="reg-icon">
                            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <circle cx="12" cy="12" r="11" fill="#fff"/>
                                <circle cx="12" cy="12" r="8" fill="#4e545a"/>
                                <circle cx="12" cy="12" r="5" fill="#fff"/>
                            </svg>
                        </div>
                        <div>
                            <b>OpenVK - универсальное средство поиска коллег основанное на структуре ВКонтакте.</b><br>
                            Мы хотим, чтобы друзья, однокурсники, одноклассники, соседи и коллеги всегда могли быть в контакте.
                        </div>
                    </div>

                    <form action="/register" method="POST">
                        <div class="error-msg {{ 'show' if error else '' }}">{{ error if error else '' }}</div>
                        
                        <div class="reg-section-title">Основное</div>
                        
                        <div class="reg-form-row">
                            <label>Имя:</label>
                            <input type="text" name="name" required>
                        </div>
                        <div class="reg-form-row">
                            <label>Фамилия:</label>
                            <input type="text" name="surname" required>
                        </div>
                        <div class="reg-form-row">
                            <label>Электронная почта:</label>
                            <input type="email" name="email" required>
                        </div>
                        <div class="reg-form-row">
                            <label>Пароль:</label>
                            <input type="password" name="password" required>
                        </div>

                        <div class="reg-section-title">Остальное</div>
                        
                        <div class="reg-form-row">
                            <label>День рождения:</label>
                            <input type="date" name="birthday">
                        </div>
                        <div class="reg-form-row">
                            <label>Местоположение:</label>
                            <select name="location">
                                <option value="он его">он его</option>
                                <option value="Москва">Москва</option>
                                <option value="Санкт-Петербург">Санкт-Петербург</option>
                                <option value="Новосибирск">Новосибирск</option>
                            </select>
                        </div>
                        
                        <!-- Капча -->
                        <div class="reg-form-row">
                            <label>CAPTCHA:</label>
                            <div class="captcha-box">
                                <span class="captcha-text">ЕВРАЗ1</span>
                            </div>
                            <input type="text" name="captcha" placeholder="Enter 8 characters" required style="width: 150px;">
                        </div>

                        <div class="reg-form-row" style="margin-top: 15px;">
                            <label></label>
                            <div style="display: flex; align-items: center; width: 250px;">
                                <input type="checkbox" name="agree" required style="margin-right: 5px;">
                                <span>Я согласен с политикой конфиденциальности и правилами сайта</span>
                            </div>
                        </div>

                        <div class="reg-form-row" style="margin-top: 15px;">
                            <label></label>
                            <button type="submit" class="btn" style="width: 120px; margin: 0;">Регистрация</button>
                        </div>
                    </form>

                </div>
            </div>
        </div>
    </div>
    """ + FOOTER_HTML + """
</div>
""")

PROFILE_PAGE = Template(BASE_CSS + """
<div class="vk-header-bar">
    <a href="/profile" class="logo">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="11" fill="#d17128"/>
            <circle cx="12" cy="12" r="8" fill="#fff"/>
            <circle cx="12" cy="12" r="5" fill="#d17128"/>
        </svg>
        OpenVK
    </a>
    <input type="text" class="search" placeholder="Поиск">
    <div class="right-menu">
        <a href="/profile" style="font-weight:bold;">{{ user.name }} {{ user.surname }}</a>
        <a href="/logout">Выход</a>
    </div>
</div>

<div class="vk-container">
    <div class="vk-sidebar">
        <div class="vk-profile-card">
            <div class="vk-avatar"></div>
            <div class="vk-name">{{ user.name }} {{ user.surname }}</div>
            <div class="vk-status">Всем привет! :)</div>
            <a href="#" class="vk-edit-link" style="font-size: 10px; color: #999;">изменить статус</a>
        </div>
        
        <ul class="vk-menu">
            <li class="active"><a href="/profile">Моя страница</a></li>
            <li><a href="#" onclick="alert('Друзья: заглушка')">Друзья <span class="count">24</span></a></li>
            <li><a href="#" onclick="alert('Фотографии: заглушка')">Фотографии <span class="count">112</span></a></li>
            <li><a href="#" onclick="alert('Аудиозаписи: заглушка')">Аудиозаписи</a></li>
            <li><a href="#" onclick="alert('Сообщения: заглушка')">Сообщения <span class="count">3</span></a></li>
            <li><a href="#" onclick="alert('Настройки: заглушка')">Настройки</a></li>
        </ul>
    </div>

    <div class="vk-content">
        <div class="vk-panel">
            <div class="vk-panel-head">Моя страница</div>
            <div class="vk-panel-body">
                <div class="vk-info-row"><div class="k">Пол:</div><div class="v">мужской</div></div>
                <div class="vk-info-row"><div class="k">День рождения:</div><div class="v">{{ user.birthday or 'Не указан' }}</div></div>
                <div class="vk-info-row"><div class="k">Местоположение:</div><div class="v">{{ user.location or 'Не указано' }}</div></div>
                <div class="vk-info-row"><div class="k">Email:</div><div class="v">{{ user.email }}</div></div>
                <div class="vk-info-row"><div class="k">О себе:</div><div class="v">Люблю старые интерфейсы, OpenVK и хорошую музыку.</div></div>
            </div>
        </div>

        <div class="vk-panel">
            <div class="vk-panel-head">Стена</div>
            
            <div class="vk-post">
                <div class="vk-post-ava" style="background-color:#8fa8c4;"></div>
                <div class="vk-post-content">
                    <div class="vk-post-author">{{ user.name }} {{ user.surname }} <span class="vk-post-date">15 июн 2010 в 14:32</span></div>
                    <div class="vk-post-text">Наконец-то разобрался с вёрсткой. OpenVK — это что-то невероятное, всё летает :)</div>
                    <div class="vk-post-actions"><a href="#" onclick="alert('Лайк!')">Мне нравится</a> 12 &nbsp;·&nbsp; <a href="#" onclick="alert('Комментарий')">Комментировать</a> 4</div>
                </div>
            </div>

            <div class="vk-post">
                <div class="vk-post-ava" style="background-color:#c99aa6;"></div>
                <div class="vk-post-content">
                    <div class="vk-post-author">Анна Смирнова <span class="vk-post-date">14 июн 2010 в 21:05</span></div>
                    <div class="vk-post-text">Кто идёт завтра на концерт? Собираемся у метро в семь!</div>
                    <div class="vk-post-actions"><a href="#" onclick="alert('Лайк!')">Мне нравится</a> 7 &nbsp;·&nbsp; <a href="#" onclick="alert('Комментарий')">Комментировать</a> 2</div>
                </div>
            </div>

            <div class="vk-post-input">
                <textarea placeholder="Что у вас нового?" id="wallText"></textarea>
                <button class="vk-btn" onclick="alert('Пост отправлен (имитация): ' + document.getElementById('wallText').value); document.getElementById('wallText').value='';">Отправить</button>
            </div>
        </div>
    </div>
</div>
""")


# ================= РОУТЫ =================

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    # Если уже авторизован - редирект в профиль
    if request.cookies.get("session_user"):
        return RedirectResponse(url="/profile", status_code=303)
    return LOGIN_PAGE.render(error=error)

@app.post("/login")
async def do_login(email: str = Form(...), password: str = Form(...)):
    user = users_db.get(email)
    if not user or user["password"] != password:
        return RedirectResponse(url="/?error=Неверный+email+или+пароль", status_code=303)
    
    response = RedirectResponse(url="/profile", status_code=303)
    response.set_cookie(key="session_user", value=email, httponly=True)
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: Optional[str] = None):
    return REGISTER_PAGE.render(error=error)

@app.post("/register")
async def do_register(
    name: str = Form(...), 
    surname: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...),
    birthday: str = Form(""),
    location: str = Form(""),
    captcha: str = Form(...),
    agree: str = Form(None)
):
    if email in users_db:
        return RedirectResponse(url="/register?error=Пользователь+с+таким+email+уже+существует", status_code=303)
    
    if not agree:
        return RedirectResponse(url="/register?error=Необходимо+согласиться+с+правилами", status_code=303)
        
    if captcha.lower() != "евраз1":
        return RedirectResponse(url="/register?error=Неверная+CAPTCHA", status_code=303)

    # Сохраняем в оперативку
    users_db[email] = {
        "name": name,
        "surname": surname,
        "email": email,
        "password": password,
        "birthday": birthday,
        "location": location,
        "status": "Всем привет! :)"
    }
    
    # Автоматический вход после регистрации
    response = RedirectResponse(url="/profile", status_code=303)
    response.set_cookie(key="session_user", value=email, httponly=True)
    return response

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    session_email = request.cookies.get("session_user")
    if not session_email or session_email not in users_db:
        return RedirectResponse(url="/", status_code=303)
    
    user = users_db[session_email]
    return PROFILE_PAGE.render(user=user)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session_user")
    return response


if __name__ == "__main__":
    print("Сервер запущен! Открой в браузере: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
