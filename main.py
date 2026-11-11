# main.py
# Запуск:  pip install fastapi uvicorn python-multipart
#          uvicorn main:app --reload
# Открой:  http://127.0.0.1:8000

import uuid
from datetime import datetime
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel


app = FastAPI(title="Tenor Articles")

# ---------- ХРАНИЛИЩЕ В ОПЕРАТИВКЕ ----------
ARTICLES: dict = {}          # id -> статья
IMAGES: dict = {}            # id -> (bytes, mime)


# ---------- МОДЕЛИ ----------
class Block(BaseModel):
    type: str                # 'p' | 'h3' | 'h4' | 'quote' | 'img' | 'hr'
    content: str = ""
    caption: str = ""


class ArticleIn(BaseModel):
    title: str
    author: str = ""
    blocks: List[Block] = []


def _blk(b: Block) -> dict:
    try:
        return b.model_dump()
    except AttributeError:
        return b.dict()


# ---------- API ----------
@app.post("/api/articles")
async def create_article(a: ArticleIn):
    aid = uuid.uuid4().hex[:10]
    now = datetime.utcnow().isoformat()
    ARTICLES[aid] = {
        "id": aid,
        "title": a.title,
        "author": a.author,
        "blocks": [_blk(b) for b in a.blocks],
        "created_at": now,
        "updated_at": now,
    }
    return ARTICLES[aid]


