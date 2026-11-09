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

USERS_BY_NAME: Dict[str, dict] = {}
USERS_BY_ID: Dict[str, dict] = {}
SESSIONS: Dict[str, str] = {}
SLIDESHOWS: List[dict] = []
LIKES: Dict[str, set] = {}


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
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


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
    if len(slides) > 15:
        raise HTTPException(400, "Максимум 15 фото")
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            raise HTTPException(400, f"Слайд {i + 1}: некорректный формат")
        img = s.get("image")
        if not isinstance(img, str) or not img.startswith("data:image/"):
            raise HTTPException(400, f"Слайд {i + 1}: нет изображения")
        if len(img) > 4_000_000:
            raise HTTPException(400, f"Слайд {i + 1}: слишком большое изображение")
        texts = s.get("texts", [])
        if not isinstance(texts, list):
            raise HTTPException(400, f"Слайд {i + 1}: некорректные тексты")
        if len(texts) > 20:
            raise HTTPException(400, f"Слайд {i + 1}: слишком много текстов")
        for t in texts:
            if not isinstance(t, dict):
                raise HTTPException(400, f"Слайд {i + 1}: некорректный текст")
            if not isinstance(t.get("text"), str) or len(t["text"]) > 300:
                raise HTTPException(400, f"Слайд {i + 1}: длина текста")
            if not isinstance(t.get("x"), (int, float)) or not 0 <= t["x"] <= 100:
                raise HTTPException(400, f"Слайд {i + 1}: X")
            if not isinstance(t.get("y"), (int, float)) or not 0 <= t["y"] <= 100:
                raise HTTPException(400, f"Слайд {i + 1}: Y")
            if not isinstance(t.get("size"), (int, float)) or not 1 <= t["size"] <= 30:
                raise HTTPException(400, f"Слайд {i + 1}: размер")
            if not isinstance(t.get("color"), str) or len(t["color"]) > 24:
                raise HTTPException(400, f"Слайд {i + 1}: цвет")


def svg_data_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def demo_image(c1: str, c2: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920" preserveAspectRatio="xMidYMid slice">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        '</linearGradient></defs>'
        '<rect width="1080" height="1920" fill="url(#g)"/>'
        '</svg>'
    )
    return svg_data_url(svg)


def seed_demo() -> None:
    demo = make_user("demo", "demo")

    def add(title, slides):
        sid = str(uuid.uuid4())
        SLIDESHOWS.append({
            "id": sid, "user_id": demo["id"], "title": title,
            "slides": slides, "created": datetime.utcnow().isoformat(),
        })
        LIKES[sid] = set()

    add("Привет, мир", [
        {"image": demo_image("#e74c3c", "#c0392b"), "texts": [
            {"id": "t1", "text": "Привет", "x": 50, "y": 45, "color": "#ffffff", "size": 9},
            {"id": "t2", "text": "это SlideTok", "x": 50, "y": 58, "color": "#ffffff", "size": 5},
        ]},
        {"image": demo_image("#3498db", "#2c3e50"), "texts": []},
    ])
    add("Закат", [
        {"image": demo_image("#ff7e5f", "#feb47b"), "texts": [
            {"id": "t3", "text": "Закат", "x": 50, "y": 50, "color": "#ffffff", "size": 10},
        ]},
        {"image": demo_image("#fbc2eb", "#a6c1ee"), "texts": []},
        {"image": demo_image("#a1c4fd", "#c2e9fb"), "texts": []},
    ])
    add("Минимализм", [
        {"image": demo_image("#232526", "#414345"), "texts": [
            {"id": "t4", "text": "меньше", "x": 50, "y": 48, "color": "#ffffff", "size": 8},
            {"id": "t5", "text": "значит больше", "x": 50, "y": 58, "color": "#a3a3a3", "size": 4},
        ]},
    ])


seed_demo()


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


def _check_username(name: str) -> str:
    name = (name or "").strip()
    if len(name) < 3 or len(name) > 32:
        raise HTTPException(400, "Имя от 3 до 32 символов")
    if not all(c.isalnum() or c in "_." for c in name):
        raise HTTPException(400, "Только буквы, цифры, _ и .")
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


@app.get("/api/me")
async def me(request: Request):
    user = require_user(request)
    mine = [s for s in SLIDESHOWS if s["user_id"] == user["id"]]
    total_likes = sum(len(LIKES.get(s["id"], set())) for s in mine)
    return {
        "id": user["id"], "username": user["username"],
        "shows_count": len(mine), "likes_count": total_likes,
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
            raise HTTPException(400, "Пароль минимум 4 символа")
        user["salt"] = secrets.token_hex(16)
        user["password_hash"] = hash_password(data.new_password, user["salt"])
    return {"id": user["id"], "username": user["username"]}


@app.get("/api/me/slideshows")
async def my_shows(request: Request):
    user = require_user(request)
    return [serialize_show(s, user["id"]) for s in SLIDESHOWS if s["user_id"] == user["id"]]


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


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0a">
<title>SlideTok</title>
<style>
:root{
  --bg:#0a0a0a; --surface:#171717; --surface-2:#262626;
  --border:#2a2a2a; --text:#f5f5f5; --dim:#a3a3a3; --dimmer:#666;
  --like:#ff3b5c; --sidebar:220px;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{
  height:100%; height:100dvh; overflow:hidden;
  background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif;
  font-size:14px; -webkit-font-smoothing:antialiased;
}
button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit}
input,textarea{font-family:inherit}
.hidden{display:none!important}
.screen{position:fixed;inset:0;background:var(--bg);display:flex;flex-direction:column}

/* Auth */
#auth{align-items:center;justify-content:center;padding:24px}
.auth-wrap{width:100%;max-width:340px;display:flex;flex-direction:column;gap:18px}
.brand{font-size:28px;font-weight:800;letter-spacing:-0.5px}
.sub{color:var(--dim);font-size:14px;margin-top:-12px}
.seg{display:flex;background:var(--surface);border-radius:8px;padding:3px;gap:2px}
.seg button{flex:1;padding:8px;color:var(--dim);font-size:14px;font-weight:500;border-radius:6px}
.seg button.active{background:var(--surface-2);color:var(--text)}
#auth-form{display:flex;flex-direction:column;gap:10px}
#auth-form input{
  padding:12px 14px;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;color:var(--text);font-size:15px;outline:none;
}
#auth-form input:focus{border-color:var(--text)}
.btn{
  padding:12px 16px;background:var(--text);color:var(--bg);border-radius:8px;
  font-size:15px;font-weight:600;
}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-sm{padding:8px 14px;font-size:14px;border-radius:6px}
.btn-ghost{
  padding:8px 14px;background:transparent;border:1px solid var(--border);
  color:var(--text);border-radius:6px;font-size:14px;font-weight:500;
}
.btn-danger{
  padding:8px 14px;background:transparent;border:1px solid #4a1a20;
  color:var(--like);border-radius:6px;font-size:14px;font-weight:500;
}
.icon-btn{width:38px;height:38px;display:grid;place-items:center;border-radius:8px;flex-shrink:0}
.icon-btn:hover{background:var(--surface)}
.icon-btn svg{width:22px;height:22px}
.err{color:var(--like);font-size:13px;min-height:18px}
.hint{color:var(--dimmer);font-size:12px;text-align:center}

