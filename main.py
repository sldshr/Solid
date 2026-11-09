# main.py
import base64
import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="SlideTok")

# ============ IN-MEMORY STORAGE ============
USERS_BY_NAME: Dict[str, dict] = {}
USERS_BY_ID: Dict[str, dict] = {}
SESSIONS: Dict[str, str] = {}          # token -> user_id
SLIDESHOWS: List[dict] = []
LIKES: Dict[str, set] = {}             # show_id -> set of user_ids


# ============ HELPERS ============
def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def make_user(username: str, password: str) -> dict:
    salt = secrets.token_hex(16)
    user = {
        "id": str(uuid.uuid4()),
        "username": username,
        "salt": salt,
        "password_hash": hash_password(password, salt),
    }
    USERS_BY_NAME[username] = user
    USERS_BY_ID[user["id"]] = user
    return user


def get_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    if not token:
        return None
    uid = SESSIONS.get(token)
    return USERS_BY_ID.get(uid) if uid else None


def require_user(request: Request) -> dict:
    user = get_user(request)
    if not user:
        raise HTTPException(401, "Требуется вход")
    return user


def set_session(response: Response, user: dict) -> None:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user["id"]
    response.set_cookie(
        "session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )


def serialize_show(show: dict, viewer_id: Optional[str] = None) -> dict:
    owner = USERS_BY_ID.get(show["user_id"])
    likes = LIKES.get(show["id"], set())
    return {
        "id": show["id"],
        "user_id": show["user_id"],
        "username": owner["username"] if owner else "deleted",
        "title": show["title"],
        "slides": show["slides"],
        "likes": len(likes),
        "liked": bool(viewer_id and viewer_id in likes),
        "mine": bool(viewer_id and viewer_id == show["user_id"]),
        "created": show["created"],
    }


def validate_slides(slides) -> None:
    if not isinstance(slides, list) or not slides:
        raise HTTPException(400, "Нужно хотя бы одно фото")
    if len(slides) > 20:
        raise HTTPException(400, "Максимум 20 фото")
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            raise HTTPException(400, f"Слайд {i + 1}: некорректный формат")
        img = s.get("image")
        if not isinstance(img, str) or not img.startswith("data:image/"):
            raise HTTPException(400, f"Слайд {i + 1}: некорректное изображение")
        if len(img) > 6_000_000:
            raise HTTPException(400, f"Слайд {i + 1}: изображение слишком большое")
        texts = s.get("texts", [])
        if not isinstance(texts, list):
            raise HTTPException(400, f"Слайд {i + 1}: тексты должны быть списком")
        if len(texts) > 20:
            raise HTTPException(400, f"Слайд {i + 1}: слишком много текстов")
        for t in texts:
            if not isinstance(t, dict):
                raise HTTPException(400, f"Слайд {i + 1}: некорректный текст")
            if not isinstance(t.get("text"), str) or len(t["text"]) > 300:
                raise HTTPException(400, f"Слайд {i + 1}: некорректный текст")
            if not isinstance(t.get("x"), (int, float)) or not 0 <= t["x"] <= 100:
                raise HTTPException(400, f"Слайд {i + 1}: некорректная позиция X")
            if not isinstance(t.get("y"), (int, float)) or not 0 <= t["y"] <= 100:
                raise HTTPException(400, f"Слайд {i + 1}: некорректная позиция Y")
            if not isinstance(t.get("size"), (int, float)) or not 1 <= t["size"] <= 30:
                raise HTTPException(400, f"Слайд {i + 1}: некорректный размер шрифта")
            if not isinstance(t.get("color"), str) or len(t["color"]) > 24:
                raise HTTPException(400, f"Слайд {i + 1}: некорректный цвет")


# ============ DEMO SEED ============
def svg_data_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def demo_image(c1: str, c2: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1600">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        "</linearGradient></defs>"
        '<rect width="900" height="1600" fill="url(#g)"/>'
        "</svg>"
    )
    return svg_data_url(svg)


def tid() -> str:
    return "t_" + secrets.token_hex(6)


def seed_demo() -> None:
    demo = make_user("demo", "demo")

    def add(title: str, slides: list) -> None:
        sid = str(uuid.uuid4())
        SLIDESHOWS.append({
            "id": sid,
            "user_id": demo["id"],
            "title": title,
            "slides": slides,
            "created": datetime.utcnow().isoformat(),
        })
        LIKES[sid] = set()

    add("Привет, мир", [
        {
            "image": demo_image("#e74c3c", "#c0392b"),
            "texts": [
                {"id": tid(), "text": "Привет", "x": 50, "y": 45, "color": "#ffffff", "size": 9},
                {"id": tid(), "text": "это SlideTok", "x": 50, "y": 58, "color": "#ffffff", "size": 5},
            ],
        },
        {"image": demo_image("#3498db", "#2c3e50"), "texts": []},
    ])
    add("Закат", [
        {
            "image": demo_image("#ff7e5f", "#feb47b"),
            "texts": [{"id": tid(), "text": "Закат", "x": 50, "y": 50, "color": "#ffffff", "size": 10}],
        },
        {"image": demo_image("#fbc2eb", "#a6c1ee"), "texts": []},
        {"image": demo_image("#a1c4fd", "#c2e9fb"), "texts": []},
    ])
    add("Минимализм", [
        {"image": demo_image("#232526", "#414345"), "texts": [
            {"id": tid(), "text": "меньше", "x": 50, "y": 48, "color": "#ffffff", "size": 8},
            {"id": tid(), "text": "значит больше", "x": 50, "y": 58, "color": "#a3a3a3", "size": 4},
        ]},
    ])


seed_demo()


# ============ MODELS ============
class AuthIn(BaseModel):
    username: str
    password: str


class ShowIn(BaseModel):
    title: str = ""
    slides: List[dict]


class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    new_password: Optional[str] = None
    current_password: Optional[str] = None


# ============ AUTH ============
def _check_username(name: str) -> str:
    name = (name or "").strip()
    if len(name) < 3 or len(name) > 32:
        raise HTTPException(400, "Имя от 3 до 32 символов")
    if not all(c.isalnum() or c in "_." for c in name):
        raise HTTPException(400, "Имя: только буквы, цифры, _ и .")
    return name


@app.post("/api/register")
async def register(data: AuthIn, response: Response):
    name = _check_username(data.username)
    if len(data.password) < 4:
        raise HTTPException(400, "Пароль минимум 4 символа")
    if name.lower() in [u.lower() for u in USERS_BY_NAME]:
        raise HTTPException(400, "Имя занято")
    user = make_user(name, data.password)
    set_session(response, user)
    return {"id": user["id"], "username": user["username"]}


@app.post("/api/login")
async def login(data: AuthIn, response: Response):
    user = USERS_BY_NAME.get((data.username or "").strip())
    if not user or user["password_hash"] != hash_password(data.password, user["salt"]):
        raise HTTPException(400, "Неверное имя или пароль")
    set_session(response, user)
    return {"id": user["id"], "username": user["username"]}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        SESSIONS.pop(token, None)
    response.delete_cookie("session")
    return {"ok": True}


# ============ ME ============
@app.get("/api/me")
async def me(request: Request):
    user = require_user(request)
    mine = [s for s in SLIDESHOWS if s["user_id"] == user["id"]]
    total_likes = sum(len(LIKES.get(s["id"], set())) for s in mine)
    return {
        "id": user["id"],
        "username": user["username"],
        "shows_count": len(mine),
        "likes_count": total_likes,
    }


@app.patch("/api/me")
async def update_me(data: ProfileUpdate, request: Request):
    user = require_user(request)

    if data.username is not None:
        new_name = _check_username(data.username)
        if new_name != user["username"]:
            if new_name.lower() in [u.lower() for u in USERS_BY_NAME]:
                raise HTTPException(400, "Имя занято")
            del USERS_BY_NAME[user["username"]]
            user["username"] = new_name
            USERS_BY_NAME[new_name] = user

    if data.new_password:
        if not data.current_password:
            raise HTTPException(400, "Введите текущий пароль")
        if user["password_hash"] != hash_password(data.current_password, user["salt"]):
            raise HTTPException(400, "Неверный текущий пароль")
        if len(data.new_password) < 4:
            raise HTTPException(400, "Новый пароль минимум 4 символа")
        user["salt"] = secrets.token_hex(16)
        user["password_hash"] = hash_password(data.new_password, user["salt"])

    return {"id": user["id"], "username": user["username"]}


@app.get("/api/me/slideshows")
async def my_shows(request: Request):
    user = require_user(request)
    mine = [s for s in SLIDESHOWS if s["user_id"] == user["id"]]
    return [serialize_show(s, user["id"]) for s in mine]


# ============ SLIDESHOWS ============
@app.get("/api/slideshows")
async def list_shows(request: Request):
    user = get_user(request)
    uid = user["id"] if user else None
    return [serialize_show(s, uid) for s in SLIDESHOWS]


@app.post("/api/slideshows")
async def create_show(data: ShowIn, request: Request):
    user = require_user(request)
    validate_slides(data.slides)
    title = (data.title or "").strip()[:80] or "Без названия"
    show = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "title": title,
        "slides": data.slides,
        "created": datetime.utcnow().isoformat(),
    }
    SLIDESHOWS.insert(0, show)
    LIKES[show["id"]] = set()
    return serialize_show(show, user["id"])