@app.put("/api/articles/{aid}")
async def update_article(aid: str, a: ArticleIn):
    if aid not in ARTICLES:
        raise HTTPException(404, "not found")
    ARTICLES[aid].update(
        {
            "title": a.title,
            "author": a.author,
            "blocks": [_blk(b) for b in a.blocks],
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    return ARTICLES[aid]


@app.get("/api/articles")
async def list_articles():
    return list(ARTICLES.values())


@app.get("/api/articles/{aid}")
async def get_article(aid: str):
    if aid not in ARTICLES:
        raise HTTPException(404, "not found")
    return ARTICLES[aid]


@app.delete("/api/articles/{aid}")
async def delete_article(aid: str):
    ARTICLES.pop(aid, None)
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "too large (max 12MB)")
    iid = uuid.uuid4().hex[:12]
    IMAGES[iid] = (data, file.content_type or "application/octet-stream")
    return {"id": iid, "url": f"/images/{iid}"}


@app.get("/images/{iid}")
async def get_image(iid: str):
    if iid not in IMAGES:
        raise HTTPException(404)
    data, mime = IMAGES[iid]
    return Response(content=data, media_type=mime)


# ---------- ФРОНТЕНД ----------
HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Статьи · Tenor</title>
<style>
:root{
  --bg:#0a0e14;
  --bg-2:#0f141b;
  --surface:#151b24;
  --surface-2:#1c2331;
  --hover:#232b3a;
  --border:#232c3b;
  --text:#eaf0fa;
  --text-2:#8a97aa;
  --text-3:#4a5567;
  --accent:#2e8bff;
  --accent-2:#4a9cff;
  --accent-dim:rgba(46,139,255,0.15);
  --danger:#ff4d5e;
  --shadow:0 4px 24px rgba(0,0,0,0.4);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  background:#0a0e14;
  background-image:
    radial-gradient(circle at 15% 0%, #14213a 0%, transparent 45%),
    radial-gradient(circle at 90% 100%, #101c33 0%, transparent 40%);
  background-attachment:fixed;
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
  min-height:100vh;
}
a{color:inherit;text-decoration:none}
button{font-family:inherit}

/* ---------- HEADER ---------- */
.header{
  position:sticky;top:0;z-index:100;
  height:60px;padding:0 28px;
  display:flex;align-items:center;justify-content:space-between;
  background:rgba(10,14,20,0.82);
  -webkit-backdrop-filter:blur(16px);
  backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);
}
.logo{
  display:flex;align-items:center;gap:10px;
  font-weight:700;font-size:19px;letter-spacing:-0.4px;
}
.logo svg{filter:drop-shadow(0 0 10px rgba(46,139,255,0.5))}
.header-actions{display:flex;gap:10px;align-items:center}

/* ---------- BUTTONS ---------- */
.btn{
  display:inline-flex;align-items:center;gap:8px;
  padding:9px 18px;border-radius:999px;
  font-size:14px;font-weight:600;
  cursor:pointer;border:none;
  transition:all .15s ease;white-space:nowrap;
  line-height:1.2;
}
.btn-primary{
  background:linear-gradient(135deg,#3d94ff,#1e6fdb);
  color:#fff;
  box-shadow:0 2px 14px rgba(46,139,255,0.35);
}
.btn-primary:hover{
  background:linear-gradient(135deg,#5aa5ff,#2a7be8);
  box-shadow:0 4px 20px rgba(46,139,255,0.5);
  transform:translateY(-1px);
}
.btn-ghost{
  background:transparent;color:var(--text-2);
  border:1px solid var(--border);
}
.btn-ghost:hover{background:var(--surface);color:var(--text);border-color:#33405a}
.btn-danger{
  background:transparent;color:var(--danger);
  border:1px solid rgba(255,77,94,0.25);
}
.btn-danger:hover{background:rgba(255,77,94,0.1);border-color:var(--danger)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}

/* ---------- CONTAINER / HOME ---------- */
.container{max-width:1280px;margin:0 auto;padding:32px 28px 80px}
.page-header{margin-bottom:28px}
.page-title{
  font-size:32px;font-weight:800;letter-spacing:-0.6px;
  background:linear-gradient(135deg,#eaf0fa 20%,#8ab8ff);
  -webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;
}
.page-sub{color:var(--text-2);font-size:14px;margin-top:6px}

.articles-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:20px;
}
.card{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:14px;overflow:hidden;
  cursor:pointer;transition:all .2s ease;
  display:flex;flex-direction:column;
}
.card:hover{
  transform:translateY(-3px);
  border-color:rgba(46,139,255,0.5);
  box-shadow:0 10px 32px rgba(46,139,255,0.14);
}
.card-thumb{
  aspect-ratio:16/9;
  background:linear-gradient(135deg,#17243d,#0e1828);
  display:flex;align-items:center;justify-content:center;
  font-size:56px;font-weight:800;color:rgba(46,139,255,0.35);
  overflow:hidden;
}
.card-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;flex:1}
.card-title{
  font-weight:700;font-size:16px;line-height:1.35;color:var(--text);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;
}
.card-meta{
  display:flex;align-items:center;gap:6px;
  font-size:13px;color:var(--text-2);margin-top:auto;
}
.card-author{color:var(--accent-2);font-weight:600}

.empty-state{text-align:center;padding:80px 20px;color:var(--text-2)}
.empty-state svg{color:var(--accent);opacity:.5;margin-bottom:20px}
.empty-state h2{color:var(--text);margin-bottom:8px;font-size:22px}
.empty-state p{margin-bottom:24px}

/* ---------- VIEW ---------- */
.view-wrap{max-width:800px;margin:0 auto;padding:24px 28px 80px}
.view-actions{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;gap:10px;flex-wrap:wrap}
.view-actions .right{display:flex;gap:10px}
.article-title{
  font-size:44px;font-weight:800;letter-spacing:-1.2px;line-height:1.15;
  margin-bottom:16px;
  background:linear-gradient(135deg,#f0f4fa 30%,#a6ccff);
  -webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;
}
.article-author{color:var(--accent-2);font-weight:600;font-size:15px}
.article-date{color:var(--text-2);font-size:13px;margin-top:4px;margin-bottom:36px}
.article-body{font-size:17px;line-height:1.75;color:#cdd7e5}
.article-body h3{
  font-size:27px;font-weight:700;margin:40px 0 14px;color:var(--text);
  letter-spacing:-0.4px;line-height:1.25;
}
.article-body h4{
  font-size:21px;font-weight:700;margin:30px 0 12px;color:var(--text);
  line-height:1.35;
}
.article-body p{margin:0 0 18px}
.article-body blockquote{
  border-left:3px solid var(--accent);
  padding:8px 0 8px 20px;margin:24px 0;
  color:#b8c4d6;font-style:italic;font-size:18px;
}
.article-body img{max-width:100%;border-radius:12px;margin:20px 0;display:block}
.article-body figure{margin:28px 0}
.article-body figcaption{color:var(--text-2);font-size:14px;text-align:center;margin-top:10px}
.article-body hr{border:none;border-top:1px solid var(--border);margin:36px 0}

/* ---------- EDITOR ---------- */
.editor-wrap{max-width:800px;margin:0 auto;padding:0 28px 80px}
.editor-toolbar{
  position:sticky;top:72px;z-index:50;
  display:flex;gap:6px;align-items:center;
  padding:8px;margin-bottom:20px;
  background:rgba(21,27,36,0.92);
  -webkit-backdrop-filter:blur(16px);
  backdrop-filter:blur(16px);
  border:1px solid var(--border);
  border-radius:14px;
  box-shadow:0 6px 28px rgba(0,0,0,0.45);
  width:fit-content;
  margin-left:auto;margin-right:auto;
  overflow-x:auto;
  scrollbar-width:none;
}
.editor-toolbar::-webkit-scrollbar{display:none}
.tool-btn{
  display:inline-flex;align-items:center;justify-content:center;
  min-width:38px;height:38px;padding:0 10px;
  background:var(--surface-2);
  border:1px solid transparent;
  border-radius:9px;
  color:#b5c2d4;cursor:pointer;
  font-size:13px;font-weight:700;
  transition:all .15s ease;
  flex-shrink:0;
}
.tool-btn:hover{background:var(--accent-dim);color:var(--accent-2);border-color:rgba(46,139,255,.35)}
.tool-btn svg{width:18px;height:18px}

.title-input{
  width:100%;background:transparent;border:none;
  font-size:46px;font-weight:800;letter-spacing:-1.2px;
  color:var(--text);padding:24px 0 8px;
  outline:none;line-height:1.15;
}
.title-input::placeholder{color:var(--text-3)}
.author-input{
  width:100%;background:transparent;border:none;
  font-size:15px;color:var(--accent-2);
  padding:4px 0 24px;outline:none;font-weight:600;
}
.author-input::placeholder{color:var(--text-3);font-weight:400}

.blocks{min-height:320px;padding:8px 0}
.block{position:relative;padding:4px 0;transition:background .1s}
.block-content{
  outline:none;min-height:1.7em;
  padding:8px 44px 8px 0;
  font-size:17px;line-height:1.75;color:#cdd7e5;
  word-wrap:break-word;
}
.block-content:empty::before{
  content:attr(data-placeholder);
  color:var(--text-3);
  pointer-events:none;
}
.block[data-type="h3"] .block-content{
  font-size:27px;font-weight:700;color:var(--text);
  line-height:1.25;letter-spacing:-0.4px;
  margin-top:24px;padding-top:8px;
}
.block[data-type="h4"] .block-content{
  font-size:21px;font-weight:700;color:var(--text);
  line-height:1.35;margin-top:14px;
}
.block[data-type="quote"] .block-content{
  border-left:3px solid var(--accent);
  padding-left:20px;color:#b8c4d6;
  font-style:italic;font-size:18px;
}
.block[data-type="hr"]{padding:18px 0}
.block[data-type="hr"] hr{
  border:none;border-top:1px solid #2a3545;
}
.block-img{
  max-width:100%;border-radius:12px;display:block;margin:8px 0;
}
.block-caption{
  font-size:14px;color:var(--text-2);
  text-align:center;padding:8px 40px 8px 0;outline:none;
}
.block-caption:empty::before{
  content:attr(data-placeholder);color:var(--text-3);
}
.block-remove{
  position:absolute;right:0;top:8px;
  width:30px;height:30px;border-radius:8px;
  background:transparent;border:1px solid transparent;
  color:var(--text-3);cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  opacity:0;transition:all .15s ease;
}
.block:hover .block-remove{opacity:1}
.block-remove:hover{
  background:rgba(255,77,94,.12);color:var(--danger);
  border-color:rgba(255,77,94,.3);
}
.block[data-type="hr"] .block-remove{top:14px}

.editor-footer{
  display:flex;justify-content:flex-end;gap:12px;
  padding-top:32px;margin-top:24px;
  border-top:1px solid var(--border);
}

.spinner{
  width:16px;height:16px;border-radius:50%;
  border:2px solid rgba(255,255,255,.35);
  border-top-color:#fff;
  animation:spin .7s linear infinite;
  display:inline-block;
}
@keyframes spin{to{transform:rotate(360deg)}}

@media (max-width:640px){
  .header{padding:0 16px}
  .container{padding:20px 16px 60px}
  .view-wrap{padding:16px 16px 60px}
  .editor-wrap{padding:0 16px 60px}
  .title-input{font-size:34px}
  .article-title{font-size:32px}
  .article-body{font-size:16px}
  .page-title{font-size:26px}
}
</style>
</head>
<body>

<header class="header">
  <a href="#/" class="logo">
    <svg width="30" height="30" viewBox="0 0 24 24">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#4a9cff"/>
          <stop offset="100%" stop-color="#1e6fdb"/>
        </linearGradient>
      </defs>
      <rect x="2" y="5" width="20" height="14" rx="4" fill="url(#lg)"/>
      <path d="M10 9l5.5 3-5.5 3V9z" fill="#fff"/>
    </svg>
    <span>Статьи</span>
  </a>
  <div class="header-actions">
    <a href="#/editor" class="btn btn-primary">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round">
        <path d="M12 5v14M5 12h14"/>
      </svg>
      Создать
    </a>
  </div>
</header>

<div id="app"></div>

<script>
/* =========================================================
   UTILS
========================================================= */
const app = document.getElementById('app');

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day:'numeric', month:'long', year:'numeric' });
}

function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text() || res.statusText);
  return res.json();
}

/* =========================================================
   HOME
========================================================= */
async function showHome() {
  let articles = [];
  try {
    articles = await api('/api/articles');
  } catch (e) {
    app.innerHTML = '<div class="container"><div class="empty-state"><h2>Ошибка загрузки</h2></div></div>';
    return;
  }
  articles.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));

  let html = `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">Все статьи</h1>
        <div class="page-sub">${articles.length} ${plural(articles.length,'статья','статьи','статей')}</div>
      </div>`;

  if (articles.length === 0) {
    html += `
      <div class="empty-state">
        <svg width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/>
        </svg>
        <h2>Пока нет статей</h2>
        <p>Создайте первую статью — это займёт минуту</p>
        <a href="#/editor" class="btn btn-primary">Создать статью</a>
      </div>`;
  } else {
    html += '<div class="articles-grid">';
    for (const a of articles) {
      const thumbImg = (a.blocks || []).find(b => b.type === 'img');
      const thumbInner = thumbImg
        ? `<img src="${escapeHtml(thumbImg.content)}" alt="">`
        : escapeHtml((a.title || '?').trim().charAt(0).toUpperCase());
      html += `
        <div class="card" data-id="${a.id}">
          <div class="card-thumb">${thumbInner}</div>
          <div class="card-body">
            <div class="card-title">${escapeHtml(a.title)}</div>
            <div class="card-meta">
              ${a.author ? `<span class="card-author">${escapeHtml(a.author)}</span><span>·</span>` : ''}
              <span>${formatDate(a.created_at)}</span>
            </div>
          </div>
        </div>`;
    }
    html += '</div>';
  }
  html += '</div>';
  app.innerHTML = html;

  document.querySelectorAll('.card').forEach(el => {
    el.onclick = () => { location.hash = '#/view/' + el.dataset.id; };
  });
}

