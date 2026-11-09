# main.py
# Минималистичный форум-постов на FastAPI. Всё хранится в оперативной памяти.
# Запуск:  pip install fastapi uvicorn
#          uvicorn main:app --reload

import hashlib
import re
import secrets
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="posts")

# ---------------------------------------------------------------- хранилище
USERS: dict[str, dict] = {}      # key = username.lower()
SESSIONS: dict[str, str] = {}    # token -> key
POSTS: list[dict] = []           # новые сверху
STATE = {"next_id": 1}

SESSION_MAX_AGE = 60 * 60 * 24 * 30
MAX_POSTS = 5000


# ---------------------------------------------------------------- утилиты
def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()


def current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("sid")
    if not token:
        return None
    return SESSIONS.get(token)


def start_session(response: Response, key: str) -> None:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = key
    response.set_cookie(
        "sid", token, httponly=True, samesite="lax", max_age=SESSION_MAX_AGE
    )


def find_post(post_id: int) -> dict:
    for post in POSTS:
        if post["id"] == post_id:
            return post
    raise HTTPException(404, "Пост не найден")


def serialize_post(post: dict, viewer: Optional[str]) -> dict:
    return {
        "id": post["id"],
        "title": post["title"],
        "body": post["body"],
        "author": post["author"],
        "created": post["created"],
        "likes": len(post["likes"]),
        "liked": bool(viewer and viewer in post["likes"]),
        "own": bool(viewer and viewer == post["author_key"]),
    }


# ---------------------------------------------------------------- модели
class Credentials(BaseModel):
    username: str
    password: str


class PostIn(BaseModel):
    title: str
    body: str


# ---------------------------------------------------------------- авторизация
@app.post("/api/register")
def register(data: Credentials, response: Response):
    username = data.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
        raise HTTPException(400, "Ник: 3–20 символов, латиница, цифры и _")
    if len(data.password) < 6:
        raise HTTPException(400, "Пароль минимум 6 символов")

    key = username.lower()
    if key in USERS:
        raise HTTPException(400, "Такой ник уже занят")

    salt = secrets.token_hex(16)
    USERS[key] = {
        "username": username,
        "salt": salt,
        "hash": hash_password(data.password, salt),
        "created": time.time(),
    }
    start_session(response, key)
    return {"username": username}


@app.post("/api/login")
def login(data: Credentials, response: Response):
    key = data.username.strip().lower()
    user = USERS.get(key)
    if not user:
        raise HTTPException(400, "Неверный ник или пароль")
    if not secrets.compare_digest(hash_password(data.password, user["salt"]), user["hash"]):
        raise HTTPException(400, "Неверный ник или пароль")

    start_session(response, key)
    return {"username": user["username"]}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("sid")
    if token:
        SESSIONS.pop(token, None)
    response.delete_cookie("sid")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    key = current_user(request)
    if not key:
        return {"username": None}
    return {"username": USERS[key]["username"]}


# ---------------------------------------------------------------- посты
@app.get("/api/posts")
def list_posts(request: Request):
    viewer = current_user(request)
    return {"posts": [serialize_post(post, viewer) for post in POSTS]}


@app.post("/api/posts")
def create_post(data: PostIn, request: Request):
    viewer = current_user(request)
    if not viewer:
        raise HTTPException(401, "Нужно войти")

    title = data.title.strip()
    body = data.body.strip()
    if not title or len(title) > 120:
        raise HTTPException(400, "Заголовок: от 1 до 120 символов")
    if not body or len(body) > 5000:
        raise HTTPException(400, "Текст: от 1 до 5000 символов")

    post = {
        "id": STATE["next_id"],
        "author_key": viewer,
        "author": USERS[viewer]["username"],
        "title": title,
        "body": body,
        "created": time.time(),
        "likes": set(),
    }
    STATE["next_id"] += 1
    POSTS.insert(0, post)
    if len(POSTS) > MAX_POSTS:
        POSTS.pop()

    return serialize_post(post, viewer)


@app.post("/api/posts/{post_id}/like")
def like_post(post_id: int, request: Request):
    viewer = current_user(request)
    if not viewer:
        raise HTTPException(401, "Нужно войти")

    post = find_post(post_id)
    if viewer in post["likes"]:
        post["likes"].remove(viewer)
    else:
        post["likes"].add(viewer)
    return serialize_post(post, viewer)


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, request: Request):
    viewer = current_user(request)
    if not viewer:
        raise HTTPException(401, "Нужно войти")

    post = find_post(post_id)
    if post["author_key"] != viewer:
        raise HTTPException(403, "Можно удалять только свои посты")

    POSTS.remove(post)
    return {"ok": True}


