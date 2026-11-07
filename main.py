from fastapi import FastAPI,Form,Cookie,Request,Response,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from supabase import create_async_client,AsyncClient
import uvicorn,html,bcrypt,secrets,asyncio,uuid,hashlib
from datetime import datetime,timezone

app=FastAPI()
app.add_middleware(GZipMiddleware,minimum_size=500)
S_URL="https://xipbsydkqsumcrjlpnbq.supabase.co"
S_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhpcGJzeWRrcXN1bWNyamxwbmJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE1MDY5MSwiZXhwIjoyMTA3NzI2NjkxfQ.164h9z3jb_4ZaVia0xrssWmXveVCHoEDwPD_Um5fDY0"
sb:AsyncClient=None
_p={};_d=set();_pi={}

@app.on_event("startup")
async def st():
    global sb
    sb=await create_async_client(S_URL,S_KEY)

def _h(p):return bcrypt.hashpw(p.encode(),bcrypt.gensalt()).decode()
def _v(p,h):
    try:
        if len(h)==64 and hashlib.sha256(p.encode()).hexdigest()==h:return True
        return bcrypt.checkpw(p.encode(),h.encode())
    except:return False
def _g(r):return r.cookies.get("csrf_token") or secrets.token_hex(32)
def _c(r,f):return r.cookies.get("csrf_token") and (r.cookies.get("csrf_token")==f or r.cookies.get("csrf_token")==r.headers.get("X-CSRF-Token"))
def _s(res,t,r):
    if not r.cookies.get("csrf_token"):res.set_cookie("csrf_token",t,httponly=True,samesite="lax")

async def _sp(p):
    try:await sb.table('posts').insert(p).execute()
    except Exception as e:print(f"DB Err: {e}")
    finally:_p.pop(p["id"],None)

async def _sd(i):
    try:await sb.table('posts').delete().eq('id',i).execute()
    except Exception as e:print(f"DB Err: {e}")
    finally:_d.discard(i)

async def _spi(i,s):
    try:await sb.table('posts').update({"is_pinned":s}).eq('id',i).execute()
    except Exception as e:print(f"DB Err: {e}")
    finally:_pi.pop(i,None)

@app.exception_handler(RequestValidationError)
async def ve(r,e):
    l=r.cookies.get("lang","ru");m="Заполните все обязательные поля!" if l=="ru" else "Fill all required fields!"
    t=_g(r);res=HTMLResponse(content=_ah(l,m,t),status_code=422);_s(res,t,r);return res

L={"ru":{"reg":"Регистрация","login":"Вход","username":"юзернейм","nickname":"никнейм","password":"пароль","re_pass":"повтор пароля","captcha":"Я не робот","register_btn":"Зарегистрироваться!","login_btn":"Войти","profile":"ПРОФИЛЬ","total_posts":"Всего записей","logout":"Выйти","edit_profile":"Редактировать профиль","save_changes":"Сохранить изменения","description":"Описание","desc_placeholder":"Расскажите о себе...","create_post_btn":"Создать запись","create_post_placeholder":"Напишите что-нибудь...","my_posts":"МОИ ЗАПИСИ","user_posts":"ЗАПИСИ ПОЛЬЗОВАТЕЛЯ","no_posts":"Записей пока нет...","pin":"Закрепить","unpin":"Открепить","delete":"Удалить","confirm_delete":"Удалить запись?","created_by":"Создано:","hosting":"Хостинг:","back_home":"На главную","user_not_found":"Пользователь не найден.","alert_captcha":"Подтвердите, что вы не робот!","alert_pass_mismatch":"Пароли не совпадают!","alert_nick_taken":"Такой никнейм уже занят!","alert_bad_login":"Неверный никнейм или пароль!","alert_desc_long":"Описание > 300 символов!","link_profile":"(Ссылка)","cancel":"Отмена","username_label":"Имя пользователя","nickname_label":"Никнейм","bugreport_title":"Баг-репорт","bugreport_name":"Ваше имя","bugreport_desc":"Описание проблемы","bugreport_send":"Отправить","bugreport_my":"Мои заявки","privacy_title":"Политика конфиденциальности","privacy_text":"1. Сбор информации. Собираем только данные при регистрации.<br><br>2. Использование. Данные нужны для работы сайта.<br><br>3. Безопасность. Используем шифрование (bcrypt).<br><br>4. Cookies. Сайт использует cookies для сессии.<br><br>5. Ваши права. Вы можете изменить данные в профиле.","privacy_agree":"Я согласен с","privacy_link":"Политикой конфиденциальности","alert_privacy":"Примите политику!","cabinet":"ЛИЧНЫЙ КАБИНЕТ","hidden_record":"Скрытая запись","hidden_label":"Сделать скрытой","record_page":"Запись"},"en":{"reg":"Registration","login":"Login","username":"username","nickname":"nickname","password":"password","re_pass":"re enter pass","captcha":"I am not a robot","register_btn":"Register!","login_btn":"Login","profile":"PROFILE","total_posts":"Total records","logout":"Logout","edit_profile":"Edit Profile","save_changes":"Save changes","description":"Description","desc_placeholder":"Tell about yourself...","create_post_btn":"Create record","create_post_placeholder":"Write something...","my_posts":"MY RECORDS","user_posts":"USER RECORDS","no_posts":"No records yet...","pin":"Pin","unpin":"Unpin","delete":"Delete","confirm_delete":"Delete record?","created_by":"Created by:","hosting":"Hosting:","back_home":"Back to home","user_not_found":"User not found.","alert_captcha":"Confirm you are not a robot!","alert_pass_mismatch":"Passwords do not match!","alert_nick_taken":"Nickname is taken!","alert_bad_login":"Invalid login!","alert_desc_long":"Description > 300 chars!","link_profile":"(Link)","cancel":"Cancel","username_label":"Username","nickname_label":"Nickname","bugreport_title":"Bug Report","bugreport_name":"Your Name","bugreport_desc":"Issue Description","bugreport_send":"Send","bugreport_my":"My Reports","privacy_title":"Privacy Policy","privacy_text":"1. We collect data you provide.<br><br>2. Used for site operation.<br><br>3. We use bcrypt.<br><br>4. Site uses cookies.<br><br>5. You can change data anytime.","privacy_agree":"I agree to the","privacy_link":"Privacy Policy","alert_privacy":"Accept the Privacy Policy!","cabinet":"PERSONAL CABINET","hidden_record":"Hidden record","hidden_label":"Make hidden","record_page":"Record"}}
def _t(k,l):return L.get(l,L["ru"]).get(k,k)
def _fd(i):
    if not i:return ""
    try:return datetime.fromisoformat(i.replace("Z","+00:00")).strftime("%d.%m.%Y %H:%M")
    except:return i[:10]

