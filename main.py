"""
MiniDiscord — минималистичный мессенджер на FastAPI + WebSocket.

Особенности:
  • Всё состояние сервера — в оперативке (nickname -> channel).
  • Сообщения НЕ хранятся на сервере: они копятся в браузере клиента
    (по каналам) и просто транслируются в реальном времени.
  • Вход по нику, список каналов, участники, чат.

Запуск:
  pip install fastapi uvicorn
  python -m uvicorn main:app --reload
  Открыть http://127.0.0.1:8000
"""
import time
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI(title="MiniDiscord")

CHANNELS: List[str] = ["general", "random", "tech", "offtopic"]

# Единственное серверное состояние, живущее в оперативке:
#   nickname -> {"channel": str}
users: Dict[str, dict] = {}


class Manager:
    """Управляет WebSocket-подключениями и рассылкой."""

    def __init__(self) -> None:
        # ws -> {"nickname": str, "channel": str}
        self.active: Dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, nickname: str, channel: str) -> None:
        self.active[ws] = {"nickname": nickname, "channel": channel}
        users[nickname] = {"channel": channel}
        await self.broadcast_system(channel, f"{nickname} вошёл в чат")
        await self.broadcast_userlist(channel)

    async def disconnect(self, ws: WebSocket) -> None:
        info = self.active.pop(ws, None)
        if not info:
            return
        users.pop(info["nickname"], None)
        await self.broadcast_system(info["channel"], f"{info['nickname']} покинул чат")
        await self.broadcast_userlist(info["channel"])

    async def broadcast_channel(self, channel: str, payload: dict) -> None:
        """Шлём всем, кто сейчас в канале, добавляя поле channel
        (чтобы клиент корректно маршрутизировал сообщения)."""
        for ws, info in list(self.active.items()):
            if info["channel"] != channel:
                continue
            try:
                await ws.send_json({**payload, "channel": channel})
            except Exception:
                pass

    async def broadcast_system(self, channel: str, text: str) -> None:
        await self.broadcast_channel(channel, {"type": "system", "text": text})

    async def broadcast_userlist(self, channel: str) -> None:
        names = [i["nickname"] for i in self.active.values() if i["channel"] == channel]
        await self.broadcast_channel(channel, {"type": "users", "users": names})


manager = Manager()


# ──────────────────────────────────────────────────────────────────────
#  REST-эндпоинты
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/channels")
async def get_channels() -> List[str]:
    return CHANNELS


@app.get("/api/users")
async def get_users() -> List[str]:
    return list(users.keys())


# ──────────────────────────────────────────────────────────────────────
#  WebSocket
# ──────────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, nickname: str = "", channel: str = "general"):
    # ВАЖНО: сначала accept(), потом уже можно закрывать/слать что-либо.
    await ws.accept()

    nickname = nickname.strip()[:32]
    if not nickname or nickname in users:
        await ws.close(code=4000)  # ник занят / пустой
        return
    if channel not in CHANNELS:
        channel = CHANNELS[0]

    await manager.connect(ws, nickname, channel)
    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")

            if mtype == "message":
                text = (data.get("text") or "").strip()
                if not text:
                    continue
                await manager.broadcast_channel(
                    channel,
                    {
                        "type": "message",
                        "user": nickname,
                        "text": text[:2000],
                        "ts": time.time(),
                    },
                )

            elif mtype == "switch":
                new_ch = data.get("channel")
                if new_ch in CHANNELS and new_ch != channel:
                    old_ch = channel
                    channel = new_ch
                    manager.active[ws]["channel"] = new_ch
                    users[nickname]["channel"] = new_ch
                    await manager.broadcast_system(old_ch, f"{nickname} покинул чат")
                    await manager.broadcast_userlist(old_ch)
                    await manager.broadcast_system(new_ch, f"{nickname} вошёл в чат")
                    await manager.broadcast_userlist(new_ch)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)


