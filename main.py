from fastapi import FastAPI, Request, Form, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, StreamingResponse
from passlib.context import CryptContext
from supabase import create_client, Client
import uuid
import base64
import html
import json
import re
import asyncio
import secrets
from typing import List
from datetime import datetime, timezone

app = FastAPI(title="sol-id")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SUPABASE_URL = "https://xipbsydkqsumcrjlpnbq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

sessions = {}
users_db = {}
posts_db = {}
votes_db = {}
scores_cache = {}
comments_db = {}

# ============ SSE REALTIME ============
sse_subscribers = []

def sse_send(msg):
    dead = []
    for q in sse_subscribers:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            sse_subscribers.remove(q)
        except Exception:
            pass

@app.get("/api/sse")
async def sse_endpoint(request: Request):
    async def event_gen():
        q = asyncio.Queue()
        sse_subscribers.append(q)
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                sse_subscribers.remove(q)
            except Exception:
                pass
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    })

# ============ CACHE ============
def rebuild_scores():
    scores_cache.clear()
    for (pid, _u), v in votes_db.items():
        scores_cache[pid] = scores_cache.get(pid, 0) + v

def get_score(post_id):
    return scores_cache.get(post_id, 0)

def load_all_from_supabase():
    global users_db, posts_db, votes_db, comments_db
    try:
        res = supabase.table("users").select("*").execute()
        users_db = {u['username']: u for u in res.data}
    except Exception as e:
        print("Error loading users:", e)
        users_db = {}
    try:
        res = supabase.table("posts").select("*").execute()
        posts_db = {p['id']: p for p in res.data}
    except Exception as e:
        print("Error loading posts:", e)
        posts_db = {}
    try:
        res = supabase.table("users_vote").select("*").execute()
        votes_db = {(v['post_id'], v['username']): v['vote'] for v in res.data}
    except Exception as e:
        print("Error loading votes:", e)
        votes_db = {}
    try:
        res = supabase.table("comments").select("*").execute()
        comments_db = {}
        for c in res.data:
            pid = c['post_id']
            comments_db.setdefault(pid, []).append(c)
    except Exception as e:
        print("Error loading comments:", e)
        comments_db = {}
    rebuild_scores()
    print(f"Loaded: {len(users_db)} users, {len(posts_db)} posts, {len(votes_db)} votes")

