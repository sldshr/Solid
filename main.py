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
USERS: Dict[str, dict] = {}      # username -> {id, username, salt, password_hash, created}
SESSIONS: Dict[str, str] = {}    # token -> username
SLIDESHOWS: List[dict] = []      # list of slideshow dicts
LIKES: Dict[str, set] = {}       # slideshow_id -> set of user_ids


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    if not token:
        return None
    username = SESSIONS.get(token)
    return USERS.get(username) if username else None


def new_session(response: Response, username: str) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = username
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return token


# ============ DEMO SEED ============
def svg_data_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def demo_slide(text: str, c1: str, c2: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1600" preserveAspectRatio="xMidYMid slice">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f'</linearGradient></defs>'
        f'<rect width="900" height="1600" fill="url(#g)"/>'
        f'<text x="450" y="820" font-size="110" text-anchor="middle" fill="#fff" '
        f'font-family="system-ui,sans-serif" font-weight="800">{text}</text>'
        f'</svg>'
    )
    return svg_data_url(svg)


def seed_demo():
    salt = secrets.token_hex(16)
    demo_id = str(uuid.uuid4())
    USERS["demo"] = {
        "id": demo_id, "username": "demo", "salt": salt,
        "password_hash": hash_password("demo", salt),
        "created": datetime.utcnow().isoformat(),
    }
    demos = [
        ("Рассвет", [
            demo_slide("Привет", "#ff6b6b", "#ee5a24"),
            demo_slide("Мир", "#48dbfb", "#0abde3"),
            demo_slide("Слайдшоу", "#feca57", "#ff9f43"),
        ]),
        ("Неон", [
            demo_slide("Неон", "#5f27cd", "#341f97"),
            demo_slide("Ночь", "#0abde3", "#006ba6"),
            demo_slide("Свет", "#f368e0", "#ff9ff3"),
            demo_slide("Тьма", "#222f3e", "#576574"),
        ]),
        ("Закат", [
            demo_slide("Закат", "#ff9a9e", "#fad0c4"),
            demo_slide("Море", "#a1c4fd", "#c2e9fb"),
            demo_slide("Небо", "#fbc2eb", "#a6c1ee"),
        ]),
    ]
    for title, slides in demos:
        sid = str(uuid.uuid4())
        SLIDESHOWS.append({
            "id": sid, "user_id": demo_id, "username": "demo",
            "title": title, "slides": slides,
            "created": datetime.utcnow().isoformat(),
        })
        LIKES[sid] = set()


seed_demo()


# ============ MODELS ============
class AuthIn(BaseModel):
    username: str
    password: str


class SlideshowIn(BaseModel):
    title: str = ""
    slides: List[str]


# ============ AUTH ROUTES ============
@app.post("/api/register")
async def register(data: AuthIn, response: Response):
    username = (data.username or "").strip()
    if len(username) < 3:
        raise HTTPException(400, "Имя минимум 3 символа")
    if len(username) > 32:
        raise HTTPException(400, "Имя слишком длинное")
    if len(data.password) < 4:
        raise HTTPException(400, "Пароль минимум 4 символа")
    if username in USERS:
        raise HTTPException(400, "Имя уже занято")
    salt = secrets.token_hex(16)
    USERS[username] = {
        "id": str(uuid.uuid4()), "username": username, "salt": salt,
        "password_hash": hash_password(data.password, salt),
        "created": datetime.utcnow().isoformat(),
    }
    new_session(response, username)
    return {"id": USERS[username]["id"], "username": username}


@app.post("/api/login")
async def login(data: AuthIn, response: Response):
    user = USERS.get((data.username or "").strip())
    if not user or user["password_hash"] != hash_password(data.password, user["salt"]):
        raise HTTPException(400, "Неверное имя или пароль")
    new_session(response, user["username"])
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
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Не авторизован")
    return {"id": user["id"], "username": user["username"]}


# ============ SLIDESHOW ROUTES ============
@app.get("/api/slideshows")
async def list_slideshows(request: Request):
    user = get_current_user(request)
    uid = user["id"] if user else None
    out = []
    for s in SLIDESHOWS:
        likes = LIKES.get(s["id"], set())
        out.append({
            "id": s["id"], "username": s["username"], "title": s["title"],
            "slides": s["slides"], "likes": len(likes),
            "liked": bool(uid and uid in likes),
            "created": s["created"],
        })
    return out