/* App */
#app{display:flex;flex-direction:column;height:100vh;height:100dvh}
#sidebar{display:none;flex-direction:column;width:var(--sidebar);padding:20px 12px;border-right:1px solid var(--border);background:#000;flex-shrink:0}
.sidebar-logo{font-size:22px;font-weight:800;letter-spacing:-0.5px;padding:0 8px 24px}
.sidebar-nav{display:flex;flex-direction:column;gap:2px;flex:1}
.sidebar-btn{display:flex;align-items:center;gap:12px;padding:12px;border-radius:8px;font-size:15px;font-weight:500;text-align:left}
.sidebar-btn:hover{background:var(--surface)}
.sidebar-btn.active{background:var(--surface-2)}
.sidebar-btn svg{width:22px;height:22px;flex-shrink:0}
.sidebar-user{display:flex;align-items:center;gap:10px;padding:12px;border-radius:8px;cursor:pointer}
.sidebar-user:hover{background:var(--surface)}
.sidebar-avatar{width:32px;height:32px;border-radius:50%;background:var(--surface-2);display:grid;place-items:center;font-size:14px;font-weight:600;text-transform:uppercase;flex-shrink:0}
.sidebar-username{font-size:14px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

#main-area{flex:1;position:relative;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.view{position:absolute;inset:0}
#feed-view{overflow:hidden}
#profile-view{overflow-y:auto}

/* Feed */
#feed{width:100%;height:100%;overflow-y:scroll;scroll-snap-type:y mandatory;scrollbar-width:none;-webkit-overflow-scrolling:touch}
#feed::-webkit-scrollbar{display:none}
.feed-item{
  height:100%;scroll-snap-align:start;scroll-snap-stop:always;
  display:grid;place-items:center;padding:8px;background:#000;
  container-type:size;
}
.feed-empty{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--dimmer);padding:40px;text-align:center}

.stage-box{
  position:relative;overflow:hidden;border-radius:12px;background:#000;
  width:min(100cqw,100cqh * 9 / 16);
  aspect-ratio:9/16;
  container-type:inline-size;
  flex-shrink:0;
}
.slides{position:absolute;inset:0}
.slide{position:absolute;inset:0;opacity:0;transition:opacity .3s ease}
.slide.active{opacity:1}
.slide img{width:100%;height:100%;object-fit:cover;display:block;user-select:none;-webkit-user-drag:none;pointer-events:none}
.txt{
  position:absolute;transform:translate(-50%,-50%);
  text-align:center;white-space:pre-wrap;line-height:1.1;
  font-weight:800;max-width:90%;word-wrap:break-word;overflow-wrap:break-word;
  text-shadow:0 2px 12px rgba(0,0,0,.55);pointer-events:none;
}