# ---------------------------------------------------------------- страница
HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>posts</title>
<style>
:root{
  --bg:#0c0c0e;
  --panel:#141417;
  --panel-2:#19191d;
  --border:#26262c;
  --text:#d8d8dc;
  --muted:#8b8b94;
  --accent:#4d7cfe;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg);
  color:var(--text);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
header{
  position:sticky;top:0;z-index:10;
  background:rgba(12,12,14,.9);
  border-bottom:1px solid var(--border);
  backdrop-filter:blur(6px);
}
header .inner{
  max-width:720px;margin:0 auto;padding:14px 20px;
  display:flex;align-items:center;justify-content:space-between;gap:12px;
}
.brand{font-weight:600;font-size:17px}
.brand .dot{color:var(--accent)}
.user-area{display:flex;align-items:center;gap:10px}
.whoami{font-size:13px;color:#c4c4cc}
.wrap{max-width:720px;margin:0 auto;padding:0 20px 80px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:20px}
.hidden{display:none}
.field{margin-bottom:10px}
.field:last-of-type{margin-bottom:12px}
input,textarea{
  width:100%;background:var(--panel-2);border:1px solid var(--border);
  color:var(--text);border-radius:6px;padding:9px 11px;font:inherit;outline:none;
}
textarea{resize:vertical;min-height:96px}
input:focus,textarea:focus{border-color:#3a4a86}
::placeholder{color:#5f5f69}
.tabs{display:flex;gap:6px;margin-bottom:14px}
.tab{background:none;border:1px solid transparent;color:var(--muted);padding:6px 10px;border-radius:6px;font:inherit;cursor:pointer}
.tab:hover{color:var(--text)}
.tab.active{background:var(--panel-2);border-color:var(--border);color:var(--text)}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.btn{background:var(--panel-2);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
.btn:hover{background:#202027}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary:hover{background:#3f6cf0}
.btn.small{padding:5px 10px;font-size:13px}
.msg{font-size:13px;color:#e08585;min-height:18px}
.post{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:12px}
.post-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.author{font-size:13px;font-weight:500;color:#a9b7ff}
.time{font-size:12px;color:#6f6f79}
.post-title{margin:0 0 8px;font-size:17px;font-weight:600;line-height:1.35;color:#ececf1}
.post-body{font-size:14.5px;color:#b9b9c2;white-space:pre-wrap;overflow-wrap:anywhere}
.post-foot{margin-top:12px}
.like{background:none;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:4px 10px;font:inherit;font-size:13px;cursor:pointer}
.like:hover{color:var(--text)}
.like.on{color:var(--accent);border-color:#33407a}
.link{background:none;border:none;padding:0;margin-left:auto;font:inherit;font-size:12px;color:#6f6f79;cursor:pointer}
.link:hover{color:#e08585}
.empty{color:var(--muted);text-align:center;padding:48px 0;font-size:14px}
</style>
</head>
<body>

<header>
  <div class="inner">
    <div class="brand">posts<span class="dot">.</span></div>
    <div class="user-area" id="userArea"></div>
  </div>
</header>

<div class="wrap">

  <section class="panel hidden" id="authPanel">
    <div class="tabs">
      <button class="tab active" id="tabLogin" type="button">Вход</button>
      <button class="tab" id="tabRegister" type="button">Регистрация</button>
    </div>
    <form id="authForm">
      <div class="field"><input id="authUsername" placeholder="ник" autocomplete="username" maxlength="20"></div>
      <div class="field"><input id="authPassword" type="password" placeholder="пароль" autocomplete="current-password" maxlength="72"></div>
      <div class="row">
        <span class="msg" id="authMsg"></span>
        <button class="btn primary" id="authSubmit" type="submit">Войти</button>
      </div>
    </form>
  </section>

  <section class="panel hidden" id="composer">
    <form id="postForm">
      <div class="field"><input id="postTitle" placeholder="Заголовок" maxlength="120"></div>
      <div class="field"><textarea id="postBody" placeholder="Текст поста" rows="4" maxlength="5000"></textarea></div>
      <div class="row">
        <span class="msg" id="postMsg"></span>
        <button class="btn primary" type="submit">Опубликовать</button>
      </div>
    </form>
  </section>

  <section id="feed"></section>

</div>

<script>
const $ = function(id){ return document.getElementById(id); };
const state = { user: null, posts: [], tab: 'login' };

function esc(s){
  return String(s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

function fmt(ts){
  const d = new Date(ts * 1000);
  const p = function(n){ return String(n).padStart(2, '0'); };
  return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + d.getFullYear() +
         ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

async function api(path, opts){
  opts = opts || {};
  const init = { method: opts.method || 'GET', credentials: 'same-origin', headers: {} };
  if (opts.body !== undefined){
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok){
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : 'Ошибка запроса');
  }
  return data;
}

function renderUser(){
  const el = $('userArea');
  if (state.user){
    el.innerHTML = '<span class="whoami">' + esc(state.user) + '</span>' +
                   '<button class="btn small" id="logoutBtn" type="button">Выйти</button>';
    $('logoutBtn').onclick = logout;
  } else {
    el.innerHTML = '<span class="whoami" style="color:#6f6f79">гость</span>';
  }
  $('authPanel').classList.toggle('hidden', !!state.user);
  $('composer').classList.toggle('hidden', !state.user);
}

function renderFeed(){
  const feed = $('feed');
  if (!state.posts.length){
    feed.innerHTML = '<div class="empty">Постов пока нет.</div>';
    return;
  }
  feed.innerHTML = state.posts.map(function(p){
    const del = p.own
      ? '<button class="link" data-del="' + p.id + '" type="button">удалить</button>'
      : '';
    return '<article class="post">' +
      '<div class="post-head">' +
        '<span class="author">' + esc(p.author) + '</span>' +
        '<span class="time">' + fmt(p.created) + '</span>' +
        del +
      '</div>' +
      '<h2 class="post-title">' + esc(p.title) + '</h2>' +
      '<div class="post-body">' + esc(p.body) + '</div>' +
      '<div class="post-foot">' +
        '<button class="like' + (p.liked ? ' on' : '') + '" data-like="' + p.id + '" type="button">' +
          '▲ <span>' + p.likes + '</span>' +
        '</button>' +
      '</div>' +
    '</article>';
  }).join('');
}

async function loadPosts(){
  try {
    const data = await api('/api/posts');
    state.posts = data.posts || [];
  } catch (e) {
    state.posts = [];
  }
  renderFeed();
}

function flashAuth(text){
  $('authMsg').textContent = text;
  $('authPanel').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function setTab(tab){
  state.tab = tab;
  $('tabLogin').classList.toggle('active', tab === 'login');
  $('tabRegister').classList.toggle('active', tab === 'register');
  $('authSubmit').textContent = tab === 'login' ? 'Войти' : 'Создать аккаунт';
  $('authPassword').setAttribute('autocomplete', tab === 'login' ? 'current-password' : 'new-password');
  $('authMsg').textContent = '';
}

async function logout(){
  try { await api('/api/logout', { method: 'POST' }); } catch (e) {}
  state.user = null;
  setTab('login');
  renderUser();
  await loadPosts();
}

$('tabLogin').onclick = function(){ setTab('login'); };
$('tabRegister').onclick = function(){ setTab('register'); };

$('authForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const username = $('authUsername').value.trim();
  const password = $('authPassword').value;
  $('authMsg').textContent = '';
  try {
    const path = state.tab === 'login' ? '/api/login' : '/api/register';
    const data = await api(path, { method: 'POST', body: { username: username, password: password } });
    state.user = data.username;
    $('authPassword').value = '';
    $('authMsg').textContent = '';
    renderUser();
    await loadPosts();
  } catch (err) {
    $('authMsg').textContent = err.message;
  }
});

$('postForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const title = $('postTitle').value.trim();
  const body = $('postBody').value.trim();
  $('postMsg').textContent = '';
  if (!title || !body){
    $('postMsg').textContent = 'Заполните заголовок и текст';
    return;
  }
  try {
    const post = await api('/api/posts', { method: 'POST', body: { title: title, body: body } });
    state.posts.unshift(post);
    $('postTitle').value = '';
    $('postBody').value = '';
    renderFeed();
    $('feed').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    $('postMsg').textContent = err.message;
  }
});

$('feed').addEventListener('click', async function(e){
  const likeBtn = e.target.closest('[data-like]');
  const delBtn = e.target.closest('[data-del]');

  if (likeBtn){
    if (!state.user){ flashAuth('Войдите, чтобы ставить отметки'); return; }
    const id = Number(likeBtn.dataset.like);
    try {
      const post = await api('/api/posts/' + id + '/like', { method: 'POST' });
      const i = state.posts.findIndex(function(x){ return x.id === id; });
      if (i >= 0) state.posts[i] = post;
      renderFeed();
    } catch (err) {
      flashAuth(err.message);
    }
    return;
  }

  if (delBtn){
    const id = Number(delBtn.dataset.del);
    if (!confirm('Удалить пост?')) return;
    try {
      await api('/api/posts/' + id, { method: 'DELETE' });
      state.posts = state.posts.filter(function(x){ return x.id !== id; });
      renderFeed();
    } catch (err) {
      alert(err.message);
    }
  }
});

async function init(){
  try {
    const me = await api('/api/me');
    state.user = me.username || null;
  } catch (e) {
    state.user = null;
  }
  setTab('login');
  renderUser();
  await loadPosts();
}

init();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