/* =========================================================
   VIEW
========================================================= */
async function showView(id) {
  let a;
  try {
    a = await api('/api/articles/' + id);
  } catch (e) {
    app.innerHTML = `
      <div class="view-wrap">
        <div class="empty-state">
          <h2>Статья не найдена</h2>
          <p>Возможно, её удалили</p>
          <a href="#/" class="btn btn-primary">На главную</a>
        </div>
      </div>`;
    return;
  }

  const edited = a.updated_at && a.updated_at !== a.created_at;
  let body = '';
  for (const b of a.blocks || []) {
    if (b.type === 'h3') body += `<h3>${b.content}</h3>`;
    else if (b.type === 'h4') body += `<h4>${b.content}</h4>`;
    else if (b.type === 'p') body += `<p>${b.content}</p>`;
    else if (b.type === 'quote') body += `<blockquote>${b.content}</blockquote>`;
    else if (b.type === 'hr') body += `<hr>`;
    else if (b.type === 'img') {
      body += `<figure>
        <img src="${escapeHtml(b.content)}" alt="">
        ${b.caption ? `<figcaption>${escapeHtml(b.caption)}</figcaption>` : ''}
      </figure>`;
    }
  }

  app.innerHTML = `
    <div class="view-wrap">
      <div class="view-actions">
        <a href="#/" class="btn btn-ghost">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
          Назад
        </a>
        <div class="right">
          <a href="#/editor/${a.id}" class="btn btn-ghost">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/>
            </svg>
            Редактировать
          </a>
          <button class="btn btn-danger" id="del-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
            </svg>
            Удалить
          </button>
        </div>
      </div>
      <article>
        <h1 class="article-title">${escapeHtml(a.title)}</h1>
        ${a.author ? `<div class="article-author">${escapeHtml(a.author)}</div>` : ''}
        <div class="article-date">
          ${formatDate(a.created_at)}
          ${edited ? ' · обновлено ' + formatDate(a.updated_at) : ''}
        </div>
        <div class="article-body">${body || '<p style="color:var(--text-2)"><em>Статья пустая</em></p>'}</div>
      </article>
    </div>`;

  document.getElementById('del-btn').onclick = async () => {
    if (!confirm('Удалить эту статью?')) return;
    try { await api('/api/articles/' + a.id, { method: 'DELETE' }); } catch (e) {}
    location.hash = '#/';
  };
}