.progress{position:absolute;top:10px;left:10px;right:10px;display:flex;gap:3px;z-index:5}
.progress-seg{flex:1;height:2px;background:rgba(255,255,255,.25);border-radius:1px;overflow:hidden}
.progress-fill{height:100%;width:0;background:#fff}

.info{position:absolute;left:16px;right:80px;bottom:20px;z-index:6;text-shadow:0 2px 8px rgba(0,0,0,.75)}
.info-user{font-weight:600;font-size:15px}
.info-title{font-size:14px;opacity:.9;margin-top:2px}

.actions{position:absolute;right:8px;bottom:20px;display:flex;flex-direction:column;gap:14px;align-items:center;z-index:6}
.act-btn{display:flex;flex-direction:column;align-items:center;gap:3px;padding:4px}
.act-btn svg{width:32px;height:32px;color:#fff;filter:drop-shadow(0 2px 6px rgba(0,0,0,.6));transition:transform .15s ease}
.act-btn:active svg{transform:scale(1.15)}
.act-btn.liked svg{color:var(--like)}
.act-count{font-size:12px;font-weight:600}

/* Bottom nav mobile */
#bottom-nav{
  display:grid;grid-template-columns:1fr 1fr 1fr;background:#000;
  border-top:1px solid var(--border);
  padding:6px 0 calc(6px + env(safe-area-inset-bottom));
  align-items:center;flex-shrink:0;
}
.nav-btn{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:4px;color:var(--dimmer);font-size:11px;font-weight:500}
.nav-btn.active{color:var(--text)}
.nav-btn svg{width:22px;height:22px}
.nav-create .plus{width:44px;height:30px;background:var(--text);color:var(--bg);border-radius:8px;display:grid;place-items:center}
.nav-create .plus svg{width:20px;height:20px}

/* Show nav (desktop) */
.show-nav-btn{
  display:none;position:absolute;top:50%;transform:translateY(-50%);
  width:48px;height:48px;border-radius:50%;background:var(--surface);
  border:1px solid var(--border);z-index:10;
  align-items:center;justify-content:center;
}
.show-nav-btn:hover:not(:disabled){background:var(--surface-2)}
.show-nav-btn:disabled{opacity:.3;cursor:not-allowed}
.show-nav-btn svg{width:24px;height:24px}
#prev-show{left:20px}
#next-show{right:20px}

/* Profile */
.profile-container{padding:20px 16px 24px}
.profile-top{display:flex;align-items:center;gap:14px;margin-bottom:20px}
.avatar{width:56px;height:56px;border-radius:50%;background:var(--surface-2);display:grid;place-items:center;font-size:22px;font-weight:700;text-transform:uppercase;flex-shrink:0}
.profile-info{flex:1;min-width:0}
.profile-name{font-size:17px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.profile-meta{color:var(--dim);font-size:13px;margin-top:2px}
.profile-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:2px}
.profile-item{aspect-ratio:9/16;position:relative;overflow:hidden;background:var(--surface);cursor:pointer}
.profile-item img{width:100%;height:100%;object-fit:cover;display:block}
.profile-item .p-del{
  position:absolute;top:4px;right:4px;width:26px;height:26px;
  background:rgba(0,0,0,.75);border-radius:50%;display:grid;place-items:center;
  opacity:0;transition:opacity .15s;
}
.profile-item .p-del svg{width:14px;height:14px;color:#fff}
.profile-item:hover .p-del{opacity:1}
@media (hover:none){.profile-item .p-del{opacity:1}}
.profile-empty{grid-column:1/-1;padding:40px 16px;text-align:center;color:var(--dimmer)}
.profile-actions{margin-top:24px;display:flex;justify-content:center}

/* Create */
#create-screen{background:var(--bg)}
.create-bar{display:flex;align-items:center;gap:8px;padding:10px 12px;padding-top:calc(10px + env(safe-area-inset-top));border-bottom:1px solid var(--border);flex-shrink:0}
.create-bar input{
  flex:1;padding:8px 12px;background:var(--surface);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-size:14px;outline:none;min-width:0;
}
.create-bar input:focus{border-color:var(--text)}
.create-body{flex:1;overflow-y:auto;padding:12px;padding-bottom:calc(12px + env(safe-area-inset-bottom))}
.create-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:12px}
.create-item{aspect-ratio:9/16;position:relative;border-radius:8px;overflow:hidden;background:var(--surface);cursor:pointer}
.create-item img{width:100%;height:100%;object-fit:cover;display:block}
.create-item .c-del{position:absolute;top:6px;right:6px;width:26px;height:26px;background:rgba(0,0,0,.75);border-radius:50%;display:grid;place-items:center}
.create-item .c-del svg{width:14px;height:14px}
.create-item .c-badge{position:absolute;bottom:6px;left:6px;background:rgba(0,0,0,.75);padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500}
.create-empty{grid-column:1/-1;padding:40px 20px;text-align:center;color:var(--dimmer)}
.add-photo{
  display:flex;align-items:center;justify-content:center;gap:8px;padding:18px;
  border:1px dashed var(--border);border-radius:8px;color:var(--dim);cursor:pointer;
  font-size:14px;font-weight:500;
}
.add-photo:hover{border-color:var(--dim)}
.add-photo svg{width:18px;height:18px}
.add-photo input{display:none}

/* Editor */
#editor-screen{background:#000}
.editor-top{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;padding-top:calc(8px + env(safe-area-inset-top));border-bottom:1px solid var(--border);flex-shrink:0}
.editor-title{font-size:14px;color:var(--dim)}
.editor-stage-wrap{flex:1;display:grid;place-items:center;padding:12px;min-height:0;container-type:size}
.editor-stage{
  position:relative;overflow:hidden;background:#000;border-radius:8px;
  width:min(100cqw,100cqh * 9 / 16);
  aspect-ratio:9/16;
  container-type:inline-size;
  touch-action:none;
}
.editor-stage img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;user-select:none;-webkit-user-drag:none;pointer-events:none}
.etext{
  position:absolute;transform:translate(-50%,-50%);
  cursor:grab;user-select:none;touch-action:none;
  white-space:pre-wrap;text-align:center;line-height:1.1;
  font-weight:800;padding:2px 4px;border-radius:4px;max-width:90%;
  word-wrap:break-word;overflow-wrap:break-word;
  text-shadow:0 2px 12px rgba(0,0,0,.55);
}
.etext.selected{outline:1px dashed rgba(255,255,255,.75);outline-offset:2px}
.editor-controls{
  background:var(--surface);border-top:1px solid var(--border);
  padding:12px 16px calc(12px + env(safe-area-inset-bottom));
  display:flex;flex-direction:column;gap:10px;flex-shrink:0;
}
.editor-controls.empty{color:var(--dim);font-size:14px;text-align:center;padding:24px 16px calc(24px + env(safe-area-inset-bottom))}
.editor-controls input[type=text]{
  padding:8px 12px;background:var(--bg);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-size:14px;outline:none;
}
.editor-controls input[type=text]:focus{border-color:var(--text)}
.size-row{display:flex;align-items:center;gap:12px;font-size:13px;color:var(--dim)}
.size-row input[type=range]{flex:1;accent-color:var(--text)}
.color-row{display:flex;gap:6px;flex-wrap:wrap}
.swatch{width:26px;height:26px;border-radius:50%;border:2px solid transparent}
.swatch.active{border-color:var(--text)}
.editor-actions{display:flex;gap:8px;padding:12px;padding-bottom:calc(12px + env(safe-area-inset-bottom));background:#000;border-top:1px solid var(--border);flex-shrink:0}

/* Viewer */
#viewer-screen{background:#000}
.viewer-top{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;padding-top:calc(8px + env(safe-area-inset-top));border-bottom:1px solid var(--border);flex-shrink:0}
.viewer-title{font-size:14px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;text-align:center;padding:0 8px}
.viewer-body{flex:1;display:grid;place-items:center;padding:12px;min-height:0;container-type:size}
.viewer-stage{position:relative;overflow:hidden;background:#000;border-radius:8px;width:min(100cqw,100cqh * 9 / 16);aspect-ratio:9/16;container-type:inline-size}
.viewer-stage .slide{position:absolute;inset:0;opacity:0;transition:opacity .3s}
.viewer-stage .slide.active{opacity:1}
.viewer-stage .slide img{width:100%;height:100%;object-fit:cover}
.viewer-stage .txt{position:absolute;transform:translate(-50%,-50%);text-align:center;white-space:pre-wrap;line-height:1.1;font-weight:800;max-width:90%;text-shadow:0 2px 12px rgba(0,0,0,.55)}

/* Modal */
.modal{position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;padding:16px;z-index:200}
.modal-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;width:100%;max-width:380px;display:flex;flex-direction:column;gap:12px}
.modal-card h3{font-size:17px;font-weight:600}
.field{display:flex;flex-direction:column;gap:6px}
.field label{font-size:13px;color:var(--dim)}
.field input{padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px;outline:none}
.field input:focus{border-color:var(--text)}
.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}

/* Desktop */
@media (min-width:768px){
  #app{flex-direction:row}
  #sidebar{display:flex}
  #bottom-nav{display:none}
  .feed-item{padding:24px 12px}
  .show-nav-btn{display:flex}
  .profile-container{max-width:720px;margin:0 auto;padding:40px 20px}
  #create-screen,#viewer-screen{align-items:center}
  #create-screen > .create-bar,#create-screen > .create-body{width:100%;max-width:720px;margin:0 auto}
  .viewer-stage{max-width:100%}
  .modal-card{max-width:420px}
}
</style>
</head>
<body>