_E="<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'></path><circle cx='12' cy='12' r='3'></circle></svg>"
_EO="<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'></path><line x1='1' y1='1' x2='23' y2='23'></line></svg>"

def _css():return "<style>*{box-sizing:border-box}body{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:20px;display:flex;flex-direction:column;align-items:center;min-height:100vh}a{color:#000;text-decoration:none;font-weight:bold}a:hover{text-decoration:underline}.container{background:#fff;padding:30px;border:10px solid #e0e0e0;display:flex;gap:40px;align-items:flex-start;max-width:100%;margin-bottom:20px}.footer{text-align:center;font-size:16px;font-weight:bold;color:#555;width:100%;max-width:1200px;margin-top:10px;display:flex;flex-direction:column;gap:5px}.footer a{color:#000;border-bottom:2px solid #000}.footer-links{font-size:14px;color:#777}.footer-links a{color:#555;border-bottom:1px solid #555;font-weight:normal}.auth-wrapper{display:flex;gap:20px;flex-direction:column;width:340px}.auth-wrapper-inner{display:flex;gap:20px;align-items:flex-end;width:100%}.form-box{background:#000;padding:5px;display:flex;flex-direction:column;gap:5px;border:2px solid #ccc;width:100%}.form-box form{display:flex;flex-direction:column;gap:5px;margin:0;width:100%}.input-group{position:relative;display:flex;align-items:center;width:100%}input[type=text],input[type=password],textarea,select{background:#a9a9a9;border:none;padding:12px;font-size:20px;font-family:Arial,sans-serif;width:100%;text-align:center;outline:none}textarea{text-align:left;resize:vertical}button,.btn{background:#a9a9a9;border:none;padding:12px;font-size:20px;font-family:Arial,sans-serif;width:100%;text-align:center;cursor:pointer;color:#000;font-weight:bold;display:inline-block;border:1px solid transparent}button:hover,.btn:hover{background:#8c8c8c}.eye-btn{position:absolute;right:5px;background:transparent;border:none;cursor:pointer;width:40px;padding:5px;display:flex;align-items:center;justify-content:center}.label-text{font-size:32px;font-weight:normal;margin-bottom:10px;white-space:nowrap}.captcha-container{background:#a9a9a9;padding:10px;display:flex;align-items:center;justify-content:center;gap:10px;width:100%;cursor:pointer;font-size:16px;font-weight:bold;text-align:center}.captcha-container input[type=checkbox]{width:20px;height:20px;cursor:pointer;flex-shrink:0}.privacy-link{color:#00f;text-decoration:underline;margin-left:5px}.dashboard-container{display:flex;gap:20px;width:100%;max-width:1200px;margin:0 auto;align-items:flex-start}.sidebar{background:#000;padding:10px;width:350px;flex-shrink:0;display:flex;flex-direction:column;gap:10px}.sidebar h2{color:#fff;text-align:center;font-size:28px;margin:10px 0}.info-card{background:#a9a9a9;padding:15px;font-size:18px;text-align:center;word-wrap:break-word;white-space:pre-wrap}.logout-btn{margin-top:10px;background:#ff4d4d}.logout-btn:hover{background:#c00}.edit-btn{background:#4da6ff;margin-top:5px;color:#fff}.edit-btn:hover{background:#1a82e2}.main-content{flex:1;min-width:0;display:flex;flex-direction:column;gap:20px}.create-post-box{background:#000;padding:5px;display:flex;flex-direction:column;gap:5px}.create-post-box textarea{height:120px;font-size:18px;padding:10px}.posts-area{background:#000;padding:20px;min-height:300px;display:flex;flex-direction:column;gap:10px}.posts-area h2{color:#fff;font-size:28px;margin:0 0 10px 0;text-align:center}.post-wrapper{position:relative;transition:opacity .3s ease}.post-item{background:#a9a9a9;padding:15px;font-size:18px;word-wrap:break-word;border-left:5px solid transparent;display:flex;flex-direction:column}.post-item.pinned{border-left:5px solid #ff4d4d;background:#d9d9d9}.post-content{margin-bottom:10px}.post-date{font-size:12px;color:#555;text-align:right;border-top:1px solid #888;padding-top:5px}.post-actions{position:absolute;top:5px;right:5px;display:flex;gap:5px;opacity:0;transition:opacity .2s;z-index:10}.post-wrapper:hover .post-actions{opacity:1}.action-btn{background:#000;color:#fff;border:none;padding:5px 10px;font-size:14px;cursor:pointer;border-radius:3px;width:auto;font-weight:normal}.action-btn:hover{background:#ff4d4d}.action-btn.pin-btn:hover{background:#4da6ff}.status-badge{display:inline-block;padding:3px 8px;border-radius:4px;font-size:14px;font-weight:bold;color:#fff;margin-left:10px}.status-Принято,.status-Accepted{background:#4da6ff}.status-В-работе,.status-In-Progress{background:#f1c40f}.status-Исправлено,.status-Fixed{background:#2ecc71}.status-Отклонено,.status-Rejected{background:#e74c3c}.hidden-badge{display:inline-block;padding:2px 6px;border-radius:3px;font-size:12px;font-weight:bold;background:#555;color:#fff;margin-left:10px}.lang-switch{display:flex;justify-content:center;gap:10px;margin-top:10px}.lang-btn{background:transparent;border:2px solid #a9a9a9;color:#a9a9a9;padding:8px 15px;width:auto;font-size:16px;font-weight:bold;cursor:pointer;transition:all .2s}.lang-btn:hover{background:#a9a9a9;color:#000}.lang-btn.active{background:#4da6ff;border-color:#4da6ff;color:#fff}.login-lang-wrapper{display:flex;justify-content:flex-end;width:100%;margin-top:5px}.privacy-content{background:#fff;color:#000;padding:20px;font-size:18px;line-height:1.5;text-align:left;word-wrap:break-word}.error-msg{color:#ff4d4d;font-weight:bold;font-size:18px;text-align:right;width:100%;margin-top:10px;min-height:20px}@media(max-width:768px){body{padding:10px}.container{flex-direction:column;padding:15px;gap:20px;border-width:5px;width:100%}.auth-wrapper{width:100%}.auth-wrapper-inner{flex-direction:column;gap:10px;width:100%;align-items:stretch}.label-text{font-size:28px;text-align:center;margin:10px 0 0 0;order:-1}.dashboard-container{flex-direction:column}.sidebar{width:100%}.posts-area{padding:10px}.post-actions{opacity:1;position:relative;margin-top:10px;justify-content:flex-end;top:0;right:0}.error-msg{text-align:center}.login-lang-wrapper{justify-content:center}}</style>"