# ──────────────────────────────────────────────────────────────────────
#  Встроенный клиент (одна страница, тёмная тема в стиле Discord)
# ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MiniDiscord</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #36393f;
    color: #dcddde;
    overflow: hidden;
  }

  /* ── Login ─────────────────────────────────────────── */
  #login {
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    background: radial-gradient(circle at 50% 20%, #40444b 0%, #2f3136 70%);
  }
  #login h1 { color: #fff; font-size: 40px; letter-spacing: 1px; margin-bottom: 4px; }
  #login .subtitle { color: #96989d; font-size: 14px; margin-bottom: 16px; text-align: center; max-width: 340px; }
  #login input {
    width: 320px; padding: 12px 16px; font-size: 15px;
    background: #202225; border: 1px solid #202225; border-radius: 6px;
    color: #dcddde; outline: none; transition: border-color .15s;
  }
  #login input:focus { border-color: #5865f2; }
  #login button {
    width: 320px; padding: 12px; font-size: 15px; font-weight: 600;
    background: #5865f2; color: #fff; border: none; border-radius: 6px;
    cursor: pointer; transition: background .15s;
  }
  #login button:hover { background: #4752c4; }
  #err { color: #ed4245; min-height: 20px; font-size: 14px; }

  /* ── App layout ────────────────────────────────────── */
  #app { display: none; height: 100vh; }
  #app.visible { display: flex; }

  #sidebar {
    width: 260px; flex-shrink: 0; background: #2f3136;
    display: flex; flex-direction: column;
  }
  #server-name {
    padding: 16px; font-weight: 700; color: #fff; font-size: 15px;
    border-bottom: 1px solid #202225; letter-spacing: .3px;
  }
  #channels { flex: 1; overflow-y: auto; padding: 8px; }
  .channel {
    padding: 8px 12px; border-radius: 4px; cursor: pointer;
    color: #96989d; font-size: 15px; user-select: none;
    transition: background .1s, color .1s;
  }
  .channel::before { content: "#  "; color: #72767d; }
  .channel:hover { background: #393c43; color: #dcddde; }
  .channel.active { background: #393c43; color: #fff; }

  #users-header {
    padding: 12px 16px 6px; color: #96989d;
    font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
    font-weight: 700; border-top: 1px solid #202225;
  }
  #user-list { max-height: 45%; overflow-y: auto; padding: 0 8px 12px; }
  .user-row {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 8px; border-radius: 4px; font-size: 14px;
  }
  .user-row:hover { background: #393c43; }
  .avatar-small {
    width: 28px; height: 28px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; color: #fff; font-size: 12px; flex-shrink: 0;
  }

  /* ── Main chat ─────────────────────────────────────── */
  #main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #header {
    padding: 14px 20px; border-bottom: 1px solid #202225;
    display: flex; align-items: center; justify-content: space-between;
    flex-shrink: 0;
  }
  #channel-name { font-weight: 700; color: #fff; font-size: 16px; }
  #conn-status { font-size: 12px; color: #72767d; }
  #conn-status.online { color: #3ba55d; }
  #conn-status.online::before { content: "●  "; }

  #messages { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .msg {
    display: flex; gap: 12px; padding: 4px 8px; margin: 0 -8px 4px;
    border-radius: 4px;
  }
  .msg:hover { background: #32353b; }
  .avatar {
    width: 40px; height: 40px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; color: #fff; font-size: 14px; flex-shrink: 0;
  }
  .msg-body { flex: 1; min-width: 0; }
  .msg-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 2px; }
  .msg-user { font-weight: 600; color: #fff; font-size: 15px; }
  .msg-time { color: #72767d; font-size: 11px; }
  .msg-text {
    color: #dcddde; font-size: 15px; line-height: 1.45;
    word-wrap: break-word; white-space: pre-wrap;
  }
  .system {
    color: #72767d; font-style: italic; font-size: 13px;
    text-align: center; padding: 6px 0;
  }

  #input-area { padding: 0 20px 20px; flex-shrink: 0; }
  #input-wrap {
    background: #40444b; border-radius: 8px;
    display: flex; align-items: center; padding: 0 8px;
  }
  #msg-input {
    flex: 1; background: transparent; border: none; outline: none;
    color: #dcddde; font-size: 15px; padding: 14px 10px;
    font-family: inherit;
  }
  #msg-input::placeholder { color: #72767d; }
  #send {
    background: none; border: none; color: #b9bbbe;
    cursor: pointer; font-size: 20px; padding: 8px 12px;
    transition: color .15s;
  }
  #send:hover { color: #fff; }

  /* scrollbars */
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: #202225; border-radius: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
</style>
</head>
<body>