/* =========================================================
   EDITOR
========================================================= */
async function showEditor(id) {
  let article = null;
  if (id) {
    try { article = await api('/api/articles/' + id); }
    catch (e) { location.hash = '#/'; return; }
  }

  app.innerHTML = `
    <div class="editor-wrap">
      <div class="editor-toolbar" id="toolbar">
        <button class="tool-btn" type="button" data-type="h3" title="Заголовок">H3</button>
        <button class="tool-btn" type="button" data-type="h4" title="Подзаголовок">H4</button>
        <button class="tool-btn" type="button" data-type="p" title="Текст">¶</button>
        <button class="tool-btn" type="button" data-type="quote" title="Цитата">❝</button>
        <button class="tool-btn" type="button" data-type="hr" title="Разделитель">—</button>
        <button class="tool-btn" type="button" data-type="img" title="Изображение">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <circle cx="9" cy="9" r="1.5"/>
            <path d="M21 15l-5-5L5 21"/>
          </svg>
        </button>
      </div>

      <input class="title-input" id="title-input" placeholder="Заголовок" value="${article ? escapeHtml(article.title) : ''}">
      <input class="author-input" id="author-input" placeholder="Автор" value="${article && article.author ? escapeHtml(article.author) : ''}">

      <div class="blocks" id="blocks"></div>

      <div class="editor-footer">
        <a href="${article ? '#/view/' + article.id : '#/'}" class="btn btn-ghost">Отмена</a>
        <button class="btn btn-primary" id="save-btn" type="button">
          ${article ? 'Сохранить' : 'Опубликовать'}
        </button>
      </div>
    </div>`;

  // populate blocks
  const blocksContainer = document.getElementById('blocks');
  if (article && article.blocks && article.blocks.length) {
    article.blocks.forEach(b => blocksContainer.appendChild(createBlockEl(b)));
  } else {
    blocksContainer.appendChild(createBlockEl({ type:'p', content:'', caption:'' }));
  }

  // toolbar
  document.querySelectorAll('.tool-btn').forEach(btn => {
    btn.onclick = () => handleToolClick(btn.dataset.type);
  });

  // title/author Enter -> focus first block
  ['title-input','author-input'].forEach(inpId => {
    document.getElementById(inpId).addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const first = blocksContainer.querySelector('[contenteditable]');
        if (first) first.focus();
      }
    });
  });

  // save
  const saveBtn = document.getElementById('save-btn');
  saveBtn.onclick = async () => {
    const title = document.getElementById('title-input').value.trim();
    if (!title) {
      document.getElementById('title-input').focus();
      return;
    }
    const author = document.getElementById('author-input').value.trim();
    const blocks = [];
    blocksContainer.querySelectorAll('.block').forEach(el => {
      const type = el.dataset.type;
      if (type === 'hr') {
        blocks.push({ type:'hr', content:'', caption:'' });
      } else if (type === 'img') {
        const img = el.querySelector('img');
        const cap = el.querySelector('.block-caption');
        blocks.push({ type:'img', content: img.getAttribute('src') || '', caption: (cap.textContent || '').trim() });
      } else {
        const ce = el.querySelector('.block-content');
        if (!ce) return;
        const text = (ce.textContent || '').trim();
        if (text || ce.innerHTML.trim()) {
          blocks.push({ type, content: ce.innerHTML, caption:'' });
        }
      }
    });

    saveBtn.disabled = true;
    const orig = saveBtn.innerHTML;
    saveBtn.innerHTML = '<span class="spinner"></span> Сохранение';
    try {
      const payload = { title, author, blocks };
      const opts = {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type':'application/json' },
        body: JSON.stringify(payload)
      };
      const saved = await api(id ? '/api/articles/' + id : '/api/articles', opts);
      location.hash = '#/view/' + saved.id;
    } catch (err) {
      alert('Ошибка сохранения: ' + err.message);
      saveBtn.disabled = false;
      saveBtn.innerHTML = orig;
    }
  };

  if (!id) setTimeout(() => document.getElementById('title-input').focus(), 30);
}