def _js(l,t):
    return f"<script>const T='{t}',X={{\"d\":\"{_t('delete',l)}\",\"p\":\"{_t('pin',l)}\",\"u\":\"{_t('unpin',l)}\",\"c\":\"{_t('confirm_delete',l)}\",\"n\":\"{_t('no_posts',l)}\",\"h\":\"{_t('hidden_record',l)}\"}};function tp(i,b){{const x=document.getElementById(i);if(x.type==='password'){{x.type='text';b.innerHTML=`{_EO}`}}else{{x.type='password';b.innerHTML=`{_E}`}}}}function uc(e){{document.getElementById('char-count').innerText=e.value.length+' / 300'}}async function hc(e){{e.preventDefault();const f=e.target,c=f.querySelector('textarea').value.trim();if(!c)return;const i=crypto.randomUUID(),n=new Date(),d=n.toLocaleDateString('ru-RU')+' '+n.toLocaleTimeString('ru-RU',{{hour:'2-digit',minute:'2-digit'}}),hid=f.querySelector('input[name=is_hidden]').checked,a=document.querySelector('.posts-area'),m=a.querySelector('.post-item:not(.post-wrapper)');if(m)m.remove();const w=document.createElement('div');w.className='post-wrapper';w.id='post-'+i;w.innerHTML=`<div class=\"post-actions\"><button onclick=\"hp('${{i}}',this)\" class=\"action-btn pin-btn\">${{X.p}}</button><button onclick=\"hd('${{i}}',this)\" class=\"action-btn\">${{X.d}}</button></div><div class=\"post-item\"><div class=\"post-content\">${{c.replace(/</g,'&lt;').replace(/>/g,'&gt;')}} ${{hid?`<span class=\"hidden-badge\">${{X.h}}</span>`:''}}</div><div class=\"post-date\">${{d}}</div></div>`;a.insertBefore(w,a.children[1]);f.reset();const fd=new FormData(f);fd.append('content',c);fd.append('client_id',i);fd.append('is_hidden',hid);fd.append('csrf_token',T);try{{const r=await fetch('/create_record',{{method:'POST',body:fd,headers:{{'X-CSRF-Token':T}}}});if(!r.ok)throw new Error('Err')}}catch(x){{w.remove();alert('Failed: '+x.message);if(a.querySelectorAll('.post-wrapper').length===0)a.innerHTML+=`<div class='post-item'>${{X.n}}</div>`}}}}async function hd(i){{if(!confirm(X.c))return;const w=document.getElementById('post-'+i);w.style.opacity='0';setTimeout(()=>w.style.display='none',300);const fd=new FormData();fd.append('csrf_token',T);try{{const r=await fetch('/delete_record/'+i,{{method:'POST',body:fd,headers:{{'X-CSRF-Token':T}}}});if(!r.ok)throw new Error('Err');w.remove()}}catch(x){{w.style.opacity='1';w.style.display='block';alert('Failed: '+x.message)}}}}async function hp(i,b){{const w=document.getElementById('post-'+i),p=w.querySelector('.post-item'),s=p.classList.contains('pinned');if(s){{p.classList.remove('pinned');b.innerText=X.p}}else{{p.classList.add('pinned');b.innerText=X.u;const a=document.querySelector('.posts-area');a.insertBefore(w,a.children[1])}}const fd=new FormData();fd.append('csrf_token',T);try{{const r=await fetch('/pin_record/'+i,{{method:'POST',body:fd,headers:{{'X-CSRF-Token':T}}}});if(!r.ok)throw new Error('Err')}}catch(x){{if(s){{p.classList.add('pinned');b.innerText=X.u}}else{{p.classList.remove('pinned');b.innerText=X.p}}alert('Failed: '+x.message)}}}}</script>"