@app.delete("/api/slideshows/{show_id}")
async def delete_show(show_id: str, request: Request):
    user = require_user(request)
    for i, s in enumerate(SLIDESHOWS):
        if s["id"] == show_id:
            if s["user_id"] != user["id"]:
                raise HTTPException(403, "Не ваше слайдшоу")
            SLIDESHOWS.pop(i)
            LIKES.pop(show_id, None)
            return {"ok": True}
    raise HTTPException(404, "Не найдено")


@app.post("/api/slideshows/{show_id}/like")
async def toggle_like(show_id: str, request: Request):
    user = require_user(request)
    if not any(s["id"] == show_id for s in SLIDESHOWS):
        raise HTTPException(404, "Не найдено")
    likes = LIKES.setdefault(show_id, set())
    if user["id"] in likes:
        likes.discard(user["id"])
        liked = False
    else:
        likes.add(user["id"])
        liked = True
    return {"liked": liked, "likes": len(likes)}


# ============ HTML ============
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0a">
<title>SlideTok</title>
<style>
:root {
  --bg: #0a0a0a;
  --surface: #171717;
  --surface-2: #262626;
  --border: #2a2a2a;
  --text: #f5f5f5;
  --dim: #a3a3a3;
  --dimmer: #666;
  --like: #ff3b5c;
}
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body {
  height: 100%; overflow: hidden; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
button { font-family: inherit; cursor: pointer; border: none; background: none; color: inherit; }
input, textarea { font-family: inherit; }
.hidden { display: none !important; }
.screen { position: fixed; inset: 0; background: var(--bg); }

/* Buttons */
.btn-primary {
  padding: 12px 16px; background: var(--text); color: var(--bg);
  border-radius: 8px; font-size: 15px; font-weight: 600;
}
.btn-primary:disabled { opacity: 0.35; cursor: not-allowed; }
.btn-sm { padding: 8px 14px; font-size: 14px; }
.btn-ghost {
  padding: 8px 14px; background: none; border: 1px solid var(--border);
  color: var(--text); border-radius: 8px; font-size: 14px; font-weight: 500;
}
.btn-danger {
  padding: 8px 14px; background: none; border: 1px solid #4a1a20;
  color: var(--like); border-radius: 8px; font-size: 14px; font-weight: 500;
}
.icon-btn {
  width: 38px; height: 38px; display: grid; place-items: center;
  border-radius: 8px; flex-shrink: 0;
}
.icon-btn:active { background: var(--surface); }
.icon-btn svg { width: 22px; height: 22px; }
.err { color: var(--like); font-size: 13px; min-height: 18px; }

/* Auth */
#auth { display: flex; align-items: center; justify-content: center; padding: 24px; }
.auth-wrap { width: 100%; max-width: 340px; display: flex; flex-direction: column; gap: 16px; }
.brand { font-size: 30px; font-weight: 800; letter-spacing: -0.8px; }
.sub { color: var(--dim); font-size: 14px; margin-top: -10px; }
.seg-control {
  display: flex; border: 1px solid var(--border); border-radius: 8px; padding: 3px; gap: 2px;
}
.seg-btn {
  flex: 1; padding: 8px; background: none; color: var(--dim);
  font-size: 14px; font-weight: 500; border-radius: 6px;
}
.seg-btn.active { background: var(--surface-2); color: var(--text); }
#auth-form { display: flex; flex-direction: column; gap: 10px; }
#auth-form input {
  padding: 12px 14px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; color: var(--text); font-size: 15px; outline: none;
}
#auth-form input:focus { border-color: var(--text); }
.hint { color: var(--dimmer); font-size: 12px; text-align: center; }