<!-- AUTH -->
<div id="auth" class="screen">
  <div class="auth-wrap">
    <h1 class="brand">SlideTok</h1>
    <p class="sub">Только слайдшоу.</p>
    <div class="seg">
      <button class="active" data-mode="login">Вход</button>
      <button data-mode="register">Регистрация</button>
    </div>
    <form id="auth-form">
      <input id="auth-user" placeholder="Имя" required minlength="3" maxlength="32" autocomplete="username">
      <input id="auth-pass" type="password" placeholder="Пароль" required minlength="4" autocomplete="current-password">
      <button class="btn" type="submit" id="auth-submit">Войти</button>
    </form>
    <div id="auth-err" class="err"></div>
    <p class="hint">Демо: demo / demo</p>
  </div>
</div>

<!-- APP -->
<div id="app" class="hidden">
  <aside id="sidebar">
    <div class="sidebar-logo">SlideTok</div>
    <nav class="sidebar-nav">
      <button class="sidebar-btn active" data-nav="feed">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5L12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>
        Лента
      </button>
      <button class="sidebar-btn" data-nav="create">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        Создать
      </button>
      <button class="sidebar-btn" data-nav="profile">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v2"/></svg>
        Профиль
      </button>
    </nav>
    <div class="sidebar-user" id="sidebar-user">
      <div class="sidebar-avatar" id="sidebar-avatar">?</div>
      <div class="sidebar-username" id="sidebar-username">@</div>
    </div>
  </aside>

  <main id="main-area">
    <div id="feed-view" class="view">
      <div id="feed"></div>
      <button id="prev-show" class="show-nav-btn" aria-label="Предыдущее">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
      </button>
      <button id="next-show" class="show-nav-btn" aria-label="Следующее">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
      </button>
    </div>
    <div id="profile-view" class="view hidden">
      <div class="profile-container">
        <div class="profile-top">
          <div class="avatar" id="profile-avatar">?</div>
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
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5L12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>
      <span>Лента</span>
    </button>
    <button class="nav-btn nav-create" data-nav="create">
      <span class="plus">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
      </span>
    </button>
    <button class="nav-btn" data-nav="profile">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v2"/></svg>
      <span>Профиль</span>
    </button>
  </nav>
</div>

<!-- CREATE -->
<div id="create-screen" class="screen hidden">
  <div class="create-bar">
    <button class="icon-btn" id="create-close" aria-label="Закрыть">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
    </button>
    <input id="create-title" type="text" placeholder="Название" maxlength="80">
    <button class="btn btn-sm" id="create-publish" disabled>Опубликовать</button>
  </div>
  <div class="create-body">
    <div class="create-grid" id="create-grid"></div>
    <label class="add-photo">
      <input id="add-photo-input" type="file" accept="image/*" multiple>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
      <span>Добавить фото</span>
    </label>
  </div>
</div>

<!-- EDITOR -->
<div id="editor-screen" class="screen hidden">
  <div class="editor-top">
    <button class="icon-btn" id="editor-back" aria-label="Назад">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>
    <div class="editor-title">Текст на фото</div>
    <button class="icon-btn" id="editor-delete" aria-label="Удалить слайд">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
    </button>
  </div>
  <div class="editor-stage-wrap">
    <div class="editor-stage" id="editor-stage"></div>
  </div>
  <div class="editor-controls" id="editor-controls"></div>
  <div class="editor-actions">
    <button class="btn-ghost" id="editor-add-text">+ Текст</button>
    <button class="btn" id="editor-done" style="flex:1">Готово</button>
  </div>
</div>

<!-- VIEWER -->
<div id="viewer-screen" class="screen hidden">
  <div class="viewer-top">
    <button class="icon-btn" id="viewer-back" aria-label="Закрыть">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>
    <div class="viewer-title" id="viewer-title"></div>
    <button class="icon-btn" id="viewer-delete" aria-label="Удалить">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
    </button>
  </div>
  <div class="viewer-body">
    <div class="viewer-stage" id="viewer-stage"></div>
  </div>
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
      <input id="edit-current" type="password" placeholder="Только при смене пароля">
    </div>
    <div class="field">
      <label>Новый пароль</label>
      <input id="edit-new" type="password" placeholder="Оставьте пустым, чтобы не менять">
    </div>
    <div id="edit-err" class="err"></div>
    <div class="modal-actions">
      <button class="btn-ghost" id="edit-cancel">Отмена</button>
      <button class="btn" id="edit-save">Сохранить</button>
    </div>
  </div>
</div>

<script>
"use strict";
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>Array.from(r.querySelectorAll(s));

const ICONS={
  heart:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>',
  close:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
};
const COLORS=["#ffffff","#000000","#ff3b5c","#ff9500","#ffcc00","#34c759","#00c7be","#007aff","#af52de","#ff6b9d"];

const state={
  user:null, view:'feed', slideshows:[], feedItems:[],
  currentIndex:0, observer:null,
  createDraft:[], editingIdx:-1, selectedTextId:null,
  viewingShow:null, viewerTimer:null, viewerIdx:0,
};

// ---------- API ----------
async function api(path,opts={}){
  const init={method:opts.method||'GET',credentials:'same-origin'};
  if(opts.body!==undefined){init.headers={'Content-Type':'application/json'};init.body=JSON.stringify(opts.body)}
  const res=await fetch(path,init);
  if(!res.ok){let msg='Ошибка';try{const j=await res.json();msg=j.detail||msg}catch{};throw new Error(msg)}
  return res.json();
}

// ---------- Image processing ----------
function loadImgFile(file){
  return new Promise((resolve,reject)=>{
    const r=new FileReader();
    r.onerror=()=>reject(new Error('Не удалось прочитать'));
    r.onload=()=>{
      const img=new Image();
      img.onload=()=>resolve(img);
      img.onerror=()=>reject(new Error('Не удалось открыть'));
      img.src=r.result;
    };
    r.readAsDataURL(file);
  });
}