def _ft(l):return f"<div class='footer'><div>{_t('created_by',l)} <a href='http://solid-link.ddns.net' target='_blank'>Solid Link</a> | {_t('hosting',l)} <a href='https://fastapicloud.com' target='_blank'>FastAPICloud</a></div><div class='footer-links'><a href='/privacy'>{_t('privacy_title',l)}</a> | <a href='/bugreport'>{_t('bugreport_title',l)}</a></div></div>"

def _ah(l,e="",t=""):
    eb=f"<div class='error-msg'>{e}</div>" if e else "<div class='error-msg'></div>"
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('login',l)}</title>{_css()}{_js(l,t)}</head><body><div class='container'><div class='auth-wrapper'><div class='label-text'>{_t('reg',l)}</div><div class='form-box'><form action='/register' method='post'><input type='hidden' name='csrf_token' value='{t}'><input type='text' name='username' placeholder='{_t('username',l)}' required><input type='text' name='nickname' placeholder='{_t('nickname',l)}' required><div class='input-group'><input type='password' name='password' id='rp' placeholder='{_t('password',l)}' required><button type='button' class='eye-btn' onclick='tp(\"rp\",this)'>{_E}</button></div><div class='input-group'><input type='password' name='re_pass' id='rr' placeholder='{_t('re_pass',l)}' required><button type='button' class='eye-btn' onclick='tp(\"rr\",this)'>{_E}</button></div><label class='captcha-container'><input type='checkbox' name='captcha' required> {_t('captcha',l)}</label><label class='captcha-container' style='background:#8c8c8c;margin-top:2px'><input type='checkbox' name='privacy' required><span>{_t('privacy_agree',l)} <a href='/privacy' target='_blank' class='privacy-link'>{_t('privacy_link',l)}</a></span></label><button type='submit'>{_t('register_btn',l)}</button></form></div></div><div class='auth-wrapper'><div class='auth-wrapper-inner'><div class='form-box'><form action='/login' method='post'><input type='hidden' name='csrf_token' value='{t}'><input type='text' name='nickname' placeholder='{_t('nickname',l)}' required><div class='input-group'><input type='password' name='password' id='lp' placeholder='{_t('password',l)}' required><button type='button' class='eye-btn' onclick='tp(\"lp\",this)'>{_E}</button></div><label class='captcha-container'><input type='checkbox' name='captcha' required> {_t('captcha',l)}</label><button type='submit'>{_t('login_btn',l)}</button></form></div><div class='label-text'>{_t('login',l)}</div></div><div class='login-lang-wrapper'><div class='lang-switch'><a href='/set_lang/ru?next=/' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div></div>{eb}</div></div>{_ft(l)}</body></html>"