/* Main layout */
#main { display: flex; flex-direction: column; }
#content { flex: 1; position: relative; overflow: hidden; }
.view { position: absolute; inset: 0; }
#feed-view { overflow: hidden; }
#profile-view { overflow-y: auto; padding-bottom: 24px; }

/* Bottom nav */
#bottom-nav {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  background: var(--bg); border-top: 1px solid var(--border);
  padding: 6px 0 calc(6px + env(safe-area-inset-bottom));
  align-items: center;
}
.nav-btn {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; padding: 4px; color: var(--dimmer); font-size: 11px; font-weight: 500;
}
.nav-btn.active { color: var(--text); }
.nav-btn svg { width: 24px; height: 24px; }
.nav-create .plus-wrap {
  width: 44px; height: 30px; background: var(--text); color: var(--bg);
  border-radius: 8px; display: grid; place-items: center;
}
.nav-create .plus-wrap svg { width: 20px; height: 20px; }

/* Feed */
#feed {
  height: 100%; overflow-y: scroll; scroll-snap-type: y mandatory; scrollbar-width: none;
}
#feed::-webkit-scrollbar { display: none; }
.feed-empty {
  height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; color: var(--dimmer); padding: 40px;
  text-align: center; font-size: 14px;
}
.slideshow {
  position: relative; height: 100%; scroll-snap-align: start;
  scroll-snap-stop: always; overflow: hidden; background: #000;
}
.slideshow .stage { position: absolute; inset: 0; }
.slideshow .slide { position: absolute; inset: 0; opacity: 0; transition: opacity 0.3s ease; }
.slideshow .slide.active { opacity: 1; }
.slideshow .slide img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  user-select: none; -webkit-user-drag: none; pointer-events: none;
}
.slideshow .slide .txt {
  position: absolute; transform: translate(-50%, -50%); text-align: center;
  white-space: pre-wrap; line-height: 1.1; font-weight: 800;
  text-shadow: 0 2px 12px rgba(0,0,0,0.5); max-width: 90%;
  pointer-events: none;
}
.progress {
  position: absolute; top: calc(10px + env(safe-area-inset-top));
  left: 10px; right: 10px; display: flex; gap: 3px; z-index: 5;
}
.progress-seg {
  flex: 1; height: 2px; background: rgba(255,255,255,0.25);
  border-radius: 1px; overflow: hidden;
}
.progress-fill { height: 100%; width: 0; background: #fff; }
.info {
  position: absolute; left: 16px; right: 90px;
  bottom: calc(24px + env(safe-area-inset-bottom));
  z-index: 6; text-shadow: 0 2px 8px rgba(0,0,0,0.7);
}
.info-user { font-weight: 600; font-size: 15px; margin-bottom: 2px; }
.info-title { font-size: 14px; opacity: 0.9; }
.actions {
  position: absolute; right: 10px; bottom: calc(24px + env(safe-area-inset-bottom));
  display: flex; flex-direction: column; gap: 16px; align-items: center; z-index: 6;
}
.like-btn {
  display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 4px;
}
.like-btn svg {
  width: 32px; height: 32px; color: #fff;
  filter: drop-shadow(0 2px 6px rgba(0,0,0,0.6));
  transition: transform 0.15s ease;
}
.like-btn:active svg { transform: scale(1.15); }
.like-btn.liked svg { color: var(--like); }
.like-count { font-size: 12px; font-weight: 600; }

/* Profile */
.profile { padding: 20px 16px; }
.profile-top { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }
.avatar {
  width: 56px; height: 56px; border-radius: 50%; background: var(--surface-2);
  display: grid; place-items: center; font-size: 22px; font-weight: 700;
  text-transform: uppercase; flex-shrink: 0;
}
.profile-info { flex: 1; min-width: 0; }
.profile-name {
  font-size: 17px; font-weight: 600; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.profile-meta { color: var(--dim); font-size: 13px; margin-top: 2px; }
.profile-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; }
.profile-grid .item {
  aspect-ratio: 9 / 16; overflow: hidden; background: var(--surface); cursor: pointer;
}
.profile-grid .item img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.profile-grid .empty {
  grid-column: 1 / -1; padding: 40px 16px; text-align: center;
  color: var(--dimmer); font-size: 14px;
}
.profile-actions { margin-top: 24px; display: flex; justify-content: center; }

/* Create */
#create-screen { display: flex; flex-direction: column; }
.create-bar {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  padding-top: calc(10px + env(safe-area-inset-top));
  border-bottom: 1px solid var(--border); background: var(--bg);
}
.create-bar input {
  flex: 1; padding: 8px 12px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; color: var(--text);
  font-size: 14px; outline: none; min-width: 0;
}
.create-bar input:focus { border-color: var(--text); }
.create-body {
  flex: 1; overflow-y: auto; padding: 12px 12px calc(12px + env(safe-area-inset-bottom));
}
.create-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }
.create-empty {
  grid-column: 1 / -1; padding: 40px 20px; text-align: center;
  color: var(--dimmer); font-size: 14px;
}
.create-item {
  aspect-ratio: 9 / 16; position: relative; border-radius: 8px;
  overflow: hidden; background: var(--surface); cursor: pointer;
}
.create-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
.create-item .del {
  position: absolute; top: 6px; right: 6px; width: 26px; height: 26px;
  border-radius: 50%; background: rgba(0,0,0,0.75); color: #fff;
  display: grid; place-items: center;
}
.create-item .del svg { width: 14px; height: 14px; }
.create-item .badge {
  position: absolute; bottom: 6px; left: 6px; background: rgba(0,0,0,0.75);
  padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500;
}
.add-photo {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 18px; border: 1px dashed var(--border); border-radius: 8px;
  color: var(--dim); font-size: 14px; cursor: pointer; font-weight: 500;
}
.add-photo:active { background: var(--surface); }
.add-photo input { display: none; }
.add-photo svg { width: 18px; height: 18px; }

