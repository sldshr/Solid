import html
import random

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI(title="Мой первый сайт")

feedbacks = []  # в памяти, при перезапуске обнуляется

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1rem 4rem; background:#0f1117; color:#e6e6e6;
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.container { max-width:820px; margin:0 auto; }
h1 { font-size:1.75rem; margin:0 0 .25rem; }
h2 { font-size:1.15rem; margin:0 0 1rem; }
.sub { color:#9aa4b2; margin:0 0 1.5rem; }
.card { background:#171a21; border:1px solid #262b36; border-radius:12px;
        padding:1.25rem 1.5rem; margin-bottom:1.25rem; }
input, select, textarea, button {
  font:inherit; color:inherit; background:#0f1117; border:1px solid #2f3644;
  border-radius:8px; padding:.55rem .7rem; width:100%;
}
input[type=radio], input[type=range] { width:auto; padding:0; border:none; background:none; }
input:focus, select:focus, textarea:focus { outline:2px solid #4f9cf9; outline-offset:1px; }
button { width:auto; cursor:pointer; background:#232936; border-color:#2f3644; }
button:hover { background:#2b3242; }
button.primary { background:#4f9cf9; border-color:#4f9cf9; color:#06101f; font-weight:600; }
button.primary:hover { background:#6badfb; }
.row { display:flex; gap:.6rem; align-items:center; flex-wrap:wrap; }
.row > input[type=text] { flex:1 1 200px; width:auto; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:.6rem; margin-bottom:.6rem; }
.ops { display:flex; gap:1.2rem; margin:.4rem 0 1rem; }
.ops label { display:flex; align-items:center; gap:.35rem; cursor:pointer; }
form > input, form > textarea, form > select { margin-bottom:.6rem; }
.chart { background:#0f1117; border-radius:8px; padding:.5rem; }
.result { margin-top:.9rem; padding:.7rem .9rem; border-radius:8px; font-size:.95rem; }
.result.ok { background:#10261a; border:1px solid #1f4d31; color:#9ae6b4; }
.result.err { background:#2a1416; border:1px solid #5a2226; color:#f8a5a5; }
.muted { color:#6b7280; font-size:.85rem; margin:.9rem 0 0; }
.range-row { display:flex; align-items:center; gap:1rem; margin-bottom:.6rem; }
.range-row input[type=range] { flex:1; }
@media (max-width:600px) { .grid2 { grid-template-columns:1fr; } }
"""


def make_svg(values, width=760, height=280):
    if not values:
        values = [0.0]
    pad_l, pad_r, pad_t, pad_b = 44, 20, 20, 26
    inner_w, inner_h = width - pad_l - pad_r, height - pad_t - pad_b
    mn, mx = min(values), max(values)
    if mx == mn:
        mx = mn + 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad_l + (i * inner_w / (n - 1) if n > 1 else inner_w / 2)
        y = pad_t + inner_h - (v - mn) / (mx - mn) * inner_h
        pts.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad_l},{pad_t + inner_h} " + polyline + f" {pad_l + inner_w},{pad_t + inner_h}"

    grid = []
    for k in range(5):
        gy = pad_t + inner_h * k / 4
        val = mx - (mx - mn) * k / 4
        grid.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + inner_w}" y2="{gy:.1f}" stroke="#262b36"/>')
        grid.append(f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" fill="#6b7280" font-size="10" text-anchor="end">{val:.1f}</text>')

    dots = ""
    if n <= 60:
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="#4f9cf9"/>' for x, y in pts)

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="display:block">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#4f9cf9" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="#4f9cf9" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'{"".join(grid)}'
        f'<polygon points="{area}" fill="url(#g)"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#4f9cf9" stroke-width="2"/>'
        f'{dots}</svg>'
    )


def render(name="Гость", rows=50, n1=0.0, n2=0.0, op="+",
           calc_result=None, calc_error=None, feedback_msg=None):
    name_safe = html.escape(name) or "Гость"
    rows = max(10, min(200, int(rows)))

    rnd = random.Random(rows * 7919)
    vals, v = [], 0.0
    for _ in range(rows):
        v += rnd.uniform(-1, 1)
        vals.append(v)
    chart = make_svg(vals)

    checked = {k: ("checked" if op == k else "") for k in ["+", "-", "×", "÷"]}

    calc_block = ""
    if calc_result is not None:
        calc_block = f'<div class="result ok">Результат: <b>{html.escape(str(calc_result))}</b></div>'
    elif calc_error:
        calc_block = f'<div class="result err">Ошибка: {html.escape(calc_error)}</div>'

    fb_block = f'<div class="result ok">{html.escape(feedback_msg)}</div>' if feedback_msg else ""

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Мой первый сайт</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>🚀 Мой первый сайт на FastAPI</h1>
  <p class="sub">Привет, <b>{name_safe}</b>! 👋</p>

  <div class="card">
    <form method="get" action="/" class="row">
      <label>Как вас зовут?</label>
      <input type="text" name="name" value="{name_safe}" placeholder="Гость">
      <input type="hidden" name="rows" value="{rows}">
      <button type="submit">OK</button>
    </form>
  </div>

  <div class="card">
    <h2>🧮 Калькулятор</h2>
    <form method="post" action="/calc">
      <div class="grid2">
        <input type="number" step="any" name="n1" value="{n1:g}" placeholder="Первое число">
        <input type="number" step="any" name="n2" value="{n2:g}" placeholder="Второе число">
      </div>
      <div class="ops">
        <label><input type="radio" name="op" value="+" {checked["+"]}> +</label>
        <label><input type="radio" name="op" value="-" {checked["-"]}> −</label>
        <label><input type="radio" name="op" value="×" {checked["×"]}> ×</label>
        <label><input type="radio" name="op" value="÷" {checked["÷"]}> ÷</label>
      </div>
      <input type="hidden" name="name" value="{name_safe}">
      <input type="hidden" name="rows" value="{rows}">
      <button type="submit" class="primary">Посчитать</button>
    </form>
    {calc_block}
  </div>

  <div class="card">
    <h2>📊 График</h2>
    <form method="get" action="/">
      <div class="range-row">
        <label>Точек: <b id="rv">{rows}</b></label>
        <input type="range" name="rows" min="10" max="200" value="{rows}"
               oninput="document.getElementById('rv').textContent=this.value"
               onchange="this.form.submit()">
      </div>
      <input type="hidden" name="name" value="{name_safe}">
    </form>
    <div class="chart">{chart}</div>
  </div>

  <div class="card">
    <h2>✉️ Обратная связь</h2>
    <form method="post" action="/feedback">
      <input type="email" name="email" placeholder="Email" required>
      <textarea name="message" rows="3" placeholder="Сообщение" required></textarea>
      <select name="rating">
        <option value="5">5 ⭐</option>
        <option value="4">4 ⭐</option>
        <option value="3">3 ⭐</option>
        <option value="2">2 ⭐</option>
        <option value="1">1 ⭐</option>
      </select>
      <input type="hidden" name="name" value="{name_safe}">
      <input type="hidden" name="rows" value="{rows}">
      <button type="submit" class="primary">Отправить</button>
    </form>
    {fb_block}
    <p class="muted">Всего сообщений: {len(feedbacks)}</p>
  </div>
</div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index(name: str = "Гость", rows: int = 50):
    return render(name=name, rows=rows)


@app.post("/calc", response_class=HTMLResponse)
def calc(n1: float = Form(0), n2: float = Form(0), op: str = Form("+"),
         name: str = Form("Гость"), rows: int = Form(50)):
    try:
        if op == "+":
            r = n1 + n2
        elif op == "-":
            r = n1 - n2
        elif op == "×":
            r = n1 * n2
        elif op == "÷":
            if n2 == 0:
                raise ZeroDivisionError("деление на ноль")
            r = n1 / n2
        else:
            raise ValueError("неизвестная операция")
        return render(name=name, rows=rows, n1=n1, n2=n2, op=op, calc_result=f"{r:g}")
    except Exception as e:
        return render(name=name, rows=rows, n1=n1, n2=n2, op=op, calc_error=str(e))


@app.post("/feedback", response_class=HTMLResponse)
def feedback(email: str = Form(...), message: str = Form(...), rating: int = Form(5),
             name: str = Form("Гость"), rows: int = Form(50)):
    feedbacks.append({"email": email, "message": message, "rating": rating})
    return render(name=name, rows=rows,
                  feedback_msg=f"Спасибо, {name}! Сообщение получено. Оценка: {rating} ⭐")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