function cropTo916(img,maxWidth=1080){
  const ratio=9/16;
  const imgRatio=img.width/img.height;
  let sx,sy,sw,sh;
  if(imgRatio>ratio){
    sh=img.height; sw=sh*ratio; sx=(img.width-sw)/2; sy=0;
  }else{
    sw=img.width; sh=sw/ratio; sx=0; sy=(img.height-sh)/2;
  }
  const outW=Math.min(sw,maxWidth);
  const outH=Math.round(outW/ratio);
  const c=document.createElement('canvas');
  c.width=outW; c.height=outH;
  const ctx=c.getContext('2d');
  ctx.imageSmoothingQuality='high';
  ctx.drawImage(img,sx,sy,sw,sh,0,0,outW,outH);
  return c.toDataURL('image/jpeg',0.85);
}

async function processImageFile(file){
  const img=await loadImgFile(file);
  return cropTo916(img);
}

// ---------- Helpers ----------
function renderTextEl(t){
  const el=document.createElement('div');
  el.className='txt';
  el.textContent=t.text||'\u00A0';
  el.style.left=t.x+'%';
  el.style.top=t.y+'%';
  el.style.color=t.color;
  el.style.fontSize=t.size+'cqw';
  return el;
}

// ---------- Player ----------
class Player{
  constructor(root,duration=3500){
    this.root=root;
    this.slides=Array.from(root.querySelectorAll('.slide'));
    this.fills=Array.from(root.querySelectorAll('.progress-fill'));
    this.duration=duration;
    this.idx=0; this.timer=null; this.paused=false; this.visible=false;
    this.startTime=0; this.remaining=duration;
  }
  start(){
    this.visible=true; this.paused=false;
    this.idx=0; this.remaining=this.duration;
    this.render(); this.run();
  }
  stop(){
    this.visible=false; this.paused=false;
    clearTimeout(this.timer);
    this.idx=0; this.remaining=this.duration;
    this.render();
    this.fills.forEach(f=>{f.style.transition='none';f.style.width='0'});
  }
  pause(){
    if(this.paused||!this.visible)return;
    this.paused=true; clearTimeout(this.timer);
    const elapsed=Date.now()-this.startTime;
    this.remaining=Math.max(100,this.remaining-elapsed);
    const fill=this.fills[this.idx];
    if(fill){
      const pw=fill.parentElement.getBoundingClientRect().width;
      const cw=fill.getBoundingClientRect().width;
      fill.style.transition='none';
      fill.style.width=pw?(cw/pw*100)+'%':'0';
    }
  }
  resume(){
    if(!this.paused||!this.visible)return;
    this.paused=false; this.runFrom();
  }
  toggle(){ if(this.paused) this.resume(); else this.pause(); }
  run(){
    this.fills.forEach((f,j)=>{
      f.style.transition='none';
      f.style.width=j<this.idx?'100%':'0';
    });
    this.runFrom();
  }
  runFrom(){
    clearTimeout(this.timer);
    this.startTime=Date.now();
    const fill=this.fills[this.idx];
    if(fill){
      const progress=1-this.remaining/this.duration;
      fill.style.transition='none';
      fill.style.width=(progress*100)+'%';
      void fill.offsetWidth;
      fill.style.transition=`width ${this.remaining}ms linear`;
      fill.style.width='100%';
    }
    this.timer=setTimeout(()=>this.next(),this.remaining);
  }
  next(){
    if(!this.visible)return;
    this.paused=false;
    this.idx=(this.idx+1)%this.slides.length;
    this.remaining=this.duration;
    this.render(); this.run();
  }
  prev(){
    if(!this.visible)return;
    this.paused=false;
    this.idx=(this.idx-1+this.slides.length)%this.slides.length;
    this.remaining=this.duration;
    this.render(); this.run();
  }
  render(){
    this.slides.forEach((s,j)=>s.classList.toggle('active',j===this.idx));
  }
}

// ---------- Feed ----------
function createStageBox(show){
  const box=document.createElement('div');
  box.className='stage-box';

  const slidesEl=document.createElement('div');
  slidesEl.className='slides';
  show.slides.forEach((slide,i)=>{
    const s=document.createElement('div');
    s.className='slide'+(i===0?' active':'');
    const img=document.createElement('img');
    img.src=slide.image; img.alt=''; img.draggable=false;
    s.appendChild(img);
    (slide.texts||[]).forEach(t=>s.appendChild(renderTextEl(t)));
    slidesEl.appendChild(s);
  });
  box.appendChild(slidesEl);

  if(show.slides.length>1){
    const prog=document.createElement('div');
    prog.className='progress';
    show.slides.forEach(()=>{
      const seg=document.createElement('div');
      seg.className='progress-seg';
      const fill=document.createElement('div');
      fill.className='progress-fill';
      seg.appendChild(fill); prog.appendChild(seg);
    });
    box.appendChild(prog);
  }

  const info=document.createElement('div');
  info.className='info';
  const u=document.createElement('div');
  u.className='info-user'; u.textContent='@'+show.username;
  const t=document.createElement('div');
  t.className='info-title'; t.textContent=show.title;
  info.appendChild(u); info.appendChild(t);
  box.appendChild(info);

  const actions=document.createElement('div');
  actions.className='actions';

  const likeBtn=document.createElement('button');
  likeBtn.className='act-btn'+(show.liked?' liked':'');
  likeBtn.innerHTML=ICONS.heart+`<span class="act-count">${show.likes}</span>`;
  likeBtn.addEventListener('click',async(e)=>{
    e.stopPropagation();
    try{
      const r=await api('/api/slideshows/'+show.id+'/like',{method:'POST'});
      likeBtn.classList.toggle('liked',r.liked);
      likeBtn.querySelector('.act-count').textContent=r.likes;
    }catch(err){
      if(err.message.includes('вход'))return showAuth();
      alert(err.message);
    }
  });
  actions.appendChild(likeBtn);

  if(show.mine){
    const delBtn=document.createElement('button');
    delBtn.className='act-btn';
    delBtn.title='Удалить';
    delBtn.innerHTML=ICONS.trash;
    delBtn.addEventListener('click',async(e)=>{
      e.stopPropagation();
      if(!confirm('Удалить это слайдшоу?'))return;
      try{
        await api('/api/slideshows/'+show.id,{method:'DELETE'});
        const keepIdx=state.currentIndex;
        state.slideshows=await api('/api/slideshows');
        renderFeed(keepIdx);
      }catch(err){alert(err.message)}
    });
    actions.appendChild(delBtn);
  }
  box.appendChild(actions);

  box._player=new Player(box);
  return box;
}