/* =========================================================
   BLOCK HELPERS
========================================================= */
const PLACEHOLDERS = {
  h3:'Подзаголовок',
  h4:'Меньший подзаголовок',
  p:'Текст…',
  quote:'Цитата'
};

const REMOVE_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>';

function createBlockEl(data) {
  const el = document.createElement('div');
  el.className = 'block';
  el.dataset.type = data.type;

  if (data.type === 'img') {
    el.innerHTML = `
      <img src="${escapeHtml(data.content || '')}" class="block-img" alt="">
      <div class="block-caption" contenteditable="true" data-placeholder="Подпись к изображению">${escapeHtml(data.caption || '')}</div>
      <button class="block-remove" type="button" title="Удалить">${REMOVE_SVG}</button>`;
  } else if (data.type === 'hr') {
    el.innerHTML = `
      <hr>
      <button class="block-remove" type="button" title="Удалить">${REMOVE_SVG}</button>`;
  } else {
    const ph = PLACEHOLDERS[data.type] || 'Текст…';
    el.innerHTML = `
      <div class="block-content" contenteditable="true" data-placeholder="${ph}">${data.content || ''}</div>
      <button class="block-remove" type="button" title="Удалить">${REMOVE_SVG}</button>`;
  }

  el.querySelector('.block-remove').onclick = () => {
    el.remove();
    ensureAtLeastOneBlock();
  };

  const ce = el.querySelector('[contenteditable]');
  if (ce) {
    ce.addEventListener('keydown', e => onBlockKeydown(e, el));
    ce.addEventListener('paste', e => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text);
    });
  }

  return el;
}

