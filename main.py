from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from passlib.context import CryptContext
import uuid
import base64
from typing import List

app = FastAPI()
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

users_db = {} 
sessions = {} 
posts_db = [] 

admin_pwd = pwd_context.hash("admin")
users_db["admin"] = {"username": "admin", "password": admin_pwd, "display_name": "Administrator", "avatar": None, "saved_posts": []}

TRANSLATIONS = {
    "en": {
        "feed": "Feed", "saved": "Saved", "profile": "Profile", "settings": "Settings", "logout": "Logout", "login": "Login",
        "new_post": "New Post", "search_placeholder": "Search...", "title": "Title", "description": "Description", "publish": "Publish",
        "visibility": "Who can see", "in_feed": "In Feed", "by_link": "By Link", "upload_hint": "Drop files here or click to upload",
        "upload_limit": "JPEG, PNG up to 3 images", "back": "Back to feed", "comments": "Comments", "no_comments": "No comments yet.",
        "write_comment": "Write a comment...", "send": "Send", "edit_profile": "Edit Profile", "display_name": "Display Name",
        "avatar": "Avatar", "save": "Save", "username": "Username", "password": "Password", "login_hint": "If user doesn't exist, Display Name is required for registration",
        "save_post": "Save post", "copy_link": "Copy link", "delete": "Delete", "no_posts": "No posts yet", "posts": "posts",
        "search_results": "Search results", "nothing_found": "Nothing found", "no_saved": "You have no saved posts",
        "wrong_pass": "Wrong password", "need_name": "Display name is required for registration", "choose_files": "Choose files",
        "allow_comments": "Allow comments", "comments_disabled": "Comments are disabled for this post", "edit_post": "Edit Post",
        "remove_saved": "Remove from saved", "delete_comment": "Delete comment", "edit": "Edit", "update": "Update",
        "404_title": "Page Not Found", "404_desc": "The page you are looking for does not exist.", "login_to_comment": "Please log in to leave a comment",
        "logout_confirm": "Are you sure you want to logout?", "delete_confirm": "Are you sure you want to delete this post?",
        "crop_avatar": "Crop Avatar", "zoom": "Zoom", "change_avatar": "Change Avatar", "cancel": "Cancel", "apply": "Apply"
    },
    "ru": {
        "feed": "Лента", "saved": "Избранное", "profile": "Профиль", "settings": "Настройки", "logout": "Выйти", "login": "Вход",
        "new_post": "Новый пост", "search_placeholder": "Поиск...", "title": "Название", "description": "Описание", "publish": "Опубликовать",
        "visibility": "Кто увидит", "in_feed": "Все, в ленте", "by_link": "По ссылке", "upload_hint": "Перетащите файлы сюда или нажмите для загрузки",
        "upload_limit": "JPEG, PNG до 3 штук", "back": "Назад в ленту", "comments": "Комментарии", "no_comments": "Пока нет комментариев.",
        "write_comment": "Напишите комментарий...", "send": "Отправить", "edit_profile": "Редактировать профиль", "display_name": "Отображаемое имя",
        "avatar": "Аватарка", "save": "Сохранить", "username": "Логин", "password": "Пароль", "login_hint": "Если аккаунта нет, введите имя для регистрации",
        "save_post": "Сохранить пост", "copy_link": "Скопировать ссылку", "delete": "Удалить", "no_posts": "Пока нет постов", "posts": "постов",
        "search_results": "Результаты поиска", "nothing_found": "Ничего не найдено", "no_saved": "У вас пока нет избранных постов",
        "wrong_pass": "Неверный пароль", "need_name": "Для регистрации нужно указать имя", "choose_files": "Выбрать файлы",
        "allow_comments": "Разрешить комментарии", "comments_disabled": "Комментарии отключены", "edit_post": "Редактировать пост",
        "remove_saved": "Убрать из избранного", "delete_comment": "Удалить комментарий", "edit": "Редактировать", "update": "Обновить",
        "404_title": "Страница не найдена", "404_desc": "Страница, которую вы ищете, не существует.", "login_to_comment": "Пожалуйста, войдите, чтобы оставить комментарий",
        "logout_confirm": "Вы уверены, что хотите выйти?", "delete_confirm": "Вы уверены, что хотите удалить этот пост?",
        "crop_avatar": "Настройка аватарки", "zoom": "Приближение", "change_avatar": "Изменить аватарку", "cancel": "Отмена", "apply": "Применить"
    }
}

def get_lang(request: Request):
    lang = request.cookies.get("lang", "ru")
    return lang if lang in TRANSLATIONS else "ru"

def t(key, lang):
    return TRANSLATIONS[lang].get(key, key)