@app.on_event("startup")
async def startup_event():
    load_all_from_supabase()

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ============ TRANSLATIONS ============
TRANSLATIONS = {
    "en": {
        "feed": "Feed", "saved": "Saved", "profile": "Profile", "settings": "Settings", "logout": "Logout", "login": "Login",
        "new_post": "New Post", "search_placeholder": "Search...", "title": "Title", "description": "Description", "publish": "Publish",
        "visibility": "Who can see", "in_feed": "In Feed", "by_link": "By Link", "upload_hint": "Drop files or paste (Ctrl+V)",
        "upload_limit": "JPEG, PNG, GIF up to 3 images", "back": "Back", "comments": "Comments", "no_comments": "No comments yet.",
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
        "got_it": "Got it!", "invalid_pass_format": "Invalid password format", "idea_by": "Idea: eblo.id",
        "login_to_interact": "Log in to vote, save, and comment", "reset": "Reset", "copy_comment_link": "Copy comment link",
        "new_posts_available": "New posts available. Refresh?", "refresh": "Refresh", "gif_too_large": "GIF is too large (max 5MB)",
        "just_now": "just now", "min_ago": "min ago", "hr_ago": "h ago", "yesterday": "yesterday", "days_ago": "d ago"
    },
    "ru": {
        "feed": "Лента", "saved": "Избранное", "profile": "Профиль", "settings": "Настройки", "logout": "Выйти", "login": "Вход",
        "new_post": "Новый пост", "search_placeholder": "Поиск...", "title": "Название", "description": "Описание", "publish": "Опубликовать",
        "visibility": "Кто увидит", "in_feed": "Все, в ленте", "by_link": "По ссылке", "upload_hint": "Перетащите файлы или вставьте (Ctrl+V)",
        "upload_limit": "JPEG, PNG, GIF до 3 штук", "back": "Назад", "comments": "Комментарии", "no_comments": "Пока нет комментариев.",
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
        "got_it": "Понятно!", "invalid_pass_format": "Неверный формат пароля", "idea_by": "Идея: eblo.id",
        "login_to_interact": "Войдите, чтобы оценивать, сохранять и комментировать", "reset": "Сброс", "copy_comment_link": "Скопировать ссылку на комментарий",
        "new_posts_available": "Есть новые посты. Обновить?", "refresh": "Обновить", "gif_too_large": "GIF слишком большой (макс. 5MB)",
        "just_now": "только что", "min_ago": "мин назад", "hr_ago": "ч назад", "yesterday": "вчера", "days_ago": "дн назад"
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
        return users_db.get(sessions[session_token])
    return None

async def image_to_base64(file: UploadFile):
    if not file or not file.filename: return None
    contents = await file.read()
    return f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"

def generate_post_id(visibility):
    if visibility == 'link':
        return secrets.token_urlsafe(24)
    return str(uuid.uuid4())[:6]

def render_card_media(post):
    """Render post media for feed/profile cards. If no images — show text description."""
    if post.get('images'):
        return f'<img src="{post["images"][0]}" loading="lazy">'
    desc = (post.get('content') or '').strip()
    if desc:
        return f'<div class="feed-card-no-image">{html.escape(desc)}</div>'
    return f'<div class="feed-card-no-image empty">{SVG_IMAGE}</div>'

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
    const CACHE_NAME = 'solid-cache-v9';
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
        if (event.request.url.includes('/api/sse')) return;
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
    return JSONResponse({"available": q not in users_db})

CSS_STYLES = """
<link rel="icon" type="image/png" href=\"""" + LOGO_URL + """\">
<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<script src="https://unpkg.com/browser-image-compression@2.0.2/dist/browser-image-compression.js"></script>
<style>
:root{--bg-color:#0a0a0a;--card-bg:#151515;--text-main:#f8fafc;--text-muted:#94a3b8;--accent-color:#3b82f6;--border-color:#262626;--danger-color:#ef4444;}
::-webkit-scrollbar{width:8px;height:8px;}
::-webkit-scrollbar-track{background:var(--bg-color);}
::-webkit-scrollbar-thumb{background:#333;border-radius:4px;}
::-webkit-scrollbar-thumb:hover{background:var(--text-muted);}
img{image-rendering:pixelated;image-rendering:-moz-crisp-edges;image-rendering:-webkit-crisp-edges;image-rendering:crisp-edges;}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Manrope',sans-serif;user-select:none;}
input,textarea,.selectable{user-select:text;}
body{background-color:var(--bg-color);color:var(--text-main);font-size:16px;min-height:100vh;overflow-x:hidden;}
a{color:var(--accent-color);text-decoration:none;}
button,a,.action-btn,.btn-primary,.feed-card,.carousel-nav-btn{touch-action:manipulation;position:relative;}
.app-layout{display:grid;grid-template-columns:260px 1fr;min-height:100vh;width:100%;}
.app-layout.sidebar-collapsed{grid-template-columns:80px 1fr;}
.topbar{grid-column:1/-1;position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:0 25px;border-bottom:1px solid var(--border-color);background:rgba(10,10,10,0.95);backdrop-filter:blur(10px);z-index:100;height:70px;}
.topbar-left{display:flex;align-items:center;gap:15px;flex-shrink:0;width:auto;}
.logo{font-size:22px;font-weight:700;color:var(--accent-color);display:flex;align-items:center;gap:10px;white-space:nowrap;}
.logo img{width:42px;height:38px;object-fit:contain;}
.menu-toggle{cursor:pointer;padding:8px;color:var(--text-muted);border-radius:6px;transition:background .2s;flex-shrink:0;}
.menu-toggle:hover{background:var(--card-bg);color:var(--text-main);}
.topbar-center{position:absolute;left:50%;transform:translateX(-50%);width:100%;max-width:500px;display:flex;justify-content:center;z-index:10;}
.search-container{width:100%;position:relative;}
.search-input{width:100%;background:var(--card-bg);border:1px solid var(--border-color);padding:8px 15px 8px 36px;border-radius:8px;color:#fff;font-size:14px;outline:none;}
.search-input:focus{border-color:var(--accent-color);}
.search-icon{position:absolute;left:10px;top:8px;color:var(--text-muted);}
.search-dropdown{display:none;position:absolute;top:40px;left:0;width:100%;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.6);z-index:150;max-height:300px;overflow-y:auto;}
.search-dropdown-item{display:flex;align-items:center;gap:10px;padding:10px 15px;color:var(--text-main);border-bottom:1px solid var(--border-color);}
.search-dropdown-item:hover{background:#2a2a2a;}
.topbar-right{display:flex;align-items:center;justify-content:flex-end;gap:15px;flex-shrink:0;width:auto;}
.btn-primary{background-color:var(--accent-color);color:#fff;border:none;padding:10px 20px;border-radius:8px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-size:15px;transition:opacity .2s;z-index:10;}
.btn-primary:hover{opacity:.9;}
.btn-primary:disabled{opacity:0.5;cursor:not-allowed;}
.user-menu-container{position:relative;}
.user-menu-btn{display:flex;align-items:center;gap:12px;cursor:pointer;padding:4px;border-radius:50%;border:none;outline:none;}
.user-menu-btn:hover{background:var(--card-bg);}
.user-avatar-small{width:36px;height:36px;border-radius:50%!important;object-fit:cover;background:#333;display:block;}
.dropdown-menu{display:none;position:absolute;right:0;top:50px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;width:240px;box-shadow:0 10px 30px rgba(0,0,0,.6);z-index:200;overflow:hidden;}
.dropdown-header{padding:15px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--border-color);}
.dropdown-header img{width:44px;height:44px;border-radius:50%!important;object-fit:cover;}
.dropdown-header div{display:flex;flex-direction:column;}
.dropdown-header .name{font-weight:700;font-size:15px;}
.dropdown-header .login{font-size:13px;color:var(--text-muted);}
.dropdown-item{display:flex;align-items:center;gap:12px;padding:14px 15px;color:var(--text-main);font-size:15px;}
.dropdown-item:hover{background:#2a2a2a;}
.dropdown-item.danger{color:var(--danger-color);border-top:1px solid var(--border-color);}
.sidebar{grid-column:1;position:sticky;top:70px;border-right:1px solid var(--border-color);padding:20px 0;display:flex;flex-direction:column;gap:8px;height:calc(100vh - 70px);overflow-y:auto;transition:padding .3s;}
.sidebar a{color:var(--text-muted);padding:12px 25px;display:flex;align-items:center;gap:15px;font-size:16px;font-weight:500;transition:all .2s;white-space:nowrap;overflow:hidden;}
.sidebar a:hover:not(.active),.sidebar a.active{color:var(--text-main);background-color:var(--card-bg);}
.sidebar a.active svg{color:var(--accent-color);}
.app-layout.sidebar-collapsed .sidebar{padding:20px 0;align-items:center;}
.app-layout.sidebar-collapsed .sidebar a{justify-content:center;padding:15px 0;width:100%;}
.app-layout.sidebar-collapsed .sidebar a span{display:none;}
.sidebar-bottom-banner{margin-top:auto;display:flex;flex-direction:column;align-items:center;width:100%;padding:0;transition:opacity .2s;text-decoration:none;}
.sidebar-bottom-banner img{width:100%;height:auto;display:block;object-fit:contain;border-radius:0;}
.sidebar-bottom-banner .banner-text{font-size:12px;color:var(--text-muted);margin-top:5px;margin-bottom:10px;text-align:center;}
.sidebar-bottom-banner:hover{opacity:0.8;}
.app-layout.sidebar-collapsed .sidebar-bottom-banner img{object-fit:cover;height:100px;}
.app-layout.sidebar-collapsed .sidebar-bottom-banner .banner-text{display:none;}
.main-content{grid-column:2;padding:30px;display:flex;flex-direction:column;min-height:calc(100vh - 70px);width:100%;max-width:100%;position:relative;z-index:1;}
.auth-container{display:flex;justify-content:center;align-items:center;flex:1;}
.auth-form{background-color:var(--card-bg);padding:40px;border-radius:16px;width:100%;max-width:450px;border:1px solid var(--border-color);}
.auth-form h2{text-align:center;margin-bottom:25px;font-weight:700;font-size:24px;}
.input-group{margin-bottom:15px;position:relative;width:100%;}
.input-group input,.input-group select,.input-group textarea{width:100%;padding:14px 16px;background-color:var(--bg-color);border:1px solid var(--border-color);border-radius:8px;color:white;font-size:16px;outline:none;}
.input-group input:focus,.input-group select:focus,.input-group textarea:focus{border-color:var(--accent-color);}
.input-group textarea{resize:none;max-height:250px;overflow-y:auto;}
.pass-toggle{position:absolute;right:15px;top:15px;cursor:pointer;color:var(--text-muted);}
.error{color:var(--danger-color);text-align:center;margin-bottom:15px;font-size:15px;}
.val-list{list-style:none;margin-top:8px;padding:0;display:flex;flex-direction:column;gap:4px;}
.val-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);transition:color .2s;}
.val-item .icon-cross{display:block;}
.val-item .icon-check{display:none;}
.val-item.valid{color:#22c55e;}
.val-item.valid .icon-cross{display:none;}
.val-item.valid .icon-check{display:block;}
.profile-header{margin-bottom:30px;display:flex;align-items:center;gap:25px;position:relative;width:100%;}
.profile-avatar{width:140px;height:140px;border-radius:50%!important;object-fit:cover;background:#333;flex-shrink:0;}
.profile-details h1{font-size:32px;margin-bottom:5px;font-weight:700;line-height:1.2;}
.profile-details p{color:var(--text-muted);font-size:16px;}
.profile-edit-btn-wrapper{margin-left:auto;}
.profile-tabs{display:flex;gap:20px;border-bottom:1px solid var(--border-color);margin-bottom:25px;}
.profile-tab-btn{background:none;border:none;color:var(--text-muted);font-size:18px;font-weight:700;padding:10px 5px;cursor:pointer;border-bottom:3px solid transparent;transition:all .2s;}
.profile-tab-btn.active{color:#fff;border-bottom-color:var(--accent-color);}
.profile-tab-content{display:none;}
.profile-tab-content.active{display:block;}
.post-view{display:flex;gap:30px;width:100%;max-width:1400px;margin:0 auto;padding:0 20px;align-items:flex-start;}
.post-view.no-media{display:block;max-width:900px;padding:0 20px;}
.post-view.no-media .post-details{min-width:0;width:100%;flex:none;}
.post-view.no-media .post-desc{font-size:18px;line-height:1.7;color:#e2e8f0;}
.post-media{flex:1.5;background:#000;border-radius:12px;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative;cursor:zoom-in;max-height:75vh;min-height:400px;aspect-ratio:16/9;}
.post-media img{max-width:100%;max-height:100%;object-fit:contain;width:100%;height:100%;}
.carousel-nav-btn{position:absolute;top:40%;transform:translateY(-50%);background:rgba(0,0,0,0.6);color:#fff;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10;transition:background 0.2s;border:none;}
.carousel-nav-btn:hover{background:rgba(0,0,0,0.9);}
.carousel-nav-btn.left{left:15px;}
.carousel-nav-btn.right{right:15px;}
.post-details{flex:1;min-width:320px;display:flex;flex-direction:column;padding:0;}
.post-top-info{flex-shrink:0;}
.post-author{display:flex;align-items:center;gap:12px;margin-bottom:15px;}
.post-author img{width:48px;height:48px;border-radius:50%!important;}
.post-title{font-size:26px;font-weight:700;margin-bottom:10px;}
.post-desc{color:#ccc;font-size:16px;margin-bottom:15px;white-space:pre-wrap;line-height:1.5;}
.actions-row{display:flex;align-items:center;gap:10px;margin-top:10px;margin-bottom:25px;flex-wrap:wrap;flex-shrink:0;}
.vote-controls{display:flex;align-items:center;gap:12px;background:var(--bg-color);padding:0 12px;border-radius:8px;border:1px solid var(--border-color);height:40px;position:relative;z-index:5;}
.vote-btn{background:none;border:none;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;transition:color .2s;height:100%;position:relative;z-index:6;}
.vote-btn.active-up{color:var(--accent-color);}
.vote-btn.active-down{color:var(--danger-color);}
.vote-count{font-weight:700;font-size:18px;min-width:20px;text-align:center;line-height:1;}
.action-btn{background:var(--bg-color);border:1px solid var(--border-color);color:var(--text-muted);padding:0 12px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:5px;text-decoration:none;height:40px;transition:background .2s;position:relative;z-index:5;}
.action-btn:hover{background:#333;color:#fff;}
.action-btn svg{width:20px;height:20px;}
form .action-btn{height:100%;width:100%;}
.login-notice{background:var(--bg-color);border:1px solid var(--border-color);border-radius:8px;padding:12px;color:var(--text-muted);font-size:14px;text-align:center;margin-top:10px;margin-bottom:25px;}
.login-notice a{font-weight:600;}
.comments-section{flex:1;min-height:0;border-top:1px solid var(--border-color);padding-top:20px;}
.feed-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;width:100%;}
@media (max-width:1600px){.feed-grid{grid-template-columns:repeat(3,1fr);}}
@media (max-width:1200px){.feed-grid{grid-template-columns:repeat(2,1fr);}}
.feed-card{background:var(--card-bg);border-radius:12px;overflow:hidden;border:1px solid var(--border-color);display:flex;flex-direction:column;position:relative;transition:border-color .2s;width:100%;z-index:2;}
.feed-card:hover{border-color:#444;}
.feed-card-img-container{width:100%;height:240px;background:#000;overflow:hidden;display:flex;align-items:center;justify-content:center;}
.feed-card-img-container img{width:100%;height:100%;object-fit:cover;}
.feed-card-no-image{padding:20px;width:100%;height:100%;color:#ccc;font-size:15px;line-height:1.6;background:linear-gradient(135deg,#1a1a1a 0%,#0f0f0f 100%);white-space:pre-wrap;word-break:break-word;overflow:hidden;display:-webkit-box;-webkit-line-clamp:8;-webkit-box-orient:vertical;}
.feed-card-no-image.empty{display:flex;align-items:center;justify-content:center;color:#444;padding:0;}
.feed-card-info{padding:15px;flex:1;display:flex;flex-direction:column;gap:10px;}
.feed-card-title{font-weight:700;font-size:18px;line-height:1.3;}
.feed-card-meta{display:flex;align-items:center;justify-content:space-between;font-size:14px;color:var(--text-muted);margin-top:auto;}
.feed-card-author{display:flex;align-items:center;gap:8px;}
.post-date{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-muted);}
.feed-card-remove-btn{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.7);border:none;color:#fff;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10;}
.feed-card-remove-btn:hover{background:var(--danger-color);}
.post-badge{position:absolute;top:10px;left:10px;background:rgba(0,0,0,0.75);color:var(--accent-color);padding:6px;border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:10;border:1px solid var(--accent-color);box-shadow:0 2px 5px rgba(0,0,0,0.5);}
.create-layout{display:flex;gap:30px;width:100%;}
.dropzone{flex:2;border:2px dashed var(--border-color);border-radius:16px;padding:50px;text-align:center;color:var(--text-muted);display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:400px;cursor:pointer;width:100%;}
.dropzone.dragover{border-color:var(--accent-color);background:rgba(59,130,246,.05);}
.file-preview{display:flex;align-items:center;gap:15px;background:var(--bg-color);padding:10px;border-radius:8px;border:1px solid var(--border-color);margin-top:15px;width:100%;text-align:left;cursor:default;}
.file-preview img{width:50px;height:50px;object-fit:cover;border-radius:6px;}
.create-sidebar{flex:1;background:var(--card-bg);padding:30px;border-radius:16px;border:1px solid var(--border-color);display:flex;flex-direction:column;gap:15px;width:100%;}
.char-counter{font-size:12px;color:var(--text-muted);text-align:right;margin-top:6px;}
.char-counter.near{color:#f59e0b;}
.char-counter.full{color:var(--danger-color);}
.switch{position:relative;display:inline-block;width:50px;height:28px;}
.switch input{opacity:0;width:0;height:0;}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:var(--border-color);transition:.4s;border-radius:34px;}
.slider:before{position:absolute;content:"";height:20px;width:20px;left:4px;bottom:4px;background-color:white;transition:.4s;border-radius:50%;}
input:checked+.slider{background-color:var(--accent-color);}
input:checked+.slider:before{transform:translateX(22px);}
#photo-viewer{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.95);z-index:9999;display:none;justify-content:center;align-items:center;overflow:hidden;touch-action:none;}
#photo-viewer-img{max-width:100%;max-height:100%;object-fit:contain;cursor:grab;transition:none;user-select:none;-webkit-user-drag:none;}
.photo-viewer-controls{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);display:flex;gap:10px;z-index:10001;}
.photo-viewer-btn{background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.3);color:#fff;width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:20px;backdrop-filter:blur(4px);}
.photo-viewer-btn:hover{background:rgba(255,255,255,0.2);}
.photo-viewer-close{position:absolute;top:15px;right:20px;font-size:40px;color:#fff;cursor:pointer;background:none;border:none;z-index:10001;line-height:1;}
.photo-nav-prev,.photo-nav-next{position:absolute;top:50%;transform:translateY(-50%);z-index:10001;}
.photo-nav-prev{left:15px;}
.photo-nav-next{right:15px;}
.overlay{display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,.95);z-index:9999;justify-content:center;align-items:center;flex-direction:column;padding:20px;overflow:hidden;}
.overlay img{max-width:100%;max-height:90vh;object-fit:contain;border-radius:8px;box-shadow:0 0 20px rgba(0,0,0,0.5);}
.close-overlay{position:absolute;top:15px;right:20px;font-size:40px;color:#fff;cursor:pointer;background:none;border:none;z-index:10000;line-height:1;}
.modal-box{background:var(--card-bg);padding:30px;border-radius:16px;border:1px solid var(--border-color);width:90%;max-width:400px;display:flex;flex-direction:column;gap:20px;text-align:center;}
.modal-box h3{font-weight:700;font-size:20px;}
.modal-box p{color:var(--text-muted);}
.modal-actions{display:flex;gap:10px;}
.modal-actions button{flex:1;padding:12px;justify-content:center;}
.welcome-modal-content{text-align:left;max-width:500px;width:100%;max-height:80vh;overflow-y:auto;padding:25px;align-items:stretch;}
.welcome-modal-content h2{text-align:center;margin-bottom:15px;color:var(--accent-color);}
.welcome-modal-content p{margin-bottom:20px;line-height:1.5;text-align:left;}
.welcome-modal-content .faq-section{background:var(--bg-color);padding:15px;border-radius:12px;border:1px solid var(--border-color);margin-bottom:20px;width:100%;}
.welcome-modal-content .faq-section h4{margin-bottom:10px;font-size:16px;color:#fff;}
.welcome-modal-content .faq-section ul{list-style:none;padding:0;display:flex;flex-direction:column;gap:10px;}
.welcome-modal-content .faq-section li{font-size:14px;color:#ddd;line-height:1.4;}
.welcome-modal-content .faq-section li strong{color:#fff;display:block;margin-bottom:2px;}
.toast{position:fixed;top:80px;right:20px;background:var(--card-bg);color:#fff;padding:12px 24px;border-radius:30px;border:1px solid var(--accent-color);font-weight:500;z-index:10000;opacity:0;transition:opacity .3s,transform .3s;pointer-events:none;}
.toast.show{opacity:1;transform:translateY(10px);}
.bottom-nav{display:none;position:fixed;bottom:0;left:0;width:100%;background:rgba(10,10,10,0.95);backdrop-filter:blur(10px);border-top:1px solid var(--border-color);justify-content:space-around;padding:12px 0;padding-bottom:max(12px,env(safe-area-inset-bottom));z-index:100;}
.bottom-nav a{display:flex;flex-direction:column;align-items:center;color:var(--text-muted);width:60px;text-decoration:none;}
.bottom-nav a.active{color:var(--accent-color);}
.bottom-nav a svg{width:28px;height:28px;}
.mobile-profile-menu{display:none;position:fixed;bottom:0;left:0;width:100%;background:var(--card-bg);z-index:1000;border-top-left-radius:20px;border-top-right-radius:20px;padding:20px;transform:translateY(100%);transition:transform .3s;flex-direction:column;gap:15px;padding-bottom:env(safe-area-inset-bottom,20px);box-shadow:0 -5px 20px rgba(0,0,0,.5);}
.mobile-profile-menu.open{transform:translateY(0);display:flex;}
.mobile-profile-header{display:flex;align-items:center;gap:15px;margin-bottom:10px;padding-bottom:15px;border-bottom:1px solid var(--border-color);}
.mobile-profile-header img{width:50px;height:50px;border-radius:50%!important;object-fit:cover;}
.mobile-menu-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:999;}
.editor-card{background:var(--card-bg);border-radius:16px;border:1px solid var(--border-color);padding:30px;display:flex;flex-direction:column;gap:15px;width:100%;max-width:600px;margin:0 auto;}
.avatar-edit-container{position:relative;width:120px;height:120px;margin:0 auto;cursor:pointer;border-radius:50%;overflow:hidden;border:2px solid var(--border-color);}
.avatar-edit-container:hover{border-color:var(--accent-color);}
.avatar-edit-container img{width:100%;height:100%;object-fit:cover;}
.avatar-edit-overlay{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;color:#fff;opacity:0;transition:opacity .2s;}
.avatar-edit-container:hover .avatar-edit-overlay{opacity:1;}
.tabs{display:flex;gap:10px;margin-bottom:20px;border-bottom:1px solid var(--border-color);padding-bottom:10px;width:100%;}
.tab-btn{background:none;border:none;color:var(--text-muted);font-size:16px;font-weight:500;cursor:pointer;padding:10px 15px;border-radius:8px;}
.tab-btn.active{color:var(--accent-color);background:var(--card-bg);}
.mobile-only{display:none!important;}
.desktop-only{display:flex!important;}
.new-posts-banner{display:none;position:sticky;top:80px;z-index:50;background:var(--accent-color);color:#fff;padding:12px 20px;border-radius:8px;text-align:center;cursor:pointer;font-weight:700;margin-bottom:20px;box-shadow:0 4px 15px rgba(59,130,246,0.4);align-items:center;justify-content:center;gap:8px;}
@media(max-width:1024px){.app-layout{grid-template-columns:220px 1fr;}.app-layout.sidebar-collapsed{grid-template-columns:80px 1fr;}}
@media(max-width:900px){
    .app-layout{display:flex;flex-direction:column;width:100%;min-height:100vh;overflow-x:hidden;}
    .topbar{position:fixed;top:0;left:0;width:100%;height:60px;padding:0 15px;gap:10px;z-index:100;}
    .topbar-left{width:auto;}
    .topbar-center{position:relative;left:auto;transform:none;max-width:100%;flex:1;margin-left:10px;}
    .topbar-right{width:auto;}
    .logo span{display:none;}
    .logo img{width:32px;height:28px;}
    .menu-toggle{display:none!important;}
    .search-container{max-width:100%;width:100%;}
    .topbar-right .user-menu-container{display:none!important;}
    .sidebar{display:none;}
    .main-content{margin-top:60px;width:100%;max-width:100vw;padding:0 0 80px 0;display:flex;flex-direction:column;position:relative;z-index:1;}
    .bottom-nav{display:flex;}
    .profile-header{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:30px 15px;margin:0;width:100%;position:relative;box-sizing:border-box;gap:15px;}
    .profile-avatar{width:100px!important;height:100px!important;border-radius:50%!important;object-fit:cover;margin:0 auto!important;display:block;flex-shrink:0;position:relative;z-index:1;}
    .profile-details{display:flex;flex-direction:column;align-items:center;width:100%;position:relative;z-index:1;}
    .profile-details h1{font-size:24px;margin-bottom:5px;word-break:break-word;line-height:1.2;}
    .profile-details p{font-size:14px;color:var(--text-muted);margin-bottom:4px;}
    .profile-edit-btn-wrapper{position:absolute;top:15px;right:15px;margin:0!important;z-index:50;}
    .profile-tabs{padding:0 15px;width:100%;display:flex;border-bottom:1px solid var(--border-color);margin-bottom:0;}
    .feed-grid{display:flex;flex-direction:column;width:100%;gap:0;padding:0;margin:0;}
    .feed-card{width:100%;border-radius:0;border-left:none;border-right:none;border-top:none;border-bottom:1px solid var(--border-color);background:transparent;margin:0;}
    .feed-card:hover{border-bottom-color:var(--border-color);}
    .feed-card-img-container{width:100%;height:auto;aspect-ratio:4/3;}
    .feed-card-info{padding:15px;width:100%;}
    .feed-card-meta{flex-wrap:wrap;gap:10px;}
    .editor-card{width:100%!important;max-width:100%!important;padding:20px 15px!important;margin:0!important;border-radius:0;border-left:none;border-right:none;}
    .tabs{padding:0 15px;margin-bottom:0;border-bottom:none;}
    .tab-content{padding:15px;}
    .create-layout{flex-direction:column;width:100%!important;padding:15px;gap:15px;}
    .dropzone{width:100%!important;max-width:100%!important;flex:none!important;padding:30px 15px!important;min-height:200px!important;}
    .create-sidebar{width:100%!important;max-width:100%!important;flex:none!important;padding:15px!important;}
    .post-view{display:flex;flex-direction:column;padding:0;gap:15px;height:auto;width:100%;}
    .post-view.no-media{padding:0;}
    .post-header-actions{padding:15px!important;background:transparent!important;border-bottom:1px solid var(--border-color);}
    .post-media{flex:none;width:100%;height:auto;aspect-ratio:4/3;max-height:60vh;border-radius:0!important;margin-bottom:0;border-bottom:1px solid var(--border-color);position:relative;z-index:1;}
    .carousel-nav-btn{top:45%;width:36px;height:36px;z-index:10;}
    .post-details{flex:none;width:100%;min-width:0;display:flex;flex-direction:column;padding:15px;position:relative;z-index:1;}
    .post-title{font-size:22px;}
    .actions-row{flex-wrap:wrap;gap:10px;margin-top:15px;margin-bottom:15px;padding:0;position:relative;z-index:10;}
    .comments-section{width:100%;padding:15px 0;border-top:1px solid var(--border-color);flex:none;position:relative;z-index:1;}
    .toast{top:20px;left:50%;right:auto;transform:translateX(-50%);}
    .toast.show{transform:translateX(-50%) translateY(10px);}
    .mobile-only{display:flex!important;}
    .desktop-only{display:none!important;}
    .auth-container{padding:15px;}
    .auth-form{width:100%;max-width:100%;padding:20px;}
    .new-posts-banner{top:70px;margin:15px;}
}
</style>
"""

JS_SCRIPT = r"""
<script>
var filesList = [];
var currentImage = null;
var currentZoom = 1;

// ============ DATE FORMATTER ============
function formatRelativeDate(iso, lang) {
    if (!iso) return '';
    try {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        var now = new Date();
        var diffSec = Math.floor((now - d) / 1000);
        var diffMin = Math.floor(diffSec / 60);
        var diffHour = Math.floor(diffMin / 60);
        var diffDay = Math.floor(diffHour / 24);
        var T = window.TRANSLATIONS;
        if (diffSec < 60) return T.just_now || 'just now';
        if (diffMin < 60) return diffMin + ' ' + (T.min_ago || 'min ago');
        if (diffHour < 24) return diffHour + ' ' + (T.hr_ago || 'h ago');
        var timeStr = d.toLocaleTimeString(lang === 'ru' ? 'ru-RU' : 'en-US', {hour:'2-digit', minute:'2-digit'});
        if (diffDay === 1) return (T.yesterday || 'yesterday') + ' ' + timeStr;
        if (diffDay < 7) return diffDay + ' ' + (T.days_ago || 'd ago');
        return d.toLocaleDateString(lang === 'ru' ? 'ru-RU' : 'en-US', {day:'2-digit', month:'2-digit', year:'numeric'});
    } catch(e) { return iso; }
}

function updateDates() {
    var lang = document.documentElement.lang || 'ru';
    document.querySelectorAll('[data-iso]').forEach(function(el) {
        var iso = el.getAttribute('data-iso');
        if (!iso) return;
        if (el.getAttribute('data-absolute') === 'true') {
            var d = new Date(iso);
            el.textContent = d.toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US', {
                day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'
            });
        } else {
            el.textContent = formatRelativeDate(iso, lang);
        }
    });
}
setInterval(updateDates, 30000);

// ============ IMAGE COMPRESSION ============
async function compressImage(file) {
    if (!file || !file.type) return null;

    // GIFs: never compress (would turn into static image, destroying animation)
    if (file.type === 'image/gif') {
        if (file.size > 5 * 1024 * 1024) {
            showToast(window.TRANSLATIONS.gif_too_large || 'GIF too large');
            throw new Error('GIF too large');
        }
        return file;
    }

    if (!file.type.startsWith('image/')) return file;

    if (window.imageCompression) {
        try {
            var compressed = await imageCompression(file, {
                maxSizeMB: 1.2, maxWidthOrHeight: 1920, useWebWorker: true, initialQuality: 0.85
            });
            // Ensure we always return a proper File (never a raw Blob) — DataTransfer requires File
            if (compressed instanceof File) return compressed;
            if (compressed instanceof Blob) {
                return new File([compressed], file.name || 'image.jpg', { type: compressed.type || file.type || 'image/jpeg' });
            }
            return file;
        } catch(e) {
            console.warn('Compression failed:', e);
        }
    }
    return file;
}

function ensureFile(blobOrFile, fallbackName) {
    if (blobOrFile instanceof File) return blobOrFile;
    return new File([blobOrFile], fallbackName || (blobOrFile && blobOrFile.name) || 'image.jpg',
                    { type: (blobOrFile && blobOrFile.type) || 'image/jpeg' });
}

// ============ PHOTO VIEWER ============
var pvState = { images: [], index: 0, scale: 1, tx: 0, ty: 0, isDragging: false, startX: 0, startY: 0, touchStartX: 0, touchStartY: 0, initialPinchDist: 0, isPinching: false };

function openPanorama(imgElement, index) {
    var container = document.getElementById('post-media-container');
    if (container && container.dataset.images) {
        try { pvState.images = JSON.parse(container.dataset.images); }
        catch(e) { pvState.images = [imgElement.src]; }
    } else { pvState.images = [imgElement.src]; }
    pvState.index = index || 0;
    pvState.scale = 1; pvState.tx = 0; pvState.ty = 0;
    var overlay = document.getElementById('photo-viewer');
    var img = document.getElementById('photo-viewer-img');
    if (img) { img.src = pvState.images[pvState.index]; img.style.transform = 'translate(0px, 0px) scale(1)'; }
    if (overlay) overlay.style.display = 'flex';
}

function closePanorama() {
    var overlay = document.getElementById('photo-viewer');
    if (overlay) overlay.style.display = 'none';
}

function updatePanoTransform() {
    var img = document.getElementById('photo-viewer-img');
    if (img) img.style.transform = 'translate(' + pvState.tx + 'px, ' + pvState.ty + 'px) scale(' + pvState.scale + ')';
}

function photoZoom(delta) { pvState.scale = Math.max(0.5, Math.min(8, pvState.scale + delta)); updatePanoTransform(); }
function photoReset() { pvState.scale = 1; pvState.tx = 0; pvState.ty = 0; updatePanoTransform(); }
function photoNext() { pvState.index = (pvState.index + 1) % pvState.images.length; var img = document.getElementById('photo-viewer-img'); if (img) img.src = pvState.images[pvState.index]; photoReset(); }
function photoPrev() { pvState.index = (pvState.index - 1 + pvState.images.length) % pvState.images.length; var img = document.getElementById('photo-viewer-img'); if (img) img.src = pvState.images[pvState.index]; photoReset(); }

document.addEventListener('DOMContentLoaded', function() {
    var viewer = document.getElementById('photo-viewer');
    var img = document.getElementById('photo-viewer-img');
    if (!viewer || !img) return;
    viewer.addEventListener('wheel', function(e) { e.preventDefault(); photoZoom(e.deltaY > 0 ? -0.2 : 0.2); }, { passive: false });
    viewer.addEventListener('mousedown', function(e) {
        if (e.target === img) { pvState.isDragging = true; pvState.startX = e.clientX - pvState.tx; pvState.startY = e.clientY - pvState.ty; img.style.cursor = 'grabbing'; }
    });
    window.addEventListener('mousemove', function(e) {
        if (pvState.isDragging) { pvState.tx = e.clientX - pvState.startX; pvState.ty = e.clientY - pvState.startY; updatePanoTransform(); }
    });
    window.addEventListener('mouseup', function() { if (pvState.isDragging) { pvState.isDragging = false; img.style.cursor = 'grab'; } });
    viewer.addEventListener('touchstart', function(e) {
        if (e.touches.length === 1) { pvState.isDragging = true; pvState.startX = e.touches[0].clientX - pvState.tx; pvState.startY = e.touches[0].clientY - pvState.ty; pvState.touchStartX = e.touches[0].clientX; pvState.touchStartY = e.touches[0].clientY; }
        else if (e.touches.length === 2) { pvState.isDragging = false; pvState.isPinching = true; pvState.initialPinchDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); }
    }, { passive: true });
    viewer.addEventListener('touchmove', function(e) {
        e.preventDefault();
        if (e.touches.length === 2 && pvState.isPinching) {
            var dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
            pvState.scale = Math.max(0.5, Math.min(8, pvState.scale * (dist / pvState.initialPinchDist)));
            pvState.initialPinchDist = dist; updatePanoTransform();
        } else if (e.touches.length === 1 && pvState.isDragging) {
            pvState.tx = e.touches[0].clientX - pvState.startX; pvState.ty = e.touches[0].clientY - pvState.startY; updatePanoTransform();
        }
    }, { passive: false });
    viewer.addEventListener('touchend', function(e) {
        if (pvState.isDragging && e.changedTouches.length === 1) {
            var dx = e.changedTouches[0].clientX - pvState.touchStartX;
            var dy = e.changedTouches[0].clientY - pvState.touchStartY;
            if (pvState.scale <= 1.05 && pvState.images.length > 1 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) {
                if (dx > 0) photoPrev(); else photoNext();
            }
        }
        pvState.isDragging = false; pvState.isPinching = false;
    });
});

function applySidebarState() {
    var layout = document.querySelector('.app-layout');
    if (!layout) return;
    if (localStorage.getItem('sidebar_collapsed') === 'true') layout.classList.add('sidebar-collapsed');
    else layout.classList.remove('sidebar-collapsed');
}

function toggleSidebar() {
    var layout = document.querySelector('.app-layout');
    if (!layout) return;
    layout.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebar_collapsed', layout.classList.contains('sidebar-collapsed'));
}

function toggleDropdown() {
    if (window.innerWidth <= 900) {
        document.getElementById('mobileProfileMenu').classList.add('open');
        document.getElementById('mobileMenuOverlay').style.display = 'block';
    } else {
        var dropdown = document.getElementById("user-dropdown");
        if (dropdown) dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
    }
}

function closeMobileMenu() {
    var menu = document.getElementById('mobileProfileMenu');
    var overlay = document.getElementById('mobileMenuOverlay');
    if (menu) menu.classList.remove('open');
    if (overlay) overlay.style.display = 'none';
}

function togglePassword(el) {
    var input = el.previousElementSibling;
    var eyeOpen = el.querySelector('.eye-open');
    var eyeClosed = el.querySelector('.eye-closed');
    if (input.type === "password") { input.type = "text"; eyeOpen.style.display = "none"; eyeClosed.style.display = "block"; }
    else { input.type = "password"; eyeOpen.style.display = "block"; eyeClosed.style.display = "none"; }
}

var searchTimeout;
function handleSearch(query) {
    clearTimeout(searchTimeout);
    var dropdown = document.getElementById('searchDropdown');
    if (!dropdown) return;
    if (!query.trim()) { dropdown.style.display = 'none'; return; }
    searchTimeout = setTimeout(async () => {
        var res = await fetch('/api/search?q=' + encodeURIComponent(query));
        var data = await res.json();
        if (data.results && data.results.length > 0) {
            dropdown.innerHTML = '';
            data.results.forEach(function(p) {
                var a = document.createElement('a');
                a.href = '/' + p.id;
                a.className = 'search-dropdown-item';
                var titleDiv = document.createElement('div');
                titleDiv.style.cssText = 'font-weight:700;font-size:14px;';
                titleDiv.innerText = p.title;
                var authorDiv = document.createElement('div');
                authorDiv.style.cssText = 'color:var(--text-muted);font-size:12px;margin-left:auto;';
                authorDiv.innerText = '@' + p.author;
                a.appendChild(titleDiv); a.appendChild(authorDiv);
                dropdown.appendChild(a);
            });
            dropdown.style.display = 'block';
        } else {
            dropdown.innerHTML = '<div style="padding:15px;color:var(--text-muted);font-size:14px;text-align:center;">' + window.TRANSLATIONS.nothing_found + '</div>';
            dropdown.style.display = 'block';
        }
    }, 300);
}

async function handleFiles(input) {
    if (!input.files) return;
    var newFiles = Array.from(input.files);
    for (var i = 0; i < newFiles.length; i++) {
        if (filesList.length >= 3) {
            showToast(window.TRANSLATIONS.max_files);
            break;
        }
        try {
            var compressed = await compressImage(newFiles[i]);
            if (!compressed) continue;
            // Final safety net — DataTransfer.items.add() requires File
            filesList.push(ensureFile(compressed, newFiles[i].name));
        } catch(e) {
            showToast(e.message || 'Error');
        }
    }
    input.value = '';
    updateInputAndRender();
}

function removeFile(index, event) {
    if (event) { event.stopPropagation(); event.preventDefault(); }
    filesList.splice(index, 1);
    updateInputAndRender();
}

function updateInputAndRender() {
    var dt = new DataTransfer();
    filesList.forEach(function(f, i) {
        // Ensure everything in filesList is a File (defensive)
        if (!(f instanceof File)) {
            filesList[i] = ensureFile(f);
        }
        dt.items.add(filesList[i]);
    });
    var fileInput = document.getElementById('file-input');
    if (fileInput) fileInput.files = dt.files;
    var previewContainer = document.getElementById('file-list');
    if (!previewContainer) return;
    previewContainer.innerHTML = '';
    var dropText = document.getElementById('dropzone-text');
    if (filesList.length === 0) { if (dropText) dropText.style.display = 'flex'; }
    else {
        if (dropText) dropText.style.display = 'none';
        filesList.forEach((file, index) => {
            var reader = new FileReader();
            reader.onload = function(e) {
                var div = document.createElement('div');
                div.className = 'file-preview';
                div.onclick = (e) => e.stopPropagation();
                var sizeLabel = file.type === 'image/gif' ? ' GIF • ' : ' ';
                div.innerHTML = '<img src="' + e.target.result + '"><div style="flex:1;overflow:hidden;"><div style="font-size:14px;color:#fff;font-weight:500;text-overflow:ellipsis;white-space:nowrap;overflow:hidden;">' + file.name + '</div><div style="font-size:12px;color:var(--text-muted);">' + sizeLabel + (file.size/1024).toFixed(1) + ' KB</div></div><span style="cursor:pointer;color:var(--text-muted);font-size:24px;padding:0 10px;" onclick="removeFile(' + index + ', event)">×</span>';
                previewContainer.appendChild(div);
            };
            reader.readAsDataURL(file);
        });
    }
}

document.addEventListener('paste', async function(e) {
    if (!document.getElementById('file-input')) return;
    var items = (e.clipboardData || e.originalEvent.clipboardData).items;
    var imageFile = null;
    for (var index = 0; index < items.length; index++) {
        if (items[index].kind === 'file' && items[index].type.includes('image/')) { imageFile = items[index].getAsFile(); break; }
    }
    if (imageFile) {
        e.preventDefault();
        if (filesList.length < 3) {
            var file = new File([imageFile], "pasted_" + Date.now() + "." + (imageFile.type === 'image/gif' ? 'gif' : 'png'), { type: imageFile.type });
            try {
                var compressed = await compressImage(file);
                if (compressed) filesList.push(ensureFile(compressed, file.name));
                updateInputAndRender();
            } catch(e) {}
        } else { showToast(window.TRANSLATIONS.max_files); }
    }
});

function setVisibility(val) {
    document.getElementById('vis-input').value = val;
    var btnFeed = document.getElementById('btn-feed'), btnLink = document.getElementById('btn-link');
    if (val === 'feed') {
        btnFeed.style.borderColor = 'var(--accent-color)'; btnFeed.style.color = 'var(--accent-color)';
        btnLink.style.borderColor = 'var(--border-color)'; btnLink.style.color = 'var(--text-muted)';
    } else {
        btnFeed.style.borderColor = 'var(--border-color)'; btnFeed.style.color = 'var(--text-muted)';
        btnLink.style.borderColor = 'var(--accent-color)'; btnLink.style.color = 'var(--accent-color)';
    }
}

function showToast(message) {
    var toast = document.getElementById('toast');
    if (!toast) return;
    toast.innerText = message;
    toast.classList.add('show');
    setTimeout(() => { toast.classList.remove('show'); }, 3000);
}

function showConfirm(title, desc, onConfirm) {
    var modal = document.getElementById('confirm-modal');
    if (!modal) return;
    document.getElementById('confirm-title').innerText = title;
    document.getElementById('confirm-desc').innerText = desc;
    var btn = document.getElementById('confirm-btn'), newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.onclick = function() { modal.style.display = 'none'; onConfirm(); };
    modal.style.display = 'flex';
}

function copyLink() { navigator.clipboard.writeText(window.location.href); showToast(window.TRANSLATIONS.link_copied); }
function copyCommentLink(postId, commentId) {
    var url = window.location.origin + '/' + postId + '/' + commentId;
    navigator.clipboard.writeText(url);
    showToast(window.TRANSLATIONS.link_copied);
}

function loadAvatar(event) {
    var file = event.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(e) {
        var img = new Image();
        img.onload = function() {
            currentImage = img; currentZoom = 1;
            document.getElementById('zoom-slider').value = 1;
            drawCropCanvas();
            document.getElementById('crop-modal').style.display = 'flex';
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
}

function drawCropCanvas() {
    if (!currentImage) return;
    var canvas = document.getElementById('crop-canvas'), ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    var scale = Math.max(canvas.width/currentImage.width, canvas.height/currentImage.height) * currentZoom;
    var x = (canvas.width - currentImage.width*scale)/2, y = (canvas.height - currentImage.height*scale)/2;
    ctx.drawImage(currentImage, x, y, currentImage.width*scale, currentImage.height*scale);
}

function applyCrop() {
    var canvas = document.getElementById('crop-canvas');
    var dataUrl = canvas.toDataURL('image/jpeg', 0.8);
    document.getElementById('avatar-base64').value = dataUrl;
    document.getElementById('avatar-preview').src = dataUrl;
    document.getElementById('crop-modal').style.display = 'none';
}

function updateCharCount(el) {
    var counter = document.getElementById('char-count');
    if (!counter) return;
    var len = el.value.length;
    counter.textContent = len + ' / 2500';
    counter.classList.toggle('near', len >= 2000 && len < 2500);
    counter.classList.toggle('full', len >= 2500);
}

async function vote(postId, action) {
    var upBtn = document.getElementById('btn-up'), downBtn = document.getElementById('btn-down');
    if (upBtn) upBtn.disabled = true;
    if (downBtn) downBtn.disabled = true;
    var res = await fetch('/api/vote/' + postId + '/' + action, { method: 'POST' });
    var data = await res.json();
    if (upBtn) upBtn.disabled = false;
    if (downBtn) downBtn.disabled = false;
    if (data.error) return showToast(data.error);
    var count = document.getElementById('vote-count');
    if (count) count.innerText = data.score;
    if (upBtn) upBtn.className = 'vote-btn ' + (data.user_vote === 1 ? 'active-up' : '');
    if (downBtn) downBtn.className = 'vote-btn ' + (data.user_vote === -1 ? 'active-down' : '');
}

async function toggleSave(postId, redirectToSaved) {
    var res = await fetch('/api/save/' + postId, { method: 'POST' });
    var data = await res.json();
    if (data.error) return showToast(data.error);
    if (redirectToSaved) { window.location.reload(); return; }
    var btn = document.getElementById('btn-save');
    if (btn) {
        if (data.saved) {
            btn.innerHTML = window.SVG_SAVED;
            btn.style.color = 'var(--accent-color)'; btn.style.borderColor = 'var(--accent-color)';
        } else {
            btn.innerHTML = window.SVG_SAVE;
            btn.style.color = ''; btn.style.borderColor = '';
        }
    }
}

function buildCommentDOM(comment, postId, isAuthor) {
    var ava = comment.avatar || ('https://api.dicebear.com/7.x/avataaars/svg?seed=' + comment.login);
    var div = document.createElement('div');
    div.id = 'comment-' + comment.id;
    div.style.cssText = 'display:flex;gap:10px;margin-bottom:15px;justify-content:space-between;';
    var leftDiv = document.createElement('div');
    leftDiv.style.cssText = 'display:flex;gap:10px;';
    var img = document.createElement('img');
    img.src = ava;
    img.style.cssText = 'width:32px;height:32px;border-radius:50%;object-fit:cover;';
    var textDiv = document.createElement('div');
    var nameDiv = document.createElement('div');
    nameDiv.style.cssText = 'font-weight:700;font-size:14px;';
    nameDiv.innerHTML = (comment.display_name || comment.login) + ' <span style="color:var(--text-muted);font-weight:400;font-size:12px;">@' + comment.login + '</span>';
    var contentDiv = document.createElement('div');
    contentDiv.style.cssText = 'font-size:14px;margin-top:2px;';
    contentDiv.innerText = comment.text || comment.comment_text;
    textDiv.appendChild(nameDiv); textDiv.appendChild(contentDiv);
    leftDiv.appendChild(img); leftDiv.appendChild(textDiv);
    var actionsDiv = document.createElement('div');
    actionsDiv.style.cssText = 'display:flex;gap:2px;align-items:flex-start;';
    var copyBtn = document.createElement('button');
    copyBtn.style.cssText = 'background:none;border:none;color:var(--text-muted);cursor:pointer;padding:5px;display:flex;align-items:center;';
    copyBtn.title = window.TRANSLATIONS.copy_comment_link;
    copyBtn.innerHTML = window.SVG_LINK;
    copyBtn.onclick = function() { copyCommentLink(postId, comment.id); };
    actionsDiv.appendChild(copyBtn);
    if (isAuthor) {
        var delBtn = document.createElement('button');
        delBtn.style.cssText = 'background:none;border:none;color:var(--danger-color);cursor:pointer;padding:5px;display:flex;align-items:center;';
        delBtn.title = window.TRANSLATIONS.delete_comment;
        delBtn.innerHTML = window.SVG_TRASH;
        delBtn.onclick = function() { confirmDeleteComment(postId, comment.id); };
        actionsDiv.appendChild(delBtn);
    }
    div.appendChild(leftDiv); div.appendChild(actionsDiv);
    return div;
}

async function submitComment(e, postId) {
    e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    var input = document.getElementById('comment-input');
    if (!input) return;
    var text = input.value.trim();
    if (!text) return;
    var formData = new FormData();
    formData.append('text', text);
    var res = await fetch('/api/comment/' + postId, { method: 'POST', body: formData });
    var data = await res.json();
    if (data.error) return showToast(data.error);
    if (data.comment) {
        input.value = '';
        var noMsg = document.getElementById('no-comments-msg');
        if (noMsg) noMsg.style.display = 'none';
        var list = document.getElementById('comments-list');
        if (!document.getElementById('comment-' + data.comment.id) && list) {
            list.appendChild(buildCommentDOM(data.comment, postId, true));
        }
        var cCount = document.getElementById('comment-count');
        if (cCount) cCount.innerText = data.total_comments;
    }
}

function confirmDeleteComment(postId, commentId) {
    showConfirm(window.TRANSLATIONS.delete, window.TRANSLATIONS.delete_comment_confirm, async function() {
        var res = await fetch('/api/comment/' + postId + '/' + commentId, { method: 'DELETE' });
        var data = await res.json();
        if (data.success) {
            var el = document.getElementById('comment-' + commentId);
            if (el) el.remove();
            var cCount = document.getElementById('comment-count');
            if (cCount) cCount.innerText = data.total_comments;
            if (data.total_comments === 0) {
                var noMsg = document.getElementById('no-comments-msg');
                if (noMsg) noMsg.style.display = 'block';
            }
        } else { showToast(data.error || 'Error'); }
    });
}

function confirmLogout(e) { e.preventDefault(); showConfirm(window.TRANSLATIONS.logout, window.TRANSLATIONS.logout_confirm, () => window.location.href = '/logout'); }

function confirmDeletePost(e, postId) {
    e.preventDefault();
    showConfirm(window.TRANSLATIONS.delete, window.TRANSLATIONS.delete_confirm, function() {
        fetch('/delete/' + postId, { method: 'POST' }).then(() => { window.location.href = '/'; });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
    document.getElementById('tab-' + tabId).style.display = 'block';
}

function switchProfileTab(tabId) {
    document.querySelectorAll('.profile-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.profile-tab-content').forEach(el => el.classList.remove('active'));
    document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
    document.getElementById('profile-' + tabId).classList.add('active');
}

function validatePassword(val) {
    var itemLen = document.querySelector('[data-rule="p_len"]');
    var itemLatin = document.querySelector('[data-rule="p_latin"]');
    if (!itemLen) return;
    itemLen.classList.toggle('valid', val.length >= 6);
    var isLatin = /^[a-zA-Z0-9!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]+$/.test(val) && val.length > 0;
    itemLatin.classList.toggle('valid', isLatin);
}

var usernameTimeout;
function validateUsername(val) {
    var itemAvail = document.querySelector('[data-rule="avail"]');
    if (!itemAvail) return;
    clearTimeout(usernameTimeout);
    if (val.length > 0) {
        usernameTimeout = setTimeout(async () => {
            try {
                var res = await fetch('/api/check_username?q=' + encodeURIComponent(val));
                var data = await res.json();
                itemAvail.classList.toggle('valid', data.available);
            } catch(e) { console.error(e); }
        }, 500);
    } else { itemAvail.classList.remove('valid'); }
}

function closeWelcomeModal() {
    document.getElementById('welcome-modal').style.display = 'none';
    window.history.replaceState({}, document.title, window.location.pathname);
}

function checkWelcome() {
    if (window.location.search.includes('welcome=1')) {
        var welcome = document.getElementById('welcome-modal');
        if (welcome) welcome.style.display = 'flex';
    }
}

function scrollToCommentIfNeeded() {
    var parts = window.location.pathname.split('/').filter(Boolean);
    if (parts.length === 2) {
        var commentId = parts[1];
        var el = document.getElementById('comment-' + commentId);
        if (el) {
            setTimeout(function() {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                el.style.transition = 'background 0.5s, padding 0.5s';
                el.style.background = 'rgba(59, 130, 246, 0.2)';
                el.style.borderRadius = '8px';
                el.style.padding = '8px';
                setTimeout(function() { el.style.background = ''; el.style.padding = ''; }, 3000);
            }, 500);
        }
    }
}

// ============ SSE REALTIME ============
var eventSource = null;
var refreshBannerVisible = false;

function setupSSE() {
    if (typeof EventSource === 'undefined') return;
    if (eventSource) eventSource.close();
    eventSource = new EventSource('/api/sse');
    eventSource.onmessage = function(e) {
        try {
            var msg = JSON.parse(e.data);
            handleSSE(msg);
        } catch(err) { }
    };
    eventSource.onerror = function() {
        setTimeout(setupSSE, 5000);
    };
}

function handleSSE(msg) {
    var postId = window.CURRENT_POST_ID;

    if (msg.type === 'new_post') {
        if (window.location.pathname === '/' && !refreshBannerVisible) {
            var banner = document.getElementById('new-posts-banner');
            if (banner) {
                banner.style.display = 'flex';
                refreshBannerVisible = true;
            }
        }
    }

    if (msg.type === 'new_comment' && postId && msg.post_id === postId) {
        if (!document.getElementById('comment-' + msg.comment.id)) {
            var list = document.getElementById('comments-list');
            var noMsg = document.getElementById('no-comments-msg');
            if (noMsg) noMsg.style.display = 'none';
            if (list) list.appendChild(buildCommentDOM(msg.comment, postId, false));
            var cCount = document.getElementById('comment-count');
            if (cCount) cCount.innerText = msg.total_comments;
        }
    }

    if (msg.type === 'vote_update' && postId && msg.post_id === postId) {
        var count = document.getElementById('vote-count');
        if (count) count.innerText = msg.score;
    }

    if (msg.type === 'delete_comment' && postId && msg.post_id === postId) {
        var el = document.getElementById('comment-' + msg.comment_id);
        if (el) el.remove();
        var cCount = document.getElementById('comment-count');
        if (cCount) cCount.innerText = msg.total_comments;
        if (msg.total_comments === 0) {
            var noMsg = document.getElementById('no-comments-msg');
            if (noMsg) noMsg.style.display = 'block';
        }
    }

    if (msg.type === 'delete_post' && window.location.pathname === '/' + msg.post_id) {
        window.location.href = '/';
    }
}

function refreshFeed() {
    window.location.reload();
}

document.addEventListener('DOMContentLoaded', function() {
    applySidebarState();
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW failed'));
    checkWelcome();
    scrollToCommentIfNeeded();
    updateDates();
    setupSSE();
    // Initialize char counter if textarea exists and has a value
    var ta = document.querySelector('textarea[name="content"]');
    if (ta) updateCharCount(ta);
});

document.addEventListener('htmx:afterSwap', function(evt) {
    applySidebarState();
    closeMobileMenu();
    checkWelcome();
    scrollToCommentIfNeeded();
    updateDates();
    var carouselImgs = document.querySelectorAll('.carousel-img');
    if (carouselImgs.length > 1) {
        var currentImg = 0;
        window.showImg = function(idx) { carouselImgs.forEach((img, i) => img.style.display = i === idx ? 'block' : 'none'); };
        window.changeImg = function(dir) { currentImg = (currentImg + dir + carouselImgs.length) % carouselImgs.length; window.showImg(currentImg); };
    }
});
</script>
"""

def render_layout(content_html, user, request: Request, active_page="feed", title_text="", post_id_for_client=""):
    lang = get_lang(request)
    avatar_url = user.get('avatar') if user and user.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username'] if user else 'guest'}"
    current_lang_str = "RU" if lang == "ru" else "EN"
    next_lang = "ru" if lang == "en" else "en"
    switch_lang_url = f"/set_lang/{next_lang}?next={request.url.path}"
    page_title = f"sol-id | {title_text}" if title_text else "sol-id"
    translations_json = f"""<script>window.TRANSLATIONS = {json.dumps(TRANSLATIONS[lang], ensure_ascii=False)}; window.SVG_SAVE = `{SVG_SAVE}`; window.SVG_SAVED = `{SVG_SAVED}`; window.SVG_LINK = `{SVG_LINK}`; window.SVG_TRASH = `{SVG_TRASH}`; window.CURRENT_POST_ID = {json.dumps(post_id_for_client)};</script>"""

    if user:
        nav_right = f"""<a href="/write" class="btn-primary desktop-only" style="padding: 8px 16px;">{SVG_PLUS} {t('new_post', lang)}</a><div class="user-menu-container"><div class="user-menu-btn" onclick="toggleDropdown()"><img src="{avatar_url}" class="user-avatar-small"></div><div id="user-dropdown" class="dropdown-menu"><div class="dropdown-header"><img src="{avatar_url}"><div><span class="name">{html.escape(user['display_name'])}</span><span class="login">@{html.escape(user['username'])}</span></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="#" onclick="confirmLogout(event)" class="dropdown-item danger">{SVG_LOGOUT} {t('logout', lang)}</a></div></div>"""
    else:
        nav_right = f"""<a href="/login" class="btn-primary desktop-only" style="padding:8px 16px;">{SVG_USER} <span>{t('login', lang)}</span></a>"""
    lang_switch_html = f"""<a href="{switch_lang_url}" class="action-btn" style="border:none; background:var(--card-bg); padding:0 10px; color:var(--text-main); font-weight:bold;">{SVG_LANG} <span class="desktop-only" style="margin-left:5px;">{current_lang_str}</span></a>"""

    sidebar_html = ""
    if user:
        sidebar_html = f"""<div class="sidebar"><a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} <span>{t('feed', lang)}</span></a><a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE} <span>{t('saved', lang)}</span></a><a href="/@{user['username']}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} <span>{t('profile', lang)}</span></a><a href="https://eblo.id" target="_blank" class="sidebar-bottom-banner"><img src="{SPRITE_URL}" alt="eblo.id"><div class="banner-text">{t('idea_by', lang)}</div></a></div>"""

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
        <div id="new-posts-banner" class="new-posts-banner" onclick="refreshFeed()">
            {t('new_posts_available', lang)}
        </div>
        {content_html}
    </div>
</div>
{f'''<div id="mobileMenuOverlay" class="mobile-menu-overlay" onclick="closeMobileMenu()"></div><div id="mobileProfileMenu" class="mobile-profile-menu"><div class="mobile-profile-header"><img src="{avatar_url}"><div><div style="font-weight:700; font-size:16px;">{html.escape(user['display_name'])}</div><div style="color:var(--text-muted); font-size:14px;">@{html.escape(user['username'])}</div></div></div><a href="/@{user['username']}" class="dropdown-item">{SVG_USER} {t('profile', lang)}</a><a href="/settings" class="dropdown-item">{SVG_SETTINGS} {t('settings', lang)}</a><a href="#" onclick="confirmLogout(event)" class="dropdown-item danger">{SVG_LOGOUT} {t('logout', lang)}</a></div>''' if user else ''}

<div id="photo-viewer">
    <button class="photo-viewer-close" onclick="closePanorama()">&times;</button>
    <button class="photo-viewer-btn photo-nav-prev" onclick="photoPrev()" style="position:absolute; left:15px; top:50%; transform:translateY(-50%); width:48px; height:48px;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
    </button>
    <button class="photo-viewer-btn photo-nav-next" onclick="photoNext()" style="position:absolute; right:15px; top:50%; transform:translateY(-50%); width:48px; height:48px;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
    </button>
    <img id="photo-viewer-img" src="" onclick="event.stopPropagation()">
    <div class="photo-viewer-controls">
        <button class="photo-viewer-btn" onclick="photoZoom(-0.3)">-</button>
        <button class="photo-viewer-btn" onclick="photoReset()" style="font-size:12px; width:auto; padding:0 16px; border-radius:20px;">{t('reset', lang)}</button>
        <button class="photo-viewer-btn" onclick="photoZoom(0.3)">+</button>
    </div>
</div>

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

@app.get("/set_lang/{lang}")
async def set_lang(lang: str, next: str = "/"):
    response = RedirectResponse(url=next, status_code=status.HTTP_302_FOUND)
    if lang in ["en", "ru"]: response.set_cookie(key="lang", value=lang, max_age=31536000, httponly=False)
    return response

@app.get("/api/search")
async def api_search(q: str = ""):
    q_lower = q.lower().strip()
    if not q_lower: return JSONResponse({"results": []})
    results = []
    for p in posts_db.values():
        if p.get('visibility') != 'feed': continue
        if q_lower in p['title'].lower() or q_lower in p.get('content', '').lower() or q_lower in p['author'].lower():
            results.append({"id": p['id'], "title": html.escape(p['title']), "author": html.escape(p['author'])})
    return JSONResponse({"results": results[:5]})

@app.get("/search", response_class=HTMLResponse)
async def search_posts(request: Request, q: str = ""):
    user = get_current_user(request)
    lang = get_lang(request)
    q_lower = q.lower().strip()
    results = []
    if q_lower:
        for p in posts_db.values():
            if p.get('visibility') != 'feed': continue
            if q_lower in p['title'].lower() or q_lower in p.get('content', '').lower() or q_lower in p['author'].lower():
                results.append(p)
    if not results:
        content = f'<div style="padding:15px;"><h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{html.escape(q)}"</h2><div style="text-align:center; padding: 60px 20px; color: var(--text-muted); font-size:18px;">{t("nothing_found", lang)}</div></div>'
    else:
        cards = ""
        for post in results:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            media_html = render_card_media(post)
            date_iso = post.get('created_at', '')
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{media_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date" data-iso="{date_iso}"></div></div></div></a>"""
        content = f'<div style="padding:15px;"><h2 style="margin-bottom:30px; font-size:24px;">{t("search_results", lang)}: "{html.escape(q)}"</h2><div class="feed-grid">{cards}</div></div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed", t('search_results', lang)))

@app.get("/", response_class=HTMLResponse)
async def read_feed(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    feed_posts = sorted([p for p in posts_db.values() if p.get('visibility') == 'feed'], key=lambda p: p.get('created_at', ''), reverse=True)
    if not feed_posts:
        content = f'<div style="text-align:center; padding: 80px 20px; color: var(--text-muted);"><h3 style="font-size: 28px; color: #fff; margin-bottom: 15px;">{t("no_posts", lang)}</h3></div>'
    else:
        cards = ""
        for post in feed_posts:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            media_html = render_card_media(post)
            score = get_score(post['id'])
            arrow_icon = SVG_DOWN if score < 0 else SVG_UP
            date_iso = post.get('created_at', '')
            cards += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{media_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div style="display:flex;align-items:center;gap:10px;"><div class="post-date" data-iso="{date_iso}"></div><div style="display:flex;align-items:center;gap:4px;">{arrow_icon} {score}</div></div></div></div></a>"""
        content = f'<div class="feed-grid">{cards}</div>'
    return HTMLResponse(content=render_layout(content, user, request, "feed", t('feed', lang)))

@app.get("/saved", response_class=HTMLResponse)
async def saved_posts(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    saved_ids = user.get('saved_posts', [])
    saved_posts_list = [posts_db[pid] for pid in saved_ids if pid in posts_db]
    if not saved_posts_list:
        content = f"<div style='text-align:center; padding:60px; color:var(--text-muted); font-size:18px;'>{t('no_saved', lang)}</div>"
    else:
        cards = ""
        for post in saved_posts_list:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            media_html = render_card_media(post)
            date_iso = post.get('created_at', '')
            cards += f"""<div class="feed-card"><button onclick="toggleSave('{post['id']}', true)" class="feed-card-remove-btn" title="{t('remove_saved', lang)}">×</button><a href="/{post['id']}" style="display:flex; flex-direction:column; flex:1;"><div class="feed-card-img-container">{media_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date" data-iso="{date_iso}"></div></div></div></a></div>"""
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
                <input type="text" name="username" id="usernameInput" placeholder="{t('username', lang)}" required autocomplete="off" oninput="validateUsername(this.value)">
                <ul class="val-list"><li class="val-item" data-rule="avail">{SVG_CROSS}{SVG_CHECK} {t('val_avail', lang)}</li></ul>
            </div>
            <div class="input-group" style="margin-top:15px;">
                <input type="password" name="password" id="passwordInput" placeholder="{t('password', lang)}" required oninput="validatePassword(this.value)">
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
    user = users_db.get(username)
    is_new = False
    if user:
        if not pwd_context.verify(password, user["password"]):
            return HTMLResponse(content=render_layout(f'<div class="auth-container"><div class="auth-form"><div class="error">{t("wrong_pass", lang)}</div><a href="/login" class="btn-primary">{t("back", lang)}</a></div></div>', None, request, "login", t('login', lang)))
    else:
        new_user_data = {"username": username, "password": pwd_context.hash(password), "display_name": username, "avatar": None, "saved_posts": []}
        supabase.table("users").insert(new_user_data).execute()
        users_db[username] = new_user_data
        is_new = True
    session_token = str(uuid.uuid4())
    sessions[session_token] = username
    redirect_url = "/?welcome=1" if is_new else "/"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
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
                        <input type="file" id="avatar-file" name="avatar" accept="image/*,image/gif" onchange="loadAvatar(event)" style="display:none;">
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
    if avatar_base64: update_data["avatar"] = avatar_base64
    elif avatar and avatar.filename: update_data["avatar"] = await image_to_base64(avatar)
    supabase.table("users").update(update_data).eq("username", user['username']).execute()
    for k, v in update_data.items(): users_db[user['username']][k] = v
    return RedirectResponse(url="/settings?updated=1", status_code=status.HTTP_302_FOUND)

@app.get("/write", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    lang = get_lang(request)
    if not user: return RedirectResponse(url="/login")
    content = f"""<div style="max-width: 1100px; margin: 0 auto; width: 100%;"><h2 style="margin-bottom: 30px; font-weight: 700; font-size: 32px; padding: 15px 15px 0 15px;">{t('new_post', lang)}</h2><form action="/write" method="post" enctype="multipart/form-data" hx-encoding="multipart/form-data" class="create-layout"><div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()"><div id="dropzone-text" style="display:flex; flex-direction:column; align-items:center;">{SVG_IMAGE}<div style="margin-top:20px; font-size:20px; font-weight:700; color:#fff;">{t('upload_hint', lang)}</div><div style="margin-top:10px; font-size:15px; color:var(--text-muted);">{t('upload_limit', lang)}</div><div style="margin-top:20px; background:#2a2a2a; padding:12px 24px; border-radius:8px; color:#fff; font-weight:500; border:1px solid var(--border-color); cursor:pointer;">{t('choose_files', lang)}</div></div><div id="file-list" style="width:100%; display:flex; flex-direction:column; gap:10px;"></div><input id="file-input" type="file" name="images" multiple accept="image/*,image/gif" style="display:none;" onchange="handleFiles(this)" onclick="event.stopPropagation()"></div><div class="create-sidebar"><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('title', lang)} *</label><input type="text" name="title" placeholder="{t('title', lang)}" required style="padding:14px;"></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('description', lang)} (Max 2500)</label><textarea name="content" placeholder="{t('description', lang)}" maxlength="2500" oninput="updateCharCount(this)" style="min-height:140px; padding:14px;"></textarea><div class="char-counter" id="char-count">0 / 2500</div></div><div class="input-group"><label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">{t('visibility', lang)}</label><div style="display:flex; gap:10px;"><button type="button" id="btn-feed" onclick="setVisibility('feed')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--accent-color); color:var(--accent-color); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_EYE} {t('in_feed', lang)}</button><button type="button" id="btn-link" onclick="setVisibility('link')" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--border-color); color:var(--text-muted); cursor:pointer; font-family:inherit; font-size:15px;">{SVG_LINK} {t('by_link', lang)}</button></div><input type="hidden" name="visibility" id="vis-input" value="feed"></div><div class="input-group" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;"><label style="font-size:15px; font-weight:700; color:#fff;">{t('allow_comments', lang)}</label><label class="switch"><input type="checkbox" name="allow_comments" checked><span class="slider"></span></label></div><button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:16px; font-size:16px;">{SVG_PLUS} {t('publish', lang)}</button></div></form></div>"""
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
    post_id = generate_post_id(visibility)
    new_post = {
        "id": post_id, "author": user["username"],
        "title": html.escape(title), "content": html.escape(content[:2500]),
        "images": img_b64_list, "visibility": visibility,
        "votes": {"up": [], "down": []}, "comments": [],
        "allow_comments": allow_comments,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    supabase.table("posts").insert(new_post).execute()
    posts_db[post_id] = new_post
    if visibility == 'feed':
        sse_send({"type": "new_post", "post_id": post_id})
    return RedirectResponse(url=f"/{post_id}", status_code=status.HTTP_302_FOUND)

@app.post("/api/vote/{post_id}/{action}")
async def vote_post(post_id: str, action: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if post_id not in posts_db: return JSONResponse({"error": "Not found"}, status_code=404)
    username = user['username']
    old_vote = votes_db.get((post_id, username), 0)
    delta = 0
    new_vote = 0
    if action == 'up':
        if old_vote == 1:
            votes_db.pop((post_id, username), None); delta = -1; new_vote = 0
            supabase.table("users_vote").delete().eq("post_id", post_id).eq("username", username).execute()
        else:
            delta = 1 - old_vote
            votes_db[(post_id, username)] = 1; new_vote = 1
            supabase.table("users_vote").upsert({"post_id": post_id, "username": username, "vote": 1}).execute()
    elif action == 'down':
        if old_vote == -1:
            votes_db.pop((post_id, username), None); delta = 1; new_vote = 0
            supabase.table("users_vote").delete().eq("post_id", post_id).eq("username", username).execute()
        else:
            delta = -1 - old_vote
            votes_db[(post_id, username)] = -1; new_vote = -1
            supabase.table("users_vote").upsert({"post_id": post_id, "username": username, "vote": -1}).execute()
    else: return JSONResponse({"error": "Invalid action"}, status_code=400)
    scores_cache[post_id] = scores_cache.get(post_id, 0) + delta
    sse_send({"type": "vote_update", "post_id": post_id, "score": scores_cache[post_id]})
    return JSONResponse({"score": scores_cache[post_id], "user_vote": new_vote})

@app.post("/api/save/{post_id}")
async def save_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    saved_posts = list(user.get('saved_posts', []))
    if post_id in saved_posts: saved_posts.remove(post_id); saved = False
    else: saved_posts.append(post_id); saved = True
    supabase.table("users").update({"saved_posts": saved_posts}).eq("username", user['username']).execute()
    users_db[user['username']]['saved_posts'] = saved_posts
    return JSONResponse({"saved": saved})

@app.post("/api/comment/{post_id}")
async def add_comment(post_id: str, request: Request, text: str = Form(...)):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if post_id not in posts_db: return JSONResponse({"error": "Not found"}, status_code=404)
    if not posts_db[post_id].get('allow_comments', True): return JSONResponse({"error": "Comments disabled"}, status_code=403)
    new_comment_id = str(uuid.uuid4())[:8]
    new_comment = {"id": new_comment_id, "post_id": post_id, "login": user['username'], "comment_text": html.escape(text)}
    supabase.table("comments").insert(new_comment).execute()
    if post_id not in comments_db: comments_db[post_id] = []
    comments_db[post_id].append(new_comment)
    author = users_db.get(user['username'])
    display_name = author.get('display_name') if author else user['username']
    avatar = author.get('avatar') if author else None
    resp_comment = {"id": new_comment_id, "login": user['username'], "display_name": display_name, "avatar": avatar, "text": html.escape(text)}
    sse_send({"type": "new_comment", "post_id": post_id, "comment": resp_comment, "total_comments": len(comments_db[post_id])})
    return JSONResponse({"comment": resp_comment, "total_comments": len(comments_db[post_id]), "is_author": True})

@app.delete("/api/comment/{post_id}/{comment_id}")
async def delete_comment(post_id: str, comment_id: str, request: Request):
    user = get_current_user(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if post_id not in posts_db: return JSONResponse({"error": "Not found"}, status_code=404)
    post_comments = comments_db.get(post_id, [])
    comment = next((c for c in post_comments if c['id'] == comment_id), None)
    if not comment: return JSONResponse({"error": "Comment not found"}, status_code=404)
    if comment['login'] != user['username']: return JSONResponse({"error": "Forbidden"}, status_code=403)
    supabase.table("comments").delete().eq("id", comment_id).execute()
    comments_db[post_id] = [c for c in post_comments if c['id'] != comment_id]
    sse_send({"type": "delete_comment", "post_id": post_id, "comment_id": comment_id, "total_comments": len(comments_db[post_id])})
    return JSONResponse({"success": True, "total_comments": len(comments_db[post_id])})

@app.post("/delete/{post_id}")
async def delete_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    if post_id in posts_db and posts_db[post_id]['author'] == user['username']:
        supabase.table("posts").delete().eq("id", post_id).execute()
        del posts_db[post_id]
        scores_cache.pop(post_id, None)
        comments_db.pop(post_id, None)
        for key in list(votes_db.keys()):
            if key[0] == post_id: del votes_db[key]
        sse_send({"type": "delete_post", "post_id": post_id})
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@app.get("/@{username}", response_class=HTMLResponse)
async def view_profile(request: Request, username: str):
    current_user = get_current_user(request)
    lang = get_lang(request)
    profile_user = users_db.get(username)
    if not profile_user: raise HTTPException(404, "User not found")
    ava = profile_user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
    is_own_profile = current_user and current_user['username'] == username
    if is_own_profile: user_posts = sorted([p for p in posts_db.values() if p['author'] == username], key=lambda p: p.get('created_at', ''), reverse=True)
    else: user_posts = sorted([p for p in posts_db.values() if p['author'] == username and p.get('visibility') == 'feed'], key=lambda p: p.get('created_at', ''), reverse=True)
    posts_html = ""
    for post in user_posts:
        media_html = render_card_media(post)
        badge = f'<div class="post-badge" title="{t("link_only", lang)}">{SVG_LOCK}</div>' if post.get('visibility') == 'link' else ''
        date_iso = post.get('created_at', '')
        posts_html += f"""<a href="/{post['id']}" class="feed-card">{badge}<div class="feed-card-img-container">{media_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="post-date" data-iso="{date_iso}"></div></div></div></a>"""
    if not posts_html: posts_html = f'<div style="color:var(--text-muted); font-size:18px; text-align:center; padding:40px 20px; width:100%;">{t("no_posts", lang)}</div>'
    saved_html = ""
    saved_ids = profile_user.get('saved_posts', [])
    if saved_ids:
        saved_posts_list = [posts_db[pid] for pid in saved_ids if pid in posts_db]
        for post in saved_posts_list:
            author = users_db.get(post['author'])
            a_ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            media_html = render_card_media(post)
            date_iso = post.get('created_at', '')
            saved_html += f"""<a href="/{post['id']}" class="feed-card"><div class="feed-card-img-container">{media_html}</div><div class="feed-card-info"><div class="feed-card-title">{html.escape(post['title'])}</div><div class="feed-card-meta"><div class="feed-card-author"><img src="{a_ava}" style="width:24px;height:24px;border-radius:50%;"> @{html.escape(post['author'])}</div><div class="post-date" data-iso="{date_iso}"></div></div></div></a>"""
    if not saved_html: saved_html = f'<div style="color:var(--text-muted); font-size:18px; text-align:center; padding:40px 20px; width:100%;">{t("no_saved", lang)}</div>'
    edit_btn = f'<div class="profile-edit-btn-wrapper"><a href="/settings" class="action-btn" style="border-radius:50%; width:44px; height:44px; padding:0; justify-content:center;" title="{t("edit_profile", lang)}">{SVG_SETTINGS}</a></div>' if is_own_profile else ''
    tabs_html = f"""<div class="profile-tabs"><button class="profile-tab-btn active" data-tab="posts" onclick="switchProfileTab('posts')">{t('posts', lang)}</button>{f'<button class="profile-tab-btn" data-tab="saved" onclick="switchProfileTab(\'saved\')">{t("saved", lang)}</button>' if is_own_profile else ''}</div>"""
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
    <div id="profile-posts" class="profile-tab-content active"><div class="feed-grid">{posts_html}</div></div>
    {f'<div id="profile-saved" class="profile-tab-content"><div class="feed-grid">{saved_html}</div></div>' if is_own_profile else ''}
    """
    return HTMLResponse(content=render_layout(content, current_user, request, "profile", f"@{username}"))

@app.get("/{post_id}/{comment_id}", response_class=HTMLResponse)
async def view_post_with_comment(request: Request, post_id: str, comment_id: str):
    return await _render_post_page(request, post_id)

@app.get("/{post_id}", response_class=HTMLResponse)
async def view_post(request: Request, post_id: str):
    return await _render_post_page(request, post_id)

async def _render_post_page(request: Request, post_id: str):
    user = get_current_user(request)
    lang = get_lang(request)
    post = posts_db.get(post_id)
    if not post: raise HTTPException(404, "Post not found")
    author = users_db.get(post['author'])
    ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
    score = get_score(post_id)
    user_vote = votes_db.get((post_id, user['username']), 0) if user else 0
    is_saved = user and post_id in user.get('saved_posts', [])
    referer = request.headers.get("referer", "")
    show_back = False
    if referer:
        base = str(request.base_url).rstrip('/')
        if referer.startswith(base) and request.url.path not in referer:
            show_back = True
    back_html = f'<a href="javascript:history.back()" id="back-btn" style="display:{"flex" if show_back else "none"}; align-items:center; color:var(--text-muted); padding:8px;">{SVG_BACK}</a>'
    delete_btn = f'''<button onclick="confirmDeletePost(event, '{post_id}')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; padding:8px; display:flex; align-items:center; justify-content:center; border-radius:8px;">{SVG_TRASH}</button>''' if user and user['username'] == post['author'] else ''
    has_media = bool(post.get('images'))
    if has_media:
        imgs_html = ""
        for i, img in enumerate(post['images']):
            display = "" if i == 0 else "none"
            imgs_html += f'<img src="{img}" style="width:100%; height:100%; object-fit:contain; display:{display};" class="carousel-img" onclick="openPanorama(this, {i})">'
        nav_btns = f'<div class="carousel-nav-btn left" onclick="changeImg(-1)">{SVG_LEFT}</div><div class="carousel-nav-btn right" onclick="changeImg(1)">{SVG_RIGHT}</div>' if len(post['images']) > 1 else ''
        safe_images_json = html.escape(json.dumps(post['images']))
        media_html = f"""<div class="post-media" id="post-media-container" data-images="{safe_images_json}" style="position:relative;">{imgs_html}{nav_btns}</div>"""
    else:
        media_html = ''
    if user:
        save_icon_html = SVG_SAVED if is_saved else SVG_SAVE
        save_btn_style = "color:var(--accent-color); border-color:var(--accent-color);" if is_saved else ""
        actions_html = f"""<div class="actions-row"><div class="vote-controls"><button onclick="vote('{post['id']}', 'up')" id="btn-up" class="vote-btn {'active-up' if user_vote == 1 else ''}">{SVG_UP}</button><span class="vote-count" id="vote-count">{score}</span><button onclick="vote('{post['id']}', 'down')" id="btn-down" class="vote-btn {'active-down' if user_vote == -1 else ''}">{SVG_DOWN}</button></div><button onclick="toggleSave('{post['id']}')" id="btn-save" class="action-btn" style="{save_btn_style}" title="{t('save_post', lang)}">{save_icon_html}</button><button class="action-btn" onclick="copyLink()" title="{t('copy_link', lang)}">{SVG_LINK}</button>{delete_btn}</div>"""
    else:
        actions_html = f"""<div class="actions-row"><button class="action-btn" onclick="copyLink()" title="{t('copy_link', lang)}">{SVG_LINK}</button></div><div class="login-notice"><a href="/login">{t('login', lang)}</a> · {t('login_to_interact', lang)}</div>"""
    if post.get('allow_comments', True):
        if user: comments_input_html = f"""<form onsubmit="submitComment(event, '{post['id']}')" hx-boost="false" style="background:var(--bg-color); padding:12px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); display:flex; gap:10px;"><input type="text" id="comment-input" placeholder="{t('write_comment', lang)}" style="flex:1; background:transparent; border:none; color:#fff; outline:none; font-size:15px;"><button type="submit" class="btn-primary" style="padding:5px 15px;">{t('send', lang)}</button></form>"""
        else: comments_input_html = f"""<div class="login-notice" style="margin-bottom:20px;"><a href="/login">{t('login', lang)}</a> · {t('login_to_comment', lang)}</div>"""
    else: comments_input_html = f'<div style="background:rgba(239,68,68,0.1); color:var(--danger-color); padding:15px; border-radius:8px; margin-bottom:20px; text-align:center; font-weight:500;">{t("comments_disabled", lang)}</div>'
    post_comments = comments_db.get(post_id, [])
    comments_list_html = ""
    for c in post_comments:
        author_c = users_db.get(c['login'])
        c_display = author_c.get('display_name') if author_c else c['login']
        c_ava = author_c.get('avatar') if author_c and author_c.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={c['login']}"
        c_text = c['comment_text']
        copy_btn = f'<button onclick="copyCommentLink(\'{post_id}\', \'{c["id"]}\')" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:5px; display:flex; align-items:center;" title="{t("copy_comment_link", lang)}">{SVG_LINK}</button>'
        del_btn = f'<button onclick="confirmDeleteComment(\'{post_id}\', \'{c["id"]}\')" style="background:none; border:none; color:var(--danger-color); cursor:pointer; padding:5px; display:flex; align-items:center;" title="{t("delete_comment", lang)}">{SVG_TRASH}</button>' if user and user['username'] == c['login'] else ''
        comments_list_html += f"""<div id="comment-{c['id']}" style="display:flex; gap:10px; margin-bottom:15px; justify-content:space-between;"><div style="display:flex; gap:10px;"><img src="{c_ava}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;"><div><div style="font-weight:700; font-size:14px;">{c_display} <span style="color:var(--text-muted); font-weight:400; font-size:12px;">@{c['login']}</span></div><div style="font-size:14px; margin-top:2px;">{c_text}</div></div></div><div style="display:flex;gap:2px;align-items:flex-start;">{copy_btn}{del_btn}</div></div>"""
    no_comments_style = "display:block;" if len(post_comments) == 0 else "display:none;"
    date_iso = post.get('created_at', '')
    details_html = f"""<div class="post-details">
            <div class="post-top-info">
                <div class="post-author">
                    <a href="/@{post['author']}"><img src="{ava}"></a>
                    <div>
                        <a href="/@{post['author']}" style="color:#fff; font-weight:700; font-size:18px;">{html.escape(author['display_name']) if author else html.escape(post['author'])}</a>
                        <div style="font-size:14px; color:var(--text-muted);">@{html.escape(post['author'])} • <span data-iso="{date_iso}" data-absolute="true"></span></div>
                    </div>
                </div>
                <div class="post-title selectable">{html.escape(post['title'])}</div>
                <div class="post-desc selectable">{html.escape(post['content'])}</div>
                {actions_html}
            </div>
            <div class="comments-section">
                <h3 style="margin-bottom:15px; font-weight:700; font-size:18px;">{t('comments', lang)} (<span id="comment-count">{len(post_comments)}</span>)</h3>
                {comments_input_html}
                <div id="no-comments-msg" style="{no_comments_style} font-size:15px; color:var(--text-muted); text-align:center; padding:20px;">{t('no_comments', lang)}</div>
                <div id="comments-list">{comments_list_html}</div>
            </div>
        </div>"""
    if has_media:
        post_view_html = f'<div class="post-view">{media_html}{details_html}</div>'
    else:
        post_view_html = f'<div class="post-view no-media">{details_html}</div>'
    content = f"""<div class="post-header-actions" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">{back_html}</div>
    {post_view_html}"""
    return HTMLResponse(content=render_layout(content, user, request, "feed", html.escape(post['title']), post_id_for_client=post_id))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
