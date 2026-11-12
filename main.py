from fastapi import FastAPI, Request, Form, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from passlib.context import CryptContext
from supabase import create_client, Client
import uuid
import base64
import html
import json
import re
from typing import List
from datetime import datetime

app = FastAPI(title="sol-id")

# Включаем GZIP для скорости (сжимает ответы сервера)
app.add_middleware(GZipMiddleware, minimum_size=1000)

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# --- SUPABASE SETUP ---
SUPABASE_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

sessions = {} 

# Мидлварь для базовых заголовков безопасности
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

TRANSLATIONS = {
    "en": {
        "feed": "Feed", "saved": "Saved", "profile": "Profile", "settings": "Settings", "logout": "Logout", "login": "Login",
        "new_post": "New Post", "search_placeholder": "Search...", "title": "Title", "description": "Description", "publish": "Publish",
        "visibility": "Who can see", "in_feed": "In Feed", "by_link": "By Link", "upload_hint": "Drop files or paste (Ctrl+V)",
        "upload_limit": "JPEG, PNG up to 3 images", "back": "Back", "comments": "Comments", "no_comments": "No comments yet.",
        "write_comment": "Write a comment...", "send": "Send", "edit_profile": "Edit Profile", "display_name": "Display Name",
        "avatar": "Avatar", "save": "Save", "username": "Username", "password": "Password", "login_hint": "If the account does not exist, it will be created automatically",
        "save_post": "Save post", "copy_link": "Copy link", "delete": "Delete", "no_posts": "No posts yet", "posts": "posts",
        "search_results": "Search results", "nothing_found": "Nothing found", "no_saved": "You have no saved posts",
        "wrong_pass": "Wrong password", "need_name": "Display name is required for registration", "choose_files": "Choose files",
        "allow_comments": "Allow comments", "comments_disabled": "Comments are disabled for this post", "edit_post": "Edit Post",
        "remove_saved": "Remove from saved", "delete_comment": "Delete comment", "edit": "Edit", "update": "Update",
        "404_title": "Page Not Found", "404_desc": "The page you are looking for does not exist.", "login_to_comment": "Please log in to leave a comment",
        "logout_confirm": "Are you sure you want to logout?", "delete_confirm": "Are you sure you want to delete this post?",
        "crop_avatar": "Crop Avatar", "zoom": "Zoom", "change_avatar": "Change Avatar", "cancel": "Cancel", "apply": "Apply",
        "language": "Language", "max_files": "Maximum 3 files!", "link_copied": "Link copied!", "delete_comment_confirm": "Delete this comment?",
        "confirm": "Confirm", "close": "Close", "profile_settings": "Profile Settings", "profile_updated": "Profile updated successfully!",
        "link_only": "Link Only (Hidden)", "val_avail": "Available", "val_p_len": "At least 6 characters",
        "val_p_latin": "Latin letters, numbers, and symbols only",
        "welcome_title": "Welcome to sol-id!", "welcome_desc": "sol-id is ebloid, but from AliExpress. A simple, fast, and minimalist social network.",
        "faq_title": "FAQ", "faq_q1": "How to post?", "faq_a1": "Click the '+' button in the top menu.",
        "faq_q2": "How to save?", "faq_a2": "Click the bookmark icon under any post.",
        "faq_q3": "How to hide a post?", "faq_a3": "When creating, select 'By Link' - only you and those with the link will see it.",
        "got_it": "Got it!", "invalid_pass_format": "Invalid password format"
    },
    "ru": {
        "feed": "Лента", "saved": "Избранное", "profile": "Профиль", "settings": "Настройки", "logout": "Выйти", "login": "Вход",
        "new_post": "Новый пост", "search_placeholder": "Поиск...", "title": "Название", "description": "Описание", "publish": "Опубликовать",
        "visibility": "Кто увидит", "in_feed": "Все, в ленте", "by_link": "По ссылке", "upload_hint": "Перетащите файлы или вставьте (Ctrl+V)",
        "upload_limit": "JPEG, PNG до 3 штук", "back": "Назад", "comments": "Комментарии", "no_comments": "Пока нет комментариев.",
        "write_comment": "Напишите комментарий...", "send": "Отправить", "edit_profile": "Редактировать профиль", "display_name": "Отображаемое имя",
        "avatar": "Аватарка", "save": "Сохранить", "username": "Логин", "password": "Пароль", "login_hint": "Если аккаунта нет, он будет создан автоматически",
        "save_post": "Сохранить пост", "copy_link": "Скопировать ссылку", "delete": "Удалить", "no_posts": "Пока нет постов", "posts": "постов",
        "search_results": "Результаты поиска", "nothing_found": "Ничего не найдено", "no_saved": "У вас пока нет избранных постов",
        "wrong_pass": "Неверный пароль", "need_name": "Для регистрации нужно указать имя", "choose_files": "Выбрать файлы",
        "allow_comments": "Разрешить комментарии", "comments_disabled": "Комментарии отключены", "edit_post": "Редактировать пост",
        "remove_saved": "Убрать из избранного", "delete_comment": "Удалить комментарий", "edit": "Редактировать", "update": "Обновить",
        "404_title": "Страница не найдена", "404_desc": "Страница, которую вы ищете, не существует.", "login_to_comment": "Пожалуйста, войдите, чтобы оставить комментарий",
        "logout_confirm": "Вы уверены, что хотите выйти?", "delete_confirm": "Вы уверены, что хотите удалить этот пост?",
        "crop_avatar": "Настройка аватарки", "zoom": "Приближение", "change_avatar": "Изменить аватарку", "cancel": "Отмена", "apply": "Применить",
        "language": "Язык", "max_files": "Максимум 3 файла!", "link_copied": "Ссылка скопирована!", "delete_comment_confirm": "Удалить этот комментарий?",
        "confirm": "Подтвердить", "close": "Закрыть", "profile_settings": "Настройки профиля", "profile_updated": "Профиль успешно обновлен!",
        "link_only": "По ссылке (Скрыт)", "val_avail": "Свободен", "val_p_len": "От 6 символов",
        "val_p_latin": "Только латиница, цифры и спецсимволы",
        "welcome_title": "Добро пожаловать в sol-id!", "welcome_desc": "sol-id — это ebloid, но с алиэкспресс. Простая, быстрая и минималистичная соцсеть.",
        "faq_title": "FAQ", "faq_q1": "Как выложить пост?", "faq_a1": "Нажмите на кнопку '+' в верхнем меню.",
        "faq_q2": "Как сохранить?", "faq_a2": "Нажмите на иконку закладки под любым постом.",
        "faq_q3": "Как скрыть пост?", "faq_a3": "При создании выберите 'По ссылке' - его увидишь только ты и те, у кого есть ссылка.",
        "got_it": "Понятно!", "invalid_pass_format": "Неверный формат пароля"
    }
}

def get_lang(request: Request):
    lang = request.cookies.get("lang", "ru")
    return lang if lang in TRANSLATIONS else "ru"

def t(key, lang):
    return TRANSLATIONS[lang].get(key, key)