SVG_LOGO = """<svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM15.5 11H8.5V13H15.5V11Z" fill="#3b82f6"/></svg>"""
SVG_FAVICON = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22><path d=%22M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM15.5 11H8.5V13H15.5V11Z%22 fill=%22%233b82f6%22/></svg>"
SVG_UP = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>"""
SVG_DOWN = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>"""
SVG_FEED = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>"""
SVG_PLUS = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>"""
SVG_USER = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
SVG_SETTINGS = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>"""
SVG_LOGOUT = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>"""
SVG_EYE = """<svg class="eye-open" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>"""
SVG_EYE_OFF = """<svg class="eye-closed" style="display:none;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>"""
SVG_BACK = """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>"""
SVG_IMAGE = """<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>"""
SVG_SAVE = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_SAVED = """<svg width="20" height="20" viewBox="0 0 24 24" fill="#3b82f6" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_LINK = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>"""
SVG_TRASH = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>"""
SVG_SEARCH = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>"""
SVG_LANG = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>"""
SVG_MENU = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>"""
SVG_CAMERA = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>"""

def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        return users_db.get(sessions[session_token])
    return None

async def image_to_base64(file: UploadFile):
    if not file or not file.filename: return None
    contents = await file.read()
    return f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"

@app.get("/manifest.json")
async def get_manifest():
    return JSONResponse({"name": "sol-id", "short_name": "sol-id", "start_url": "/", "display": "standalone", "background_color": "#0a0a0a", "theme_color": "#3b82f6", "icons": [{"src": SVG_FAVICON, "sizes": "192x192", "type": "image/svg+xml"}]})

@app.get("/sw.js")
async def get_sw():
    return Response(content="self.addEventListener('install',e=>{self.skipWaiting()});self.addEventListener('fetch',e=>{e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});", media_type="application/javascript")

CSS_STYLES = """
<link rel="icon" type="image/svg+xml" href=\"""" + SVG_FAVICON + """\">
<link rel="manifest" href="/manifest.json">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>
    :root { --bg-color: #0a0a0a; --card-bg: #151515; --text-main: #f8fafc; --text-muted: #94a3b8; --accent-color: #3b82f6; --border-color: #262626; --danger-color: #ef4444; }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: var(--bg-color); }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Manrope', sans-serif; user-select: none; }
    input, textarea, .selectable { user-select: text; }
    body { background-color: var(--bg-color); color: var(--text-main); display: flex; flex-direction: column; min-height: 100vh; font-size: 16px; overflow: hidden; }
    a { color: var(--accent-color); text-decoration: none; }
    .app-layout { display: grid; grid-template-columns: 260px 1fr; grid-template-rows: 70px 1fr; height: 100vh; width: 100%; transition: grid-template-columns 0.3s; }
    .app-layout.sidebar-collapsed { grid-template-columns: 80px 1fr; }
    .topbar { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; padding: 0 25px; border-bottom: 1px solid var(--border-color); background-color: var(--bg-color); z-index: 100; gap: 20px; }
    .topbar-left { display: flex; align-items: center; gap: 15px; width: 260px; flex-shrink: 0; transition: width 0.3s; overflow: hidden; }
    .app-layout.sidebar-collapsed .topbar-left { width: 80px; }
    .logo { font-size: 22px; font-weight: 700; color: var(--text-main); display: flex; align-items: center; gap: 10px; white-space: nowrap; flex-shrink: 0; }
    .logo svg { flex-shrink: 0; }
    .logo span { transition: opacity 0.2s; }
    .app-layout.sidebar-collapsed .logo span { opacity: 0; width: 0; display: none; }
    .menu-toggle { cursor: pointer; padding: 8px; color: var(--text-muted); border-radius: 6px; display: flex; align-items: center; justify-content: center; transition: background 0.2s; flex-shrink: 0; margin: 0; }
    .menu-toggle:hover { background: var(--card-bg); color: var(--text-main); }
    .menu-toggle svg { display: block; }
    .topbar-center { flex: 1; display: flex; justify-content: center; position: relative; }
    .search-container { width: 100%; max-width: 500px; position: relative; }
    .search-input { width: 100%; background: var(--card-bg); border: 1px solid var(--border-color); padding: 10px 15px 10px 40px; border-radius: 8px; color: #fff; font-size: 15px; outline: none; }
    .search-input:focus { border-color: var(--accent-color); }
    .search-icon { position: absolute; left: 12px; top: 10px; color: var(--text-muted); }
    .search-dropdown { display: none; position: absolute; top: 50px; left: 0; width: 100%; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); z-index: 150; max-height: 300px; overflow-y: auto; }
    .search-dropdown-item { display: flex; align-items: center; gap: 10px; padding: 10px 15px; color: var(--text-main); border-bottom: 1px solid var(--border-color); transition: background 0.2s; }
    .search-dropdown-item:hover { background: #2a2a2a; }
    .topbar-right { display: flex; align-items: center; justify-content: flex-end; gap: 15px; width: 260px; flex-shrink: 0; }
    .btn-primary { background-color: var(--accent-color); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; font-size: 15px; transition: opacity 0.2s; }
    .btn-primary:hover { opacity: 0.9; }
    .user-menu-container { position: relative; }
    .user-menu-btn { display: flex; align-items: center; gap: 12px; cursor: pointer; padding: 4px; border-radius: 50%; border: none; outline: none; }
    .user-menu-btn:focus { outline: none; box-shadow: none; }
    .user-menu-btn:hover { background: var(--card-bg); }
    .user-avatar-small { width: 36px; height: 36px; border-radius: 50% !important; object-fit: cover; background: #333; display: block; border: none; outline: none; }
    .dropdown-menu { display: none; position: absolute; right: 0; top: 50px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; width: 240px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); z-index: 200; overflow: hidden; }
    .dropdown-header { padding: 15px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border-color); }
    .dropdown-header img { width: 44px; height: 44px; border-radius: 50% !important; object-fit: cover; }
    .dropdown-header div { display: flex; flex-direction: column; }
    .dropdown-header .name { font-weight: 700; font-size: 15px; }
    .dropdown-header .login { font-size: 13px; color: var(--text-muted); }
    .dropdown-item { display: flex; align-items: center; gap: 12px; padding: 14px 15px; color: var(--text-main); font-size: 15px; }
    .dropdown-item:hover { background: #2a2a2a; }
    .dropdown-item.danger { color: var(--danger-color); border-top: 1px solid var(--border-color); }
    .sidebar { grid-column: 1; grid-row: 2; border-right: 1px solid var(--border-color); padding: 20px 15px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; transition: padding 0.3s; }
    .sidebar a { color: var(--text-muted); padding: 12px 15px; border-radius: 8px; display: flex; align-items: center; gap: 15px; font-size: 16px; font-weight: 500; transition: all 0.2s; white-space: nowrap; overflow: hidden; }
    .sidebar a:hover:not(.active), .sidebar a.active { color: var(--text-main); background-color: var(--card-bg); }
    .sidebar a.active svg { color: var(--accent-color); }
    .sidebar a.active { pointer-events: none; }
    .app-layout.sidebar-collapsed .sidebar { padding: 20px 10px; align-items: center; }
    .app-layout.sidebar-collapsed .sidebar a { justify-content: center; padding: 15px 0; width: 100%; }
    .app-layout.sidebar-collapsed .sidebar a span { display: none; }
    .app-layout.sidebar-collapsed .sidebar svg { margin: 0; }
    .main-content { grid-column: 2; grid-row: 2; padding: 30px; overflow-y: auto; display: flex; flex-direction: column; height: 100%; }
    .auth-container { display: flex; justify-content: center; align-items: center; flex: 1; }
    .auth-form { background-color: var(--card-bg); padding: 40px; border-radius: 16px; width: 100%; max-width: 450px; border: 1px solid var(--border-color); }
    .auth-form h2 { text-align: center; margin-bottom: 25px; font-weight: 700; font-size: 24px; }
    .input-group { margin-bottom: 20px; position: relative; }
    .input-group input, .input-group select, .input-group textarea { width: 100%; padding: 14px 16px; background-color: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; color: white; font-size: 16px; outline: none; }
    .input-group input:focus, .input-group select:focus, .input-group textarea:focus { border-color: var(--accent-color); }
    .input-group textarea { resize: none; max-height: 250px; overflow-y: auto; }
    .pass-toggle { position: absolute; right: 15px; top: 15px; cursor: pointer; color: var(--text-muted); }
    .error { color: var(--danger-color); text-align: center; margin-bottom: 15px; font-size: 15px; }
    .profile-header { margin-bottom: 30px; display: flex; align-items: center; gap: 25px; }
    .profile-avatar { width: 140px; height: 140px; border-radius: 50% !important; border: none; outline: none; box-shadow: none; object-fit: cover; background: #333; }
    .profile-details h1 { font-size: 32px; margin-bottom: 5px; font-weight: 700; }
    .profile-details p { color: var(--text-muted); font-size: 16px; }
    .post-view { display: flex; gap: 25px; height: calc(100vh - 130px); overflow: hidden; background: transparent; }
    .post-media { flex: 2; background: #000; border-radius: 12px; display: flex; align-items: center; justify-content: center; overflow: hidden; position: relative; cursor: zoom-in; height: 100%; }
    .post-media img { max-width: 100%; max-height: 100%; object-fit: contain; }
    .post-details { flex: 1; min-width: 320px; display: flex; flex-direction: column; height: 100%; background: transparent; padding: 0; }
    .post-top-info { flex-shrink: 0; }
    .post-author { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
    .post-author img { width: 48px; height: 48px; border-radius: 50% !important; }
    .post-title { font-size: 26px; font-weight: 700; margin-bottom: 15px; }
    .post-desc { color: #ccc; font-size: 16px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.5; max-height: 150px; overflow-y: auto; }
    .actions-row { display: flex; align-items: center; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; flex-shrink: 0; }
    .vote-controls { display: flex; align-items: center; gap: 12px; background: var(--bg-color); padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border-color); }
    .vote-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 4px; border-radius: 4px; transition: color 0.2s; }
    .vote-btn:hover { background: #333; }
    .vote-btn.active-up { color: var(--accent-color); }
    .vote-btn.active-down { color: var(--danger-color); }
    .vote-count { font-weight: 700; font-size: 18px; min-width: 20px; text-align: center; }
    .action-btn { background: var(--bg-color); border: 1px solid var(--border-color); color: var(--text-muted); padding: 8px 12px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 5px; text-decoration: none; transition: background 0.2s; }
    .action-btn:hover { background: #333; color: #fff; }
    .comments-section { flex: 1; overflow-y: auto; min-height: 0; border-top: 1px solid var(--border-color); padding-top: 20px; }
    .feed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
    .feed-card { background: var(--card-bg); border-radius: 12px; overflow: hidden; border: 1px solid var(--border-color); display: flex; flex-direction: column; transition: transform 0.2s; position: relative; }
    .feed-card:hover { transform: translateY(-3px); border-color: #333; }
    .feed-card-img-container { width: 100%; aspect-ratio: 16 / 9; background: #000; overflow: hidden; display: flex; align-items: center; justify-content: center; }
    .feed-card-img-container img { width: 100%; height: 100%; object-fit: cover; }
    .feed-card-info { padding: 15px; flex: 1; display: flex; flex-direction: column; }
    .feed-card-title { font-weight: 700; font-size: 18px; margin-bottom: 10px; line-height: 1.3; }
    .feed-card-author { font-size: 14px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; margin-top: auto; }
    .feed-card-remove-btn { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); border: none; color: #fff; border-radius: 50%; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 10; }
    .feed-card-remove-btn:hover { background: var(--danger-color); }
    .create-layout { display: flex; gap: 30px; width: 100%; }
    .dropzone { flex: 2; border: 2px dashed var(--border-color); border-radius: 16px; padding: 50px; text-align: center; color: var(--text-muted); display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; transition: border-color 0.2s; cursor: pointer; }
    .dropzone.dragover { border-color: var(--accent-color); background: rgba(59, 130, 246, 0.05); }
    .file-preview { display: flex; align-items: center; gap: 15px; background: var(--bg-color); padding: 10px; border-radius: 8px; border: 1px solid var(--border-color); margin-top: 15px; width: 100%; text-align: left; cursor: default; }
    .file-preview img { width: 50px; height: 50px; object-fit: cover; border-radius: 6px; }
    .create-sidebar { flex: 1; background: var(--card-bg); padding: 30px; border-radius: 16px; border: 1px solid var(--border-color); display: flex; flex-direction: column; gap: 20px; }
    .switch { position: relative; display: inline-block; width: 50px; height: 28px; }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: var(--border-color); transition: .4s; border-radius: 34px; }
    .slider:before { position: absolute; content: ""; height: 20px; width: 20px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
    input:checked + .slider { background-color: var(--accent-color); }
    input:checked + .slider:before { transform: translateX(22px); }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 9999; justify-content: center; align-items: center; flex-direction: column; }
    .overlay img { max-width: 95%; max-height: 95%; object-fit: contain; }
    .close-overlay { position: absolute; top: 20px; right: 30px; font-size: 40px; color: #fff; cursor: pointer; background: none; border: none; }
    .bottom-nav { display: none; position: fixed; bottom: 0; left: 0; width: 100%; background: var(--bg-color); border-top: 1px solid var(--border-color); justify-content: space-around; padding: 12px 0; z-index: 100; padding-bottom: env(safe-area-inset-bottom, 12px); }
    .bottom-nav a { display: flex; flex-direction: column; align-items: center; color: var(--text-muted); width: 60px; text-decoration: none; }
    .bottom-nav a.active { color: var(--accent-color); pointer-events: none; }
    .bottom-nav a svg { width: 32px; height: 32px; margin-top: -8px; }
    .mobile-profile-menu { display: none; position: fixed; bottom: 0; left: 0; width: 100%; background: var(--card-bg); z-index: 1000; border-top-left-radius: 20px; border-top-right-radius: 20px; padding: 20px; transform: translateY(100%); transition: transform 0.3s ease-in-out; flex-direction: column; gap: 15px; padding-bottom: env(safe-area-inset-bottom, 20px); box-shadow: 0 -5px 20px rgba(0,0,0,0.5); }
    .mobile-profile-menu.open { transform: translateY(0); display: flex; }
    .mobile-profile-header { display: flex; align-items: center; gap: 15px; margin-bottom: 10px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color); }
    .mobile-profile-header img { width: 50px; height: 50px; border-radius: 50% !important; object-fit: cover; }
    .mobile-profile-menu .dropdown-item { padding: 12px 10px; border-radius: 8px; }
    .mobile-menu-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 999; }
    .crop-container { background: var(--card-bg); padding: 20px; border-radius: 16px; display: flex; flex-direction: column; gap: 15px; align-items: center; border: 1px solid var(--border-color); width: 90%; max-width: 350px; }
    .crop-canvas { border-radius: 50%; border: 2px solid var(--accent-color); background: #000; width: 100%; max-width: 250px; height: auto; aspect-ratio: 1; }
    .crop-controls { display: flex; flex-direction: column; width: 100%; gap: 10px; }
    .editor-card { background: var(--card-bg); border-radius: 16px; border: 1px solid var(--border-color); padding: 30px; display: flex; flex-direction: column; gap: 25px; width: 100%; max-width: 600px; margin: 0 auto; }
    .avatar-edit-container { position: relative; width: 120px; height: 120px; margin: 0 auto; cursor: pointer; border-radius: 50%; overflow: hidden; border: 2px solid var(--border-color); transition: border-color 0.2s; }
    .avatar-edit-container:hover { border-color: var(--accent-color); }
    .avatar-edit-container img { width: 100%; height: 100%; object-fit: cover; }
    .avatar-edit-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; color: #fff; opacity: 0; transition: opacity 0.2s; }
    .avatar-edit-container:hover .avatar-edit-overlay { opacity: 1; }
    .mobile-only { display: none !important; }
    .desktop-only { display: flex !important; }
    @media (max-width: 1024px) { .app-layout { grid-template-columns: 220px 1fr; } .app-layout.sidebar-collapsed { grid-template-columns: 80px 1fr; } .main-content { padding: 20px; } .feed-grid { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); } }
    @media (max-width: 900px) {
        .app-layout { grid-template-columns: 1fr; grid-template-rows: 60px 1fr; }
        .sidebar { display: none; }
        .main-content { grid-column: 1; padding: 15px; padding-bottom: 80px; }
        .bottom-nav { display: flex; }
        .topbar { padding: 0 15px; gap: 10px; height: 60px; }
        .topbar-left { width: auto; }
        .logo span { display: none; }
        .menu-toggle { display: none !important; }
        .topbar-center { display: none; } 
        .topbar-right .user-menu-container { display: none !important; } 
        .topbar-right { width: auto; }
        .mobile-only { display: flex !important; }
        .desktop-only { display: none !important; }
        .mobile-search-input { width: 100%; background: var(--card-bg); border: 1px solid var(--border-color); padding: 8px 12px; border-radius: 8px; color: #fff; font-size: 14px; outline: none; }
        .post-view { flex-direction: column; padding: 0; gap: 15px; height: auto; max-height: none; overflow: visible; }
        .post-details { display: contents; }
        .post-author { order: 1; margin-bottom: 0; }
        .post-media { order: 2; width: 100%; max-height: 50vh; min-height: 200px; border-radius: 12px; }
        .post-title { order: 3; margin-bottom: 0; }
        .post-desc { order: 4; margin-bottom: 0; max-height: none; }
        .actions-row { order: 5; margin-bottom: 0; padding: 0 15px; }
        .comments-section { order: 6; width: 100%; border-top: 1px solid var(--border-color); padding: 15px; overflow: visible; }
        .create-layout { flex-direction: column; }
        .dropzone { padding: 30px; min-height: 250px; }
        .profile-header { flex-direction: column; text-align: center; gap: 15px; }
        .profile-header .btn-primary { width: 100%; margin-top: 10px; }
        .profile-avatar { width: 100px; height: 100px; }
    }
</style>
<script>
    var filesList = [];
    var currentImage = null;
    var currentZoom = 1;

    function applySidebarState() {
        if(localStorage.getItem('sidebar_collapsed') === 'true') {
            var layout = document.querySelector('.app-layout');
            if(layout) layout.classList.add('sidebar-collapsed');
        } else {
            var layout = document.querySelector('.app-layout');
            if(layout) layout.classList.remove('sidebar-collapsed');
        }
    }
    
    function toggleSidebar() {
        var layout = document.querySelector('.app-layout');
        if(!layout) return;
        layout.classList.toggle('sidebar-collapsed');
        var isCollapsed = layout.classList.contains('sidebar-collapsed');
        localStorage.setItem('sidebar_collapsed', isCollapsed);
    }

    function toggleDropdown() {
        if(window.innerWidth <= 900) {
            var menu = document.getElementById('mobileProfileMenu');
            var overlay = document.getElementById('mobileMenuOverlay');
            if(menu) menu.classList.add('open');
            if(overlay) overlay.style.display = 'block';
        } else {
            var dropdown = document.getElementById("user-dropdown");
            if(dropdown) dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
        }
    }
    
    function closeMobileMenu() {
        var menu = document.getElementById('mobileProfileMenu');
        var overlay = document.getElementById('mobileMenuOverlay');
        if(menu) menu.classList.remove('open');
        if(overlay) overlay.style.display = 'none';
    }

    function togglePassword(el) {
        var input = el.previousElementSibling;
        var eyeOpen = el.querySelector('.eye-open');
        var eyeClosed = el.querySelector('.eye-closed');
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

    var searchTimeout;
    function handleSearch(query) {
        clearTimeout(searchTimeout);
        var dropdown = document.getElementById('searchDropdown');
        if (!dropdown) return;
        if (!query.trim()) {
            dropdown.style.display = 'none';
            return;
        }
        searchTimeout = setTimeout(async () => {
            var res = await fetch('/api/search?q=' + encodeURIComponent(query));
            var data = await res.json();
            if (data.results && data.results.length > 0) {
                dropdown.innerHTML = data.results.map(p => '<a href="/' + p.id + '" class="search-dropdown-item"><div style="font-weight:700; font-size:14px;">' + p.title + '</div><div style="color:var(--text-muted); font-size:12px; margin-left:auto;">@' + p.author + '</div></a>').join('');
                dropdown.style.display = 'block';
            } else {
                dropdown.innerHTML = '<div style="padding:15px; color:var(--text-muted); font-size:14px; text-align:center;">Ничего не найдено / Nothing found</div>';
                dropdown.style.display = 'block';
            }
        }, 300);
    }

    function handleFiles(input) {
        if (!input.files) return;
        var newFiles = Array.from(input.files);
        for (var i = 0; i < newFiles.length; i++) {
            if (filesList.length < 3) {
                filesList.push(newFiles[i]);
            } else {
                alert('Максимум 3 файла!');
                break;
            }
        }
        input.value = ''; 
        updateInputAndRender();
    }

    function removeFile(index, event) {
        if(event) { event.stopPropagation(); event.preventDefault(); }
        filesList.splice(index, 1);
        updateInputAndRender();
    }

    function updateInputAndRender() {
        var dt = new DataTransfer();
        filesList.forEach(f => dt.items.add(f));
        var fileInput = document.getElementById('file-input');
        if(fileInput) fileInput.files = dt.files;
        var previewContainer = document.getElementById('file-list');
        if(!previewContainer) return;
        previewContainer.innerHTML = '';
        if (filesList.length === 0) {
            var dropText = document.getElementById('dropzone-text');
            if(dropText) dropText.style.display = 'flex';
        } else {
            var dropText = document.getElementById('dropzone-text');
            if(dropText) dropText.style.display = 'none';
            filesList.forEach((file, index) => {
                var reader = new FileReader();
                reader.onload = function(e) {
                    var div = document.createElement('div');
                    div.className = 'file-preview';
                    div.onclick = (e) => e.stopPropagation();
                    div.innerHTML = '<img src="' + e.target.result + '"><div style="flex:1; overflow:hidden;"><div style="font-size:14px; color:#fff; font-weight:500; text-overflow:ellipsis; white-space:nowrap; overflow:hidden;">' + file.name + '</div><div style="font-size:12px; color:var(--text-muted);">' + (file.size/1024).toFixed(1) + ' KB</div></div><span style="cursor:pointer; color:var(--text-muted); font-size:24px; padding:0 10px;" onclick="removeFile(' + index + ', event)">×</span>';
                    previewContainer.appendChild(div);
                }
                reader.readAsDataURL(file);
            });
        }
    }

    function setVisibility(val) {
        var input = document.getElementById('vis-input');
        if(input) input.value = val;
        var btnFeed = document.getElementById('btn-feed');
        var btnLink = document.getElementById('btn-link');
        if(!btnFeed || !btnLink) return;
        if(val === 'feed') {
            btnFeed.style.borderColor = 'var(--accent-color)';
            btnFeed.style.color = 'var(--accent-color)';
            btnLink.style.borderColor = 'var(--border-color)';
            btnLink.style.color = 'var(--text-muted)';
        } else {
            btnFeed.style.borderColor = 'var(--border-color)';
            btnFeed.style.color = 'var(--text-muted)';
            btnLink.style.borderColor = 'var(--accent-color)';
            btnLink.style.color = 'var(--accent-color)';
        }
    }

    function copyLink() {
        navigator.clipboard.writeText(window.location.href);
        alert('Ссылка скопирована!');
    }

    function openPanorama(src) {
        var img = document.getElementById('panorama-img');
        var pano = document.getElementById('panorama');
        if(img) img.src = src;
        if(pano) pano.style.display = 'flex';
    }
    
    function closePanorama() {
        var pano = document.getElementById('panorama');
        if(pano) pano.style.display = 'none';
    }

    function loadAvatar(event) {
        var file = event.target.files[0];
        if(!file) return;
        var reader = new FileReader();
        reader.onload = function(e) {
            var img = new Image();
            img.onload = function() {
                currentImage = img;
                currentZoom = 1;
                var slider = document.getElementById('zoom-slider');
                if(slider) slider.value = 1;
                drawCropCanvas();
                var modal = document.getElementById('crop-modal');
                if(modal) modal.style.display = 'flex';
            }
            img.src = e.target.result;
        }
        reader.readAsDataURL(file);
    }

    function drawCropCanvas() {
        if(!currentImage) return;
        var canvas = document.getElementById('crop-canvas');
        if(!canvas) return;
        var ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        var scale = Math.max(canvas.width / currentImage.width, canvas.height / currentImage.height) * currentZoom;
        var x = (canvas.width - currentImage.width * scale) / 2;
        var y = (canvas.height - currentImage.height * scale) / 2;
        ctx.drawImage(currentImage, x, y, currentImage.width * scale, currentImage.height * scale);
    }

    function applyCrop() {
        var canvas = document.getElementById('crop-canvas');
        if(!canvas) return;
        var dataUrl = canvas.toDataURL('image/jpeg', 0.8);
        var inputB64 = document.getElementById('avatar-base64');
        var preview = document.getElementById('avatar-preview');
        var modal = document.getElementById('crop-modal');
        if(inputB64) inputB64.value = dataUrl;
        if(preview) preview.src = dataUrl;
        if(modal) modal.style.display = 'none';
    }

    async function vote(postId, action) {
        var res = await fetch('/api/vote/' + postId + '/' + action, { method: 'POST' });
        var data = await res.json();
        if(data.error) return alert(data.error);
        var count = document.getElementById('vote-count');
        if(count) count.innerText = data.score;
        var upBtn = document.getElementById('btn-up');
        var downBtn = document.getElementById('btn-down');
        if(upBtn) upBtn.className = 'vote-btn ' + (data.user_vote === 1 ? 'active-up' : '');
        if(downBtn) downBtn.className = 'vote-btn ' + (data.user_vote === -1 ? 'active-down' : '');
    }

    async function toggleSave(postId, redirectToSaved = false) {
        var res = await fetch('/api/save/' + postId, { method: 'POST' });
        var data = await res.json();
        if(data.error) return alert(data.error);
        if(redirectToSaved) { window.location.reload(); return; }
        var btn = document.getElementById('btn-save');
        if(btn) {
            if(data.saved) {
                btn.innerHTML = `""" + SVG_SAVED + """`;
                btn.style.color = 'var(--accent-color)';
                btn.style.borderColor = 'var(--accent-color)';
            } else {
                btn.innerHTML = `""" + SVG_SAVE + """`;
                btn.style.color = '';
                btn.style.borderColor = '';
            }
        }
    }

    async function submitComment(e, postId) {
        e.preventDefault();
        var input = document.getElementById('comment-input');
        if(!input) return;
        var text = input.value.trim();
        if (!text) return;
        var formData = new FormData(); 
        formData.append('text', text);
        var res = await fetch('/api/comment/' + postId, { method: 'POST', body: formData });
        var data = await res.json();
        if (data.error) return alert(data.error);
        if (data.comment) {
            input.value = '';
            var noMsg = document.getElementById('no-comments-msg');
            if(noMsg) noMsg.style.display = 'none';
            var list = document.getElementById('comments-list');
            var ava = data.comment.avatar || 'https://api.dicebear.com/7.x/avataaars/svg?seed=' + data.comment.author;
            var div = document.createElement('div');
            div.id = 'comment-' + data.comment.id;
            div.style.cssText = 'display:flex; gap:10px; margin-bottom:15px; justify-content:space-between;';
            var deleteBtn = '';
            if(data.is_author) {
                deleteBtn = '<button onclick="deleteComment(\'' + postId + '\', \'' + data.comment.id + '\')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; font-size:12px; padding:5px;">Удалить</button>';
            }
            div.innerHTML = '<div style="display:flex; gap:10px;"><img src="' + ava + '" style="width:32px; height:32px; border-radius:50%; object-fit:cover;"><div><div style="font-weight:700; font-size:14px;">' + data.comment.display_name + ' <span style="color:var(--text-muted); font-weight:400; font-size:12px;">@' + data.comment.author + '</span></div><div style="font-size:14px; margin-top:2px;">' + data.comment.text + '</div></div></div>' + deleteBtn;
            if(list) list.appendChild(div);
            var cCount = document.getElementById('comment-count');
            if(cCount) cCount.innerText = data.total_comments;
        }
    }

    async function deleteComment(postId, commentId) {
        if(!confirm('Удалить комментарий?')) return;
        var res = await fetch('/api/comment/' + postId + '/' + commentId, { method: 'DELETE' });
        var data = await res.json();
        if(data.success) {
            var el = document.getElementById('comment-' + commentId);
            if(el) el.remove();
            var cCount = document.getElementById('comment-count');
            if(cCount) cCount.innerText = data.total_comments;
            if(data.total_comments === 0) {
                var noMsg = document.getElementById('no-comments-msg');
                if(noMsg) noMsg.style.display = 'block';
            }
        } else {
            alert(data.error || 'Error');
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        applySidebarState();
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW failed'));
        }
    });

    document.addEventListener('htmx:afterSettle', function() {
        applySidebarState();
    });
</script>
"""

def render_layout(content_html, user, request: Request, active_page="feed"):
    lang = get_lang(request)
    avatar_url = user.get('avatar') if user and user.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username'] if user else 'guest'}"
    current_lang_str = "RU" if lang == "ru" else "EN"
    next_lang = "ru" if lang == "en" else "en"
    switch_lang_url = f"/set_lang/{next_lang}?next={request.url.path}"

    if user:
        nav_right = f"""<a href="/write" class="btn-primary desktop-only" style="padding: 8px 16px; display: flex; gap:6px;">{SVG_PLUS} {t('new_post', lang)}</a><div class="user-menu-container"><div class="user-menu-btn" onclick="toggleDropdown()"><img src="{avatar_url}" class="user-avatar-small"></div><div id="user-dropdown" class="dropdown-menu"><div class="dropdown-header"><img src="{avatar_url}"><div><span class="name">{user['display_name']}</span><span class="login">@{user['username']}</span></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="/logout" class="dropdown-item danger" onclick="return confirm('{t('logout_confirm', lang)}')">{SVG_LOGOUT} {t('logout', lang)}</a></div></div>"""
    else:
        nav_right = f"""<a href="{switch_lang_url}" class="action-btn" style="border:none; background:none; padding:5px; color:var(--text-muted); font-weight:bold; display:flex; gap:5px;">{SVG_LANG} <span class="desktop-only">{current_lang_str}</span></a><a href="/login" class="btn-primary" style="padding:8px 16px;">{SVG_USER} <span class="desktop-only">{t('login', lang)}</span></a>"""

    sidebar_html = ""
    if user:
        sidebar_html = f"""<div class="sidebar"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} <span>{t('feed', lang)}</span></a><a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE} <span>{t('saved', lang)}</span></a><a href="/@{user['username']}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} <span>{t('profile', lang)}</span></a></div>"""

    if user:
        bottom_nav = f"""<div class="bottom-nav"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED}</a><a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE}</a><a href="/write" class="{'active' if active_page == 'write' else ''}">{SVG_PLUS}</a><a href="javascript:void(0)" onclick="toggleDropdown()" class="{'active' if active_page == 'profile' else ''}">{SVG_USER}</a></div>"""
    else:
        bottom_nav = f"""<div class="bottom-nav"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED}</a><a href="/login" class="{'active' if active_page == 'login' else ''}">{SVG_USER}</a></div>"""

    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><title>sol-id</title>{CSS_STYLES}</head><body hx-boost="true"><div class="app-layout"><div class="topbar"><div class="topbar-left">{f'<div class="menu-toggle desktop-only" onclick="toggleSidebar()">{SVG_MENU}</div>' if user else ''}<a href="/" class="logo">{SVG_LOGO} <span>sol-id</span></a></div><div class="topbar-center"><div class="search-container"><span class="search-icon">{SVG_SEARCH}</span><input type="text" id="searchInput" class="search-input" placeholder="{t('search_placeholder', lang)}" oninput="handleSearch(this.value)" onfocus="handleSearch(this.value)" autocomplete="off"><div id="searchDropdown" class="search-dropdown"></div></div></div><form action="/search" method="get" class="mobile-only" style="flex:1;"><input type="text" name="q" placeholder="{t('search_placeholder', lang)}" class="mobile-search-input" value="{request.query_params.get('q', '')}"></form><div class="topbar-right">{nav_right}</div></div>{sidebar_html}<div class="main-content" style="{'grid-column: 1 / -1;' if not user else ''}">{content_html}</div></div>{f'''<div id="mobileMenuOverlay" class="mobile-menu-overlay" onclick="closeMobileMenu()"></div><div id="mobileProfileMenu" class="mobile-profile-menu"><div class="mobile-profile-header"><img src="{avatar_url}"><div><div style="font-weight:700; font-size:16px;">{user['display_name']}</div><div style="color:var(--text-muted); font-size:14px;">@{user['username']}</div></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="/logout" class="dropdown-item danger" onclick="return confirm('{t('logout_confirm', lang)}')">{SVG_LOGOUT} {t('logout', lang)}</a></div>''' if user else ''}<div id="panorama" class="overlay" onclick="closePanorama()"><button class="close-overlay">&times;</button><img id="panorama-img" src="" onclick="event.stopPropagation()"></div>{bottom_nav}</body></html>"""

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: HTTPException):
    lang = get_lang(request)
    user = get_current_user(request)
    content = f"""<div style="text-align:center; padding: 100px 20px; display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1;"><h1 style="font-size: 100px; font-weight: 900; color: var(--accent-color); margin-bottom: 10px; line-height:1;">404</h1><h2 style="margin-bottom: 20px; font-weight:700;">{t('404_title', lang)}</h2><p style="color:var(--text-muted); margin-bottom:30px;">{t('404_desc', lang)}</p><a href="/" class="btn-primary" style="padding:12px 24px;">{SVG_BACK} {t('back', lang)}</a></div>"""
    return HTMLResponse(content=render_layout(content, user, request), status_code=404)

@app.exception_handler(500)
async def custom_500_handler(request: Request, exc: Exception):
    lang = get_lang(request)
    user = get_current_user(request)
    content = f"""<div style="text-align:center; padding: 100px 20px; display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1;"><h1 style="font-size: 100px; font-weight: 900; color: var(--danger-color); margin-bottom: 10px; line-height:1;">500</h1><h2 style="margin-bottom: 20px; font-weight:700;">Internal Server Error</h2><p style="color:var(--text-muted); margin-bottom:30px;">Something went wrong.</p><a href="/" class="btn-primary" style="padding:12px 24px;">{SVG_BACK} {t('back', lang)}</a></div>"""
    return HTMLResponse(content=render_layout(content, user, request), status_code=500)

@app.get("/set_lang/{lang}")
async def set_lang(lang: str, next: str = "/"):
    response = RedirectResponse(url=next, status_code=status.HTTP_302_FOUND)
    if lang in ["en", "ru"]:
        response.set_cookie(key="lang", value=lang, max_age=31536000, httponly=False)
    return response

@app.get("/api/search")
async def api_search(q: str = ""):
    q_lower = q.lower().strip()
    if not q_lower: return JSONResponse({"results": []})
    results = [{"id": p['id'], "title": p['title'], "author": p['author']} for p in posts_db if p.get('visibility') == 'feed' and (q_lower in p['title'].lower() or q_lower in p['content'].lower() or q_lower in p['author'].lower())][:5]
    return JSONResponse({"results": results})

@app.get("/search", response_class=HTMLResponse)
async def search_posts(request: Request, q: str = ""):
    user = get_current_user(request)
    lang = get_lang(request)
    q_lower = q.lower().strip()
    results = [p for p in posts_db if p.get('visibility') == 'feed' and (q_lower in p['title'].lower() or q_lower in p['content'].lower() or q_lower in p['author'].lower())] if q_lower else []
    if not results:
        content = f'<h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{q}"</h2><div style="text-align:center; padding: 60px 20px; color: var(--text-muted); font-size:18px;">{t("nothing_found", lang)}</div>'
    else:
        cards = ""
        for post in results:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{post['title']}</div><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{post['author']}</div></div></a>"""
        content = f'<h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{q}"</h2><div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed"))

@app.get("/", response_class=HTMLResponse)
async def read_feed(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    feed_posts = [p for p in posts_db if p.get('visibility') == 'feed']
    if not feed_posts:
        content = f'<div style="text-align:center; padding: 80px 20px; color: var(--text-muted);"><h3 style="font-size: 28px; color: #fff; margin-bottom: 15px;">{t("no_posts", lang)}</h3></div>'
    else:
        cards = ""
        for post in feed_posts:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            score = len(post['votes']['up']) - len(post['votes']['down'])
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{post['title']}</div><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{post['author']}<span style="margin-left:auto; display:flex; align-items:center; gap:4px;">{SVG_UP} {score}</span></div></div></a>"""
        content = f'<div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed"))

@app.get("/saved", response_class=HTMLResponse)
async def saved_posts(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    saved_ids = user.get('saved_posts', [])
    saved_posts_list = [p for p in posts_db if p['id'] in saved_ids]
    if not saved_posts_list:
        content = f"<div style='text-align:center; padding:60px; color:var(--text-muted); font-size:18px;'>{t('no_saved', lang)}</div>"
    else:
        cards = ""
        for post in saved_posts_list:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            cards += f"""<div class="feed-card"><button onclick="toggleSave('{post['id']}', true)" class="feed-card-remove-btn" title="{t('remove_saved', lang)}">×</button><a href="/{post['id']}" style="display:flex; flex-direction:column; flex:1;"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{post['title']}</div><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{post['author']}</div></div></a></div>"""
        content = f'<h2 style="margin-bottom:25px;">{t("saved", lang)}</h2><div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "saved"))

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    lang = get_lang(request)
    content = f"""<div class="auth-container"><form class="auth-form" action="/login" method="post"><h2>{t('login', lang)}</h2><div class="input-group"><input type="text" name="username" placeholder="{t('username', lang)}" required></div><div class="input-group"><input type="text" name="display_name" placeholder="{t('display_name', lang)} (Only for new accounts)"></div><div class="input-group"><input type="password" name="password" placeholder="{t('password', lang)}" required><span class="pass-toggle" onclick="togglePassword(this)">{SVG_EYE}{SVG_EYE_OFF}</span></div><p style="color:var(--text-muted); font-size:13px; margin-bottom:15px;">{t('login_hint', lang)}</p><button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:14px;">{SVG_USER} {t('login', lang)}</button></form></div>"""
    return HTMLResponse(content=render_layout(content, None, request, "login"))

@app.post("/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...), display_name: str = Form("")):
    lang = get_lang(request)
    username = username.strip()
    user = users_db.get(username)
    if user:
        if not pwd_context.verify(password, user["password"]):
            return HTMLResponse(content=render_layout(f'<div class="auth-container"><div class="auth-form"><div class="error">{t("wrong_pass", lang)}</div><a href="/login" class="btn-primary">{t("back", lang)}</a></div></div>', None, request, "login"))
    else:
        if not display_name.strip():
            return HTMLResponse(content=render_layout(f'<div class="auth-container"><div class="auth-form"><div class="error">{t("need_name", lang)}</div><a href="/login" class="btn-primary">{t("back", lang)}</a></div></div>', None, request, "login"))
        users_db[username] = {"username": username, "password": pwd_context.hash(password), "display_name": display_name.strip(), "avatar": None, "saved_posts": []}
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

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    content = f"""<div style="max-width: 700px; margin: 0 auto; width: 100%;"><h2 style="margin-bottom: 25px; font-weight: 700; font-size: 28px;">{t('settings', lang)}</h2><div style="background: var(--card-bg); padding: 25px; border-radius: 16px; border: 1px solid var(--border-color); margin-bottom: 20px;"><h3 style="margin-bottom: 15px; font-weight: 500; font-size: 20px;">Language / Язык</h3><div style="display:flex; gap:10px;"><a href="/set_lang/en?next=/settings" class="btn-primary" style="background:{'var(--accent-color)' if lang=='en' else '#333'};">English (EN)</a><a href="/set_lang/ru?next=/settings" class="btn-primary" style="background:{'var(--accent-color)' if lang=='ru' else '#333'};">Русский (RU)</a></div></div></div>"""
    return HTMLResponse(content=render_layout(content, user, request, "settings"))

@app.get("/write", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    content = f"""<div style="max-width: 1100px; margin: 0 auto; width: 100%;"><h2 style="margin-bottom: 30px; font-weight: 700; font-size: 32px;">{t('new_post', lang)}</h2><form action="/write" method="post" enctype="multipart/form-data" class="create-layout"><div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()"><div id="dropzone-text" style="display:flex; flex-direction:column; align-items:center;">{SVG_IMAGE}<div style="margin-top:20px; font-size:20px; font-weight:700; color:#fff;">{t('upload_hint', lang)}</div><div style="margin-top:10px; font-size:15px; color:var(--text-muted);">{t('upload_limit', lang)}</div><div style="margin-top:20px; background:#2a2a2a; padding:12px 24px; border-radius:8px; color:#fff; font-weight:500; border:1px solid var(--border-color); cursor:pointer;">{t('choose_files', lang)}</div></div><div id="file-list" style="width:100%; display:flex; flex-direction:column; gap:10px;"></div><input id="file-input" type="file" name="images" multiple accept="image/*" style="display:none;" onchange="handleFiles(this)" onclick="event.stopPropagation()"></div><div class="create-sidebar"><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('title', lang)} *</label><input type="text" name="title" placeholder="{t('title', lang)}" required style="padding:14px;"></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('description', lang)} (Max 500)</label><textarea name="content" placeholder="{t('description', lang)}" maxlength="500" style="min-height:120px; padding:14px;"></textarea></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('visibility', lang)}</label><div style="display:flex; gap:10px;"><button type="button" id="btn-feed" onclick="setVisibility('feed')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--accent-color); color:var(--accent-color); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_EYE} {t('in_feed', lang)}</button><button type="button" id="btn-link" onclick="setVisibility('link')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--border-color); color:var(--text-muted); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_LINK} {t('by_link', lang)}</button></div><input type="hidden" name="visibility" id="vis-input" value="feed"></div><div class="input-group" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;"><label style="font-size:15px; font-weight:700; color:#fff;">{t('allow_comments', lang)}</label><label class="switch"><input type="checkbox" name="allow_comments" checked><span class="slider"></span></label></div><button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:16px; font-size:16px;">{SVG_PLUS} {t('publish', lang)}</button></div></form></div>"""
    return HTMLResponse(content=render_layout(content, user, request, "write"))

@app.post("/write")
async def create_post(request: Request, title: str = Form(...), content: str = Form(""), visibility: str = Form("feed"), allow_comments: bool = Form(False), images: List[UploadFile] = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    img_b64_list = []
    if images and images[0].filename:
        for img in images[:3]:
            b64 = await image_to_base64(img)
            if b64: img_b64_list.append(b64)
    new_post = {"id": str(uuid.uuid4())[:6], "author": user["username"], "title": title, "content": content, "images": img_b64_list, "visibility": visibility, "votes": {"up": [], "down": []}, "comments": [], "allow_comments": allow_comments}
    posts_db.insert(0, new_post)
    return RedirectResponse(url=f"/{new_post['id']}", status_code=status.HTTP_302_FOUND)

@app.post("/api/vote/{post_id}/{action}")
async def vote_post(post_id: str, action: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    username = user['username']
    up_votes = post['votes'].get('up', [])
    down_votes = post['votes'].get('down', [])
    user_vote = 0
    if action == 'up':
        if username in up_votes: up_votes.remove(username)
        else:
            up_votes.append(username)
            if username in down_votes: down_votes.remove(username)
            user_vote = 1
    elif action == 'down':
        if username in down_votes: down_votes.remove(username)
        else:
            down_votes.append(username)
            if username in up_votes: up_votes.remove(username)
            user_vote = -1
    post['votes']['up'] = up_votes
    post['votes']['down'] = down_votes
    score = len(up_votes) - len(down_votes)
    if username in post['votes']['up']: user_vote = 1
    elif username in post['votes']['down']: user_vote = -1
    else: user_vote = 0
    return JSONResponse({"score": score, "user_vote": user_vote})

@app.post("/api/save/{post_id}")
async def save_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if 'saved_posts' not in users_db[user['username']]: users_db[user['username']]['saved_posts'] = []
    if post_id in users_db[user['username']]['saved_posts']:
        users_db[user['username']]['saved_posts'].remove(post_id)
        saved = False
    else:
        users_db[user['username']]['saved_posts'].append(post_id)
        saved = True
    return JSONResponse({"saved": saved})

@app.post("/api/comment/{post_id}")
async def add_comment(post_id: str, request: Request, text: str = Form(...)):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    if not post.get('allow_comments', True): return JSONResponse({"error": "Comments disabled"}, status_code=403)
    comment = {"id": str(uuid.uuid4())[:6], "author": user['username'], "display_name": user['display_name'], "avatar": user.get('avatar'), "text": text}
    post['comments'].append(comment)
    return JSONResponse({"comment": comment, "total_comments": len(post['comments']), "is_author": True})

@app.delete("/api/comment/{post_id}/{comment_id}")
async def delete_comment(post_id: str, comment_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    comment = next((c for c in post['comments'] if c['id'] == comment_id), None)
    if not comment: return JSONResponse({"error": "Comment not found"}, status_code=404)
    if comment['author'] != user['username']: return JSONResponse({"error": "Forbidden"}, status_code=403)
    post['comments'] = [c for c in post['comments'] if c['id'] != comment_id]
    return JSONResponse({"success": True, "total_comments": len(post['comments'])})

@app.post("/delete/{post_id}")
async def delete_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    global posts_db
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if post and post['author'] == user['username']:
        posts_db = [p for p in posts_db if p['id'] != post_id]
        for u in users_db.values():
            if 'saved_posts' in u and post_id in u['saved_posts']: u['saved_posts'].remove(post_id)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@app.get("/@{username}", response_class=HTMLResponse)
async def view_profile(request: Request, username: str):
    current_user = get_current_user(request)
    lang = get_lang(request)
    profile_user = users_db.get(username)
    if not profile_user: raise HTTPException(404, "User not found")
    ava = profile_user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
    if current_user and current_user['username'] == username: user_posts = [p for p in posts_db if p['author'] == username]
    else: user_posts = [p for p in posts_db if p['author'] == username and p.get('visibility') == 'feed']
    posts_html = ""
    for post in user_posts:
        img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
        posts_html += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{post['title']}</div></div></a>"""
    if not posts_html: posts_html = f'<div style="color:var(--text-muted); font-size:18px; text-align:center; padding:20px;">{t("no_posts", lang)}</div>'
    edit_btn = f'<a href="/edit_profile" class="btn-primary" style="background:#333; color:#fff; display:flex; gap:8px;">{SVG_SETTINGS} {t("edit_profile", lang)}</a>' if current_user and current_user['username'] == username else ''
    content = f"""<div class="profile-header"><img src="{ava}" class="profile-avatar"><div class="profile-details"><h1>{profile_user['display_name']}</h1><p>@{username}</p><p style="margin-top:8px; font-size:15px; font-weight:500;">{len(user_posts)} {t('posts', lang)}</p></div><div style="margin-left:auto;">{edit_btn}</div></div><div style="border-bottom: 1px solid var(--border-color); margin-bottom: 25px; display:flex; gap:25px;"><a href="#" style="color:#fff; padding-bottom:12px; border-bottom:3px solid var(--accent-color); font-size:18px; font-weight:700;">{t('posts', lang)}</a></div><div class="feed-grid">{posts_html}</div>"""
    return HTMLResponse(content=render_layout(content, current_user, request, "profile"))

@app.get("/edit_profile", response_class=HTMLResponse)
async def edit_profile_page(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    avatar_url = user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username']}"
    content = f"""
    <div class="editor-card">
        <h2 style="margin-bottom:10px; font-weight:700; font-size:28px; text-align:center;">{t('edit_profile', lang)}</h2>
        <form action="/edit_profile" method="post" enctype="multipart/form-data" style="display:flex; flex-direction:column; gap:20px;">
            <div style="text-align:center;">
                <div class="avatar-edit-container" onclick="document.getElementById('avatar-file').click()">
                    <img id="avatar-preview" src="{avatar_url}">
                    <div class="avatar-edit-overlay">{SVG_CAMERA}</div>
                </div>
                <div style="font-size:13px; color:var(--text-muted); margin-top:10px;">{t('change_avatar', lang)}</div>
                <input type="file" id="avatar-file" name="avatar" accept="image/*" onchange="loadAvatar(event)" style="display:none;">
                <input type="hidden" name="avatar_base64" id="avatar-base64">
            </div>
            <div class="input-group">
                <label style="font-size:15px; color:var(--text-muted); margin-bottom:8px; display:block; font-weight:500;">{t('display_name', lang)}</label>
                <input type="text" name="display_name" value="{user['display_name']}" required style="padding:14px;">
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; margin-top:10px; padding:14px;">{SVG_SETTINGS} {t('save', lang)}</button>
        </form>
    </div>
    <div id="crop-modal" class="overlay">
        <div class="crop-container" onclick="event.stopPropagation()">
            <h3 style="font-weight:700;">{t('crop_avatar', lang)}</h3>
            <canvas id="crop-canvas" width="300" height="300" class="crop-canvas"></canvas>
            <div class="crop-controls">
                <label style="font-size:14px; color:var(--text-muted);">{t('zoom', lang)}</label>
                <input type="range" id="zoom-slider" min="1" max="3" step="0.05" value="1" oninput="currentZoom = parseFloat(this.value); drawCropCanvas();" style="width:100%;">
            </div>
            <div style="display:flex; gap:10px; width:100%;">
                <button type="button" onclick="document.getElementById('crop-modal').style.display='none'" class="action-btn" style="flex:1; justify-content:center;">{t('cancel', lang)}</button>
                <button type="button" onclick="applyCrop()" class="btn-primary" style="flex:1; justify-content:center;">{t('apply', lang)}</button>
            </div>
        </div>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, request, "profile"))

@app.post("/edit_profile")
async def edit_profile(request: Request, display_name: str = Form(...), avatar_base64: str = Form(None), avatar: UploadFile = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    users_db[user['username']]['display_name'] = display_name
    if avatar_base64: users_db[user['username']]['avatar'] = avatar_base64
    elif avatar and avatar.filename: users_db[user['username']]['avatar'] = await image_to_base64(avatar)
    return RedirectResponse(url=f"/@{user['username']}", status_code=status.HTTP_302_FOUND)

@app.get("/{post_id}", response_class=HTMLResponse)
async def view_post(request: Request, post_id: str):
    user = get_current_user(request)
    lang = get_lang(request)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post: raise HTTPException(404, "Post not found")
    author = users_db.get(post['author'])
    ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
    score = len(post['votes']['up']) - len(post['votes']['down'])
    user_vote = 0
    if user:
        if user['username'] in post['votes']['up']: user_vote = 1
        elif user['username'] in post['votes']['down']: user_vote = -1
    is_saved = user and post_id in user.get('saved_posts', [])
    save_icon = SVG_SAVED if is_saved else SVG_SAVE
    delete_btn = f'''<form action="/delete/{post_id}" method="post" style="margin:0;" onsubmit="return confirm('{t("delete_confirm", lang)}');"><button type="submit" class="action-btn" style="color:var(--danger-color);">{SVG_TRASH}</button></form>''' if user and user['username'] == post['author'] else ''
    if post['images']:
        media_html = "".join([f'<img src="{img}" style="max-width:100%; max-height:100%; object-fit:contain; display:{"" if i==0 else "none"};" class="carousel-img" onclick="openPanorama(this.src)">' for i, img in enumerate(post['images'])])
        if len(post['images']) > 1:
            media_html += f"""<div style="position:absolute; bottom:20px; left:0; width:100%; display:flex; justify-content:center; gap:15px;"><button class="btn-primary" style="padding:8px 16px; background:rgba(0,0,0,0.7); color:#fff; border:none;" onclick="changeImg(-1)">&lt;</button><button class="btn-primary" style="padding:8px 16px; background:rgba(0,0,0,0.7); color:#fff; border:none;" onclick="changeImg(1)">&gt;</button></div><script>let currentImg=0;let imgs=document.querySelectorAll('.carousel-img');function showImg(idx){{imgs.forEach((img,i)=>img.style.display=i===idx?'block':'none');}}function changeImg(dir){{currentImg=(currentImg+dir+imgs.length)%imgs.length;showImg(currentImg);}}document.addEventListener('keydown',function(e){{if(e.target.tagName.toLowerCase()==='input'||e.target.tagName.toLowerCase()==='textarea')return;if(e.key==='ArrowLeft'){{e.preventDefault();changeImg(-1);}}if(e.key==='ArrowRight'){{e.preventDefault();changeImg(1);}}}});</script>"""
    else: media_html = f'<div style="color:#555;">{SVG_IMAGE}</div>'
    if post.get('allow_comments', True):
        if user: comments_input_html = f"""<form onsubmit="submitComment(event, '{post['id']}')" style="background:var(--bg-color); padding:12px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); display:flex; gap:10px;"><input type="text" id="comment-input" placeholder="{t('write_comment', lang)}" style="flex:1; background:transparent; border:none; color:#fff; outline:none; font-size:15px;"><button type="submit" class="btn-primary" style="padding:5px 15px;">{t('send', lang)}</button></form>"""
        else: comments_input_html = f"""<div style="background:var(--bg-color); padding:15px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); text-align:center;"><a href="/login" class="btn-primary" style="display:inline-flex;">{SVG_USER} {t('login_to_comment', lang)}</a></div>"""
    else: comments_input_html = f'<div style="background:rgba(239,68,68,0.1); color:var(--danger-color); padding:15px; border-radius:8px; margin-bottom:20px; text-align:center; font-weight:500;">{t("comments_disabled", lang)}</div>'
    comments_list_html = ""
    for c in post['comments']:
        c_ava = c.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={c['author']}"
        del_btn = f'<button onclick="deleteComment(\'{post["id"]}\', \'{c["id"]}\')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; font-size:12px; padding:5px;">Удалить</button>' if user and user['username'] == c['author'] else ''
        comments_list_html += f"""<div id="comment-{c['id']}" style="display:flex; gap:10px; margin-bottom:15px; justify-content:space-between;"><div style="display:flex; gap:10px;"><img src="{c_ava}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;"><div><div style="font-weight:700; font-size:14px;">{c.get('display_name', c['author'])} <span style="color:var(--text-muted); font-weight:400; font-size:12px;">@{c['author']}</span></div><div style="font-size:14px; margin-top:2px;">{c['text']}</div></div></div>{del_btn}</div>"""
    no_comments_style = "display:block;" if len(post['comments']) == 0 else "display:none;"
    content = f"""<div style="margin-bottom:20px; display:flex; justify-content:space-between; align-items:center;"><a href="/" style="display:flex; align-items:center; gap:10px; color:var(--text-muted); font-weight:500; font-size:16px;">{SVG_BACK} {t('back', lang)}</a></div><div class="post-view"><div class="post-media">{media_html}</div><div class="post-details"><div class="post-top-info"><div class="post-author"><a href="/@{post['author']}"><img src="{ava}"></a><div><a href="/@{post['author']}" style="color:#fff; font-weight:700; font-size:18px;">{author['display_name'] if author else post['author']}</a><div style="font-size:14px; color:var(--text-muted);">@{post['author']}</div></div></div><div class="post-title selectable">{post['title']}</div><div class="post-desc selectable">{post['content']}</div><div class="actions-row"><div class="vote-controls"><button onclick="vote('{post['id']}', 'up')" id="btn-up" class="vote-btn {'active-up' if user_vote == 1 else ''}">{SVG_UP}</button><span class="vote-count" id="vote-count">{score}</span><button onclick="vote('{post['id']}', 'down')" id="btn-down" class="vote-btn {'active-down' if user_vote == -1 else ''}">{SVG_DOWN}</button></div><button onclick="toggleSave('{post['id']}')" id="btn-save" class="action-btn" style="{'color:var(--accent-color); border-color:var(--accent-color);' if is_saved else ''}" title="{t('save_post', lang)}">{save_icon}</button><button class="action-btn" onclick="copyLink()" title="{t('copy_link', lang)}">{SVG_LINK}</button>{delete_btn}</div></div><div class="comments-section"><h3 style="margin-bottom:15px; font-weight:700; font-size:18px;">{t('comments', lang)} (<span id="comment-count">{len(post['comments'])}</span>)</h3>{comments_input_html}<div id="no-comments-msg" style="{no_comments_style} font-size:15px; color:var(--text-muted); text-align:center; padding:20px;">{t('no_comments', lang)}</div><div id="comments-list">{comments_list_html}</div></div></div></div>"""
    return HTMLResponse(content=render_layout(content, user, request, "feed"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