def _rp(p,l,t,s=False):
    if not p:return f"<div class='post-item'>{_t('no_posts',l)}</div>"
    o=""
    for x in p:
        i=x.get('id','');pi=x.get('is_pinned',False);hid=x.get('is_hidden',False);c=html.escape(x.get('content','')).replace('\n','<br>');d=_fd(x.get('created_at',''));pc="pinned" if pi else "";pt=_t('unpin',l) if pi else _t('pin',l);hb=f"<span class='hidden-badge'>{_t('hidden_record',l)}</span>" if hid else ""
        a=f"<div class='post-actions'><button onclick='hp(\"{i}\",this)' class='action-btn pin-btn'>{pt}</button><button onclick='hd(\"{i}\",this)' class='action-btn'>{_t('delete',l)}</button></div>" if s else ""
        o+=f"<div class='post-wrapper' id='post-{i}'>{a}<div class='post-item {pc}'><div class='post-content'><a href='/{x.get('user_nickname','')}/{i}'>{c}</a> {hb}</div><div class='post-date'>{d}</div></div></div>"
    return o

def _mp(dp,n,is_owner=False):
    f=[x for x in dp if x['id'] not in _d and (is_owner or not x.get('is_hidden',False))]
    for x in f:
        if x['id'] in _pi:x['is_pinned']=_pi[x['id']]
    for i,x in _p.items():
        if x['user_nickname']==n and (is_owner or not x.get('is_hidden',False)):f.append(x)
    f.sort(key=lambda x:(not x['is_pinned'],x['created_at']),reverse=True)
    return f

def _dh(n,u,p,l,t):
    ph=_rp(p,l,t,True);d=u.get('description','');db=f"<div class='info-card'><b>{_t('description',l)}:</b><br>{html.escape(d)}</div>" if d else ""
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('cabinet',l)}</title>{_css()}{_js(l,t)}</head><body><div class='dashboard-container'><div class='sidebar'><h2>{_t('cabinet',l)}</h2><div class='info-card'><b>{_t('username_label',l)}:</b><br>{html.escape(u['username'])}</div><div class='info-card'><b>{_t('nickname_label',l)}:</b><br><a href='/{n}' target='_blank'>{html.escape(n)} {_t('link_profile',l)}</a></div>{db}<div class='info-card'><b>{_t('total_posts',l)}:</b><br>{len(p)}</div><a href='/cabinet/edit' class='btn edit-btn'>{_t('edit_profile',l)}</a><form action='/logout' method='get' style='margin:0;width:100%'><button type='submit' class='logout-btn'>{_t('logout',l)}</button></form><div class='lang-switch'><a href='/set_lang/ru?next=/cabinet' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/cabinet' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div></div><div class='main-content'><div class='create-post-box'><form id='create-form' onsubmit='hc(event)'><textarea name='content' placeholder='{_t('create_post_placeholder',l)}' required maxlength='500' style='margin-bottom:5px'></textarea><label style='color:#fff;display:flex;align-items:center;gap:5px;margin-bottom:5px;font-weight:bold'><input type='checkbox' name='is_hidden'> {_t('hidden_label',l)}</label><button type='submit'>{_t('create_post_btn',l)}</button></form></div><div class='posts-area'><h2>{_t('my_posts',l)}</h2>{ph}</div></div></div>{_ft(l)}</body></html>"

def _eh(n,u,l,t):
    d=u.get('description','')
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('edit_profile',l)}</title>{_css()}{_js(l,t)}</head><body><div class='dashboard-container' style='justify-content:center'><div class='main-content' style='max-width:600px'><div class='posts-area'><h2>{_t('edit_profile',l)}</h2><form action='/cabinet/edit' method='post' style='display:flex;flex-direction:column;gap:10px'><input type='hidden' name='csrf_token' value='{t}'><div style='color:#fff;font-size:18px;margin-bottom:-5px'>{_t('username_label',l)}</div><input type='text' name='username' value='{html.escape(u['username'])}' required style='background:#a9a9a9;padding:12px;font-size:18px'><div style='color:#fff;font-size:18px;margin-bottom:-5px'>{_t('description',l)}</div><textarea name='description' maxlength='300' placeholder='{_t('desc_placeholder',l)}' oninput='uc(this)' style='background:#a9a9a9;height:150px;padding:12px;font-size:18px'>{html.escape(d)}</textarea><div id='char-count' style='color:#fff;text-align:right;font-size:14px'>{len(d)} / 300</div><button type='submit' style='background:#4da6ff;color:#fff;margin-top:10px'>{_t('save_changes',l)}</button><a href='/cabinet' class='btn' style='background:#a9a9a9'>{_t('cancel',l)}</a></form><div class='lang-switch' style='margin-top:20px'><a href='/set_lang/ru?next=/cabinet/edit' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/cabinet/edit' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div></div></div></div>{_ft(l)}</body></html>"