/* Editor */
#editor-screen { display: flex; flex-direction: column; background: #000; }
.editor-bar {
  display: flex; align-items: center; gap: 4px; padding: 6px 8px;
  padding-top: calc(6px + env(safe-area-inset-top));
  background: #000; border-bottom: 1px solid rgba(255,255,255,0.06);
}
.editor-bar-title { flex: 1; text-align: center; font-size: 14px; color: var(--dim); }
.editor-stage {
  flex: 1; position: relative; overflow: hidden; touch-action: none;
  background: #000;
}
.editor-stage img {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover; pointer-events: none; user-select: none;
  -webkit-user-drag: none;
}
.etext {
  position: absolute; transform: translate(-50%, -50%); cursor: grab;
  user-select: none; touch-action: none; white-space: pre-wrap;
  text-align: center; line-height: 1.1; font-weight: 800;
  padding: 4px; border-radius: 4px; max-width: 90%;
  text-shadow: 0 2px 12px rgba(0,0,0,0.5);
}
.etext.selected { outline: 1px dashed rgba(255,255,255,0.7); outline-offset: 2px; }
.text-controls {
  background: var(--surface); border-top: 1px solid var(--border);
  padding: 12px 16px; display: flex; flex-direction: column; gap: 10px;
}
#text-input {
  padding: 8px 12px; background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 14px; outline: none;
}
#text-input:focus { border-color: var(--text); }
.text-row { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--dim); }
.text-row label { min-width: 56px; }
.text-row input[type=range] { flex: 1; accent-color: var(--text); }
.text-colors { display: flex; gap: 6px; flex-wrap: wrap; }
.color-swatch {
  width: 26px; height: 26px; border-radius: 50%;
  border: 2px solid transparent; cursor: pointer;
}
.color-swatch.active { border-color: var(--text); }
.editor-tools {
  display: flex; gap: 8px; padding: 12px;
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
  background: #000; border-top: 1px solid rgba(255,255,255,0.06);
}
.tool-btn {
  padding: 8px 16px; background: var(--surface-2); border-radius: 8px;
  color: var(--text); font-size: 14px; font-weight: 500;
  display: inline-flex; align-items: center; gap: 6px;
}
.tool-btn svg { width: 16px; height: 16px; }

/* Viewer */
#viewer-screen { display: flex; flex-direction: column; background: #000; }
.viewer-stage { flex: 1; position: relative; overflow: hidden; background: #000; }
.viewer-stage .slide { position: absolute; inset: 0; opacity: 0; transition: opacity 0.3s; }
.viewer-stage .slide.active { opacity: 1; }
.viewer-stage .slide img { width: 100%; height: 100%; object-fit: cover; }
.viewer-stage .txt {
  position: absolute; transform: translate(-50%, -50%); text-align: center;
  white-space: pre-wrap; line-height: 1.1; font-weight: 800;
  text-shadow: 0 2px 12px rgba(0,0,0,0.5); max-width: 90%;
}

/* Modal */
.modal {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7);
  display: flex; align-items: center; justify-content: center; padding: 16px; z-index: 200;
}
.modal-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; width: 100%; max-width: 380px;
  display: flex; flex-direction: column; gap: 12px;
}
.modal-card h3 { font-size: 17px; font-weight: 600; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 13px; color: var(--dim); }
.field input {
  padding: 10px 12px; background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 14px; outline: none;
}
.field input:focus { border-color: var(--text); }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
</style>
</head>
<body>

<!-- AUTH -->
<div id="auth" class="screen">
  <div class="auth-wrap">
    <h1 class="brand">SlideTok</h1>
    <p class="sub">Только слайдшоу.</p>
    <div class="seg-control">
      <button class="seg-btn active" data-mode="login">Вход</button>
      <button class="seg-btn" data-mode="register">Регистрация</button>
    </div>
    <form id="auth-form">
      <input id="auth-user" placeholder="Имя" required minlength="3" maxlength="32" autocomplete="username">
      <input id="auth-pass" type="password" placeholder="Пароль" required minlength="4" autocomplete="current-password">
      <button class="btn-primary" type="submit" id="auth-submit">Войти</button>
    </form>
    <div id="auth-err" class="err"></div>
    <p class="hint">Демо-аккаунт: demo / demo</p>
  </div>