<!-- Логин -->
<div id="login">
  <h1>MiniDiscord</h1>
  <div class="subtitle">Войдите по нику — сообщения хранятся только у вас в браузере</div>
  <input id="nick" placeholder="Ваш ник" maxlength="32" autocomplete="off" autofocus>
  <button id="enter">Войти</button>
  <div id="err"></div>
</div>

<!-- Приложение -->
<div id="app">
  <aside id="sidebar">
    <div id="server-name">MiniDiscord</div>
    <div id="channels"></div>
    <div id="users-header">В сети</div>
    <div id="user-list"></div>
  </aside>
  <main id="main">
    <header id="header">
      <div id="channel-name">#general</div>
      <div id="conn-status">подключение…</div>
    </header>
    <div id="messages"></div>
    <div id="input-area">
      <div id="input-wrap">
        <input id="msg-input" placeholder="Написать сообщение…" maxlength="2000" autocomplete="off">
        <button id="send" title="Отправить">➤</button>
      </div>
    </div>
  </main>
</div>

<script>
/* ─────────── Состояние клиента ─────────── */
let nickname = "";
let currentChannel = "general";
let channels = [];
let localMessages = {};   // {channel: [ {type, user, text, ts} ]}
let ws = null;
let shouldReconnect = false;

/* ─────────── Утилиты ─────────── */
function colorFor(name) {
  const palette = ["#5865f2","#3ba55d","#ed4245","#faa61a",
                   "#eb459e","#00b0f4","#9b59b6","#e67e22"];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  return palette[Math.abs(h) % palette.length];
}
function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString("ru-RU",
    { hour: "2-digit", minute: "2-digit" });
}

/* ─────────── Сборка DOM сообщения ─────────── */
function buildMessageEl(msg) {
  if (msg.type === "system") {
    const d = document.createElement("div");
    d.className = "system";
    d.textContent = msg.text;
    return d;
  }
  const el = document.createElement("div");
  el.className = "msg";

  const av = document.createElement("div");
  av.className = "avatar";
  av.style.background = colorFor(msg.user);
  av.textContent = (msg.user || "?")[0].toUpperCase();

  const body = document.createElement("div");
  body.className = "msg-body";

  const head = document.createElement("div");
  head.className = "msg-head";
  const u = document.createElement("span");
  u.className = "msg-user"; u.textContent = msg.user;
  const t = document.createElement("span");
  t.className = "msg-time"; t.textContent = fmtTime(msg.ts);
  head.append(u, t);

  const txt = document.createElement("div");
  txt.className = "msg-text"; txt.textContent = msg.text;

  body.append(head, txt);
  el.append(av, body);
  return el;
}

function appendMessageEl(msg) {
  const box = document.getElementById("messages");
  box.appendChild(buildMessageEl(msg));
  box.scrollTop = box.scrollHeight;
}

function renderMessages() {
  const box = document.getElementById("messages");
  box.innerHTML = "";
  const list = localMessages[currentChannel] || [];
  for (const m of list) box.appendChild(buildMessageEl(m));
  box.scrollTop = box.scrollHeight;
}

function renderChannels() {
  const box = document.getElementById("channels");
  box.innerHTML = "";
  for (const ch of channels) {
    const el = document.createElement("div");
    el.className = "channel" + (ch === currentChannel ? " active" : "");
    el.textContent = ch;
    el.onclick = () => switchChannel(ch);
    box.appendChild(el);
  }
}