def _ph(n,u,p,l,t):
    ph=_rp(p,l,t,False);d=u.get('description','');db=f"<div class='info-card'><b>{_t('description',l)}:</b><br>{html.escape(d)}</div>" if d else ""
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('profile',l)} {html.escape(n)}</title>{_css()}{_js(l,t)}</head><body><div class='dashboard-container'><div class='sidebar'><h2>{_t('profile',l)}</h2><div class='info-card'><b>{_t('username_label',l)}:</b><br>{html.escape(u['username'])}</div><div class='info-card'><b>{_t('nickname_label',l)}:</b><br>{html.escape(n)}</div>{db}<div class='info-card'><b>{_t('total_posts',l)}:</b><br>{len(p)}</div><div class='lang-switch'><a href='/set_lang/ru?next=/{n}' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/{n}' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div><a href='/' class='btn' style='margin-top:auto;background:#a9a9a9'>{_t('back_home',l)}</a></div><div class='main-content'><div class='posts-area' style='min-height:500px'><h2>{_t('user_posts',l)}</h2>{ph}</div></div></div>{_ft(l)}</body></html>"

def _rh(n,u,r,l,t):
    c=html.escape(r.get('content','')).replace('\n','<br>');d=_fd(r.get('created_at',''));hb=f"<span class='hidden-badge'>{_t('hidden_record',l)}</span>" if r.get('is_hidden') else ""
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('record_page',l)}</title>{_css()}{_js(l,t)}</head><body><div class='dashboard-container'><div class='sidebar'><h2>{_t('profile',l)}</h2><div class='info-card'><b>{_t('nickname_label',l)}:</b><br><a href='/{n}'>{html.escape(n)}</a></div><div class='info-card'><b>{_t('username_label',l)}:</b><br>{html.escape(u['username'])}</div><a href='/{n}' class='btn' style='margin-top:auto;background:#a9a9a9'>{_t('back_home',l)}</a></div><div class='main-content'><div class='posts-area'><h2>{_t('record_page',l)}</h2><div class='post-wrapper'><div class='post-item { "pinned" if r.get("is_pinned") else ""}'><div class='post-content' style='font-size:22px'>{c} {hb}</div><div class='post-date'>{d}</div></div></div></div></div></div>{_ft(l)}</body></html>"

def _bh(u,r,l,t):
    rh="<div class='post-item'>Заявок пока нет...</div>" if not r else "".join([f"<div class='post-item' style='border-left-color:transparent'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'><b>{_t('bugreport_title',l)}</b><span class='status-badge status-{x.get('status','Принято').replace(' ','-')}'>{x.get('status','Принято')}</span></div><div class='post-content'>{html.escape(x.get('content',''))}</div><div class='post-date'>{_fd(x.get('created_at',''))}</div></div>" for x in r])
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('bugreport_title',l)}</title>{_css()}{_js(l,t)}</head><body><div class='dashboard-container'><div class='sidebar' style='display:none'></div><div class='main-content' style='max-width:800px;margin:0 auto'><div class='create-post-box'><h2 style='color:#fff;text-align:center;margin:10px 0'>{_t('bugreport_title',l)}</h2><form action='/bugreport' method='post' style='display:flex;flex-direction:column;gap:5px'><input type='hidden' name='csrf_token' value='{t}'><input type='text' name='name' value='{u}' placeholder='{_t('bugreport_name',l)}' required style='background:#a9a9a9;padding:12px;margin-bottom:5px'><textarea name='content' placeholder='{_t('bugreport_desc',l)}' required style='background:#a9a9a9;height:150px;padding:12px;margin-bottom:5px'></textarea><button type='submit' style='background:#f1c40f;color:#000'>{_t('bugreport_send',l)}</button></form></div><div class='posts-area'><h2>{_t('bugreport_my',l)}</h2>{rh}</div><a href='/cabinet' class='btn' style='background:#a9a9a9;margin-top:10px'>{_t('cancel',l)}</a><div class='lang-switch' style='margin-top:20px'><a href='/set_lang/ru?next=/bugreport' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/bugreport' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div></div></div>{_ft(l)}</body></html>"

def _prh(l,t):
    return f"<!DOCTYPE html><html lang='{l}'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_t('privacy_title',l)}</title>{_css()}</head><body><div class='dashboard-container' style='justify-content:center'><div class='main-content' style='max-width:800px'><div class='posts-area'><h2 style='color:#fff;text-align:center;margin-bottom:20px'>{_t('privacy_title',l)}</h2><div class='privacy-content'>{_t('privacy_text',l)}</div><a href='/' class='btn' style='background:#a9a9a9;margin-top:20px'>{_t('back_home',l)}</a><div class='lang-switch' style='margin-top:20px'><a href='/set_lang/ru?next=/privacy' class='btn lang-btn {'active' if l=='ru' else ''}'>RU</a><a href='/set_lang/en?next=/privacy' class='btn lang-btn {'active' if l=='en' else ''}'>EN</a></div></div></div></div>{_ft(l)}</body></html>"