</div>

<!-- MAIN -->
<div id="main" class="screen hidden">
  <main id="content">
    <div id="feed-view" class="view">
      <div id="feed"></div>
    </div>
    <div id="profile-view" class="view hidden">
      <div class="profile">
        <div class="profile-top">
          <div class="avatar" id="avatar">?</div>
          <div class="profile-info">
            <div class="profile-name" id="profile-name">@</div>
            <div class="profile-meta" id="profile-meta">0 · 0</div>
          </div>
          <button class="btn-ghost" id="edit-profile-btn">Изменить</button>
        </div>
        <div class="profile-grid" id="profile-grid"></div>
        <div class="profile-actions">
          <button class="btn-ghost" id="logout-btn">Выйти</button>
        </div>
      </div>
    </div>
  </main>

  <nav id="bottom-nav">
    <button class="nav-btn active" data-nav="feed">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 10.5L12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>
      </svg>
      <span>Лента</span>
    </button>
    <button class="nav-btn nav-create" data-nav="create">
      <span class="plus-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </span>
    </button>
    <button class="nav-btn" data-nav="profile">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="8" r="4"/><path d="M4 21v-2a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v2"/>
      </svg>
      <span>Профиль</span>
    </button>
  </nav>
</div>

<!-- CREATE -->
<div id="create-screen" class="screen hidden">
  <div class="create-bar">
    <button class="icon-btn" id="create-close" aria-label="Отмена">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
    </button>
    <input id="create-title" type="text" placeholder="Название" maxlength="80">
    <button class="btn-primary btn-sm" id="create-publish" disabled>Опубликовать</button>
  </div>
  <div class="create-body">
    <div class="create-grid" id="create-grid"></div>
    <label class="add-photo">
      <input id="add-photo-input" type="file" accept="image/*" multiple>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
      <span>Добавить фото</span>
    </label>
  </div>
</div>

<!-- EDITOR -->
<div id="editor-screen" class="screen hidden">
  <div class="editor-bar">
    <button class="icon-btn" id="editor-back" aria-label="Назад">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>
    <div class="editor-bar-title">Текст на фото</div>
    <button class="icon-btn" id="editor-delete" aria-label="Удалить слайд">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
      </svg>
    </button>
  </div>
  <div id="editor-stage" class="editor-stage"></div>
  <div id="text-controls" class="text-controls hidden">
    <input id="text-input" type="text" placeholder="Текст" maxlength="300">
    <div class="text-row">
      <label>Размер</label>
      <input type="range" id="text-size" min="3" max="16" step="0.5" value="6">
    </div>
    <div class="text-colors" id="text-colors"></div>
    <button class="btn-danger btn-sm" id="text-delete" style="align-self:flex-start">Удалить текст</button>
  </div>
  <div class="editor-tools">
    <button class="tool-btn" id="tool-add-text">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7V4h16v3M9 20h6M12 4v16"/></svg>
      Текст
    </button>
  </div>
</div>

<!-- VIEWER -->
<div id="viewer-screen" class="screen hidden">
  <div class="editor-bar">
    <button class="icon-btn" id="viewer-close" aria-label="Закрыть">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
    </button>
    <div class="editor-bar-title" id="viewer-title"></div>
    <button class="icon-btn" id="viewer-delete" aria-label="Удалить">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
      </svg>
    </button>
  </div>
  <div id="viewer-stage" class="viewer-stage"></div>
</div>

<!-- EDIT PROFILE MODAL -->
<div id="edit-profile-modal" class="modal hidden">
  <div class="modal-card">
    <h3>Редактировать профиль</h3>
    <div class="field">
      <label>Имя пользователя</label>
      <input id="edit-username" type="text" maxlength="32">
    </div>
    <div class="field">
      <label>Текущий пароль</label>
      <input id="edit-current-pass" type="password" placeholder="Только если меняете пароль">
    </div>
    <div class="field">
      <label>Новый пароль</label>
      <input id="edit-new-pass" type="password" placeholder="Оставьте пустым, чтобы не менять">
    </div>
    <div id="edit-err" class="err"></div>
    <div class="modal-actions">
      <button class="btn-ghost" id="edit-cancel">Отмена</button>
      <button class="btn-primary" id="edit-save">Сохранить</button>
    </div>
  </div>
</div>

<script>
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const ICONS = {
  heart: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21.2l7.8-7.8 1.1-1.1a5.5 5.5 0 0 0 0-7.8z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
};

const COLORS = ["#ffffff", "#000000", "#ff3b5c", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#007aff", "#af52de", "#ff6b9d"];

const state = {
  user: null,
  view: "feed",
  slideshows: [],
  players: [],
  observer: null,
  createDraft: [],
  editingIdx: -1,
  selectedTextId: null,
  viewingShow: null,
  viewerTimer: null,
};

// ---------- UTILS ----------
function el(tag, props = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "style") Object.assign(e.style, v);
    else if (k === "html") e.innerHTML = v;
    else if (k === "text") e.textContent = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2).toLowerCase(), v);
    else e.setAttribute(k, v);
  }
  for (const c of (Array.isArray(children) ? children : [children])) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", credentials: "same-origin" };
  if (opts.body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = "Ошибка";
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function readImage(file, maxSize = 1200) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("Не удалось прочитать файл"));
    r.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Не удалось открыть изображение"));
      img.onload = () => {
        let { width, height } = img;
        if (width > maxSize || height > maxSize) {
          const s = maxSize / Math.max(width, height);
          width = Math.round(width * s);
          height = Math.round(height * s);
        }
        const c = document.createElement("canvas");
        c.width = width; c.height = height;
        c.getContext("2d").drawImage(img, 0, 0, width, height);
        resolve(c.toDataURL("image/jpeg", 0.82));
      };
      img.src = r.result;
    };
    r.readAsDataURL(file);
  });
}