function insertBlock(data) {
  const container = document.getElementById('blocks');
  if (!container) return;
  const focused = document.activeElement ? document.activeElement.closest('.block') : null;
  const el = createBlockEl(data);
  if (focused && focused.parentElement === container) {
    focused.after(el);
  } else {
    container.appendChild(el);
  }
  const ce = el.querySelector('[contenteditable]');
  if (ce) {
    ce.focus();
    const r = document.createRange();
    r.selectNodeContents(ce);
    r.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }
}

function ensureAtLeastOneBlock() {
  const container = document.getElementById('blocks');
  if (!container) return;
  if (!container.querySelector('.block')) {
    container.appendChild(createBlockEl({ type:'p', content:'', caption:'' }));
  }
}

function onBlockKeydown(e, blockEl) {
  const ce = e.target.closest('[contenteditable]');
  if (!ce) return;

  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const range = sel.getRangeAt(0);

    // split: extract content after caret
    const afterRange = document.createRange();
    afterRange.setStart(range.endContainer, range.endOffset);
    afterRange.setEnd(ce, ce.childNodes.length);
    const fragment = afterRange.extractContents();

    const newEl = createBlockEl({ type:'p', content:'', caption:'' });
    const newCe = newEl.querySelector('[contenteditable]');
    newCe.appendChild(fragment);
    blockEl.after(newEl);

    const r = document.createRange();
    r.setStart(newCe, 0);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    return;
  }

  if (e.key === 'Backspace') {
    const hasContent = (ce.textContent || '').trim().length > 0;
    if (!hasContent) {
      const sel = window.getSelection();
      if (sel.rangeCount > 0 && sel.getRangeAt(0).collapsed) {
        e.preventDefault();
        const prev = blockEl.previousElementSibling;
        blockEl.remove();
        if (prev) {
          const prevCe = prev.querySelector('[contenteditable]');
          if (prevCe) {
            prevCe.focus();
            const r = document.createRange();
            r.selectNodeContents(prevCe);
            r.collapse(false);
            sel.removeAllRanges();
            sel.addRange(r);
          }
        }
        ensureAtLeastOneBlock();
      }
    }
  }
}