@app.post("/api/slideshows")
async def create_slideshow(data: SlideshowIn, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Войдите, чтобы публиковать")
    if not data.slides:
        raise HTTPException(400, "Нужно хотя бы одно изображение")
    if len(data.slides) > 20:
        raise HTTPException(400, "Максимум 20 слайдов")
    for s in data.slides:
        if not isinstance(s, str) or not s.startswith("data:image/"):
            raise HTTPException(400, "Некорректный слайд")
    title = (data.title or "").strip()[:80] or "Без названия"
    sid = str(uuid.uuid4())
    show = {
        "id": sid, "user_id": user["id"], "username": user["username"],
        "title": title, "slides": data.slides,
        "created": datetime.utcnow().isoformat(),
    }
    SLIDESHOWS.insert(0, show)
    LIKES[sid] = set()
    return {"id": sid}


@app.post("/api/slideshows/{slideshow_id}/like")
async def toggle_like(slideshow_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Войдите, чтобы ставить лайки")
    if not any(s["id"] == slideshow_id for s in SLIDESHOWS):
        raise HTTPException(404, "Не найдено")
    likes = LIKES.setdefault(slideshow_id, set())
    if user["id"] in likes:
        likes.remove(user["id"])
        liked = False
    else:
        likes.add(user["id"])
        liked = True
    return {"liked": liked, "likes": len(likes)}


# ============ HTML ============
HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>SlideTok</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; background: #000; color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif; }
  .hidden { display: none !important; }

  #auth { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
    padding: 20px; background: radial-gradient(circle at 50% 0%, #2a0845, #000 70%); }
  .auth-box { width: 100%; max-width: 360px; display: flex; flex-direction: column; gap: 16px; }
  .logo { font-size: 44px; font-weight: 900; letter-spacing: -1.5px; text-align: center;
    background: linear-gradient(90deg, #fe2c55, #25f4ee);
    -webkit-background-clip: text; background-clip: text; color: transparent; }
  .tagline { text-align: center; color: #999; font-size: 14px; }
  .tabs { display: flex; background: #1a1a1a; border-radius: 12px; padding: 4px; }
  .tab { flex: 1; padding: 10px; background: none; border: none; color: #888;
    font-weight: 600; cursor: pointer; border-radius: 8px; font-size: 14px; }
  .tab.active { background: #fe2c55; color: #fff; }
  #auth-form { display: flex; flex-direction: column; gap: 10px; }
  #auth-form input { padding: 14px 16px; border-radius: 12px; border: 1px solid #222;
    background: #111; color: #fff; font-size: 15px; outline: none; }
  #auth-form input:focus { border-color: #fe2c55; }
  #auth-form button { padding: 14px; border-radius: 12px; border: none;
    background: #fe2c55; color: #fff; font-weight: 700; font-size: 16px; cursor: pointer; margin-top: 4px; }
  #auth-form button:active { opacity: 0.85; }
  .error { color: #ff5c5c; font-size: 13px; text-align: center; min-height: 18px; }

  #app { position: fixed; inset: 0; }
  header { position: fixed; top: 0; left: 0; right: 0; height: 56px; display: flex;
    align-items: center; justify-content: space-between; padding: 0 16px; z-index: 20;
    background: linear-gradient(180deg, rgba(0,0,0,0.55), transparent); pointer-events: none; }
  header .logo-sm { font-size: 20px; font-weight: 900;
    background: linear-gradient(90deg, #fe2c55, #25f4ee);
    -webkit-background-clip: text; background-clip: text; color: transparent; }
  header button { pointer-events: auto; }
  .icon-btn { width: 40px; height: 40px; border-radius: 50%; border: none;
    background: rgba(255,255,255,0.12); color: #fff; display: grid; place-items: center;
    cursor: pointer; backdrop-filter: blur(10px); }
  .icon-btn:active { background: rgba(255,255,255,0.25); }

  #feed { position: absolute; inset: 0; overflow-y: scroll;
    scroll-snap-type: y mandatory; scrollbar-width: none; -webkit-overflow-scrolling: touch; }
  #feed::-webkit-scrollbar { display: none; }

  .slideshow { position: relative; height: 100vh; scroll-snap-align: start;
    scroll-snap-stop: always; overflow: hidden; background: #000; }
  .stage { position: absolute; inset: 0; }
  .slide { position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; opacity: 0; transition: opacity 0.4s ease; }
  .slide.active { opacity: 1; }

  .progress { position: absolute; top: 12px; left: 12px; right: 12px;
    display: flex; gap: 4px; z-index: 5; }
  .seg { flex: 1; height: 3px; background: rgba(255,255,255,0.25);
    border-radius: 2px; overflow: hidden; }
  .fill { height: 100%; width: 0; background: #fff; }
  @keyframes fillBar { from { width: 0; } to { width: 100%; } }

  .info { position: absolute; left: 16px; right: 90px; bottom: 32px;
    z-index: 6; text-shadow: 0 2px 8px rgba(0,0,0,0.85); }
  .info .user { font-weight: 700; font-size: 16px; margin-bottom: 4px; }
  .info .title { font-size: 15px; opacity: 0.95; }

  .actions { position: absolute; right: 12px; bottom: 32px; display: flex;
    flex-direction: column; gap: 16px; align-items: center; z-index: 6; }
  .like-btn { background: none; border: none; color: #fff; display: flex;
    flex-direction: column; align-items: center; gap: 4px; cursor: pointer; padding: 4px; }
  .like-btn svg { width: 34px; height: 34px; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.6));
    transition: transform 0.15s ease; }
  .like-btn:active svg { transform: scale(1.2); }
  .like-btn .like-count { font-size: 12px; font-weight: 600; }
  .like-btn.liked svg { color: #fe2c55; }

  .empty { display: flex; flex-direction: column; align-items: center;
    justify-content: center; height: 100vh; color: #666; gap: 12px; text-align: center; padding: 20px; }

  #create-btn { position: fixed; bottom: 24px; right: 24px; width: 60px; height: 60px;
    border-radius: 50%; border: none; background: #fe2c55; color: #fff;
    display: grid; place-items: center; cursor: pointer;
    box-shadow: 0 6px 24px rgba(254,44,85,0.5); z-index: 15; }
  #create-btn:active { transform: scale(0.95); }

  .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.75);
    display: flex; align-items: center; justify-content: center; padding: 16px;
    z-index: 30; backdrop-filter: blur(6px); }
  .modal-content { background: #111; border-radius: 16px; padding: 20px; width: 100%;
    max-width: 440px; display: flex; flex-direction: column; gap: 12px;
    max-height: 90vh; overflow: auto; border: 1px solid #222; }
  .modal-content h2 { font-size: 20px; }
  .modal-content input[type=text] { padding: 12px; border-radius: 10px; border: 1px solid #222;
    background: #000; color: #fff; font-size: 15px; outline: none; }
  .modal-content input[type=text]:focus { border-color: #fe2c55; }
  .file-label { display: block; padding: 14px; border: 2px dashed #333; border-radius: 10px;
    text-align: center; color: #888; cursor: pointer; font-size: 14px; }
  .file-label:hover { border-color: #fe2c55; color: #ccc; }
  .file-label input { display: none; }
  #preview { display: flex; gap: 6px; flex-wrap: wrap; max-height: 180px; overflow-y: auto; }
  #preview img { width: 64px; height: 64px; object-fit: cover; border-radius: 8px; }
  .modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
  .modal-actions button { padding: 10px 18px; border-radius: 10px; border: none;
    font-weight: 600; font-size: 14px; cursor: pointer; }
  #cancel-create { background: #222; color: #fff; }
  #submit-create { background: #fe2c55; color: #fff; }
  #submit-create:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
</head>
<body>

<div id="auth" class="hidden">
  <div class="auth-box">
    <div class="logo">SlideTok</div>
    <p class="tagline">Только слайдшоу. Ничего лишнего.</p>
    <div class="tabs">
      <button class="tab active" data-tab="login">Вход</button>
      <button class="tab" data-tab="register">Регистрация</button>
    </div>
    <form id="auth-form">
      <input id="username" placeholder="Имя пользователя" autocomplete="username" required>
      <input id="password" type="password" placeholder="Пароль" autocomplete="current-password" required>
      <button type="submit" id="auth-submit">Войти</button>
    </form>
    <div id="auth-error" class="error"></div>
    <p class="tagline" style="font-size:12px;margin-top:8px;">Тест: <b>demo</b> / <b>demo</b></p>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <div class="logo-sm">SlideTok</div>
    <button id="logout-btn" class="icon-btn" title="Выйти" aria-label="Выйти">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
        <polyline points="16 17 21 12 16 7"/>
        <line x1="21" y1="12" x2="9" y2="12"/>
      </svg>
    </button>
  </header>

  <div id="feed"></div>

  <button id="create-btn" title="Создать слайдшоу" aria-label="Создать">
    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor"
         stroke-width="2.5" stroke-linecap="round">
      <line x1="12" y1="5" x2="12" y2="19"/>
      <line x1="5" y1="12" x2="19" y2="12"/>
    </svg>
  </button>

  <div id="create-modal" class="modal hidden">
    <div class="modal-content">
      <h2>Новое слайдшоу</h2>
      <input id="new-title" type="text" placeholder="Название (необязательно)" maxlength="80">
      <label class="file-label">
        + Добавить изображения
        <input id="file-input" type="file" accept="image/*" multiple>
      </label>
      <div id="preview"></div>
      <div id="create-error" class="error"></div>
      <div class="modal-actions">
        <button id="cancel-create">Отмена</button>
        <button id="submit-create" disabled>Опубликовать</button>
      </div>
    </div>
  </div>
</div>

<script>
const SVG_HEART = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>';

const state = { user: null, players: [], observer: null };
const $ = (s) => document.querySelector(s);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', credentials: 'same-origin' };
  if (opts.body) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = 'Ошибка';
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

class SlideshowPlayer {
  constructor(el, duration = 3500) {
    this.el = el;
    this.slides = Array.from(el.querySelectorAll('.slide'));
    this.fills = Array.from(el.querySelectorAll('.fill'));
    this.duration = duration;
    this.index = 0;
    this.timer = null;
    this.active = false;
  }
  reset() {
    clearTimeout(this.timer);
    this.index = 0;
    this.slides.forEach((s, i) => s.classList.toggle('active', i === 0));
    this.fills.forEach(f => { f.style.animation = 'none'; f.style.width = '0'; });
  }
  play() { this.active = true; this.startSlide(this.index); }
  pause() { this.active = false; clearTimeout(this.timer); }
  startSlide(i) {
    this.index = i;
    this.slides.forEach((s, j) => s.classList.toggle('active', j === i));
    this.fills.forEach((f, j) => {
      f.style.animation = 'none';
      f.style.width = j < i ? '100%' : '0';
    });
    const cur = this.fills[i];
    if (cur) {
      void cur.offsetWidth;
      cur.style.animation = `fillBar ${this.duration}ms linear forwards`;
    }
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.next(), this.duration);
  }
  next() {
    if (!this.active || !this.slides.length) return;
    this.startSlide((this.index + 1) % this.slides.length);
  }
}

function buildSlideshowEl(s) {
  const el = document.createElement('div');
  el.className = 'slideshow';
  el.dataset.id = s.id;

  const stage = document.createElement('div');
  stage.className = 'stage';
  s.slides.forEach((src, i) => {
    const img = document.createElement('img');
    img.className = 'slide' + (i === 0 ? ' active' : '');
    img.src = src;
    stage.appendChild(img);
  });
  el.appendChild(stage);

  const prog = document.createElement('div');
  prog.className = 'progress';
  s.slides.forEach(() => {
    const seg = document.createElement('div');
    seg.className = 'seg';
    const fill = document.createElement('div');
    fill.className = 'fill';
    seg.appendChild(fill);
    prog.appendChild(seg);
  });
  el.appendChild(prog);

  const info = document.createElement('div');
  info.className = 'info';
  info.innerHTML = `<div class="user">@${escapeHtml(s.username)}</div><div class="title">${escapeHtml(s.title)}</div>`;
  el.appendChild(info);

  const actions = document.createElement('div');
  actions.className = 'actions';
  const likeBtn = document.createElement('button');
  likeBtn.className = 'like-btn' + (s.liked ? ' liked' : '');
  likeBtn.innerHTML = `${SVG_HEART}<span class="like-count">${s.likes}</span>`;
  likeBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    try {
      const r = await api('/api/slideshows/' + s.id + '/like', { method: 'POST' });
      likeBtn.classList.toggle('liked', r.liked);
      likeBtn.querySelector('.like-count').textContent = r.likes;
    } catch (err) { alert(err.message); }
  });
  actions.appendChild(likeBtn);
  el.appendChild(actions);

  const player = new SlideshowPlayer(el);
  el._player = player;
  state.players.push(player);
  return el;
}

function setupObserver() {
  if (state.observer) state.observer.disconnect();
  const feed = $('#feed');
  state.observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      const player = entry.target._player;
      if (!player) return;
      if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
        player.reset();
        player.play();
      } else {
        player.pause();
      }
    });
  }, { root: feed, threshold: [0.5] });
  state.players.forEach(p => state.observer.observe(p.el));
}

async function loadFeed() {
  const feed = $('#feed');
  state.players.forEach(p => p.pause());
  state.players = [];
  if (state.observer) { state.observer.disconnect(); state.observer = null; }
  feed.innerHTML = '';

  try {
    const list = await api('/api/slideshows');
    if (!list.length) {
      feed.innerHTML = '<div class="empty"><div>Пока нет слайдшоу</div>' +
        '<div style="font-size:13px;color:#444">Нажмите + чтобы создать первое</div></div>';
      return;
    }
    list.forEach(s => feed.appendChild(buildSlideshowEl(s)));
    setupObserver();
  } catch (e) {
    feed.innerHTML = `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

function showAuth() {
  $('#auth').classList.remove('hidden');
  $('#app').classList.add('hidden');
}
async function showApp() {
  $('#auth').classList.add('hidden');
  $('#app').classList.remove('hidden');
  await loadFeed();
}

let authMode = 'login';
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    authMode = tab.dataset.tab;
    $('#auth-submit').textContent = authMode === 'login' ? 'Войти' : 'Создать аккаунт';
    $('#auth-error').textContent = '';
  });
});

$('#auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = $('#username').value.trim();
  const password = $('#password').value;
  $('#auth-error').textContent = '';
  try {
    const path = authMode === 'login' ? '/api/login' : '/api/register';
    const user = await api(path, { method: 'POST', body: { username, password } });
    state.user = user;
    $('#auth-form').reset();
    await showApp();
  } catch (err) {
    $('#auth-error').textContent = err.message;
  }
});

$('#logout-btn').addEventListener('click', async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch {}
  state.user = null;
  state.players.forEach(p => p.pause());
  showAuth();
});

const createState = { slides: [] };

$('#create-btn').addEventListener('click', () => {
  $('#create-modal').classList.remove('hidden');
  $('#new-title').value = '';
  $('#preview').innerHTML = '';
  $('#create-error').textContent = '';
  createState.slides = [];
  $('#submit-create').disabled = true;
});
$('#cancel-create').addEventListener('click', () => {
  $('#create-modal').classList.add('hidden');
});

function readImageFile(file, maxSize = 1200) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Ошибка чтения файла'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('Не удалось открыть изображение'));
      img.onload = () => {
        let { width, height } = img;
        if (width > maxSize || height > maxSize) {
          const scale = maxSize / Math.max(width, height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width; canvas.height = height;
        canvas.getContext('2d').drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', 0.82));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

$('#file-input').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  $('#create-error').textContent = '';
  const preview = $('#preview');
  for (const file of files) {
    try {
      const dataUrl = await readImageFile(file);
      createState.slides.push(dataUrl);
      const thumb = document.createElement('img');
      thumb.src = dataUrl;
      preview.appendChild(thumb);
    } catch (err) {
      $('#create-error').textContent = err.message;
    }
  }
  $('#submit-create').disabled = createState.slides.length === 0;
  e.target.value = '';
});

$('#submit-create').addEventListener('click', async () => {
  if (!createState.slides.length) return;
  $('#submit-create').disabled = true;
  $('#create-error').textContent = '';
  try {
    await api('/api/slideshows', {
      method: 'POST',
      body: { title: $('#new-title').value, slides: createState.slides },
    });
    $('#create-modal').classList.add('hidden');
    await loadFeed();
    $('#feed').scrollTo({ top: 0 });
  } catch (err) {
    $('#create-error').textContent = err.message;
    $('#submit-create').disabled = false;
  }
});

(async function init() {
  try {
    state.user = await api('/api/me');
    await showApp();
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