function renderText(t) {
  return el("div", {
    class: "txt",
    style: {
      left: t.x + "%", top: t.y + "%",
      color: t.color, fontSize: t.size + "vw",
    },
  }, t.text || "\u00A0");
}

// ---------- PLAYER ----------
class Player {
  constructor(root, duration = 3500) {
    this.root = root;
    this.slides = Array.from(root.querySelectorAll(".slide"));
    this.fills = Array.from(root.querySelectorAll(".progress-fill"));
    this.duration = duration;
    this.idx = 0;
    this.timer = null;
  }
  reset() {
    clearTimeout(this.timer);
    this.idx = 0;
    this.render();
  }
  play() {
    this.reset();
    this.schedule();
  }
  pause() {
    clearTimeout(this.timer);
    this.fills.forEach(f => {
      const w = f.getBoundingClientRect().width;
      const p = f.parentElement.getBoundingClientRect().width;
      f.style.transition = "none";
      f.style.width = p ? (w / p * 100) + "%" : "0";
    });
  }
  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.idx = (this.idx + 1) % this.slides.length;
      this.render();
      this.schedule();
    }, this.duration);
  }
  render() {
    this.slides.forEach((s, j) => s.classList.toggle("active", j === this.idx));
    this.fills.forEach((f, j) => {
      f.style.transition = "none";
      f.style.width = j < this.idx ? "100%" : "0";
    });
    const cur = this.fills[this.idx];
    if (cur) {
      void cur.offsetWidth;
      cur.style.transition = `width ${this.duration}ms linear`;
      cur.style.width = "100%";
    }
  }
}

// ---------- FEED ----------
function buildSlideshow(show) {
  const root = el("div", { class: "slideshow" });
  const stage = el("div", { class: "stage" });
  show.slides.forEach((slide, i) => {
    const s = el("div", { class: "slide" + (i === 0 ? " active" : "") });
    s.appendChild(el("img", { src: slide.image, alt: "" }));
    (slide.texts || []).forEach(t => s.appendChild(renderText(t)));
    stage.appendChild(s);
  });
  root.appendChild(stage);

  const prog = el("div", { class: "progress" });
  show.slides.forEach(() => {
    const seg = el("div", { class: "progress-seg" });
    seg.appendChild(el("div", { class: "progress-fill" }));
    prog.appendChild(seg);
  });
  root.appendChild(prog);

  const info = el("div", { class: "info" });
  info.appendChild(el("div", { class: "info-user", text: "@" + show.username }));
  info.appendChild(el("div", { class: "info-title", text: show.title }));
  root.appendChild(info);

  const actions = el("div", { class: "actions" });
  const likeBtn = el("button", { class: "like-btn" + (show.liked ? " liked" : "") });
  likeBtn.innerHTML = ICONS.heart + `<span class="like-count">${show.likes}</span>`;
  likeBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const r = await api("/api/slideshows/" + show.id + "/like", { method: "POST" });
      likeBtn.classList.toggle("liked", r.liked);
      likeBtn.querySelector(".like-count").textContent = r.likes;
    } catch (err) {
      if (err.message === "Требуется вход") return showAuth();
      alert(err.message);
    }
  });
  actions.appendChild(likeBtn);
  root.appendChild(actions);

  const player = new Player(root);
  root._player = player;
  state.players.push(player);
  return root;
}

function renderFeed() {
  state.players = [];
  if (state.observer) { state.observer.disconnect(); state.observer = null; }
  const feed = $("#feed");
  feed.innerHTML = "";
  if (!state.slideshows.length) {
    feed.innerHTML = '<div class="feed-empty"><div>Пока пусто</div><div style="font-size:13px;opacity:0.7">Создайте первое слайдшоу кнопкой +</div></div>';
    return;
  }
  state.slideshows.forEach(show => feed.appendChild(buildSlideshow(show)));
  setupFeedObserver();
}

function setupFeedObserver() {
  if (state.observer) state.observer.disconnect();
  state.observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      const p = entry.target._player;
      if (!p) return;
      if (entry.isIntersecting && entry.intersectionRatio >= 0.5) p.play();
      else p.pause();
    });
  }, { root: $("#feed"), threshold: [0.5] });
  state.players.forEach(p => state.observer.observe(p.root));
}

// ---------- AUTH ----------
let authMode = "login";

function showAuth() {
  $("#auth").classList.remove("hidden");
  $("#main").classList.add("hidden");
  state.players.forEach(p => p.pause());
  state.players = [];
}

async function enterApp() {
  $("#auth").classList.add("hidden");
  $("#main").classList.remove("hidden");
  state.slideshows = await api("/api/slideshows");
  renderFeed();
  switchView("feed");
}

$$(".seg-btn").forEach(b => b.addEventListener("click", () => {
  authMode = b.dataset.mode;
  $$(".seg-btn").forEach(x => x.classList.toggle("active", x === b));
  $("#auth-submit").textContent = authMode === "login" ? "Войти" : "Создать";
  $("#auth-err").textContent = "";
}));

$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("#auth-user").value.trim();
  const password = $("#auth-pass").value;
  $("#auth-err").textContent = "";
  $("#auth-submit").disabled = true;
  try {
    await api(authMode === "login" ? "/api/login" : "/api/register", {
      method: "POST", body: { username, password },
    });
    state.user = await api("/api/me");
    await enterApp();
  } catch (err) {
    $("#auth-err").textContent = err.message;
  } finally {
    $("#auth-submit").disabled = false;
  }
});

$("#logout-btn").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch {}
  state.user = null;
  showAuth();
});