/* =========================================================
   TOOLBAR ACTIONS
========================================================= */
function handleToolClick(type) {
  if (type === 'img') {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      if (!file.type.startsWith('image/')) {
        alert('Можно загружать только изображения');
        return;
      }
      const fd = new FormData();
      fd.append('file', file);
      try {
        const res = await fetch('/api/upload', { method:'POST', body: fd });
        if (!res.ok) throw new Error('upload failed');
        const data = await res.json();
        insertBlock({ type:'img', content: data.url, caption:'' });
      } catch (err) {
        alert('Не удалось загрузить изображение');
      }
    };
    input.click();
    return;
  }
  insertBlock({ type, content:'', caption:'' });
}

/* =========================================================
   ROUTER
========================================================= */
function router() {
  window.scrollTo(0, 0);
  const path = (location.hash || '#/').slice(1) || '/';
  const parts = path.split('/').filter(Boolean);

  if (parts[0] === 'editor') {
    showEditor(parts[1]);
  } else if (parts[0] === 'view') {
    showView(parts[1]);
  } else {
    showHome();
  }
}

window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', () => {
  if (!location.hash) location.hash = '#/';
  else router();
});
if (document.readyState === 'complete' || document.readyState === 'interactive') {
  if (!location.hash) location.hash = '#/';
  else router();
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