@app.get("/set_lang/{lang}")
async def sl(lang:str,next:str="/"):
    res=RedirectResponse(next,303)
    res.set_cookie("lang",lang if lang in["ru","en"] else"ru",max_age=31536000)
    return res

@app.get("/",response_class=HTMLResponse)
async def ix(r:Request,nickname:str=Cookie(None),lang:str=Cookie("ru")):
    t=_g(r)
    if nickname:
        x=await sb.table('users').select('nickname').eq('nickname',nickname).execute()
        if x.data:return RedirectResponse("/cabinet",303)
    res=HTMLResponse(_ah(lang,"",t))
    _s(res,t,r)
    return res

@app.get("/privacy",response_class=HTMLResponse)
async def pr(r:Request,lang:str=Cookie("ru")):
    t=_g(r);res=HTMLResponse(_prh(lang,t));_s(res,t,r);return res

@app.post("/register",response_class=HTMLResponse)
async def reg(r:Request,res:Response,username:str=Form(...),nickname:str=Form(...),password:str=Form(...),re_pass:str=Form(...),captcha:str=Form(None),privacy:str=Form(None),csrf_token:str=Form(None),lang:str=Cookie("ru")):
    t=_g(r)
    if not _c(r,csrf_token):return _ah(lang,"CSRF Error",t)
    if not captcha:return _ah(lang,_t('alert_captcha',lang),t)
    if not privacy:return _ah(lang,_t('alert_privacy',lang),t)
    if password!=re_pass:return _ah(lang,_t('alert_pass_mismatch',lang),t)
    x=await sb.table('users').select('nickname').eq('nickname',nickname).execute()
    if x.data:return _ah(lang,_t('alert_nick_taken',lang),t)
    try:await sb.table('users').insert({"username":username,"nickname":nickname,"password":_h(password),"description":""}).execute()
    except Exception as e:return _ah(lang,f"DB Error: {str(e)}",t)
    res=RedirectResponse("/cabinet",303);res.set_cookie("nickname",nickname,httponly=True,samesite="lax");return res

@app.post("/login",response_class=HTMLResponse)
async def lg(r:Request,res:Response,nickname:str=Form(...),password:str=Form(...),captcha:str=Form(None),csrf_token:str=Form(None),lang:str=Cookie("ru")):
    t=_g(r)
    if not _c(r,csrf_token):return _ah(lang,"CSRF Error",t)
    if not captcha:return _ah(lang,_t('alert_captcha',lang),t)
    x=await sb.table('users').select('password').eq('nickname',nickname).execute()
    u=x.data[0] if x.data else None
    if u and _v(password,u["password"]):
        if len(u["password"])==64:await sb.table('users').update({"password":_h(password)}).eq('nickname',nickname).execute()
        res=RedirectResponse("/cabinet",303);res.set_cookie("nickname",nickname,httponly=True,samesite="lax");return res
    return _ah(lang,_t('alert_bad_login',lang),t)

@app.get("/cabinet",response_class=HTMLResponse)
async def db(r:Request,nickname:str=Cookie(None),lang:str=Cookie("ru")):
    if not nickname:return RedirectResponse("/",303)
    u,p=await asyncio.gather(sb.table('users').select('username,description').eq('nickname',nickname).execute(),sb.table('posts').select('id,user_nickname,content,is_pinned,is_hidden,created_at').eq('user_nickname',nickname).execute())
    if not u.data:return RedirectResponse("/",303)
    po=_mp(p.data,nickname,True);t=_g(r);res=HTMLResponse(_dh(nickname,u.data[0],po,lang,t));_s(res,t,r);return res

@app.post("/create_record")
async def cp(r:Request,content:str=Form(...),client_id:str=Form(None),is_hidden:bool=Form(False),csrf_token:str=Form(None),nickname:str=Cookie(None)):
    if not _c(r,csrf_token):return JSONResponse({"e":"CSRF"},403)
    if not nickname:return JSONResponse({"e":"Unauth"},401)
    if not content.strip():return JSONResponse({"e":"Empty"},400)
    i=client_id or str(uuid.uuid4());n=datetime.now(timezone.utc).isoformat()
    pd={"id":i,"user_nickname":nickname,"content":content.strip(),"is_pinned":False,"is_hidden":is_hidden,"created_at":n}
    _p[i]=pd;asyncio.create_task(_sp(pd));return JSONResponse({"s":"ok","id":i})

@app.post("/delete_record/{post_id}")
async def dp(post_id:str,r:Request,csrf_token:str=Form(None),nickname:str=Cookie(None)):
    if not _c(r,csrf_token):return JSONResponse({"e":"CSRF"},403)
    if not nickname:return JSONResponse({"e":"Unauth"},401)
    _d.add(post_id);asyncio.create_task(_sd(post_id));return JSONResponse({"s":"ok"})