SVG_UP = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>"""
SVG_DOWN = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>"""
SVG_FEED = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>"""
SVG_PLUS = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>"""
SVG_USER = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
SVG_SETTINGS = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>"""
SVG_LOGOUT = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>"""
SVG_EYE = """<svg class="eye-open" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>"""
SVG_EYE_OFF = """<svg class="eye-closed" style="display:none;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>"""
SVG_BACK = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>"""
SVG_LEFT = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>"""
SVG_RIGHT = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>"""
SVG_IMAGE = """<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>"""
SVG_SAVE = """<svg class="icon-save" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_SAVED = """<svg class="icon-saved" width="20" height="20" viewBox="0 0 24 24" fill="#3b82f6" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_LINK = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>"""
SVG_TRASH = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>"""
SVG_SEARCH = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>"""
SVG_LANG = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>"""
SVG_MENU = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>"""
SVG_CAMERA = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>"""
SVG_LOCK = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>"""
SVG_CALENDAR = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>"""
SVG_CROSS = """<svg class="icon-cross" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>"""
SVG_CHECK = """<svg class="icon-check" style="display:none;" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>"""

LOGO_URL = "https://i.ibb.co/5hLnbhYC/solid-logo.png"
SPRITE_URL = "https://i.ibb.co/7x55NbD0/solidsprite.png"

def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        username = sessions[session_token]
        res = supabase.table("users").select("*").eq("username", username).execute()
        if res.data:
            return res.data[0]
    return None

async def image_to_base64(file: UploadFile):
    if not file or not file.filename: return None
    contents = await file.read()
    return f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"

@app.get("/manifest.json")
async def get_manifest():
    return JSONResponse({
        "name": "sol-id", "short_name": "sol-id", "start_url": "/", 
        "display": "standalone", "background_color": "#0a0a0a", "theme_color": "#3b82f6",
        "icons": [{"src": LOGO_URL, "sizes": "192x192", "type": "image/png"}]
    })

@app.get("/sw.js")
async def get_sw():
    sw_code = """
    const CACHE_NAME = 'solid-cache-v4';
    const urlsToCache = ['/', '/manifest.json', '""" + LOGO_URL + """', '""" + SPRITE_URL + """'];
    self.addEventListener('install', event => {
        self.skipWaiting();
        event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache)));
    });
    self.addEventListener('activate', event => {
        event.waitUntil(clients.claim());
    });
    self.addEventListener('fetch', event => {
        if (event.request.method !== 'GET') return;
        event.respondWith(
            fetch(event.request).then(response => {
                let responseClone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseClone));
                return response;
            }).catch(() => caches.match(event.request))
        );
    });
    """
    return Response(content=sw_code, media_type="application/javascript")

@app.get("/api/check_username")
async def api_check_username(q: str = ""):
    if not q: return JSONResponse({"available": False})
    res = supabase.table("users").select("username").eq("username", q).execute()
    return JSONResponse({"available": len(res.data) == 0})

CSS_STYLES = f"""
<link rel="icon" type="image/png" href="{LOGO_URL}">
<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>
:root{{--bg-color:#0a0a0a;--card-bg:#151515;--text-main:#f8fafc;--text-muted:#94a3b8;--accent-color:#3b82f6;--border-color:#262626;--danger-color:#ef4444;}}
::-webkit-scrollbar{{width:8px;height:8px;}}
::-webkit-scrollbar-track{{background:var(--bg-color);}}
::-webkit-scrollbar-thumb{{background:#333;border-radius:4px;}}
::-webkit-scrollbar-thumb:hover{{background:var(--text-muted);}}
*{{box-sizing:border-box;margin:0;padding:0;font-family:'Manrope',sans-serif;user-select:none;}}
input,textarea,.selectable{{user-select:text;}}
body{{background-color:var(--bg-color);color:var(--text-main);font-size:16px;min-height:100vh;overflow-x:hidden;}}
a{{color:var(--accent-color);text-decoration:none;}}

/* Сетка */
.app-layout{{display:grid;grid-template-columns:260px 1fr;min-height:100vh;width:100%;}}
.app-layout.sidebar-collapsed{{grid-template-columns:80px 1fr;}}

/* Верхняя панель */
.topbar{{grid-column:1/-1;position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:0 25px;border-bottom:1px solid var(--border-color);background:rgba(10,10,10,0.95);backdrop-filter:blur(10px);z-index:100;height:70px;}}
.topbar-left{{display:flex;align-items:center;gap:15px;flex-shrink:0;width:auto;}}
.logo{{font-size:22px;font-weight:700;color:var(--accent-color);display:flex;align-items:center;gap:10px;white-space:nowrap;}}
.logo img{{width:42px;height:38px;object-fit:contain;image-rendering:pixelated;image-rendering:crisp-edges;}}
.menu-toggle{{cursor:pointer;padding:8px;color:var(--text-muted);border-radius:6px;transition:background .2s;flex-shrink:0;}}
.menu-toggle:hover{{background:var(--card-bg);color:var(--text-main);}}

/* Поиск в центре */
.topbar-center{{position:absolute;left:50%;transform:translateX(-50%);width:100%;max-width:500px;display:flex;justify-content:center;z-index:10;}}
.search-container{{width:100%;position:relative;}}
.search-input{{width:100%;background:var(--card-bg);border:1px solid var(--border-color);padding:8px 15px 8px 36px;border-radius:8px;color:#fff;font-size:14px;outline:none;}}
.search-input:focus{{border-color:var(--accent-color);}}
.search-icon{{position:absolute;left:10px;top:8px;color:var(--text-muted);}}
.search-dropdown{{display:none;position:absolute;top:40px;left:0;width:100%;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.6);z-index:150;max-height:300px;overflow-y:auto;}}
.search-dropdown-item{{display:flex;align-items:center;gap:10px;padding:10px 15px;color:var(--text-main);border-bottom:1px solid var(--border-color);}}
.search-dropdown-item:hover{{background:#2a2a2a;}}

.topbar-right{{display:flex;align-items:center;justify-content:flex-end;gap:15px;flex-shrink:0;width:auto;}}

.btn-primary{{background-color:var(--accent-color);color:#fff;border:none;padding:10px 20px;border-radius:8px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-size:15px;transition:opacity .2s;}}
.btn-primary:hover{{opacity:.9;}}
.btn-primary:disabled{{opacity:0.5;cursor:not-allowed;}}
.user-menu-container{{position:relative;}}
.user-menu-btn{{display:flex;align-items:center;gap:12px;cursor:pointer;padding:4px;border-radius:50%;border:none;outline:none;}}
.user-menu-btn:hover{{background:var(--card-bg);}}
.user-avatar-small{{width:36px;height:36px;border-radius:50%!important;object-fit:cover;background:#333;display:block;}}
.dropdown-menu{{display:none;position:absolute;right:0;top:50px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;width:240px;box-shadow:0 10px 30px rgba(0,0,0,.6);z-index:200;overflow:hidden;}}
.dropdown-header{{padding:15px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--border-color);}}
.dropdown-header img{{width:44px;height:44px;border-radius:50%!important;object-fit:cover;}}
.dropdown-header div{{display:flex;flex-direction:column;}}
.dropdown-header .name{{font-weight:700;font-size:15px;}}
.dropdown-header .login{{font-size:13px;color:var(--text-muted);}}
.dropdown-item{{display:flex;align-items:center;gap:12px;padding:14px 15px;color:var(--text-main);font-size:15px;}}
.dropdown-item:hover{{background:#2a2a2a;}}
.dropdown-item.danger{{color:var(--danger-color);border-top:1px solid var(--border-color);}}

/* Сайдбар */
.sidebar{{grid-column:1;position:sticky;top:70px;border-right:1px solid var(--border-color);padding:20px 0;display:flex;flex-direction:column;gap:8px;height:calc(100vh - 70px);overflow-y:auto;transition:padding .3s;}}
.sidebar a{{color:var(--text-muted);padding:12px 25px;display:flex;align-items:center;gap:15px;font-size:16px;font-weight:500;transition:all .2s;white-space:nowrap;overflow:hidden;}}
.sidebar a:hover:not(.active),.sidebar a.active{{color:var(--text-main);background-color:var(--card-bg);}}
.sidebar a.active svg{{color:var(--accent-color);}}
.app-layout.sidebar-collapsed .sidebar{{padding:20px 0;align-items:center;}}
.app-layout.sidebar-collapsed .sidebar a{{justify-content:center;padding:15px 0;width:100%;}}
.app-layout.sidebar-collapsed .sidebar a span{{display:none;}}

/* Баннер eblo.id от края до края */
.sidebar-bottom-banner{{margin-top:auto;display:block;width:100%;padding:0;transition:opacity .2s;}}
.sidebar-bottom-banner img{{width:100%;height:auto;display:block;object-fit:contain;image-rendering:pixelated;image-rendering:crisp-edges;border-radius:0;}}
.sidebar-bottom-banner:hover{{opacity:0.8;}}
.app-layout.sidebar-collapsed .sidebar-bottom-banner img{{object-fit:cover;height:100px;}} /* В свернутом виде делаем квадратным */

/* Основной контент */
.main-content{{grid-column:2;padding:30px;display:flex;flex-direction:column;min-height:calc(100vh - 70px);width:100%;max-width:100%;}}
.auth-container{{display:flex;justify-content:center;align-items:center;flex:1;}}
.auth-form{{background-color:var(--card-bg);padding:40px;border-radius:16px;width:100%;max-width:450px;border:1px solid var(--border-color);}}
.auth-form h2{{text-align:center;margin-bottom:25px;font-weight:700;font-size:24px;}}
.input-group{{margin-bottom:15px;position:relative;width:100%;}}
.input-group input,.input-group select,.input-group textarea{{width:100%;padding:14px 16px;background-color:var(--bg-color);border:1px solid var(--border-color);border-radius:8px;color:white;font-size:16px;outline:none;}}
.input-group input:focus,.input-group select:focus,.input-group textarea:focus{{border-color:var(--accent-color);}}
.input-group textarea{{resize:none;max-height:250px;overflow-y:auto;}}
.pass-toggle{{position:absolute;right:15px;top:15px;cursor:pointer;color:var(--text-muted);}}
.error{{color:var(--danger-color);text-align:center;margin-bottom:15px;font-size:15px;}}

/* Валидация */
.val-list{{list-style:none;margin-top:8px;padding:0;display:flex;flex-direction:column;gap:4px;}}
.val-item{{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);transition:color .2s;}}
.val-item .icon-cross{{display:block;}}
.val-item .icon-check{{display:none;}}
.val-item.valid{{color:#22c55e;}}
.val-item.valid .icon-cross{{display:none;}}
.val-item.valid .icon-check{{display:block;}}

/* Профиль */
.profile-header{{margin-bottom:30px;display:flex;align-items:center;gap:25px;position:relative;width:100%;}}
.profile-avatar{{width:140px;height:140px;border-radius:50%!important;object-fit:cover;background:#333;}}
.profile-details h1{{font-size:32px;margin-bottom:5px;font-weight:700;line-height:1.2;}}
.profile-details p{{color:var(--text-muted);font-size:16px;}}

/* Табы профиля */
.profile-tabs{{display:flex; gap:20px; border-bottom:1px solid var(--border-color); margin-bottom:25px;}}
.profile-tab-btn{{background:none; border:none; color:var(--text-muted); font-size:18px; font-weight:700; padding:10px 5px; cursor:pointer; border-bottom:3px solid transparent; transition:all .2s;}}
.profile-tab-btn.active{{color:#fff; border-bottom-color:var(--accent-color);}}
.profile-tab-content{{display:none;}}
.profile-tab-content.active{{display:block;}}

/* Пост */
.post-view{{display:flex;gap:30px;width:100%;max-width:1400px;margin:0 auto;padding:0 20px;align-items:flex-start;}}
.post-media{{flex:1.5;background:#000;border-radius:12px;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative;cursor:zoom-in;max-height:75vh;min-height:400px;aspect-ratio:16/9;}}
.post-media img{{max-width:100%;max-height:100%;object-fit:contain;width:100%;height:100%;}}
.carousel-nav-btn{{position:absolute;top:40%;transform:translateY(-50%);background:rgba(0,0,0,0.6);color:#fff;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10;transition:background 0.2s;border:none;}}
.carousel-nav-btn:hover{{background:rgba(0,0,0,0.9);}}
.carousel-nav-btn.left{{left:15px;}}
.carousel-nav-btn.right{{right:15px;}}
.post-details{{flex:1;min-width:320px;display:flex;flex-direction:column;padding:0;}}
.post-top-info{{flex-shrink:0;}}
.post-author{{display:flex;align-items:center;gap:12px;margin-bottom:15px;}}
.post-author img{{width:48px;height:48px;border-radius:50%!important;}}
.post-title{{font-size:26px;font-weight:700;margin-bottom:10px;}}
.post-desc{{color:#ccc;font-size:16px;margin-bottom:15px;white-space:pre-wrap;line-height:1.5;}}

/* Кнопки */
.actions-row{{display:flex;align-items:center;gap:10px;margin-top:10px;margin-bottom:25px;flex-wrap:wrap;flex-shrink:0;}}
.vote-controls{{display:flex;align-items:center;gap:12px;background:var(--bg-color);padding:0 12px;border-radius:8px;border:1px solid var(--border-color);height:40px;}}
.vote-btn{{background:none;border:none;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;transition:color .2s;height:100%;}}
.vote-btn.active-up{{color:var(--accent-color);}}
.vote-btn.active-down{{color:var(--danger-color);}}
.vote-count{{font-weight:700;font-size:18px;min-width:20px;text-align:center;line-height:1;}}
.action-btn{{background:var(--bg-color);border:1px solid var(--border-color);color:var(--text-muted);padding:0 12px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:5px;text-decoration:none;height:40px;transition:background .2s;}}
.action-btn:hover{{background:#333;color:#fff;}}
.action-btn svg{{width:20px;height:20px;}}
form .action-btn{{height:100%;width:100%;}}

/* Комментарии */
.comments-section{{flex:1;min-height:0;border-top:1px solid var(--border-color);padding-top:20px;}}

/* Лента (4 колонки на ПК) */
.feed-grid{{display:grid;grid-template-columns:repeat(4, 1fr);gap:20px;width:100%;}}
@media (max-width:1600px){{.feed-grid{{grid-template-columns:repeat(3, 1fr);}}}}
@media (max-width:1200px){{.feed-grid{{grid-template-columns:repeat(2, 1fr);}}}}
.feed-card{{background:var(--card-bg);border-radius:12px;overflow:hidden;border:1px solid var(--border-color);display:flex;flex-direction:column;position:relative;transition:border-color .2s;width:100%;}}
.feed-card:hover{{border-color:#444;}}
.feed-card-img-container{{width:100%;height:240px;background:#000;overflow:hidden;display:flex;align-items:center;justify-content:center;}}
.feed-card-img-container img{{width:100%;height:100%;object-fit:cover;}}
.feed-card-info{{padding:15px;flex:1;display:flex;flex-direction:column;gap:10px;}}
.feed-card-title{{font-weight:700;font-size:18px;line-height:1.3;}}
.feed-card-meta{{display:flex;align-items:center;justify-content:space-between;font-size:14px;color:var(--text-muted);margin-top:auto;}}
.feed-card-author{{display:flex;align-items:center;gap:8px;}}
.post-date{{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-muted);}}
.feed-card-remove-btn{{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.7);border:none;color:#fff;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10;}}
.feed-card-remove-btn:hover{{background:var(--danger-color);}}
.post-badge{{position:absolute;top:10px;left:10px;background:rgba(0,0,0,0.75);color:var(--accent-color);padding:6px;border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:10;border:1px solid var(--accent-color);box-shadow:0 2px 5px rgba(0,0,0,0.5);}}

/* Создание поста */
.create-layout{{display:flex;gap:30px;width:100%;}}
.dropzone{{flex:2;border:2px dashed var(--border-color);border-radius:16px;padding:50px;text-align:center;color:var(--text-muted);display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:400px;cursor:pointer;width:100%;}}
.dropzone.dragover{{border-color:var(--accent-color);background:rgba(59,130,246,.05);}}
.file-preview{{display:flex;align-items:center;gap:15px;background:var(--bg-color);padding:10px;border-radius:8px;border:1px solid var(--border-color);margin-top:15px;width:100%;text-align:left;cursor:default;}}
.file-preview img{{width:50px;height:50px;object-fit:cover;border-radius:6px;}}
.create-sidebar{{flex:1;background:var(--card-bg);padding:30px;border-radius:16px;border:1px solid var(--border-color);display:flex;flex-direction:column;gap:15px;width:100%;}}
.switch{{position:relative;display:inline-block;width:50px;height:28px;}}
.switch input{{opacity:0;width:0;height:0;}}
.slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:var(--border-color);transition:.4s;border-radius:34px;}}
.slider:before{{position:absolute;content:"";height:20px;width:20px;left:4px;bottom:4px;background-color:white;transition:.4s;border-radius:50%;}}
input:checked+.slider{{background-color:var(--accent-color);}}
input:checked+.slider:before{{transform:translateX(22px);}}

/* Оверлеи (ПОЧИНЕН ПРОСМОТР КАРТИНОК + ЗУМ) */
.overlay{{display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,.95);z-index:9999;justify-content:center;align-items:center;flex-direction:column;padding:20px;overflow:hidden;}}
.overlay img{{max-width:100%;max-height:90vh;object-fit:contain;border-radius:8px;box-shadow:0 0 20px rgba(0,0,0,0.5);transition:transform 0.1s ease-out; cursor:grab;}}
.overlay img:active{{cursor:grabbing;}}
.close-overlay{{position:absolute;top:15px;right:20px;font-size:40px;color:#fff;cursor:pointer;background:none;border:none;z-index:10000;line-height:1;}}

/* Модалки (ПОЧИНЕН WELCOME) */
.modal-box{{background:var(--card-bg);padding:30px;border-radius:16px;border:1px solid var(--border-color);width:90%;max-width:400px;display:flex;flex-direction:column;gap:20px;text-align:center;}}
.modal-box h3{{font-weight:700;font-size:20px;}}
.modal-box p{{color:var(--text-muted);}}
.modal-actions{{display:flex;gap:10px;}}
.modal-actions button{{flex:1;padding:12px;justify-content:center;}}

.welcome-modal-content{{text-align:left; max-width:500px; width: 100%; max-height:80vh; overflow-y:auto; padding: 25px; align-items: stretch;}}
.welcome-modal-content h2{{text-align:center; margin-bottom:15px; color:var(--accent-color);}}
.welcome-modal-content p{{margin-bottom:20px; line-height:1.5; text-align:left;}}
.welcome-modal-content .faq-section{{background:var(--bg-color); padding:15px; border-radius:12px; border:1px solid var(--border-color); margin-bottom:20px; width: 100%;}}
.welcome-modal-content .faq-section h4{{margin-bottom:10px; font-size:16px; color:#fff;}}
.welcome-modal-content .faq-section ul{{list-style:none; padding:0; display:flex; flex-direction:column; gap:10px;}}
.welcome-modal-content .faq-section li{{font-size:14px; color:#ddd; line-height: 1.4;}}
.welcome-modal-content .faq-section li strong{{color:#fff; display:block; margin-bottom:2px;}}

/* Утилиты */
.toast{{position:fixed;top:80px;right:20px;background:var(--card-bg);color:#fff;padding:12px 24px;border-radius:30px;border:1px solid var(--accent-color);font-weight:500;z-index:10000;opacity:0;transition:opacity .3s,transform .3s;pointer-events:none;}}
.toast.show{{opacity:1;transform:translateY(10px);}}
.bottom-nav{{display:none;position:fixed;bottom:0;left:0;width:100%;background:rgba(10,10,10,0.95);backdrop-filter:blur(10px);border-top:1px solid var(--border-color);justify-content:space-around;padding:12px 0;padding-bottom:max(12px, env(safe-area-inset-bottom));z-index:100;}}
.bottom-nav a{{display:flex;flex-direction:column;align-items:center;color:var(--text-muted);width:60px;text-decoration:none;}}
.bottom-nav a.active{{color:var(--accent-color);}}
.bottom-nav a svg{{width:28px;height:28px;}}
.mobile-profile-menu{{display:none;position:fixed;bottom:0;left:0;width:100%;background:var(--card-bg);z-index:1000;border-top-left-radius:20px;border-top-right-radius:20px;padding:20px;transform:translateY(100%);transition:transform .3s;flex-direction:column;gap:15px;padding-bottom:env(safe-area-inset-bottom,20px);box-shadow:0 -5px 20px rgba(0,0,0,.5);}}
.mobile-profile-menu.open{{transform:translateY(0);display:flex;}}
.mobile-profile-header{{display:flex;align-items:center;gap:15px;margin-bottom:10px;padding-bottom:15px;border-bottom:1px solid var(--border-color);}}
.mobile-profile-header img{{width:50px;height:50px;border-radius:50%!important;object-fit:cover;}}
.mobile-menu-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:999;}}

/* Настройки */
.editor-card{{background:var(--card-bg);border-radius:16px;border:1px solid var(--border-color);padding:30px;display:flex;flex-direction:column;gap:15px;width:100%;max-width:600px;margin:0 auto;}}
.avatar-edit-container{{position:relative;width:120px;height:120px;margin:0 auto;cursor:pointer;border-radius:50%;overflow:hidden;border:2px solid var(--border-color);}}
.avatar-edit-container:hover{{border-color:var(--accent-color);}}
.avatar-edit-container img{{width:100%;height:100%;object-fit:cover;}}
.avatar-edit-overlay{{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;color:#fff;opacity:0;transition:opacity .2s;}}
.avatar-edit-container:hover .avatar-edit-overlay{{opacity:1;}}
.tabs{{display:flex;gap:10px;margin-bottom:20px;border-bottom:1px solid var(--border-color);padding-bottom:10px;width:100%;}}
.tab-btn{{background:none;border:none;color:var(--text-muted);font-size:16px;font-weight:500;cursor:pointer;padding:10px 15px;border-radius:8px;}}
.tab-btn.active{{color:var(--accent-color);background:var(--card-bg);}}

.mobile-only{{display:none!important;}}
.desktop-only{{display:flex!important;}}

@media(max-width:1024px){{.app-layout{{grid-template-columns:220px 1fr;}}.app-layout.sidebar-collapsed{{grid-template-columns:80px 1fr;}}}}

@media(max-width:900px){{
    .app-layout{{display:flex;flex-direction:column;width:100%;min-height:100vh;overflow-x:hidden;}}
    .topbar{{position:fixed;top:0;left:0;width:100%;height:60px;padding:0 15px;gap:10px;z-index:100;}}
    .topbar-left{{width:auto;}}
    .topbar-center{{position:relative;left:auto;transform:none;max-width:100%;flex:1;margin-left:10px;}}
    .topbar-right{{width:auto;}}
    .logo span{{display:none;}}
    .logo img{{width:32px;height:28px;}}
    .menu-toggle{{display:none!important;}}
    .search-container{{max-width:100%;width:100%;}}
    .topbar-right .user-menu-container{{display:none!important;}}
    .sidebar{{display:none;}}
    
    .main-content{{margin-top:60px;width:100%;max-width:100vw;padding:0 0 80px 0;display:flex;flex-direction:column;}}
    .bottom-nav{{display:flex;}}
    
    .profile-header{{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:30px 15px;margin:0;width:100%;position:relative;}}
    .profile-avatar{{width:100px!important;height:100px!important;border-radius:50%!important;object-fit:cover;margin:0 0 15px 0;}}
    .profile-details{{display:flex;flex-direction:column;align-items:center;width:100%;}}
    .profile-details h1{{font-size:24px;text-align:center;margin-bottom:5px;word-break:break-word;}}
    .profile-details p{{font-size:14px;text-align:center;}}
    .profile-header > div:last-child{{position:absolute;top:20px;right:15px;margin:0!important;}}
    .profile-tabs{{padding:0 15px;width:100%;display:flex;border-bottom:1px solid var(--border-color);margin-bottom:0;}}
    
    .feed-grid{{display:flex;flex-direction:column;width:100%;gap:0;padding:0;margin:0;}}
    .feed-card{{width:100%;border-radius:0;border-left:none;border-right:none;border-top:none;border-bottom:1px solid var(--border-color);background:transparent;margin:0;}}
    .feed-card:hover{{border-bottom-color:var(--border-color);}}
    .feed-card-img-container{{width:100%;height:auto;aspect-ratio:4/3;}}
    .feed-card-info{{padding:15px;width:100%;}}
    .feed-card-meta{{flex-wrap:wrap;gap:10px;}}
    
    .editor-card{{width:100%!important;max-width:100%!important;padding:20px 15px!important;margin:0!important;border-radius:0;border-left:none;border-right:none;}}
    .tabs{{padding:0 15px;margin-bottom:0;border-bottom:none;}}
    .tab-content{{padding:15px;}}
    
    .create-layout{{flex-direction:column;width:100%!important;padding:15px;gap:15px;}}
    .dropzone{{width:100%!important;max-width:100%!important;flex:none!important;padding:30px 15px!important;min-height:200px!important;}}
    .create-sidebar{{width:100%!important;max-width:100%!important;flex:none!important;padding:15px!important;}}
    
    .post-view{{display:flex;flex-direction:column;padding:0;gap:15px;height:auto;width:100%;}}
    .post-header-actions{{padding:15px!important;background:transparent!important;border-bottom:1px solid var(--border-color);}}
    .post-media{{flex:none;width:100%;height:auto;aspect-ratio:4/3;max-height:60vh;border-radius:0!important;margin-bottom:0;border-bottom:1px solid var(--border-color);}}
    .carousel-nav-btn{{top:45%;width:36px;height:36px;}}
    .post-details{{flex:none;width:100%;min-width:0;display:flex;flex-direction:column;padding:15px;}}
    .post-title{{font-size:22px;}}
    .actions-row{{flex-wrap:wrap;gap:10px;margin-top:15px;margin-bottom:15px;padding:0;}}
    .comments-section{{width:100%;padding:15px 0;border-top:1px solid var(--border-color);flex:none;}}
    
    .toast{{top:20px;left:50%;right:auto;transform:translateX(-50%);}}
    .toast.show{{transform:translateX(-50%) translateY(10px);}}
    .mobile-only{{display:flex!important;}}
    .desktop-only{{display:none!important;}}
    .auth-container{{padding:15px;}}
    .auth-form{{width:100%;max-width:100%;padding:20px;}}
}}
</style>
"""

JS_SCRIPT = """
<script>
var filesList=[];
var currentImage=null;
var currentZoom=1;

// --- ЛОГИКА ЗУМА И ПЕРЕМЕЩЕНИЯ КАРТИНКИ ---
var panoImg = null;
var panoScale = 1;
var panoX = 0, panoY = 0;
var isDragging = false;
var startX, startY;

function openPanorama(src) {
    var img = document.getElementById('panorama-img');
    var pano = document.getElementById('panorama');
    if(img) {
        img.src = src;
        panoImg = img;
        panoScale = 1;
        panoX = 0; panoY = 0;
        updatePanoTransform();
    }
    if(pano) pano.style.display='flex';
}

function closePanorama() {
    var pano = document.getElementById('panorama');
    if(pano) pano.style.display='none';
}

function updatePanoTransform() {
    if(panoImg) {
        panoImg.style.transform = `translate(${panoX}px, ${panoY}px) scale(${panoScale})`;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var pano = document.getElementById('panorama');
    if(pano) {
        pano.addEventListener('wheel', function(e) {
            e.preventDefault();
            if(!panoImg) return;
            var delta = e.deltaY > 0 ? -0.1 : 0.1;
            panoScale = Math.max(0.5, Math.min(5, panoScale + delta));
            updatePanoTransform();
        });

        pano.addEventListener('mousedown', function(e) {
            if(e.target === panoImg) {
                isDragging = true;
                startX = e.clientX - panoX;
                startY = e.clientY - panoY;
                panoImg.style.cursor = 'grabbing';
            }
        });

        window.addEventListener('mousemove', function(e) {
            if(isDragging && panoImg) {
                panoX = e.clientX - startX;
                panoY = e.clientY - startY;
                updatePanoTransform();
            }
        });

        window.addEventListener('mouseup', function() {
            if(isDragging) {
                isDragging = false;
                if(panoImg) panoImg.style.cursor = 'grab';
            }
        });

        var touchStartX = 0, touchStartY = 0;
        pano.addEventListener('touchstart', function(e) {
            if(e.target === panoImg && e.touches.length === 1) {
                isDragging = true;
                touchStartX = e.touches[0].clientX - panoX;
                touchStartY = e.touches[0].clientY - panoY;
            }
        });

        pano.addEventListener('touchmove', function(e) {
            if(isDragging && panoImg && e.touches.length === 1) {
                panoX = e.touches[0].clientX - touchStartX;
                panoY = e.touches[0].clientY - touchStartY;
                updatePanoTransform();
            }
        });

        pano.addEventListener('touchend', function() {
            isDragging = false;
        });
    }
});

// --- ОСТАЛЬНАЯ ЛОГИКА ---
function applySidebarState(){
    var layout=document.querySelector('.app-layout');
    if(!layout)return;
    if(localStorage.getItem('sidebar_collapsed')==='true') layout.classList.add('sidebar-collapsed');
    else layout.classList.remove('sidebar-collapsed');
}

function toggleSidebar(){
    var layout=document.querySelector('.app-layout');
    if(!layout)return;
    layout.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebar_collapsed',layout.classList.contains('sidebar-collapsed'));
}

function toggleDropdown(){
    if(window.innerWidth<=900){
        document.getElementById('mobileProfileMenu').classList.add('open');
        document.getElementById('mobileMenuOverlay').style.display='block';
    }else{
        var dropdown=document.getElementById("user-dropdown");
        if(dropdown)dropdown.style.display=dropdown.style.display==="block"?"none":"block";
    }
}

function closeMobileMenu(){
    document.getElementById('mobileProfileMenu').classList.remove('open');
    document.getElementById('mobileMenuOverlay').style.display='none';
}

function togglePassword(el){
    var input=el.previousElementSibling;
    var eyeOpen=el.querySelector('.eye-open');
    var eyeClosed=el.querySelector('.eye-closed');
    if(input.type==="password"){ input.type="text"; eyeOpen.style.display="none"; eyeClosed.style.display="block"; }
    else { input.type="password"; eyeOpen.style.display="block"; eyeClosed.style.display="none"; }
}

var searchTimeout;
function handleSearch(query){
    clearTimeout(searchTimeout);
    var dropdown=document.getElementById('searchDropdown');
    if(!dropdown)return;
    if(!query.trim()){ dropdown.style.display='none'; return; }
    searchTimeout=setTimeout(async()=>{
        var res=await fetch('/api/search?q='+encodeURIComponent(query));
        var data=await res.json();
        if(data.results&&data.results.length>0){
            dropdown.innerHTML=data.results.map(p=>`<a href="/${p.id}" class="search-dropdown-item"><div style="font-weight:700;font-size:14px;">${p.title}</div><div style="color:var(--text-muted);font-size:12px;margin-left:auto;">@${p.author}</div></a>`).join('');
        }else{ dropdown.innerHTML='<div style="padding:15px;color:var(--text-muted);font-size:14px;text-align:center;">'+window.TRANSLATIONS.nothing_found+'</div>'; }
        dropdown.style.display='block';
    },300);
}

function compressImage(file, maxWidth = 1920, maxHeight = 1920) {
    return new Promise((resolve, reject) => {
        if (!file.type.startsWith('image/')) return resolve(file);
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = event => {
            const img = new Image();
            img.src = event.target.result;
            img.onload = () => {
                let width = img.width;
                let height = img.height;
                if (width > maxWidth) { height = Math.round(height * maxWidth / width); width = maxWidth; }
                if (height > maxHeight) { width = Math.round(width * maxHeight / height); height = maxHeight; }
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);
                canvas.toBlob(blob => {
                    const newFile = new File([blob], file.name.replace(/\.[^/.]+$/, "") + ".jpg", { type: 'image/jpeg', lastModified: Date.now() });
                    resolve(newFile);
                }, 'image/jpeg', 0.85);
            };
            img.onerror = error => reject(error);
        };
        reader.onerror = error => reject(error);
    });
}

async function handleFiles(input){
    if(!input.files)return;
    var newFiles=Array.from(input.files);
    for(var i=0;i<newFiles.length;i++){
        if(filesList.length<3) {
            var compressed = await compressImage(newFiles[i]);
            filesList.push(compressed);
        } else { 
            showToast(window.TRANSLATIONS.max_files); 
            break; 
        }
    }
    input.value=''; updateInputAndRender();
}

function removeFile(index,event){
    if(event){event.stopPropagation();event.preventDefault();}
    filesList.splice(index,1); updateInputAndRender();
}

function updateInputAndRender(){
    var dt=new DataTransfer(); filesList.forEach(f=>dt.items.add(f));
    var fileInput=document.getElementById('file-input'); if(fileInput)fileInput.files=dt.files;
    var previewContainer=document.getElementById('file-list'); if(!previewContainer)return;
    previewContainer.innerHTML='';
    var dropText=document.getElementById('dropzone-text');
    if(filesList.length===0){ if(dropText)dropText.style.display='flex'; }
    else{
        if(dropText)dropText.style.display='none';
        filesList.forEach((file,index)=>{
            var reader=new FileReader();
            reader.onload=function(e){
                var div=document.createElement('div'); div.className='file-preview';
                div.onclick=(e)=>e.stopPropagation();
                div.innerHTML='<img src="'+e.target.result+'"><div style="flex:1;overflow:hidden;"><div style="font-size:14px;color:#fff;font-weight:500;text-overflow:ellipsis;white-space:nowrap;overflow:hidden;">'+file.name+'</div><div style="font-size:12px;color:var(--text-muted);">'+(file.size/1024).toFixed(1)+' KB</div></div><span style="cursor:pointer;color:var(--text-muted);font-size:24px;padding:0 10px;" onclick="removeFile('+index+', event)">×</span>';
                previewContainer.appendChild(div);
            }; reader.readAsDataURL(file);
        });
    }
}

document.addEventListener('paste', async function(e) {
    if (!document.getElementById('file-input')) return; 

    var items = (e.clipboardData || e.originalEvent.clipboardData).items;
    var imageFile = null;
    
    for (var index = 0; index < items.length; index++) {
        if (items[index].kind === 'file' && items[index].type.includes('image/')) {
            imageFile = items[index].getAsFile();
            break;
        }
    }

    if (imageFile) {
        e.preventDefault();
        if (filesList.length < 3) {
            var file = new File([imageFile], "pasted_" + Date.now() + ".png", { type: imageFile.type });
            var compressed = await compressImage(file);
            filesList.push(compressed);
            updateInputAndRender();
        } else {
            showToast(window.TRANSLATIONS.max_files);
        }
    }
});

function setVisibility(val){
    document.getElementById('vis-input').value=val;
    var btnFeed=document.getElementById('btn-feed'), btnLink=document.getElementById('btn-link');
    if(val==='feed'){
        btnFeed.style.borderColor='var(--accent-color)'; btnFeed.style.color='var(--accent-color)';
        btnLink.style.borderColor='var(--border-color)'; btnLink.style.color='var(--text-muted)';
    }else{
        btnFeed.style.borderColor='var(--border-color)'; btnFeed.style.color='var(--text-muted)';
        btnLink.style.borderColor='var(--accent-color)'; btnLink.style.color='var(--accent-color)';
    }
}

function showToast(message){
    var toast=document.getElementById('toast'); if(!toast)return;
    toast.innerText=message; toast.classList.add('show');
    setTimeout(()=>{toast.classList.remove('show')},3000);
}

function showConfirm(title, desc, onConfirm){
    var modal=document.getElementById('confirm-modal'); if(!modal)return;
    document.getElementById('confirm-title').innerText=title;
    document.getElementById('confirm-desc').innerText=desc;
    var btn=document.getElementById('confirm-btn'), newBtn=btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn,btn);
    newBtn.onclick=function(){ modal.style.display='none'; onConfirm(); };
    modal.style.display='flex';
}

function copyLink(){ navigator.clipboard.writeText(window.location.href); showToast(window.TRANSLATIONS.link_copied); }

function loadAvatar(event){
    var file=event.target.files[0]; if(!file)return;
    var reader=new FileReader();
    reader.onload=function(e){
        var img=new Image();
        img.onload=function(){
            currentImage=img; currentZoom=1;
            document.getElementById('zoom-slider').value=1;
            drawCropCanvas();
            document.getElementById('crop-modal').style.display='flex';
        }; img.src=e.target.result;
    }; reader.readAsDataURL(file);
}

function drawCropCanvas(){
    if(!currentImage)return;
    var canvas=document.getElementById('crop-canvas'), ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    var scale=Math.max(canvas.width/currentImage.width,canvas.height/currentImage.height)*currentZoom;
    var x=(canvas.width-currentImage.width*scale)/2, y=(canvas.height-currentImage.height*scale)/2;
    ctx.drawImage(currentImage,x,y,currentImage.width*scale,currentImage.height*scale);
}

function applyCrop(){
    var canvas=document.getElementById('crop-canvas');
    var dataUrl=canvas.toDataURL('image/jpeg',0.8);
    document.getElementById('avatar-base64').value=dataUrl;
    document.getElementById('avatar-preview').src=dataUrl;
    document.getElementById('crop-modal').style.display='none';
}

async function vote(postId,action){
    var upBtn=document.getElementById('btn-up'), downBtn=document.getElementById('btn-down');
    if(upBtn) upBtn.disabled = true;
    if(downBtn) downBtn.disabled = true;
    
    var res=await fetch('/api/vote/'+postId+'/'+action,{method:'POST'}); var data=await res.json();
    
    if(upBtn) upBtn.disabled = false;
    if(downBtn) downBtn.disabled = false;
    
    if(data.error)return showToast(data.error);
    var count=document.getElementById('vote-count'); if(count)count.innerText=data.score;
    if(upBtn)upBtn.className='vote-btn '+(data.user_vote===1?'active-up':'');
    if(downBtn)downBtn.className='vote-btn '+(data.user_vote===-1?'active-down':'');
}

async function toggleSave(postId,redirectToSaved=false){
    var res=await fetch('/api/save/'+postId,{method:'POST'}); var data=await res.json();
    if(data.error)return showToast(data.error);
    if(redirectToSaved){ window.location.reload(); return; }
    var btn=document.getElementById('btn-save');
    if(btn){
        if(data.saved){
            btn.innerHTML=window.SVG_SAVED;
            btn.style.color='var(--accent-color)'; btn.style.borderColor='var(--accent-color)';
        }else{
            btn.innerHTML=window.SVG_SAVE;
            btn.style.color=''; btn.style.borderColor='';
        }
    }
}

async function submitComment(e,postId){
    e.preventDefault();
    var input=document.getElementById('comment-input'); if(!input)return;
    var text=input.value.trim(); if(!text)return;
    var formData=new FormData(); formData.append('text',text);
    var res=await fetch('/api/comment/'+postId,{method:'POST',body:formData}); var data=await res.json();
    if(data.error)return showToast(data.error);
    if(data.comment){
        input.value=''; document.getElementById('no-comments-msg').style.display='none';
        var list=document.getElementById('comments-list');
        var ava=data.comment.avatar||'https://api.dicebear.com/7.x/avataaars/svg?seed='+data.comment.author;
        var div=document.createElement('div'); div.id='comment-'+data.comment.id;
        div.style.cssText='display:flex;gap:10px;margin-bottom:15px;justify-content:space-between;';
        div.innerHTML=`
            <div style="display:flex;gap:10px;">
                <img src="${ava}" style="width:32px;height:32px;border-radius:50%;object-fit:cover;">
                <div>
                    <div style="font-weight:700;font-size:14px;">${data.comment.display_name} <span style="color:var(--text-muted);font-weight:400;font-size:12px;">@${data.comment.author}</span></div>
                    <div style="font-size:14px;margin-top:2px;">${data.comment.text}</div>
                </div>
            </div>
            <button onclick="confirmDeleteComment('${postId}', '${data.comment.id}')" style="background:none;border:none;color:var(--danger-color);cursor:pointer;font-size:12px;padding:5px;">${window.TRANSLATIONS.delete}</button>
        `;
        list.appendChild(div);
        document.getElementById('comment-count').innerText=data.total_comments;
    }
}

function confirmDeleteComment(postId,commentId){
    showConfirm(window.TRANSLATIONS.delete, window.TRANSLATIONS.delete_comment_confirm, async function(){
        var res=await fetch('/api/comment/'+postId+'/'+commentId,{method:'DELETE'}); var data=await res.json();
        if(data.success){
            document.getElementById('comment-'+commentId).remove();
            document.getElementById('comment-count').innerText=data.total_comments;
            if(data.total_comments===0) document.getElementById('no-comments-msg').style.display='block';
        }else{ showToast(data.error||'Error'); }
    });
}

function confirmLogout(e){ e.preventDefault(); showConfirm(window.TRANSLATIONS.logout, window.TRANSLATIONS.logout_confirm, ()=>window.location.href='/logout'); }

function confirmDeletePost(e, postId){
    e.preventDefault();
    showConfirm(window.TRANSLATIONS.delete, window.TRANSLATIONS.delete_confirm, function(){
        fetch('/delete/' + postId, { method: 'POST' })
        .then(() => { window.location.href = '/'; })
        .catch(() => showToast('Error deleting post'));
    });
}

function switchTab(tabId){
    document.querySelectorAll('.tab-btn').forEach(btn=>btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(el=>el.style.display='none');
    document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
    document.getElementById('tab-'+tabId).style.display='block';
}

function switchProfileTab(tabId) {
    document.querySelectorAll('.profile-tab-btn').forEach(btn=>btn.classList.remove('active'));
    document.querySelectorAll('.profile-tab-content').forEach(el=>el.classList.remove('active'));
    document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
    document.getElementById('profile-'+tabId).classList.add('active');
}

function validatePassword(val) {
    var itemLen = document.querySelector('[data-rule="p_len"]');
    var itemLatin = document.querySelector('[data-rule="p_latin"]');

    if(!itemLen) return;

    itemLen.classList.toggle('valid', val.length >= 6);
    var isLatin = /^[a-zA-Z0-9!@@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]+$/.test(val) && val.length > 0;
    itemLatin.classList.toggle('valid', isLatin);
}

var usernameTimeout;
function validateUsername(val) {
    var itemAvail = document.querySelector('[data-rule="avail"]');
    if(!itemAvail) return; 

    clearTimeout(usernameTimeout);
    if(val.length > 0) {
        usernameTimeout = setTimeout(async () => {
            try {
                var res = await fetch('/api/check_username?q=' + encodeURIComponent(val));
                var data = await res.json();
                itemAvail.classList.toggle('valid', data.available);
            } catch (e) {
                console.error(e);
            }
        }, 500);
    } else {
        itemAvail.classList.remove('valid');
    }
}

function closeWelcomeModal(){
    document.getElementById('welcome-modal').style.display='none';
    window.history.replaceState({}, document.title, window.location.pathname);
}

function checkWelcome() {
    if (window.location.search.includes('welcome=1')) {
        var welcome = document.getElementById('welcome-modal');
        if(welcome) welcome.style.display = 'flex';
    }
}

document.addEventListener('DOMContentLoaded',function(){
    applySidebarState();
    if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(err=>console.log('SW failed'));

    var userInp = document.getElementById('usernameInput');
    var passInp = document.getElementById('passwordInput');
    
    if(userInp) userInp.addEventListener('input', function() { validateUsername(this.value); });
    if(passInp) passInp.addEventListener('input', function() { validatePassword(this.value); });

    checkWelcome();
});

document.addEventListener('htmx:afterSwap', function(evt) {
    applySidebarState();
    checkWelcome();
    var carouselImgs=document.querySelectorAll('.carousel-img');
    if(carouselImgs.length>1){
        var currentImg=0;
        window.showImg=function(idx){carouselImgs.forEach((img,i)=>img.style.display=i===idx?'block':'none');};
        window.changeImg=function(dir){currentImg=(currentImg+dir+carouselImgs.length)%carouselImgs.length;window.showImg(currentImg);};
    }
});
</script>
"""

def render_layout(content_html, user, request: Request, active_page="feed", title_text=""):
    lang = get_lang(request)
    avatar_url = user.get('avatar') if user and user.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username'] if user else 'guest'}"
    current_lang_str = "RU" if lang == "ru" else "EN"
    next_lang = "ru" if lang == "en" else "en"
    switch_lang_url = f"/set_lang/{next_lang}?next={request.url.path}"
    
    page_title = f"sol-id | {title_text}" if title_text else "sol-id"
    
    translations_json = f"""<script>window.TRANSLATIONS = {json.dumps(TRANSLATIONS[lang])}; window.SVG_SAVE = `{SVG_SAVE}`; window.SVG_SAVED = `{SVG_SAVED}`;</script>"""

    if user:
        nav_right = f"""<a href="/write" class="btn-primary desktop-only" style="padding: 8px 16px;">{SVG_PLUS} {t('new_post', lang)}</a><div class="user-menu-container"><div class="user-menu-btn" onclick="toggleDropdown()"><img src="{avatar_url}" class="user-avatar-small"></div><div id="user-dropdown" class="dropdown-menu"><div class="dropdown-header"><img src="{avatar_url}"><div><span class="name">{html.escape(user['display_name'])}</span><span class="login">@{html.escape(user['username'])}</span></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="#" onclick="confirmLogout(event)" class="dropdown-item danger">{SVG_LOGOUT} {t('logout', lang)}</a></div></div>"""
    else:
        nav_right = f"""<a href="/login" class="btn-primary desktop-only" style="padding:8px 16px;">{SVG_USER} <span>{t('login', lang)}</span></a>"""
        
    lang_switch_html = f"""<a href="{switch_lang_url}" class="action-btn" style="border:none; background:var(--card-bg); padding:0 10px; color:var(--text-main); font-weight:bold;">{SVG_LANG} <span class="desktop-only" style="margin-left:5px;">{current_lang_str}</span></a>"""

    sidebar_html = ""
    if user:
        sidebar_html = f"""<div class="sidebar"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} <span>{t('feed', lang)}</span></a><a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE} <span>{t('saved', lang)}</span></a><a href="/@{user['username']}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} <span>{t('profile', lang)}</span></a><a href="https://eblo.id" target="_blank" class="sidebar-bottom-banner"><img src="{SPRITE_URL}" alt="eblo.id"></a></div>"""

    if user:
        bottom_nav = f"""<div class="bottom-nav"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED}</a><a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE}</a><a href="/write" class="{'active' if active_page == 'write' else ''}">{SVG_PLUS}</a><a href="javascript:void(0)" onclick="toggleDropdown()" class="{'active' if active_page == 'profile' else ''}">{SVG_USER}</a></div>"""
    else:
        bottom_nav = f"""<div class="bottom-nav"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED}</a><a href="/login" class="{'active' if active_page == 'login' else ''}">{SVG_USER}</a></div>"""

    html_content = f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><title>{page_title}</title>{CSS_STYLES}</head>
<body hx-boost="true" hx-target="body" hx-swap="outerHTML show:window:top">
{translations_json}
<div class="app-layout">
    <div class="topbar">
        <div class="topbar-left">
            {f'<div class="menu-toggle desktop-only" onclick="toggleSidebar()">{SVG_MENU}</div>' if user else ''}
            <a href="/" class="logo"><img src="{LOGO_URL}" alt="Logo"> <span>sol-id</span></a>
        </div>
        <div class="topbar-center">
            <div class="search-container">
                <span class="search-icon">{SVG_SEARCH}</span>
                <input type="text" id="searchInput" class="search-input" placeholder="{t('search_placeholder', lang)}" oninput="handleSearch(this.value)" autocomplete="off">
                <div id="searchDropdown" class="search-dropdown"></div>
            </div>
        </div>
        <div class="topbar-right">
            {lang_switch_html}
            {nav_right}
        </div>
    </div>
    {sidebar_html}
    <div class="main-content" style="{'grid-column: 1 / -1;' if not user else ''}">
        {content_html}
    </div>
</div>
{f'''<div id="mobileMenuOverlay" class="mobile-menu-overlay" onclick="closeMobileMenu()"></div><div id="mobileProfileMenu" class="mobile-profile-menu"><div class="mobile-profile-header"><img src="{avatar_url}"><div><div style="font-weight:700; font-size:16px;">{html.escape(user['display_name'])}</div><div style="color:var(--text-muted); font-size:14px;">@{html.escape(user['username'])}</div></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="#" onclick="confirmLogout(event)" class="dropdown-item danger">{SVG_LOGOUT} {t('logout', lang)}</a></div>''' if user else ''}
<div id="panorama" class="overlay" onclick="closePanorama()"><button class="close-overlay">&times;</button><img id="panorama-img" src="" onclick="event.stopPropagation()"></div>
<div id="confirm-modal" class="overlay" onclick="this.style.display='none'"><div class="modal-box" onclick="event.stopPropagation()"><h3 id="confirm-title"></h3><p id="confirm-desc"></p><div class="modal-actions"><button class="btn-primary" onclick="document.getElementById('confirm-modal').style.display='none'" style="background:#333;">{t('cancel', lang)}</button><button class="btn-primary" id="confirm-btn" style="background:var(--danger-color);">{t('confirm', lang)}</button></div></div></div>
<div id="welcome-modal" class="overlay" onclick="closeWelcomeModal()">
    <div class="modal-box welcome-modal-content" onclick="event.stopPropagation()">
        <h2>{t('welcome_title', lang)}</h2>
        <p>{t('welcome_desc', lang)}</p>
        <div class="faq-section">
            <h4>{t('faq_title', lang)}</h4>
            <ul>
                <li><strong>{t('faq_q1', lang)}</strong> {t('faq_a1', lang)}</li>
                <li><strong>{t('faq_q2', lang)}</strong> {t('faq_a2', lang)}</li>
                <li><strong>{t('faq_q3', lang)}</strong> {t('faq_a3', lang)}</li>
            </ul>
        </div>
        <button class="btn-primary" onclick="closeWelcomeModal()" style="width:100%; justify-content:center; padding:12px; margin-top:10px;">{t('got_it', lang)}</button>
    </div>
</div>
<div id="toast" class="toast"></div>
{bottom_nav}
{JS_SCRIPT}
</body></html>"""
    
    return html_content

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
    if lang in ["en", "ru"]: response.set_cookie(key="lang", value=lang, max_age=31536000, httponly=False)
    return response

@app.get("/api/search")
async def api_search(q: str = ""):
    q_lower = q.lower().strip()
    if not q_lower: return JSONResponse({"results": []})
    
    res = supabase.table("posts").select("*").eq("visibility", "feed").execute()
    results = []
    for p in res.data:
        if q_lower in p['title'].lower() or q_lower in p['content'].lower() or q_lower in p['author'].lower():
            results.append({"id": p['id'], "title": html.escape(p['title']), "author": html.escape(p['author'])})
    
    return JSONResponse({"results": results[:5]})

@app.get("/search", response_class=HTMLResponse)
async def search_posts(request: Request, q: str = ""):
    user = get_current_user(request)
    lang = get_lang(request)
    q_lower = q.lower().strip()
    
    res = supabase.table("posts").select("*").eq("visibility", "feed").execute()
    results = []
    if q_lower:
        for p in res.data:
            if q_lower in p['title'].lower() or q_lower in p['content'].lower() or q_lower in p['author'].lower():
                results.append(p)

    if not results:
        content = f'<div style="padding:15px;"><h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{html.escape(q)}"</h2><div style="text-align:center; padding: 60px 20px; color: var(--text-muted); font-size:18px;">{t("nothing_found", lang)}</div></div>'
    else:
        # Оптимизация: получаем авторов пачкой
        author_usernames = list(set([p['author'] for p in results]))
        res_users = supabase.table("users").select("username, avatar").in_("username", author_usernames).execute()
        users_map = {u['username']: u for u in res_users.data}

        cards = ""
        for post in results:
            author = users_map.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}" loading="lazy">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date">{SVG_CALENDAR} {date_str}</div></div></div></a>"""
        content = f'<div style="padding:15px;"><h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{html.escape(q)}"</h2><div class="feed-grid">{cards}</div></div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed", t('search_results', lang)))

@app.get("/", response_class=HTMLResponse)
async def read_feed(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    
    # Оптимизация: 1 запрос на посты
    res = supabase.table("posts").select("*").eq("visibility", "feed").order("created_at", desc=True).execute()
    feed_posts = res.data
    
    if not feed_posts:
        content = f'<div style="text-align:center; padding: 80px 20px; color: var(--text-muted);"><h3 style="font-size: 28px; color: #fff; margin-bottom: 15px;">{t("no_posts", lang)}</h3></div>'
    else:
        # Оптимизация: 1 запрос на авторов
        author_usernames = list(set([p['author'] for p in feed_posts]))
        res_users = supabase.table("users").select("username, avatar").in_("username", author_usernames).execute()
        users_map = {u['username']: u for u in res_users.data}

        cards = ""
        for post in feed_posts:
            author = users_map.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}" loading="lazy">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            
            score = len(post['votes'].get('up', [])) - len(post['votes'].get('down', []))
            arrow_icon = SVG_DOWN if score < 0 else SVG_UP
            
            date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div style="display:flex;align-items:center;gap:10px;"><div class="post-date">{SVG_CALENDAR} {date_str}</div><div style="display:flex;align-items:center;gap:4px;">{arrow_icon} {score}</div></div></div></div></a>"""
        content = f'<div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed", t('feed', lang)))

@app.get("/saved", response_class=HTMLResponse)
async def saved_posts(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    saved_ids = user.get('saved_posts', [])
    
    if not saved_ids:
        content = f"<div style='text-align:center; padding:60px; color:var(--text-muted); font-size:18px;'>{t('no_saved', lang)}</div>"
    else:
        res = supabase.table("posts").select("*").in_("id", saved_ids).execute()
        saved_posts_list = res.data
        
        author_usernames = list(set([p['author'] for p in saved_posts_list]))
        res_users = supabase.table("users").select("username, avatar").in_("username", author_usernames).execute()
        users_map = {u['username']: u for u in res_users.data}
        
        cards = ""
        for post in saved_posts_list:
            author = users_map.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}" loading="lazy">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
            cards += f"""<div class="feed-card"><button onclick="toggleSave('{post['id']}', true)" class="feed-card-remove-btn" title="{t('remove_saved', lang)}">×</button><a href="/{post['id']}" style="display:flex; flex-direction:column; flex:1;"><div class="feed-card-img-container">{img_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date">{SVG_CALENDAR} {date_str}</div></div></div></a></div>"""
        content = f'<h2 style="margin-bottom:25px; padding:15px 15px 0 15px;">{t("saved", lang)}</h2><div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "saved", t('saved', lang)))

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    lang = get_lang(request)
    content = f"""
    <div class="auth-container">
        <form class="auth-form" action="/login" method="post" hx-boost="false">
            <h2>{t('login', lang)}</h2>
            
            <div class="input-group">
                <input type="text" name="username" id="usernameInput" placeholder="{t('username', lang)}" required autocomplete="off">
                <ul class="val-list">
                    <li class="val-item" data-rule="avail">{SVG_CROSS}{SVG_CHECK} {t('val_avail', lang)}</li>
                </ul>
            </div>
            
            <div class="input-group" style="margin-top:15px;">
                <input type="password" name="password" id="passwordInput" placeholder="{t('password', lang)}" required>
                <span class="pass-toggle" onclick="togglePassword(this)">{SVG_EYE}{SVG_EYE_OFF}</span>
                <ul class="val-list">
                    <li class="val-item" data-rule="p_len">{SVG_CROSS}{SVG_CHECK} {t('val_p_len', lang)}</li>
                    <li class="val-item" data-rule="p_latin">{SVG_CROSS}{SVG_CHECK} {t('val_p_latin', lang)}</li>
                </ul>
            </div>
            
            <p style="color:var(--text-muted); font-size:13px; margin-top:20px; margin-bottom:15px;">{t('login_hint', lang)}</p>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:14px;">{SVG_USER} {t('login', lang)}</button>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, None, request, "login", t('login', lang)))

@app.post("/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    lang = get_lang(request)
    username = username.strip()
    
    if len(password) < 6 or not re.match(r"^[a-zA-Z0-9!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]+$", password):
        return HTMLResponse(content=render_layout(f'<div class="auth-container"><div class="auth-form"><div class="error">{t("invalid_pass_format", lang)}</div><a href="/login" class="btn-primary">{t("back", lang)}</a></div></div>', None, request, "login", t('login', lang)))

    res = supabase.table("users").select("*").eq("username", username).execute()
    user = res.data[0] if res.data else None
    
    is_new = False
    if user:
        if not pwd_context.verify(password, user["password"]):
            return HTMLResponse(content=render_layout(f'<div class="auth-container"><div class="auth-form"><div class="error">{t("wrong_pass", lang)}</div><a href="/login" class="btn-primary">{t("back", lang)}</a></div></div>', None, request, "login", t('login', lang)))
    else:
        supabase.table("users").insert({
            "username": username,
            "password": pwd_context.hash(password),
            "display_name": username,
            "avatar": None,
            "saved_posts": []
        }).execute()
        is_new = True
        
    session_token = str(uuid.uuid4())
    sessions[session_token] = username
    redirect_url = "/?welcome=1" if is_new else "/"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    
    # Безопасные куки
    response.set_cookie(key="session_token", value=session_token, httponly=True, samesite="lax")
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
    avatar_url = user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username']}"
    
    updated = request.query_params.get("updated")
    toast_script = f"<script>setTimeout(()=>showToast('{t('profile_updated', lang)}'), 100);</script>" if updated else ""

    content = f"""
    <div style="max-width: 800px; margin: 0 auto; width: 100%;">
        <h2 style="margin-bottom: 25px; font-weight: 700; font-size: 28px; padding: 15px 15px 0 15px;">{t('settings', lang)}</h2>
        <div class="tabs">
            <button class="tab-btn active" data-tab="profile" onclick="switchTab('profile')">{t('profile', lang)}</button>
            <button class="tab-btn" data-tab="language" onclick="switchTab('language')">{t('language', lang)}</button>
        </div>
        <div id="tab-profile" class="tab-content" style="display:block;">
            <div class="editor-card">
                <form action="/settings/profile" method="post" enctype="multipart/form-data" hx-encoding="multipart/form-data" style="display:flex; flex-direction:column; gap:15px; width: 100%;">
                    <div style="text-align:center;">
                        <div class="avatar-edit-container" onclick="document.getElementById('avatar-file').click()">
                            <img id="avatar-preview" src="{avatar_url}">
                            <div class="avatar-edit-overlay">{SVG_CAMERA}</div>
                        </div>
                        <div style="font-size:13px; color:var(--text-muted); margin-top:10px;">{t('change_avatar', lang)}</div>
                        <input type="file" id="avatar-file" name="avatar" accept="image/*" onchange="loadAvatar(event)" style="display:none;">
                        <input type="hidden" name="avatar_base64" id="avatar-base64">
                    </div>
                    <div class="input-group" style="margin-bottom:0;">
                        <label style="font-size:15px; color:var(--text-muted); margin-bottom:8px; display:block; font-weight:500;">{t('display_name', lang)}</label>
                        <input type="text" name="display_name" value="{html.escape(user['display_name'])}" required style="padding:14px;">
                    </div>
                    <button type="submit" class="btn-primary" style="justify-content:center; padding:14px; margin-top:5px;">{SVG_SETTINGS} {t('save', lang)}</button>
                </form>
            </div>
        </div>
        <div id="tab-language" class="tab-content" style="display:none; padding: 0 15px;">
            <div style="background: var(--card-bg); padding: 25px; border-radius: 16px; border: 1px solid var(--border-color);">
                <div style="display:flex; gap:10px;">
                    <a href="/set_lang/en?next=/settings" class="btn-primary" style="background:{'var(--accent-color)' if lang=='en' else '#333'};">English (EN)</a>
                    <a href="/set_lang/ru?next=/settings" class="btn-primary" style="background:{'var(--accent-color)' if lang=='ru' else '#333'};">Русский (RU)</a>
                </div>
            </div>
        </div>
    </div>
    <div id="crop-modal" class="overlay">
        <div class="crop-container" onclick="event.stopPropagation()">
            <h3 style="font-weight:700;">{t('crop_avatar', lang)}</h3>
            <canvas id="crop-canvas" width="300" height="300" class="crop-canvas" style="border-radius:50%;border:2px solid var(--accent-color);background:#000;width:100%;max-width:250px;aspect-ratio:1;"></canvas>
            <div class="crop-controls" style="display:flex;flex-direction:column;width:100%;gap:10px;">
                <label style="font-size:14px; color:var(--text-muted);">{t('zoom', lang)}</label>
                <input type="range" id="zoom-slider" min="1" max="3" step="0.05" value="1" oninput="currentZoom = parseFloat(this.value); drawCropCanvas();" style="width:100%;">
            </div>
            <div style="display:flex; gap:10px; width:100%;">
                <button type="button" onclick="document.getElementById('crop-modal').style.display='none'" class="action-btn" style="flex:1; justify-content:center; height:44px;">{t('cancel', lang)}</button>
                <button type="button" onclick="applyCrop()" class="btn-primary" style="flex:1; justify-content:center;">{t('apply', lang)}</button>
            </div>
        </div>
    </div>
    {toast_script}
    """
    return HTMLResponse(content=render_layout(content, user, request, "settings", t('settings', lang)))

@app.post("/settings/profile")
async def update_profile(request: Request, display_name: str = Form(...), avatar_base64: str = Form(None), avatar: UploadFile = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    update_data = {"display_name": html.escape(display_name)}
    if avatar_base64: 
        update_data["avatar"] = avatar_base64
    elif avatar and avatar.filename: 
        update_data["avatar"] = await image_to_base64(avatar)
        
    supabase.table("users").update(update_data).eq("username", user['username']).execute()
    return RedirectResponse(url="/settings?updated=1", status_code=status.HTTP_302_FOUND)

@app.get("/write", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    content = f"""<div style="max-width: 1100px; margin: 0 auto; width: 100%;"><h2 style="margin-bottom: 30px; font-weight: 700; font-size: 32px; padding: 15px 15px 0 15px;">{t('new_post', lang)}</h2><form action="/write" method="post" enctype="multipart/form-data" hx-encoding="multipart/form-data" class="create-layout"><div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()"><div id="dropzone-text" style="display:flex; flex-direction:column; align-items:center;">{SVG_IMAGE}<div style="margin-top:20px; font-size:20px; font-weight:700; color:#fff;">{t('upload_hint', lang)}</div><div style="margin-top:10px; font-size:15px; color:var(--text-muted);">{t('upload_limit', lang)}</div><div style="margin-top:20px; background:#2a2a2a; padding:12px 24px; border-radius:8px; color:#fff; font-weight:500; border:1px solid var(--border-color); cursor:pointer;">{t('choose_files', lang)}</div></div><div id="file-list" style="width:100%; display:flex; flex-direction:column; gap:10px;"></div><input id="file-input" type="file" name="images" multiple accept="image/*" style="display:none;" onchange="handleFiles(this)" onclick="event.stopPropagation()"></div><div class="create-sidebar"><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('title', lang)} *</label><input type="text" name="title" placeholder="{t('title', lang)}" required style="padding:14px;"></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('description', lang)} (Max 500)</label><textarea name="content" placeholder="{t('description', lang)}" maxlength="500" style="min-height:120px; padding:14px;"></textarea></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('visibility', lang)}</label><div style="display:flex; gap:10px;"><button type="button" id="btn-feed" onclick="setVisibility('feed')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--accent-color); color:var(--accent-color); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_EYE} {t('in_feed', lang)}</button><button type="button" id="btn-link" onclick="setVisibility('link')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--border-color); color:var(--text-muted); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_LINK} {t('by_link', lang)}</button></div><input type="hidden" name="visibility" id="vis-input" value="feed"></div><div class="input-group" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;"><label style="font-size:15px; font-weight:700; color:#fff;">{t('allow_comments', lang)}</label><label class="switch"><input type="checkbox" name="allow_comments" checked><span class="slider"></span></label></div><button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:16px; font-size:16px;">{SVG_PLUS} {t('publish', lang)}</button></div></form></div>"""
    return HTMLResponse(content=render_layout(content, user, request, "write", t('new_post', lang)))

@app.post("/write")
async def create_post(request: Request, title: str = Form(...), content: str = Form(""), visibility: str = Form("feed"), allow_comments: bool = Form(False), images: List[UploadFile] = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    img_b64_list = []
    if images and images[0].filename:
        for img in images[:3]:
            b64 = await image_to_base64(img)
            if b64: img_b64_list.append(b64)
            
    new_post = {
        "id": str(uuid.uuid4())[:6], 
        "author": user["username"], 
        "title": html.escape(title), 
        "content": html.escape(content), 
        "images": img_b64_list, 
        "visibility": visibility, 
        "votes": {"up": [], "down": []}, 
        "comments": [], 
        "allow_comments": allow_comments
    }
    supabase.table("posts").insert(new_post).execute()
    return RedirectResponse(url=f"/{new_post['id']}", status_code=status.HTTP_302_FOUND)

@app.post("/api/vote/{post_id}/{action}")
async def vote_post(post_id: str, action: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    res = supabase.table("posts").select("*").eq("id", post_id).execute()
    post = res.data[0] if res.data else None
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    
    username = user['username']
    up_votes, down_votes = post['votes'].get('up', []), post['votes'].get('down', [])
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
            
    score = len(up_votes) - len(down_votes)
    if username in up_votes: user_vote = 1
    elif username in down_votes: user_vote = -1
    else: user_vote = 0
    
    supabase.table("posts").update({"votes": {"up": up_votes, "down": down_votes}}).eq("id", post_id).execute()
    return JSONResponse({"score": score, "user_vote": user_vote})

@app.post("/api/save/{post_id}")
async def save_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    saved_posts = user.get('saved_posts', [])
    if post_id in saved_posts:
        saved_posts.remove(post_id)
        saved = False
    else:
        saved_posts.append(post_id)
        saved = True
        
    supabase.table("users").update({"saved_posts": saved_posts}).eq("username", user['username']).execute()
    return JSONResponse({"saved": saved})

@app.post("/api/comment/{post_id}")
async def add_comment(post_id: str, request: Request, text: str = Form(...)):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    res = supabase.table("posts").select("*").eq("id", post_id).execute()
    post = res.data[0] if res.data else None
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    if not post.get('allow_comments', True): return JSONResponse({"error": "Comments disabled"}, status_code=403)
    
    comment = {"id": str(uuid.uuid4())[:6], "author": user['username'], "display_name": html.escape(user['display_name']), "avatar": user.get('avatar'), "text": html.escape(text)}
    comments = post['comments']
    comments.append(comment)
    
    supabase.table("posts").update({"comments": comments}).eq("id", post_id).execute()
    return JSONResponse({"comment": comment, "total_comments": len(comments), "is_author": True})

@app.delete("/api/comment/{post_id}/{comment_id}")
async def delete_comment(post_id: str, comment_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    res = supabase.table("posts").select("*").eq("id", post_id).execute()
    post = res.data[0] if res.data else None
    if not post: return JSONResponse({"error": "Not found"}, status_code=404)
    
    comment = next((c for c in post['comments'] if c['id'] == comment_id), None)
    if not comment: return JSONResponse({"error": "Comment not found"}, status_code=404)
    if comment['author'] != user['username']: return JSONResponse({"error": "Forbidden"}, status_code=403)
    
    new_comments = [c for c in post['comments'] if c['id'] != comment_id]
    supabase.table("posts").update({"comments": new_comments}).eq("id", post_id).execute()
    return JSONResponse({"success": True, "total_comments": len(new_comments)})

@app.post("/delete/{post_id}")
async def delete_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    res = supabase.table("posts").select("*").eq("id", post_id).execute()
    post = res.data[0] if res.data else None
    if post and post['author'] == user['username']:
        supabase.table("posts").delete().eq("id", post_id).execute()
        
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@app.get("/@{username}", response_class=HTMLResponse)
async def view_profile(request: Request, username: str):
    current_user = get_current_user(request)
    lang = get_lang(request)
    
    res = supabase.table("users").select("*").eq("username", username).execute()
    profile_user = res.data[0] if res.data else None
    if not profile_user: raise HTTPException(404, "User not found")
    
    ava = profile_user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
    is_own_profile = current_user and current_user['username'] == username
    
    if is_own_profile: 
        res_posts = supabase.table("posts").select("*").eq("author", username).order("created_at", desc=True).execute()
    else: 
        res_posts = supabase.table("posts").select("*").eq("author", username).eq("visibility", "feed").order("created_at", desc=True).execute()
    
    user_posts = res_posts.data
    
    posts_html = ""
    for post in user_posts:
        img_html = f'<img src="{post["images"][0]}" loading="lazy">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
        badge = f'<div class="post-badge" title="{t("link_only", lang)}">{SVG_LOCK}</div>' if post.get('visibility') == 'link' else ''
        date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
        
        posts_html += f"""<a href="/{post['id']}" class="feed-card">
            {badge}
            <div class="feed-card-img-container">{img_html}</div>
            <div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div>
            <div class="feed-card-meta"><div class="post-date">{SVG_CALENDAR} {date_str}</div></div>
            </div>
        </a>"""
    if not posts_html: posts_html = f'<div style="color:var(--text-muted); font-size:18px; text-align:center; padding:40px 20px; width:100%;">{t("no_posts", lang)}</div>'
    
    saved_html = ""
    saved_ids = profile_user.get('saved_posts', [])
    if saved_ids:
        res_saved = supabase.table("posts").select("*").in_("id", saved_ids).execute()
        saved_posts_list = res_saved.data
        
        author_usernames = list(set([p['author'] for p in saved_posts_list]))
        res_users = supabase.table("users").select("username, avatar").in_("username", author_usernames).execute()
        users_map = {u['username']: u for u in res_users.data}
        
        for post in saved_posts_list:
            author = users_map.get(post['author'])
            a_ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}" loading="lazy">' if post['images'] else f'<div style="color:#555;">{SVG_IMAGE}</div>'
            date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
            saved_html += f"""<a href="/{post['id']}" class="feed-card">
                <div class="feed-card-img-container">{img_html}</div>
                <div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div>
                <div class="feed-card-meta"><div class="feed-card-author"><img src="{a_ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date">{SVG_CALENDAR} {date_str}</div></div>
                </div>
            </a>"""
    if not saved_html: saved_html = f'<div style="color:var(--text-muted); font-size:18px; text-align:center; padding:40px 20px; width:100%;">{t("no_saved", lang)}</div>'

    edit_btn = f'<div><a href="/settings" class="action-btn" style="border-radius:50%; width:44px; height:44px; padding:0; justify-content:center;" title="{t("edit_profile", lang)}">{SVG_SETTINGS}</a></div>' if is_own_profile else ''
    
    tabs_html = f"""
    <div class="profile-tabs">
        <button class="profile-tab-btn active" data-tab="posts" onclick="switchProfileTab('posts')">{t('posts', lang)}</button>
        {f'<button class="profile-tab-btn" data-tab="saved" onclick="switchProfileTab(\'saved\')">{t("saved", lang)}</button>' if is_own_profile else ''}
    </div>
    """
    
    content = f"""
    <div class="profile-header">
        <img src="{ava}" class="profile-avatar">
        <div class="profile-details">
            <h1>{html.escape(profile_user['display_name'])}</h1>
            <p>@{html.escape(username)}</p>
            <p style="margin-top:8px; font-size:15px; font-weight:500;">{len(user_posts)} {t('posts', lang)}</p>
        </div>
        {edit_btn}
    </div>
    {tabs_html}
    <div id="profile-posts" class="profile-tab-content active">
        <div class="feed-grid">{posts_html}</div>
    </div>
    {f'<div id="profile-saved" class="profile-tab-content"><div class="feed-grid">{saved_html}</div></div>' if is_own_profile else ''}
    """
    return HTMLResponse(content=render_layout(content, current_user, request, "profile", f"@{username}"))

@app.get("/{post_id}", response_class=HTMLResponse)
async def view_post(request: Request, post_id: str):
    user = get_current_user(request)
    lang = get_lang(request)
    
    res = supabase.table("posts").select("*").eq("id", post_id).execute()
    post = res.data[0] if res.data else None
    if not post: raise HTTPException(404, "Post not found")
    
    author_res = supabase.table("users").select("*").eq("username", post['author']).execute()
    author = author_res.data[0] if author_res.data else None
    ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
    
    score = len(post['votes'].get('up', [])) - len(post['votes'].get('down', []))
    user_vote = 0
    if user:
        if user['username'] in post['votes'].get('up', []): user_vote = 1
        elif user['username'] in post['votes'].get('down', []): user_vote = -1
        
    is_saved = user and post_id in user.get('saved_posts', [])
    
    save_icon_html = SVG_SAVED if is_saved else SVG_SAVE
    save_btn_style = "color:var(--accent-color); border-color:var(--accent-color);" if is_saved else ""
    
    delete_btn = f'''<button onclick="confirmDeletePost(event, '{post_id}')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; padding:8px; display:flex; align-items:center; justify-content:center; border-radius:8px;">{SVG_TRASH}</button>''' if user and user['username'] == post['author'] else ''

    if post['images']:
        imgs = "".join([f'<img src="{img}" style="width:100%; height:100%; object-fit:contain; display:{"" if i==0 else "none"};" class="carousel-img" onclick="openPanorama(this.src)">' for i, img in enumerate(post['images'])])
        nav_btns = f'<div class="carousel-nav-btn left" onclick="changeImg(-1)">{SVG_LEFT}</div><div class="carousel-nav-btn right" onclick="changeImg(1)">{SVG_RIGHT}</div>' if len(post['images']) > 1 else ''
        media_html = f"""<div class="post-media" style="position:relative;">
            {imgs}
            {nav_btns}
        </div>"""
    else: 
        media_html = f'<div class="post-media" style="display:flex; align-items:center; justify-content:center; color:#555; aspect-ratio:4/3;">{SVG_IMAGE}</div>'
    
    if post.get('allow_comments', True):
        if user: comments_input_html = f"""<form onsubmit="submitComment(event, '{post['id']}')" style="background:var(--bg-color); padding:12px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); display:flex; gap:10px;"><input type="text" id="comment-input" placeholder="{t('write_comment', lang)}" style="flex:1; background:transparent; border:none; color:#fff; outline:none; font-size:15px;"><button type="submit" class="btn-primary" style="padding:5px 15px;">{t('send', lang)}</button></form>"""
        else: comments_input_html = f"""<div style="background:var(--bg-color); padding:15px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); text-align:center;"><a href="/login" class="btn-primary" style="display:inline-flex;">{SVG_USER} {t('login_to_comment', lang)}</a></div>"""
    else: comments_input_html = f'<div style="background:rgba(239,68,68,0.1); color:var(--danger-color); padding:15px; border-radius:8px; margin-bottom:20px; text-align:center; font-weight:500;">{t("comments_disabled", lang)}</div>'
    
    comments_list_html = ""
    for c in post['comments']:
        c_ava = c.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={c['author']}"
        del_btn = f'<button onclick="confirmDeleteComment(\'{post["id"]}\', \'{c["id"]}\')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; font-size:12px; padding:5px;">{t("delete_comment", lang)}</button>' if user and user['username'] == c['author'] else ''
        comments_list_html += f"""<div id="comment-{c['id']}" style="display:flex; gap:10px; margin-bottom:15px; justify-content:space-between;"><div style="display:flex; gap:10px;"><img src="{c_ava}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;"><div><div style="font-weight:700; font-size:14px;">{c.get('display_name', c['author'])} <span style="color:var(--text-muted); font-weight:400; font-size:12px;">@{c['author']}</span></div><div style="font-size:14px; margin-top:2px;">{c['text']}</div></div></div>{del_btn}</div>"""
    
    no_comments_style = "display:block;" if len(post['comments']) == 0 else "display:none;"
    date_str = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime("%d.%m.%Y %H:%M")
    
    content = f"""<div class="post-header-actions" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
        <a href="/" style="display:flex; align-items:center; color:var(--text-muted); padding:8px;">{SVG_BACK}</a>
        {delete_btn}
    </div>
    <div class="post-view">
        {media_html}
        <div class="post-details">
            <div class="post-top-info">
                <div class="post-author">
                    <a href="/@{post['author']}"><img src="{ava}"></a>
                    <div>
                        <a href="/@{post['author']}" style="color:#fff; font-weight:700; font-size:18px;">{html.escape(author['display_name']) if author else html.escape(post['author'])}</a>
                        <div style="font-size:14px; color:var(--text-muted);">@{html.escape(post['author'])} • {date_str}</div>
                    </div>
                </div>
                <div class="post-title selectable">{html.escape(post['title'])}</div>
                <div class="post-desc selectable">{html.escape(post['content'])}</div>
                <div class="actions-row">
                    <div class="vote-controls">
                        <button onclick="vote('{post['id']}', 'up')" id="btn-up" class="vote-btn {'active-up' if user_vote == 1 else ''}">{SVG_UP}</button>
                        <span class="vote-count" id="vote-count">{score}</span>
                        <button onclick="vote('{post['id']}', 'down')" id="btn-down" class="vote-btn {'active-down' if user_vote == -1 else ''}">{SVG_DOWN}</button>
                    </div>
                    <button onclick="toggleSave('{post['id']}')" id="btn-save" class="action-btn" style="{save_btn_style}" title="{t('save_post', lang)}">{save_icon_html}</button>
                    <button class="action-btn" onclick="copyLink()" title="{t('copy_link', lang)}">{SVG_LINK}</button>
                </div>
            </div>
            <div class="comments-section">
                <h3 style="margin-bottom:15px; font-weight:700; font-size:18px;">{t('comments', lang)} (<span id="comment-count">{len(post['comments'])}</span>)</h3>
                {comments_input_html}
                <div id="no-comments-msg" style="{no_comments_style} font-size:15px; color:var(--text-muted); text-align:center; padding:20px;">{t('no_comments', lang)}</div>
                <div id="comments-list">{comments_list_html}</div>
            </div>
        </div>
    </div>"""
    return HTMLResponse(content=render_layout(content, user, request, "feed", html.escape(post['title'])))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