// ---------- NAVIGATION ----------
function switchView(view) {
  state.view = view;
  if (view !== "feed") state.players.forEach(p => p.pause());
  $$(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.nav === view));
  $("#feed-view").classList.toggle("hidden", view !== "feed");
  $("#profile-view").classList.toggle("hidden", view !== "profile");
  if (view === "profile") loadProfile();
}

$$(".nav-btn").forEach(b => b.addEventListener("click", () => {
  const nav = b.dataset.nav;
  if (nav === "create") openCreate();
  else switchView(nav);
}));

// ---------- PROFILE ----------
async function loadProfile() {
  try {
    const data = await api("/api/me");
    state.user = data;
    $("#profile-name").textContent = "@" + data.username;
    $("#profile-meta").textContent = `${data.shows_count} слайдшоу · ${data.likes_count} лайков`;
    $("#avatar").textContent = data.username.charAt(0);
    const shows = await api("/api/me/slideshows");
    const grid = $("#profile-grid");
    grid.innerHTML = "";
    if (!shows.length) {
      grid.innerHTML = '<div class="empty">Пока нет слайдшоу</div>';
      return;
    }
    shows.forEach(s => {
      const item = el("div", { class: "item", onclick: () => openViewer(s) });
      item.appendChild(el("img", { src: s.slides[0].image, alt: "" }));
      grid.appendChild(item);
    });
  } catch (e) {
    console.error(e);
  }
}

$("#edit-profile-btn").addEventListener("click", () => {
  $("#edit-username").value = state.user.username;
  $("#edit-current-pass").value = "";
  $("#edit-new-pass").value = "";
  $("#edit-err").textContent = "";
  $("#edit-profile-modal").classList.remove("hidden");
});

$("#edit-cancel").addEventListener("click", () => {
  $("#edit-profile-modal").classList.add("hidden");
});

$("#edit-save").addEventListener("click", async () => {
  const body = {};
  const newName = $("#edit-username").value.trim();
  if (newName && newName !== state.user.username) body.username = newName;
  const newPass = $("#edit-new-pass").value;
  if (newPass) {
    body.new_password = newPass;
    body.current_password = $("#edit-current-pass").value;
  }
  if (!Object.keys(body).length) {
    $("#edit-profile-modal").classList.add("hidden");
    return;
  }
  try {
    await api("/api/me", { method: "PATCH", body });
    $("#edit-profile-modal").classList.add("hidden");
    state.slideshows = await api("/api/slideshows");
    renderFeed();
    await loadProfile();
  } catch (e) {
    $("#edit-err").textContent = e.message;
  }
});

// ---------- VIEWER ----------
function openViewer(show) {
  state.viewingShow = show;
  $("#viewer-title").textContent = show.title;
  const stage = $("#viewer-stage");
  stage.innerHTML = "";
  show.slides.forEach((slide, i) => {
    const s = el("div", { class: "slide" + (i === 0 ? " active" : "") });
    s.appendChild(el("img", { src: slide.image, alt: "" }));
    (slide.texts || []).forEach(t => s.appendChild(renderText(t)));
    stage.appendChild(s);
  });
  if (state.viewerTimer) clearInterval(state.viewerTimer);
  if (show.slides.length > 1) {
    let idx = 0;
    state.viewerTimer = setInterval(() => {
      idx = (idx + 1) % show.slides.length;
      $$(".slide", stage).forEach((s, j) => s.classList.toggle("active", j === idx));
    }, 3500);
  }
  $("#viewer-screen").classList.remove("hidden");
}

function closeViewer() {
  if (state.viewerTimer) { clearInterval(state.viewerTimer); state.viewerTimer = null; }
  state.viewingShow = null;
  $("#viewer-screen").classList.add("hidden");
}

$("#viewer-close").addEventListener("click", closeViewer);

$("#viewer-delete").addEventListener("click", async () => {
  if (!state.viewingShow) return;
  if (!confirm("Удалить это слайдшоу?")) return;
  try {
    await api("/api/slideshows/" + state.viewingShow.id, { method: "DELETE" });
    closeViewer();
    state.slideshows = await api("/api/slideshows");
    renderFeed();
    await loadProfile();
  } catch (e) {
    alert(e.message);
  }
});

// ---------- CREATE ----------
function openCreate() {
  state.createDraft = [];
  $("#create-title").value = "";
  $("#create-screen").classList.remove("hidden");
  renderCreateGrid();
}

function closeCreate() {
  $("#create-screen").classList.add("hidden");
  state.createDraft = [];
}

function renderCreateGrid() {
  const grid = $("#create-grid");
  grid.innerHTML = "";
  if (!state.createDraft.length) {
    grid.innerHTML = '<div class="create-empty">Добавьте фото, чтобы начать</div>';
  } else {
    state.createDraft.forEach((slide, i) => {
      const item = el("div", { class: "create-item", onclick: () => openEditor(i) });
      item.appendChild(el("img", { src: slide.image, alt: "" }));
      if (slide.texts && slide.texts.length) {
        item.appendChild(el("div", { class: "badge", text: slide.texts.length + " текст" }));
      }
      const del = el("button", { class: "del", "aria-label": "Удалить" });
      del.innerHTML = ICONS.x;
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        state.createDraft.splice(i, 1);
        renderCreateGrid();
      });
      item.appendChild(del);
      grid.appendChild(item);
    });
  }
  $("#create-publish").disabled = state.createDraft.length === 0;
}

$("#create-close").addEventListener("click", () => {
  if (state.createDraft.length && !confirm("Отменить создание?")) return;
  closeCreate();
});

$("#add-photo-input").addEventListener("change", async (e) => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  for (const f of files) {
    try {
      const dataUrl = await readImage(f);
      state.createDraft.push({ image: dataUrl, texts: [] });
    } catch (err) {
      alert(err.message);
    }
  }
  renderCreateGrid();
});