@app.post("/pin_record/{post_id}")
async def pp(post_id:str,r:Request,csrf_token:str=Form(None),nickname:str=Cookie(None)):
    if not _c(r,csrf_token):return JSONResponse({"e":"CSRF"},403)
    if not nickname:return JSONResponse({"e":"Unauth"},401)
    c=_pi.get(post_id)
    if c is None:
        x=await sb.table('posts').select('is_pinned').eq('id',post_id).eq('user_nickname',nickname).execute()
        if x.data:c=x.data[0]['is_pinned']
    ns=not c if c is not None else False
    _pi[post_id]=ns;asyncio.create_task(_spi(post_id,ns));return JSONResponse({"s":"ok"})

@app.get("/cabinet/edit",response_class=HTMLResponse)
async def ed(r:Request,nickname:str=Cookie(None),lang:str=Cookie("ru")):
    if not nickname:return RedirectResponse("/",303)
    u=await sb.table('users').select('username,description').eq('nickname',nickname).execute()
    if not u.data:return RedirectResponse("/",303)
    t=_g(r);res=HTMLResponse(_eh(nickname,u.data[0],lang,t));_s(res,t,r);return res

@app.post("/cabinet/edit",response_class=HTMLResponse)
async def eda(r:Request,res:Response,username:str=Form(...),description:str=Form(""),csrf_token:str=Form(None),nickname:str=Cookie(None),lang:str=Cookie("ru")):
    if not _c(r,csrf_token):return HTMLResponse("<script>alert('CSRF Error');window.history.back()</script>")
    if not nickname:return RedirectResponse("/",303)
    if len(description)>300:return HTMLResponse(f"<script>alert('{_t('alert_desc_long',lang)}');window.history.back()</script>")
    await sb.table('users').update({"username":username,"description":description}).eq('nickname',nickname).execute()
    return RedirectResponse("/cabinet",303)

@app.get("/bugreport",response_class=HTMLResponse)
async def br(r:Request,nickname:str=Cookie(None),lang:str=Cookie("ru")):
    u="";rp=[]
    if nickname:
        x,y=await asyncio.gather(sb.table('users').select('username').eq('nickname',nickname).execute(),sb.table('bug_reports').select('*').eq('user_nickname',nickname).order('created_at',desc=True).execute())
        if x.data:u=x.data[0]['username']
        rp=y.data
    t=_g(r);res=HTMLResponse(_bh(u,rp,lang,t));_s(res,t,r);return res

@app.post("/bugreport",response_class=HTMLResponse)
async def brs(r:Request,res:Response,name:str=Form(...),content:str=Form(...),csrf_token:str=Form(None),nickname:str=Cookie(None),lang:str=Cookie("ru")):
    if not _c(r,csrf_token):return HTMLResponse("<script>alert('CSRF Error');window.history.back()</script>")
    d={"name":name,"content":content,"status":"Принято" if lang=="ru" else "Accepted"}
    if nickname:d["user_nickname"]=nickname
    await sb.table('bug_reports').insert(d).execute()
    return RedirectResponse("/bugreport",303)

@app.get("/logout")
async def lo():
    res=RedirectResponse("/",303);res.delete_cookie("nickname");return res

@app.get("/{nickname}/{rid}",response_class=HTMLResponse)
async def rp(nickname:str,rid:str,r:Request,lang:str=Cookie("ru")):
    u,x=await asyncio.gather(sb.table('users').select('username').eq('nickname',nickname).execute(),sb.table('posts').select('id,user_nickname,content,is_pinned,is_hidden,created_at').eq('id',rid).eq('user_nickname',nickname).execute())
    if not u.data:return HTMLResponse(f"<h2>{_t('user_not_found',lang)}</h2>",404)
    if not x.data:return HTMLResponse(f"<h2>{_t('no_posts',lang)}</h2>",404)
    rec=x.data[0]
    if rec.get('is_hidden') and r.cookies.get("nickname")!=nickname:return HTMLResponse(f"<h2>{_t('user_not_found',lang)}</h2>",404)
    t=_g(r);res=HTMLResponse(_rh(nickname,u.data[0],rec,lang,t));_s(res,t,r);return res

@app.get("/{nickname}",response_class=HTMLResponse)
async def pb(nickname:str,r:Request,lang:str=Cookie("ru")):
    u,p=await asyncio.gather(sb.table('users').select('username,description').eq('nickname',nickname).execute(),sb.table('posts').select('id,user_nickname,content,is_pinned,is_hidden,created_at').eq('user_nickname',nickname).execute())
    if not u.data:return HTMLResponse(f"<h2>{_t('user_not_found',lang)} <a href='/'>OK</a></h2>",404)
    is_owner=(r.cookies.get("nickname")==nickname)
    po=_mp(p.data,nickname,is_owner);t=_g(r);res=HTMLResponse(_ph(nickname,u.data[0],po,lang,t));_s(res,t,r);return res

if __name__=="__main__":uvicorn.run(app,host="127.0.0.1",port=8000)