function renderFeed(preserveIdx=0){
  state.feedItems.forEach(item=>item.player.stop());
  if(state.observer){state.observer.disconnect();state.observer=null}
  state.feedItems=[];
  const feed=$('#feed');
  feed.innerHTML='';

  if(!state.slideshows.length){
    feed.innerHTML='<div class="feed-empty"><div>Пока пусто</div><div style="font-size:13px;opacity:.7">Создайте первое слайдшоу кнопкой «+»</div></div>';
    updateShowNav();
    return;
  }

  state.slideshows.forEach((show,i)=>{
    const item=document.createElement('div');
    item.className='feed-item';
    item.dataset.index=i;
    const box=createStageBox(show);
    item.appendChild(box);
    feed.appendChild(item);
    state.feedItems.push({show,player:box._player,el:item});
  });

  setupFeedObserver();

  const idx=Math.max(0,Math.min(preserveIdx,state.feedItems.length-1));
  requestAnimationFrame(()=>{
    feed.scrollTop=idx*feed.clientHeight;
    setActiveItem(idx,true);
  });
}

function setupFeedObserver(){
  if(state.observer)state.observer.disconnect();
  state.observer=new IntersectionObserver((entries)=>{
    let bestIdx=state.currentIndex, bestRatio=0;
    entries.forEach(entry=>{
      const idx=parseInt(entry.target.dataset.index,10);
      if(entry.intersectionRatio>bestRatio){
        bestRatio=entry.intersectionRatio; bestIdx=idx;
      }
    });
    if(bestRatio>=0.5) setActiveItem(bestIdx);
  },{root:$('#feed'),threshold:[0,0.5,0.75,1]});
  state.feedItems.forEach(item=>state.observer.observe(item.el));
}

function setActiveItem(idx,force=false){
  if(!force && state.currentIndex===idx && state.feedItems[idx] && state.feedItems[idx].player.visible) return;
  state.currentIndex=idx;
  state.feedItems.forEach((item,i)=>{
    if(i===idx) item.player.start();
    else item.player.stop();
  });
  updateShowNav();
}

function updateShowNav(){
  const prev=$('#prev-show'), next=$('#next-show');
  if(!prev||!next)return;
  prev.disabled=state.currentIndex<=0;
  next.disabled=state.currentIndex>=state.feedItems.length-1;
}

function scrollToItem(idx){
  if(!state.feedItems.length)return;
  idx=Math.max(0,Math.min(idx,state.feedItems.length-1));
  const feed=$('#feed');
  feed.scrollTop=idx*feed.clientHeight;
  setActiveItem(idx);
}

$('#prev-show').addEventListener('click',()=>scrollToItem(state.currentIndex-1));
$('#next-show').addEventListener('click',()=>scrollToItem(state.currentIndex+1));

// ---------- Keyboard ----------
document.addEventListener('keydown',(e)=>{
  const tag=e.target.tagName;
  if(['INPUT','TEXTAREA','SELECT'].includes(tag)||e.target.isContentEditable)return;
  if(state.view!=='feed'||!state.feedItems.length)return;
  const player=state.feedItems[state.currentIndex]?.player;
  if(!player)return;

  if(e.key==='ArrowDown'){e.preventDefault();scrollToItem(state.currentIndex+1)}
  else if(e.key==='ArrowUp'){e.preventDefault();scrollToItem(state.currentIndex-1)}
  else if(e.key===' '){e.preventDefault();player.toggle()}
  else if(e.key==='ArrowRight'){e.preventDefault();player.next()}
  else if(e.key==='ArrowLeft'){e.preventDefault();player.prev()}
});

// ---------- Auth ----------
let authMode='login';

function showAuth(){
  $('#auth').classList.remove('hidden');
  $('#app').classList.add('hidden');
  state.feedItems.forEach(item=>item.player.stop());
}

async function enterApp(){
  $('#auth').classList.add('hidden');
  $('#app').classList.remove('hidden');
  state.user=await api('/api/me');
  updateUserUI();
  state.slideshows=await api('/api/slideshows');
  state.currentIndex=0;
  renderFeed(0);
  switchView('feed');
}

function updateUserUI(){
  if(!state.user)return;
  $('#sidebar-avatar').textContent=state.user.username.charAt(0);
  $('#sidebar-username').textContent='@'+state.user.username;
}

$$('.seg button').forEach(b=>b.addEventListener('click',()=>{
  authMode=b.dataset.mode;
  $$('.seg button').forEach(x=>x.classList.toggle('active',x===b));
  $('#auth-submit').textContent=authMode==='login'?'Войти':'Создать';
  $('#auth-err').textContent='';
}));

$('#auth-form').addEventListener('submit',async(e)=>{
  e.preventDefault();
  const username=$('#auth-user').value.trim();
  const password=$('#auth-pass').value;
  $('#auth-err').textContent='';
  $('#auth-submit').disabled=true;
  try{
    await api(authMode==='login'?'/api/login':'/api/register',{method:'POST',body:{username,password}});
    await enterApp();
  }catch(err){
    $('#auth-err').textContent=err.message;
  }finally{
    $('#auth-submit').disabled=false;
  }
});

$('#logout-btn').addEventListener('click',async()=>{
  try{await api('/api/logout',{method:'POST'})}catch{}
  state.user=null;
  state.slideshows=[];
  showAuth();
});

$('#sidebar-user').addEventListener('click',()=>switchView('profile'));