$("#create-publish").addEventListener("click", async () => {
  if (!state.createDraft.length) return;
  const btn = $("#create-publish");
  btn.disabled = true;
  try {
    await api("/api/slideshows", {
      method: "POST",
      body: { title: $("#create-title").value, slides: state.createDraft },
    });
    closeCreate();
    state.slideshows = await api("/api/slideshows");
    renderFeed();
    switchView("feed");
    $("#feed").scrollTo({ top: 0 });
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
  }
});

// ---------- EDITOR ----------
function getEditingSlide() {
  return state.createDraft[state.editingIdx];
}

function getSelectedText() {
  const s = getEditingSlide();
  if (!s) return null;
  return s.texts.find(t => t.id === state.selectedTextId) || null;
}

function findTextEl(id) {
  return $(`.etext[data-id="${id}"]`, $("#editor-stage"));
}

function openEditor(idx) {
  state.editingIdx = idx;
  state.selectedTextId = null;
  $("#editor-screen").classList.remove("hidden");
  $("#text-controls").classList.add("hidden");
  renderEditor();
}

function closeEditor() {
  state.editingIdx = -1;
  state.selectedTextId = null;
  $("#editor-screen").classList.add("hidden");
  renderCreateGrid();
}

function renderEditor() {
  const slide = getEditingSlide();
  if (!slide) { closeEditor(); return; }
  const stage = $("#editor-stage");
  stage.innerHTML = "";
  stage.appendChild(el("img", { src: slide.image, alt: "", draggable: "false" }));
  slide.texts.forEach(t => {
    const te = el("div", {
      class: "etext" + (t.id === state.selectedTextId ? " selected" : ""),
      dataset: { id: t.id },
      style: {
        left: t.x + "%", top: t.y + "%",
        color: t.color, fontSize: t.size + "vw",
      },
    }, t.text || "\u00A0");
    attachDrag(te, t);
    stage.appendChild(te);
  });
  updateTextControls();
}

function updateTextControls() {
  const text = getSelectedText();
  if (!text) {
    $("#text-controls").classList.add("hidden");
    return;
  }
  $("#text-controls").classList.remove("hidden");
  $("#text-input").value = text.text;
  $("#text-size").value = text.size;
  $$(".color-swatch").forEach(s => s.classList.toggle("active", s.dataset.color === text.color));
}

function attachDrag(te, textObj) {
  te.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();

    // Select this text
    if (state.selectedTextId !== textObj.id) {
      state.selectedTextId = textObj.id;
      $$(".etext", $("#editor-stage")).forEach(x => x.classList.remove("selected"));
      te.classList.add("selected");
      updateTextControls();
    }

    te.setPointerCapture(e.pointerId);
    const stage = $("#editor-stage");

    const onMove = (ev) => {
      const rect = stage.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 100;
      const y = ((ev.clientY - rect.top) / rect.height) * 100;
      textObj.x = Math.max(2, Math.min(98, x));
      textObj.y = Math.max(2, Math.min(98, y));
      te.style.left = textObj.x + "%";
      te.style.top = textObj.y + "%";
    };
    const onUp = () => {
      te.removeEventListener("pointermove", onMove);
      te.removeEventListener("pointerup", onUp);
      te.removeEventListener("pointercancel", onUp);
    };
    te.addEventListener("pointermove", onMove);
    te.addEventListener("pointerup", onUp);
    te.addEventListener("pointercancel", onUp);
  });
}

$("#editor-back").addEventListener("click", closeEditor);

$("#editor-delete").addEventListener("click", () => {
  const s = getEditingSlide();
  if (!s) return;
  if (!confirm("Удалить это фото?")) return;
  state.createDraft.splice(state.editingIdx, 1);
  closeEditor();
});

$("#tool-add-text").addEventListener("click", () => {
  const slide = getEditingSlide();
  if (!slide) return;
  const t = {
    id: "t_" + Math.random().toString(36).slice(2, 10),
    text: "Текст",
    x: 50, y: 50,
    color: "#ffffff", size: 6,
  };
  slide.texts.push(t);
  state.selectedTextId = t.id;
  renderEditor();
  setTimeout(() => {
    $("#text-input").focus();
    $("#text-input").select();
  }, 50);
});

$("#text-input").addEventListener("input", (e) => {
  const t = getSelectedText();
  if (!t) return;
  t.text = e.target.value;
  const te = findTextEl(t.id);
  if (te) te.textContent = t.text || "\u00A0";
});

$("#text-size").addEventListener("input", (e) => {
  const t = getSelectedText();
  if (!t) return;
  t.size = parseFloat(e.target.value);
  const te = findTextEl(t.id);
  if (te) te.style.fontSize = t.size + "vw";
});

$("#text-delete").addEventListener("click", () => {
  const s = getEditingSlide();
  if (!s) return;
  s.texts = s.texts.filter(t => t.id !== state.selectedTextId);
  state.selectedTextId = null;
  renderEditor();
});

// Build color swatches
const colorWrap = $("#text-colors");
COLORS.forEach(c => {
  const sw = el("button", {
    class: "color-swatch",
    dataset: { color: c },
    style: { background: c },
    "aria-label": c,
  });
  sw.addEventListener("click", () => {
    const t = getSelectedText();
    if (!t) return;
    t.color = c;
    const te = findTextEl(t.id);
    if (te) te.style.color = c;
    $$(".color-swatch").forEach(x => x.classList.toggle("active", x.dataset.color === c));
  });
  colorWrap.appendChild(sw);
});

// ---------- INIT ----------
(async function init() {
  try {
    state.user = await api("/api/me");
    await enterApp();
  } catch {
    showAuth();
  }
})();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