function renderUsers(names) {
  document.getElementById("users-header").textContent =
    names.length ? `В сети — ${names.length}` : "В сети";
  const box = document.getElementById("user-list");
  box.innerHTML = "";
  for (const n of names) {
    const row = document.createElement("div");
    row.className = "user-row";
    const dot = document.createElement("div");
    dot.className = "avatar-small";
    dot.style.background = colorFor(n);
    dot.textContent = n[0].toUpperCase();
    const label = document.createElement("span");
    label.textContent = n + (n === nickname ? " (вы)" : "");
    row.append(dot, label);
    box.appendChild(row);
  }
}

function setStatus(ok) {
  const s = document.getElementById("conn-status");
  if (ok) { s.className = "online"; s.textContent = "в сети"; }
  else    { s.className = "";       s.textContent = "переподключение…"; }
}

/* ─────────── Локальное хранилище сообщений ─────────── */
function pushMessage(channel, msg) {
  if (!localMessages[channel]) localMessages[channel] = [];
  localMessages[channel].push(msg);
  if (channel === currentChannel) appendMessageEl(msg);
}

/* ─────────── Обработка входящих ─────────── */
function handleIncoming(data) {
  const ch = data.channel || currentChannel;
  if (data.type === "message") {
    pushMessage(ch, { type: "message", user: data.user, text: data.text, ts: data.ts });
  } else if (data.type === "system") {
    pushMessage(ch, { type: "system", text: data.text, ts: Date.now() / 1000 });
  } else if (data.type === "users") {
    if (ch === currentChannel) renderUsers(data.users);
  }
}

/* ─────────── WebSocket ─────────── */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(
    `${proto}://${location.host}/ws` +
    `?nickname=${encodeURIComponent(nickname)}&channel=${currentChannel}`
  );

  ws.onopen = () => {
    shouldReconnect = true;
    document.getElementById("login").style.display = "none";
    document.getElementById("app").classList.add("visible");
    document.getElementById("channel-name").textContent = "#" + currentChannel;
    setStatus(true);
    renderChannels();
    renderMessages();
    renderUsers([]);
    document.getElementById("msg-input").focus();
  };

  ws.onmessage = (e) => {
    try { handleIncoming(JSON.parse(e.data)); }
    catch (err) { console.error(err); }
  };

  ws.onclose = (e) => {
    setStatus(false);
    if (e.code === 4000) {
      const appVisible = document.getElementById("app").classList.contains("visible");
      shouldReconnect = false;
      if (appVisible) {
        alert("Соединение разорвано: этот ник только что занял другой пользователь.");
        location.reload();
      } else {
        document.getElementById("err").textContent = "Этот ник уже занят";
      }
      return;
    }
    if (shouldReconnect) setTimeout(connectWS, 2000);
  };
}

/* ─────────── Действия пользователя ─────────── */
async function start() {
  const nick = document.getElementById("nick").value.trim();
  if (!nick) { document.getElementById("err").textContent = "Введите ник"; return; }

  try {
    const r = await fetch("/api/channels");
    if (!r.ok) throw new Error("bad status");
    channels = await r.json();
  } catch {
    document.getElementById("err").textContent = "Сервер недоступен";
    return;
  }

  nickname = nick;
  connectWS();
}

function switchChannel(ch) {
  if (ch === currentChannel) return;
  currentChannel = ch;
  document.getElementById("channel-name").textContent = "#" + ch;
  renderChannels();
  renderUsers([]);
  renderMessages();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "switch", channel: ch }));
  }
  document.getElementById("msg-input").focus();
}

function sendMessage() {
  const input = document.getElementById("msg-input");
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "message", text }));
  input.value = "";
  input.focus();
}

/* ─────────── Слушатели ─────────── */
document.getElementById("enter").onclick = start;
document.getElementById("nick").addEventListener("keydown", (e) => {
  if (e.key === "Enter") start();
});
document.getElementById("send").onclick = sendMessage;
document.getElementById("msg-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────
#  Отдача клиента  ←  вот этого не хватало в прошлый раз
# ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return HTML


@app.get("/favicon.ico")
async def favicon():
    # Чтобы браузер не спамил 404-ми
    return HTMLResponse(status_code=204)