// ---------- Navigation ----------
function switchView(view){
  state.view=view;
  if(view!=='feed') state.feedItems.forEach(item=>item.player.stop());
  $$('.sidebar-btn,.nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.nav===view));
  $('#feed-view').classList.toggle('hidden',view!=='feed');
  $('#profile-view').classList.toggle('hidden',view!=='profile');
  if(view==='profile') loadProfile();
}

$$('.sidebar-btn,.nav-btn').forEach(b=>b.addEventListener('click',()=>{
  const nav=b.dataset.nav;
  if(nav==='create') openCreate();
  else switchView(nav);
}));

// ---------- Profile ----------
async function loadProfile(){
  try{
    const data=await api('/api/me');
    state.user=data;
    $('#profile-name').textContent='@'+data.username;
    $('#profile-meta').textContent=`${data.shows_count} слайдшоу · ${data.likes_count} лайков`;
    $('#profile-avatar').textContent=data.username.charAt(0);
    updateUserUI();
    const shows=await api('/api/me/slideshows');
    const grid=$('#profile-grid');
    grid.innerHTML='';
    if(!shows.length){
      grid.innerHTML='<div class="profile-empty">Пока нет слайдшоу</div>';
      return;
    }
    shows.forEach(s=>{
      const item=document.createElement('div');
      item.className='profile-item';
      const img=document.createElement('img');
      img.src=s.slides[0].image; img.alt='';
      item.appendChild(img);
      const del=document.createElement('button');
      del.className='p-del';
      del.innerHTML=ICONS.trash;
      del.addEventListener('click',async(e)=>{
        e.stopPropagation();
        if(!confirm('Удалить это слайдшоу?'))return;
        try{
          await api('/api/slideshows/'+s.id,{method:'DELETE'});
          state.slideshows=await api('/api/slideshows');
          renderFeed(state.currentIndex);
          await loadProfile();
        }catch(err){alert(err.message)}
      });
      item.appendChild(del);
      item.addEventListener('click',()=>openViewer(s));
      grid.appendChild(item);
    });
  }catch(e){console.error(e)}
}

$('#edit-profile-btn').addEventListener('click',()=>{
  $('#edit-username').value=state.user.username;
  $('#edit-current').value='';
  $('#edit-new').value='';
  $('#edit-err').textContent='';
  $('#edit-profile-modal').classList.remove('hidden');
});

$('#edit-cancel').addEventListener('click',()=>$('#edit-profile-modal').classList.add('hidden'));

$('#edit-save').addEventListener('click',async()=>{
  const body={};
  const newName=$('#edit-username').value.trim();
  if(newName&&newName!==state.user.username) body.username=newName;
  const newPass=$('#edit-new').value;
  if(newPass){body.new_password=newPass;body.current_password=$('#edit-current').value}
  if(!Object.keys(body).length){$('#edit-profile-modal').classList.add('hidden');return}
  try{
    await api('/api/me',{method:'PATCH',body});
    $('#edit-profile-modal').classList.add('hidden');
    await loadProfile();
    state.slideshows=await api('/api/slideshows');
    renderFeed(state.currentIndex);
  }catch(e){$('#edit-err').textContent=e.message}
});

// ---------- Viewer ----------
function openViewer(show){
  state.viewingShow=show;
  state.viewerIdx=0;
  $('#viewer-title').textContent=show.title;
  const stage=$('#viewer-stage');
  stage.innerHTML='';
  show.slides.forEach((slide,i)=>{
    const s=document.createElement('div');
    s.className='slide'+(i===0?' active':'');
    const img=document.createElement('img');
    img.src=slide.image; img.alt='';
    s.appendChild(img);
    (slide.texts||[]).forEach(t=>s.appendChild(renderTextEl(t)));
    stage.appendChild(s);
  });
  if(state.viewerTimer)clearInterval(state.viewerTimer);
  if(show.slides.length>1){
    state.viewerTimer=setInterval(()=>{
      state.viewerIdx=(state.viewerIdx+1)%show.slides.length;
      $$('.slide',stage).forEach((s,j)=>s.classList.toggle('active',j===state.viewerIdx));
    },3500);
  }
  $('#viewer-screen').classList.remove('hidden');
}

function closeViewer(){
  if(state.viewerTimer){clearInterval(state.viewerTimer);state.viewerTimer=null}
  state.viewingShow=null;
  $('#viewer-screen').classList.add('hidden');
}

$('#viewer-back').addEventListener('click',closeViewer);

$('#viewer-delete').addEventListener('click',async()=>{
  if(!state.viewingShow)return;
  if(!confirm('Удалить это слайдшоу?'))return;
  try{
    await api('/api/slideshows/'+state.viewingShow.id,{method:'DELETE'});
    closeViewer();
    state.slideshows=await api('/api/slideshows');
    renderFeed(state.currentIndex);
    await loadProfile();
  }catch(e){alert(e.message)}
});

// ---------- Create ----------
function openCreate(){
  state.createDraft=[];
  state.editingIdx=-1;
  state.selectedTextId=null;
  $('#create-title').value='';
  $('#create-screen').classList.remove('hidden');
  renderCreateGrid();
}

function closeCreate(){
  $('#create-screen').classList.add('hidden');
  state.createDraft=[];
}

function renderCreateGrid(){
  const grid=$('#create-grid');
  grid.innerHTML='';
  if(!state.createDraft.length){
    grid.innerHTML='<div class="create-empty">Добавьте фото</div>';
  }else{
    state.createDraft.forEach((slide,i)=>{
      const item=document.createElement('div');
      item.className='create-item';
      const img=document.createElement('img');
      img.src=slide.image; img.alt='';
      item.appendChild(img);
      if(slide.texts&&slide.texts.length){
        const badge=document.createElement('div');
        badge.className='c-badge';
        badge.textContent=slide.texts.length+' текст'+(slide.texts.length>1?'а':'');
        item.appendChild(badge);
      }
      const del=document.createElement('button');
      del.className='c-del';
      del.innerHTML=ICONS.close;
      del.addEventListener('click',(e)=>{
        e.stopPropagation();
        state.createDraft.splice(i,1);
        renderCreateGrid();
      });
      item.appendChild(del);
      item.addEventListener('click',()=>openEditor(i));
      grid.appendChild(item);
    });
  }
  $('#create-publish').disabled=state.createDraft.length===0;
}

$('#create-close').addEventListener('click',()=>{
  if(state.createDraft.length&&!confirm('Отменить создание?'))return;
  closeCreate();
});

$('#add-photo-input').addEventListener('change',async(e)=>{
  const files=Array.from(e.target.files||[]);
  e.target.value='';
  for(const f of files){
    try{
      const dataUrl=await processImageFile(f);
      state.createDraft.push({image:dataUrl,texts:[]});
    }catch(err){alert(err.message)}
  }
  renderCreateGrid();
});

$('#create-publish').addEventListener('click',async()=>{
  if(!state.createDraft.length)return;
  const btn=$('#create-publish');
  btn.disabled=true;
  try{
    await api('/api/slideshows',{method:'POST',body:{title:$('#create-title').value,slides:state.createDraft}});
    closeCreate();
    state.slideshows=await api('/api/slideshows');
    renderFeed(0);
    switchView('feed');
  }catch(err){
    alert(err.message);
    btn.disabled=false;
  }
});

// ---------- Editor ----------
function getEditingSlide(){
  return state.createDraft[state.editingIdx];
}

function getSelectedText(){
  const s=getEditingSlide();
  if(!s)return null;
  return s.texts.find(t=>t.id===state.selectedTextId)||null;
}

function findTextEl(id){
  return $(`.etext[data-id="${id}"]`, $('#editor-stage'));
}

function openEditor(idx){
  state.editingIdx=idx;
  state.selectedTextId=null;
  $('#editor-screen').classList.remove('hidden');
  renderEditor();
}

function closeEditor(){
  state.editingIdx=-1;
  state.selectedTextId=null;
  $('#editor-screen').classList.add('hidden');
  renderCreateGrid();
}

function renderEditor(){
  const slide=getEditingSlide();
  if(!slide){closeEditor();return}
  const stage=$('#editor-stage');
  stage.innerHTML='';
  const img=document.createElement('img');
  img.src=slide.image; img.alt=''; img.draggable=false;
  stage.appendChild(img);
  slide.texts.forEach(t=>{
    const te=document.createElement('div');
    te.className='etext'+(t.id===state.selectedTextId?' selected':'');
    te.dataset.id=t.id;
    te.textContent=t.text||'\u00A0';
    te.style.left=t.x+'%';
    te.style.top=t.y+'%';
    te.style.color=t.color;
    te.style.fontSize=t.size+'cqw';
    attachDrag(te,t,stage);
    stage.appendChild(te);
  });
  renderTextControls();
}

function attachDrag(te,textObj,stage){
  te.addEventListener('pointerdown',(e)=>{
    e.preventDefault(); e.stopPropagation();
    if(state.selectedTextId!==textObj.id){
      state.selectedTextId=textObj.id;
      $$('.etext',stage).forEach(x=>x.classList.toggle('selected',x===te));
      renderTextControls();
    }
    const rect=stage.getBoundingClientRect();
    const move=(ev)=>{
      const x=((ev.clientX-rect.left)/rect.width)*100;
      const y=((ev.clientY-rect.top)/rect.height)*100;
      textObj.x=Math.max(0,Math.min(100,x));
      textObj.y=Math.max(0,Math.min(100,y));
      te.style.left=textObj.x+'%';
      te.style.top=textObj.y+'%';
    };
    const up=()=>{
      window.removeEventListener('pointermove',move);
      window.removeEventListener('pointerup',up);
      window.removeEventListener('pointercancel',up);
      clampText(te,textObj,stage);
    };
    window.addEventListener('pointermove',move);
    window.addEventListener('pointerup',up);
    window.addEventListener('pointercancel',up);
  });
}

function clampText(te,textObj,stage){
  const sRect=stage.getBoundingClientRect();
  const tRect=te.getBoundingClientRect();
  let dx=0,dy=0;
  if(tRect.left<sRect.left) dx=sRect.left-tRect.left;
  else if(tRect.right>sRect.right) dx=sRect.right-tRect.right;
  if(tRect.top<sRect.top) dy=sRect.top-tRect.top;
  else if(tRect.bottom>sRect.bottom) dy=sRect.bottom-tRect.bottom;
  if(dx||dy){
    textObj.x=Math.max(0,Math.min(100,textObj.x+(dx/sRect.width)*100));
    textObj.y=Math.max(0,Math.min(100,textObj.y+(dy/sRect.height)*100));
    te.style.left=textObj.x+'%';
    te.style.top=textObj.y+'%';
  }
}

function renderTextControls(){
  const wrap=$('#editor-controls');
  const text=getSelectedText();
  if(!text){
    wrap.className='editor-controls empty';
    wrap.textContent='Нажмите на текст, чтобы редактировать, или добавьте новый';
    return;
  }
  wrap.className='editor-controls';
  wrap.innerHTML='';

  const input=document.createElement('input');
  input.type='text'; input.placeholder='Текст'; input.maxLength=300;
  input.value=text.text||'';
  input.addEventListener('input',(e)=>{
    text.text=e.target.value;
    const te=findTextEl(text.id);
    if(te)te.textContent=text.text||'\u00A0';
  });
  wrap.appendChild(input);

  const sizeRow=document.createElement('div');
  sizeRow.className='size-row';
  const label=document.createElement('span');
  label.textContent='Размер';
  const range=document.createElement('input');
  range.type='range'; range.min=2; range.max=20; range.step=0.5;
  range.value=text.size;
  range.addEventListener('input',(e)=>{
    text.size=parseFloat(e.target.value);
    const te=findTextEl(text.id);
    if(te)te.style.fontSize=text.size+'cqw';
    const stage=$('#editor-stage');
    if(te&&stage) clampText(te,text,stage);
  });
  sizeRow.appendChild(label); sizeRow.appendChild(range);
  wrap.appendChild(sizeRow);

  const colorRow=document.createElement('div');
  colorRow.className='color-row';
  COLORS.forEach(c=>{
    const sw=document.createElement('button');
    sw.className='swatch'+(c===text.color?' active':'');
    sw.style.background=c;
    sw.addEventListener('click',()=>{
      text.color=c;
      const te=findTextEl(text.id);
      if(te)te.style.color=c;
      $$('.swatch',colorRow).forEach(x=>x.classList.toggle('active',x===sw));
    });
    colorRow.appendChild(sw);
  });
  wrap.appendChild(colorRow);

  const delBtn=document.createElement('button');
  delBtn.className='btn-danger btn-sm';
  delBtn.textContent='Удалить текст';
  delBtn.style.alignSelf='flex-start';
  delBtn.addEventListener('click',()=>{
    const s=getEditingSlide();
    if(!s)return;
    s.texts=s.texts.filter(t=>t.id!==state.selectedTextId);
    state.selectedTextId=null;
    renderEditor();
  });
  wrap.appendChild(delBtn);
}

$('#editor-back').addEventListener('click',()=>{
  state.selectedTextId=null;
  closeEditor();
});

$('#editor-done').addEventListener('click',()=>closeEditor());

$('#editor-delete').addEventListener('click',()=>{
  if(state.editingIdx<0)return;
  if(!confirm('Удалить это фото?'))return;
  state.createDraft.splice(state.editingIdx,1);
  closeEditor();
});

$('#editor-add-text').addEventListener('click',()=>{
  const slide=getEditingSlide();
  if(!slide)return;
  const t={
    id:'t_'+Math.random().toString(36).slice(2,10),
    text:'Текст',
    x:50, y:50,
    color:'#ffffff', size:6,
  };
  slide.texts.push(t);
  state.selectedTextId=t.id;
  renderEditor();
  setTimeout(()=>{
    const input=$('#editor-controls input[type=text]');
    if(input){input.focus();input.select()}
  },50);
});

// ---------- Init ----------
(async function init(){
  try{
    await enterApp();
  }catch{
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
