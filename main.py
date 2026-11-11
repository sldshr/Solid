from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext
import uuid
import base64
from typing import List, Optional

app = FastAPI(title="sol.id")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ==========================================
# БАЗА ДАННЫХ В ОПЕРАТИВНОЙ ПАМЯТИ
# ==========================================
users_db = {} 
sessions = {} 
posts_db = [] 

# Дефолтный пользователь для теста
admin_pwd = pwd_context.hash("admin")
users_db["admin"] = {
    "username": "admin",
    "password": admin_pwd,
    "display_name": "Администратор",
    "avatar": None,
    "saved_posts": []
}

# ==========================================
# SVG ИКОНКИ
# ==========================================
SVG_LOGO = """<svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM15.5 11H8.5V13H15.5V11Z" fill="#8cc84b"/></svg>"""
SVG_FAVICON = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22><path d=%22M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM15.5 11H8.5V13H15.5V11Z%22 fill=%22%238cc84b%22/></svg>"

SVG_UP = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>"""
SVG_DOWN = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>"""
SVG_FEED = """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>"""
SVG_PLUS = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>"""
SVG_USER = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
SVG_SETTINGS = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>"""
SVG_LOGOUT = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>"""
SVG_COMMENT = """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>"""
SVG_EYE = """<svg class="eye-open" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>"""
SVG_EYE_OFF = """<svg class="eye-closed" style="display:none;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>"""
SVG_BACK = """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>"""
SVG_IMAGE = """<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>"""
SVG_SAVE = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_SAVED = """<svg width="20" height="20" viewBox="0 0 24 24" fill="#8cc84b" stroke="#8cc84b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>"""
SVG_LINK = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>"""
SVG_TRASH = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>"""

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        return users_db.get(sessions[session_token])
    return None

async def image_to_base64(file: UploadFile):
    if not file or not file.filename: return None
    contents = await file.read()
    return f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"

# ==========================================
# CSS И JS
# ==========================================
CSS_STYLES = """
<link rel="icon" type="image/svg+xml" href=\"""" + SVG_FAVICON + """\">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700&display=swap" rel="stylesheet">
<style>
    :root {
        --bg-color: #0f0f0f; --card-bg: #1c1c1c; --text-main: #f3f3f3; --text-muted: #888;
        --accent-color: #8cc84b; --border-color: #2a2a2a; --danger-color: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Manrope', sans-serif; user-select: none; }
    input, textarea, .selectable { user-select: text; }
    
    body { background-color: var(--bg-color); color: var(--text-main); display: flex; flex-direction: column; min-height: 100vh; font-size: 16px; }
    a { color: var(--accent-color); text-decoration: none; }
    
    /* Layout */
    .app-layout { display: grid; grid-template-columns: 260px 1fr; grid-template-rows: 70px 1fr; height: 100vh; width: 100%; }
    
    /* Topbar */
    .topbar { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; padding: 0 30px; border-bottom: 1px solid var(--border-color); background-color: var(--bg-color); z-index: 100; }
    .logo { font-size: 22px; font-weight: 700; color: var(--text-main); display: flex; align-items: center; gap: 10px; }
    .btn-primary { background-color: var(--accent-color); color: #000; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; font-size: 15px; }
    .btn-primary:hover { opacity: 0.9; }
    
    /* User Dropdown */
    .user-menu-container { position: relative; }
    .user-menu-btn { display: flex; align-items: center; gap: 12px; cursor: pointer; padding: 6px 12px; border-radius: 8px; border: 1px solid transparent; }
    .user-menu-btn:hover { background: var(--card-bg); border-color: var(--border-color); }
    .user-avatar-small { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: #333; }
    .dropdown-menu { display: none; position: absolute; right: 0; top: 55px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; width: 240px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); z-index: 200; overflow: hidden; }
    .dropdown-header { padding: 15px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border-color); }
    .dropdown-header img { width: 44px; height: 44px; border-radius: 50%; object-fit: cover; }
    .dropdown-header div { display: flex; flex-direction: column; }
    .dropdown-header .name { font-weight: 700; font-size: 15px; }
    .dropdown-header .login { font-size: 13px; color: var(--text-muted); }
    .dropdown-item { display: flex; align-items: center; gap: 12px; padding: 14px 15px; color: var(--text-main); font-size: 15px; }
    .dropdown-item:hover { background: #2a2a2a; }
    .dropdown-item.danger { color: var(--danger-color); border-top: 1px solid var(--border-color); }
    
    /* Sidebar */
    .sidebar { grid-column: 1; grid-row: 2; border-right: 1px solid var(--border-color); padding: 20px 15px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; }
    .sidebar a { color: var(--text-muted); padding: 12px 15px; border-radius: 8px; display: flex; align-items: center; gap: 15px; font-size: 16px; font-weight: 500; }
    .sidebar a:hover, .sidebar a.active { color: var(--text-main); background-color: var(--card-bg); }
    .sidebar a.active svg { color: var(--accent-color); }
    
    /* Main Content */
    .main-content { grid-column: 2; grid-row: 2; padding: 30px; overflow-y: auto; display: flex; flex-direction: column; }
    
    /* Auth Forms */
    .auth-container { display: flex; justify-content: center; align-items: center; flex: 1; }
    .auth-form { background-color: var(--card-bg); padding: 40px; border-radius: 16px; width: 100%; max-width: 450px; border: 1px solid var(--border-color); }
    .auth-form h2 { text-align: center; margin-bottom: 25px; font-weight: 700; font-size: 24px; }
    .input-group { margin-bottom: 20px; position: relative; }
    .input-group input, .input-group select, .input-group textarea { width: 100%; padding: 14px 16px; background-color: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; color: white; font-size: 16px; outline: none; }
    .input-group input:focus, .input-group select:focus, .input-group textarea:focus { border-color: var(--accent-color); }
    .pass-toggle { position: absolute; right: 15px; top: 15px; cursor: pointer; color: var(--text-muted); }
    .checkbox-group { display: flex; gap: 10px; align-items: center; margin-bottom: 25px; font-size: 14px; color: var(--text-muted); }
    .error { color: var(--danger-color); text-align: center; margin-bottom: 15px; font-size: 15px; }
    
    /* Profile */
    .profile-header { margin-bottom: 30px; display: flex; align-items: center; gap: 25px; }
    .profile-avatar { width: 140px; height: 140px; border-radius: 50%; border: 4px solid var(--card-bg); object-fit: cover; background: #333; }
    .profile-details h1 { font-size: 32px; margin-bottom: 5px; font-weight: 700; }
    .profile-details p { color: var(--text-muted); font-size: 16px; }
    
    /* Post View */
    .post-view { display: flex; gap: 25px; background: var(--card-bg); border-radius: 16px; padding: 25px; border: 1px solid var(--border-color); margin-bottom: 20px; min-height: 70vh; }
    .post-media { flex: 2; background: #000; border-radius: 12px; display: flex; align-items: center; justify-content: center; overflow: hidden; position: relative; cursor: zoom-in; }
    .post-media img { max-width: 100%; max-height: 80vh; object-fit: contain; }
    .post-details { flex: 1; min-width: 320px; display: flex; flex-direction: column; }
    .post-author { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
    .post-author img { width: 48px; height: 48px; border-radius: 50%; }
    .post-title { font-size: 26px; font-weight: 700; margin-bottom: 15px; }
    .post-desc { color: #ccc; font-size: 16px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.5; }
    
    /* Actions Row */
    .actions-row { display: flex; align-items: center; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
    .vote-controls { display: flex; align-items: center; gap: 12px; background: var(--bg-color); padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border-color); }
    .vote-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 4px; border-radius: 4px; }
    .vote-btn:hover { background: #333; color: #fff; }
    .vote-btn.up:hover { color: var(--accent-color); }
    .vote-btn.down:hover { color: var(--danger-color); }
    .vote-count { font-weight: 700; font-size: 18px; }
    
    .action-btn { background: var(--bg-color); border: 1px solid var(--border-color); color: var(--text-muted); padding: 8px 12px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 5px; text-decoration: none; }
    .action-btn:hover { background: #333; color: #fff; }
    
    /* Feed Grid */
    .feed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
    .feed-card { background: var(--card-bg); border-radius: 12px; overflow: hidden; border: 1px solid var(--border-color); display: flex; flex-direction: column; transition: transform 0.2s; }
    .feed-card:hover { transform: translateY(-3px); }
    .feed-card img { width: 100%; height: 200px; object-fit: cover; }
    .feed-card-info { padding: 15px; }
    .feed-card-title { font-weight: 700; font-size: 18px; margin-bottom: 10px; }
    .feed-card-author { font-size: 14px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; }
    
    /* Create Post */
    .create-layout { display: flex; gap: 30px; max-width: 1100px; margin: 0 auto; width: 100%; }
    .dropzone { flex: 2; border: 2px dashed var(--border-color); border-radius: 16px; padding: 50px; text-align: center; color: var(--text-muted); display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; transition: border-color 0.2s; }
    .dropzone.dragover { border-color: var(--accent-color); background: rgba(140, 200, 75, 0.05); }
    .file-preview { display: flex; align-items: center; gap: 15px; background: var(--bg-color); padding: 10px; border-radius: 8px; border: 1px solid var(--border-color); margin-top: 15px; width: 100%; text-align: left; }
    .file-preview img { width: 50px; height: 50px; object-fit: cover; border-radius: 6px; }
    .create-sidebar { flex: 1; background: var(--card-bg); padding: 30px; border-radius: 16px; border: 1px solid var(--border-color); display: flex; flex-direction: column; gap: 20px; }

    /* Panorama Overlay */
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 9999; justify-content: center; align-items: center; flex-direction: column; }
    .overlay img { max-width: 95%; max-height: 95%; object-fit: contain; }
    .close-overlay { position: absolute; top: 20px; right: 30px; font-size: 40px; color: #fff; cursor: pointer; background: none; border: none; }

    /* Mobile Nav */
    .bottom-nav { display: none; position: fixed; bottom: 0; left: 0; width: 100%; background: var(--bg-color); border-top: 1px solid var(--border-color); justify-content: space-around; padding: 12px 0; z-index: 100; padding-bottom: env(safe-area-inset-bottom, 12px); }
    .bottom-nav a { display: flex; flex-direction: column; align-items: center; font-size: 12px; color: var(--text-muted); gap: 6px; }
    .bottom-nav a.active { color: var(--accent-color); }
    .bottom-nav .plus-btn { background: var(--accent-color); color: #000; padding: 12px; border-radius: 50%; transform: translateY(-20px); box-shadow: 0 4px 15px rgba(140, 200, 75, 0.4); }

    @media (max-width: 900px) {
        .app-layout { grid-template-columns: 1fr; grid-template-rows: 70px 1fr; }
        .sidebar { display: none; }
        .main-content { grid-column: 1; padding: 15px; padding-bottom: 100px; }
        .bottom-nav { display: flex; }
        .topbar .user-menu-btn span { display: none; }
        .topbar .btn-primary span { display: none; }
        .post-view { flex-direction: column; padding: 15px; }
        .create-layout { flex-direction: column; }
        .profile-header { flex-direction: column; text-align: center; }
    }
</style>
<script>
    // Dropdown Menu
    function toggleDropdown() {
        var dropdown = document.getElementById("user-dropdown");
        dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
    }
    window.onclick = function(event) {
        if (!event.target.closest('.user-menu-container')) {
            var dropdowns = document.getElementsByClassName("dropdown-menu");
            for (var i = 0; i < dropdowns.length; i++) {
                if (dropdowns[i].style.display === "block") dropdowns[i].style.display = "none";
            }
        }
    }

    // Password Toggle
    function togglePassword(el) {
        let input = el.previousElementSibling;
        let eyeOpen = el.querySelector('.eye-open');
        let eyeClosed = el.querySelector('.eye-closed');
        if (input.type === "password") {
            input.type = "text";
            eyeOpen.style.display = "none";
            eyeClosed.style.display = "block";
        } else {
            input.type = "password";
            eyeOpen.style.display = "block";
            eyeClosed.style.display = "none";
        }
    }

    // File Upload Logic
    function handleFiles(input) {
        const previewContainer = document.getElementById('file-list');
        previewContainer.innerHTML = ''; // Clear existing
        if (input.files.length > 5) {
            alert('Максимум 5 файлов!');
            input.value = '';
            return;
        }
        if (input.files.length > 0) {
            document.getElementById('dropzone-text').style.display = 'none';
            for (let i = 0; i < input.files.length; i++) {
                let file = input.files[i];
                let reader = new FileReader();
                reader.onload = function(e) {
                    let div = document.createElement('div');
                    div.className = 'file-preview';
                    div.innerHTML = `
                        <img src="${e.target.result}">
                        <div style="flex:1;">
                            <div style="font-size:14px; color:#fff; font-weight:500;">${file.name}</div>
                            <div style="font-size:12px; color:var(--text-muted);">${(file.size/1024).toFixed(1)} КБ</div>
                        </div>
                        <span style="cursor:pointer; color:var(--text-muted); font-size:20px;" onclick="this.parentElement.remove()">×</span>
                    `;
                    previewContainer.appendChild(div);
                }
                reader.readAsDataURL(file);
            }
        }
    }

    // Copy Link
    function copyLink() {
        navigator.clipboard.writeText(window.location.href);
        alert('Ссылка скопирована!');
    }

    // Panorama Viewer
    function openPanorama(src) {
        document.getElementById('panorama-img').src = src;
        document.getElementById('panorama').style.display = 'flex';
    }
    function closePanorama() {
        document.getElementById('panorama').style.display = 'none';
    }
</script>
"""

# ==========================================
# LAYOUT
# ==========================================
def render_layout(content_html, user, active_page="feed", prev_id=None, next_id=None, is_post_view=False):
    avatar_url = user.get('avatar') if user and user.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={user['username'] if user else 'guest'}"
    
    if user:
        nav_html = f"""
        <div style="display:flex; align-items:center; gap:20px;">
            <a href="/write" class="btn-primary">{SVG_PLUS} <span>Новый пост</span></a>
            <div class="user-menu-container">
                <div class="user-menu-btn" onclick="toggleDropdown()">
                    <img src="{avatar_url}" class="user-avatar-small">
                    <span style="font-weight:500; font-size:15px;">{user['display_name']}</span>
                </div>
                <div id="user-dropdown" class="dropdown-menu">
                    <div class="dropdown-header">
                        <img src="{avatar_url}">
                        <div>
                            <span class="name">{user['display_name']}</span>
                            <span class="login">@{user['username']}</span>
                        </div>
                    </div>
                    <a href="/@{user['username']}" class="dropdown-item">{SVG_USER} Профиль</a>
                    <a href="/settings" class="dropdown-item">{SVG_SETTINGS} Настройки</a>
                    <a href="/logout" class="dropdown-item danger">{SVG_LOGOUT} Выход</a>
                </div>
            </div>
        </div>
        """
    else:
        nav_html = f"""
        <div style="display:flex; align-items:center; gap:20px;">
            <a href="/login" style="color:var(--text-main); font-weight:700;">Вход</a>
            <a href="/register" class="btn-primary">Регистрация</a>
        </div>
        """

    sidebar_html = ""
    if user:
        sidebar_html = f"""
        <div class="sidebar">
            <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
            <a href="/saved" class="{'active' if active_page == 'saved' else ''}">{SVG_SAVE} Избранное</a>
            <a href="/@{user['username']}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} Профиль</a>
        </div>
        """

    # Keyboard navigation script if on post view
    keyboard_js = ""
    if is_post_view:
        keyboard_js = f"""
        <script>
            document.addEventListener('keydown', function(e) {{
                if (e.target.tagName.toLowerCase() === 'input' || e.target.tagName.toLowerCase() === 'textarea') return;
                
                if (e.key === 'ArrowUp' && '{prev_id}') {{
                    e.preventDefault(); window.location.href = '/post/{prev_id}';
                }} else if (e.key === 'ArrowDown' && '{next_id}') {{
                    e.preventDefault(); window.location.href = '/post/{next_id}';
                }}
            }});
        </script>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>sol.id</title>
        {CSS_STYLES}
    </head>
    <body>
        <div class="app-layout">
            <div class="topbar">
                <a href="/" class="logo">{SVG_LOGO} sol.id</a>
                {nav_html}
            </div>
            {sidebar_html}
            <div class="main-content" style="{'grid-column: 1 / -1;' if not user else ''}">
                {content_html}
            </div>
        </div>
        
        <!-- Panorama Modal -->
        <div id="panorama" class="overlay" onclick="closePanorama()">
            <button class="close-overlay">&times;</button>
            <img id="panorama-img" src="" onclick="event.stopPropagation()">
        </div>

        <div class="bottom-nav">
            <a href="/" class="{'active' if active_page == 'feed' else ''}">{SVG_FEED} Лента</a>
            <a href="/write" class="plus-btn">{SVG_PLUS}</a>
            <a href="/@{user['username'] if user else 'login'}" class="{'active' if active_page == 'profile' else ''}">{SVG_USER} Профиль</a>
        </div>
        {keyboard_js}
    </body>
    </html>
    """

# ==========================================
# МАРШРУТЫ
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def read_feed(request: Request):
    user = get_current_user(request)
    feed_posts = [p for p in posts_db if p.get('visibility') == 'feed']
    
    if not feed_posts:
        content = """
        <div style="text-align:center; padding: 80px 20px; color: var(--text-muted);">
            <h3 style="font-size: 28px; color: #fff; margin-bottom: 15px;">Здесь пока пусто</h3>
            <p style="font-size: 18px;">Станьте первым, кто опубликует пост!</p>
        </div>
        """
    else:
        cards = ""
        for post in feed_posts:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="height:200px; background:#222; display:flex; align-items:center; justify-content:center;">{SVG_IMAGE}</div>'
            score = post['upvotes'] - post['downvotes']
            
            cards += f"""
            <a href="/post/{post['id']}" class="feed-card">
                {img_html}
                <div class="feed-card-info">
                    <div class="feed-card-title">{post['title']}</div>
                    <div class="feed-card-author">
                        <img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{post['author']}
                        <span style="margin-left:auto;">{SVG_UP} {score}</span>
                    </div>
                </div>
            </a>
            """
        content = f'<div class="feed-grid">{cards}</div>'
        
    return HTMLResponse(content=render_layout(content, user, "feed"))

@app.get("/saved", response_class=HTMLResponse)
async def saved_posts(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    saved_ids = user.get('saved_posts', [])
    saved_posts_list = [p for p in posts_db if p['id'] in saved_ids]
    
    if not saved_posts_list:
        content = "<div style='text-align:center; padding:60px; color:var(--text-muted); font-size:18px;'>У вас пока нет избранных постов.</div>"
    else:
        cards = ""
        for post in saved_posts_list:
            author = users_db.get(post['author'])
            ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
            img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="height:200px; background:#222; display:flex; align-items:center; justify-content:center;">{SVG_IMAGE}</div>'
            cards += f"""
            <a href="/post/{post['id']}" class="feed-card">
                {img_html}
                <div class="feed-card-info">
                    <div class="feed-card-title">{post['title']}</div>
                    <div class="feed-card-author"><img src="{ava}" style="width:24px;height:24px;border-radius:50%;"> @{post['author']}</div>
                </div>
            </a>
            """
        content = f'<h2 style="margin-bottom:25px;">Избранное</h2><div class="feed-grid">{cards}</div>'
        
    return HTMLResponse(content=render_layout(content, user, "saved"))

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    content = f"""
    <div class="auth-container">
        <form class="auth-form" action="/register" method="post">
            <h2>Регистрация</h2>
            <div class="input-group"><input type="text" name="username" placeholder="Логин (без @)" required></div>
            <div class="input-group"><input type="text" name="display_name" placeholder="Отображаемое имя" required></div>
            <div class="input-group">
                <input type="password" name="password" placeholder="Пароль" required>
                <span class="pass-toggle" onclick="togglePassword(this)">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <div class="input-group">
                <input type="password" name="confirm_password" placeholder="Подтвердите пароль" required>
                <span class="pass-toggle" onclick="togglePassword(this)">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <div class="checkbox-group">
                <input type="checkbox" id="privacy" name="privacy" required>
                <label for="privacy">Я согласен с <a href="#">политикой конфиденциальности</a>.</label>
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:14px;">Создать аккаунт</button>
            <div style="text-align:center; margin-top:20px; font-size:15px; color: var(--text-muted);">Уже есть аккаунт? <a href="/login">Войти</a></div>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, None))

@app.post("/register")
async def register_user(username: str = Form(...), display_name: str = Form(...), password: str = Form(...), confirm_password: str = Form(...)):
    if username in users_db:
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Пользователь уже существует</div><a href="/register" class="btn-primary" style="margin-top:10px;">Назад</a></div></div>', None))
    if password != confirm_password:
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Пароли не совпадают</div><a href="/register" class="btn-primary" style="margin-top:10px;">Назад</a></div></div>', None))
    
    users_db[username] = {
        "username": username,
        "password": pwd_context.hash(password),
        "display_name": display_name,
        "avatar": None,
        "saved_posts": []
    }
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = f"""
    <div class="auth-container">
        <form class="auth-form" action="/login" method="post">
            <h2>Вход</h2>
            <div class="input-group"><input type="text" name="username" placeholder="Логин" required></div>
            <div class="input-group">
                <input type="password" name="password" placeholder="Пароль" required>
                <span class="pass-toggle" onclick="togglePassword(this)">{SVG_EYE}{SVG_EYE_OFF}</span>
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:14px;">Войти</button>
            <div style="text-align:center; margin-top:20px; font-size:15px; color: var(--text-muted);">Нет аккаунта? <a href="/register">Создать</a></div>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, None))

@app.post("/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users_db.get(username)
    if not user or not pwd_context.verify(password, user["password"]):
        return HTMLResponse(content=render_layout('<div class="auth-container"><div class="auth-form"><div class="error">Неверный логин или пароль</div><a href="/login" class="btn-primary" style="margin-top:10px;">Назад</a></div></div>', None))

    session_token = str(uuid.uuid4())
    sessions[session_token] = username
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="session_token", value=session_token, httponly=True)
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
    if not user: return RedirectResponse(url="/login")
    
    content = f"""
    <div style="max-width: 700px; margin: 0 auto; width: 100%;">
        <h2 style="margin-bottom: 25px; font-weight: 700; font-size: 28px;">Настройки</h2>
        <div style="background: var(--card-bg); padding: 25px; border-radius: 16px; border: 1px solid var(--border-color); margin-bottom: 20px;">
            <h3 style="margin-bottom: 15px; font-weight: 500; font-size: 20px;">Язык интерфейса</h3>
            <div class="input-group" style="max-width: 350px;">
                <select style="padding: 12px;">
                    <option value="ru">Русский (RU)</option>
                    <option value="en">English (EN)</option>
                </select>
            </div>
        </div>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "settings"))

@app.get("/write", response_class=HTMLResponse)
async def create_post_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    content = f"""
    <h2 style="margin-bottom: 30px; font-weight: 700; font-size: 32px;">Новый пост</h2>
    <form action="/write" method="post" enctype="multipart/form-data" class="create-layout">
        
        <!-- Left side: Upload Zone -->
        <div class="dropzone" id="dropzone">
            <div id="dropzone-text">
                {SVG_IMAGE}
                <div style="margin-top:20px; font-size:20px; font-weight:700; color:#fff;">Перетащите файлы сюда</div>
                <div style="margin-top:10px; font-size:15px; color:var(--text-muted);">JPEG, PNG, GIF до 5 штук</div>
                <div style="margin-top:20px; background:#2a2a2a; padding:12px 24px; border-radius:8px; color:#fff; font-weight:500; border:1px solid var(--border-color); cursor:pointer;" onclick="document.getElementById('file-input').click()">Выбрать файлы</div>
            </div>
            <div id="file-list" style="width:100%; display:flex; flex-direction:column; gap:10px;"></div>
            <input id="file-input" type="file" name="images" multiple accept="image/*" style="display:none;" onchange="handleFiles(this)">
        </div>

        <!-- Right side: Post Info -->
        <div class="create-sidebar">
            <div class="input-group">
                <label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">Название *</label>
                <input type="text" name="title" placeholder="Как назовёте пост" required style="padding:14px;">
            </div>
            
            <div class="input-group">
                <label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">Описание</label>
                <textarea name="content" placeholder="Пара слов о том, что тут, можно с #тегами" style="min-height:180px; resize:vertical; padding:14px;"></textarea>
            </div>

            <div class="input-group">
                <label style="font-size:15px; font-weight:700; color:#fff; margin-bottom:8px; display:block;">Кто увидит</label>
                <div style="display:flex; gap:10px;">
                    <label style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--accent-color); color:var(--accent-color); cursor:pointer;">
                        <input type="radio" name="visibility" value="feed" checked style="display:none;">
                        Все, в ленте
                    </label>
                    <label style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg-color); padding:12px; border-radius:8px; border:1px solid var(--border-color); color:var(--text-muted); cursor:pointer;">
                        <input type="radio" name="visibility" value="link" style="display:none;">
                        По ссылке
                    </label>
                </div>
            </div>

            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; padding:16px; font-size:16px; margin-top:10px;">Опубликовать</button>
        </div>
    </form>
    """
    return HTMLResponse(content=render_layout(content, user, "feed"))

@app.post("/write")
async def create_post(request: Request, title: str = Form(...), content: str = Form(...), visibility: str = Form("feed"), images: List[UploadFile] = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    img_b64_list = []
    if images and images[0].filename:
        for img in images[:5]: 
            b64 = await image_to_base64(img)
            if b64: img_b64_list.append(b64)
            
    new_post = {
        "id": str(uuid.uuid4())[:6],
        "author": user["username"],
        "title": title,
        "content": content,
        "images": img_b64_list,
        "visibility": visibility,
        "upvotes": 0,
        "downvotes": 0,
        "comments": []
    }
    posts_db.insert(0, new_post)
    return RedirectResponse(url=f"/post/{new_post['id']}", status_code=status.HTTP_302_FOUND)

@app.post("/vote/{post_id}/{action}")
async def vote_post(post_id: str, action: str, request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if post:
        if action == "up": post['upvotes'] += 1
        elif action == "down": post['downvotes'] += 1
    
    return RedirectResponse(url=f"/post/{post_id}", status_code=status.HTTP_302_FOUND)

@app.post("/save/{post_id}")
async def save_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    if 'saved_posts' not in users_db[user['username']]:
        users_db[user['username']]['saved_posts'] = []
        
    if post_id in users_db[user['username']]['saved_posts']:
        users_db[user['username']]['saved_posts'].remove(post_id)
    else:
        users_db[user['username']]['saved_posts'].append(post_id)
        
    return RedirectResponse(url=f"/post/{post_id}", status_code=status.HTTP_302_FOUND)

@app.post("/delete/{post_id}")
async def delete_post(post_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    global posts_db
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if post and post['author'] == user['username']:
        posts_db = [p for p in posts_db if p['id'] != post_id]
        # Remove from all users' saved lists
        for u in users_db.values():
            if 'saved_posts' in u and post_id in u['saved_posts']:
                u['saved_posts'].remove(post_id)
                
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@app.get("/post/{post_id}", response_class=HTMLResponse)
async def view_post(request: Request, post_id: str):
    user = get_current_user(request)
    post = next((p for p in posts_db if p['id'] == post_id), None)
    if not post:
        raise HTTPException(404, "Post not found")
        
    author = users_db.get(post['author'])
    ava = author.get('avatar') if author and author.get('avatar') else f"https://api.dicebear.com/7.x/avataaars/svg?seed={post['author']}"
    score = post['upvotes'] - post['downvotes']
    
    # Logic for Prev/Next navigation (all posts, even link-only)
    idx = next((i for i, p in enumerate(posts_db) if p['id'] == post_id), -1)
    prev_id = posts_db[idx - 1]['id'] if idx > 0 else ""
    next_id = posts_db[idx + 1]['id'] if idx < len(posts_db) - 1 and idx != -1 else ""
    
    # Save button state
    is_saved = user and post_id in user.get('saved_posts', [])
    save_icon = SVG_SAVED if is_saved else SVG_SAVE
    save_action = "Убрать из избранного" if is_saved else "В избранное"

    # Delete button
    delete_btn = f'''
    <form action="/delete/{post_id}" method="post" style="margin:0;" onsubmit="return confirm('Вы уверены, что хотите удалить пост?');">
        <button type="submit" class="action-btn" style="color:var(--danger-color);">{SVG_TRASH}</button>
    </form>
    ''' if user and user['username'] == post['author'] else ''

    # Media HTML
    if post['images']:
        # Assign unique classes for JS navigation
        media_html = "".join([f'<img src="{img}" style="max-width:100%; max-height:80vh; object-fit:contain; display:{"" if i==0 else "none"};" class="carousel-img" onclick="openPanorama(this.src)">' for i, img in enumerate(post['images'])])
        if len(post['images']) > 1:
            media_html += f"""
            <div style="position:absolute; bottom:20px; left:0; width:100%; display:flex; justify-content:center; gap:15px;">
                <button class="btn-primary" style="padding:8px 16px; background:rgba(0,0,0,0.7); color:#fff; border:none;" onclick="changeImg(-1)">&lt;</button>
                <button class="btn-primary" style="padding:8px 16px; background:rgba(0,0,0,0.7); color:#fff; border:none;" onclick="changeImg(1)">&gt;</button>
            </div>
            <script>
                let currentImg = 0; let imgs = document.querySelectorAll('.carousel-img');
                function showImg(idx) {{ 
                    imgs.forEach((img, i) => img.style.display = i === idx ? 'block' : 'none'); 
                }}
                function changeImg(dir) {{ 
                    currentImg = (currentImg + dir + imgs.length) % imgs.length; 
                    showImg(currentImg); 
                }}
                document.addEventListener('keydown', function(e) {{
                    if (e.target.tagName.toLowerCase() === 'input' || e.target.tagName.toLowerCase() === 'textarea') return;
                    if (e.key === 'ArrowLeft') {{ e.preventDefault(); changeImg(-1); }}
                    if (e.key === 'ArrowRight') {{ e.preventDefault(); changeImg(1); }}
                }});
            </script>
            """
    else:
        media_html = f'<div style="color:#555;">{SVG_IMAGE}</div>'

    content = f"""
    <div style="margin-bottom:20px; display:flex; justify-content:space-between; align-items:center;">
        <a href="/" style="display:flex; align-items:center; gap:10px; color:var(--text-muted); font-weight:500; font-size:16px;">{SVG_BACK} Назад в ленту</a>
        <span style="color:var(--text-muted); font-size:14px;">Навигация: <kbd style="background:#333; padding:2px 5px; border-radius:4px;">↑</kbd> <kbd style="background:#333; padding:2px 5px; border-radius:4px;">↓</kbd> посты, <kbd style="background:#333; padding:2px 5px; border-radius:4px;">←</kbd> <kbd style="background:#333; padding:2px 5px; border-radius:4px;">→</kbd> фото</span>
    </div>
    <div class="post-view">
        <div class="post-media">
            {media_html}
        </div>
        <div class="post-details">
            <div class="post-author">
                <a href="/@{post['author']}"><img src="{ava}"></a>
                <div>
                    <a href="/@{post['author']}" style="color:#fff; font-weight:700; font-size:18px;">{author['display_name'] if author else post['author']}</a>
                    <div style="font-size:14px; color:var(--text-muted);">@{post['author']}</div>
                </div>
            </div>
            <div class="post-title selectable">{post['title']}</div>
            <div class="post-desc selectable">{post['content']}</div>
            
            <div class="actions-row">
                <div class="vote-controls">
                    <form action="/vote/{post['id']}/up" method="post" style="margin:0;">
                        <button type="submit" class="vote-btn up">{SVG_UP}</button>
                    </form>
                    <span class="vote-count">{score}</span>
                    <form action="/vote/{post['id']}/down" method="post" style="margin:0;">
                        <button type="submit" class="vote-btn down">{SVG_DOWN}</button>
                    </form>
                </div>
                
                <form action="/save/{post['id']}" method="post" style="margin:0;">
                    <button type="submit" class="action-btn" title="{save_action}">{save_icon}</button>
                </form>
                
                <button class="action-btn" onclick="copyLink()" title="Скопировать ссылку">{SVG_LINK}</button>
                
                {delete_btn}
            </div>
            
            <div class="comments-section" style="flex:1; border-top:1px solid var(--border-color); padding-top:20px; overflow-y:auto;">
                <h3 style="margin-bottom:15px; font-weight:700; font-size:18px;">Комментарии ({len(post['comments'])})</h3>
                <div style="background:var(--bg-color); padding:12px; border-radius:8px; margin-bottom:20px; border: 1px solid var(--border-color); display:flex; gap:10px;">
                    <input type="text" placeholder="Напишите комментарий..." style="flex:1; background:transparent; border:none; color:#fff; outline:none; font-size:15px;">
                    <button class="btn-primary" style="padding:5px 15px;">Отправить</button>
                </div>
                <div style="font-size:15px; color:var(--text-muted); text-align:center; padding:20px;">Пока нет комментариев.</div>
            </div>
        </div>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "feed", prev_id=prev_id, next_id=next_id, is_post_view=True))

@app.get("/@{username}", response_class=HTMLResponse)
async def view_profile(request: Request, username: str):
    current_user = get_current_user(request)
    profile_user = users_db.get(username)
    if not profile_user:
        raise HTTPException(404, "User not found")
        
    ava = profile_user.get('avatar') or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
    
    # Filter profile posts to only show 'feed' posts (or if it's the owner, show all? Let's show only 'feed' on public profile, but all on own profile)
    if current_user and current_user['username'] == username:
        user_posts = [p for p in posts_db if p['author'] == username]
    else:
        user_posts = [p for p in posts_db if p['author'] == username and p.get('visibility') == 'feed']
        
    posts_html = ""
    for post in user_posts:
        img_html = f'<img src="{post["images"][0]}">' if post['images'] else f'<div style="height:200px; background:#222; display:flex; align-items:center; justify-content:center;">{SVG_IMAGE}</div>'
        posts_html += f"""
        <a href="/post/{post['id']}" class="feed-card">
            {img_html}
            <div class="feed-card-info">
                <div class="feed-card-title">{post['title']}</div>
            </div>
        </a>
        """
        
    if not posts_html:
        posts_html = '<div style="color:var(--text-muted); font-size:18px;">Пока нет постов.</div>'

    edit_btn = f'<a href="/edit_profile" class="btn-primary" style="background:#333; color:#fff;">Редактировать профиль</a>' if current_user and current_user['username'] == username else ''

    content = f"""
    <div class="profile-header">
        <img src="{ava}" class="profile-avatar">
        <div class="profile-details">
            <h1>{profile_user['display_name']}</h1>
            <p>@{username}</p>
            <p style="margin-top:8px; font-size:15px; font-weight:500;">{len(user_posts)} постов</p>
        </div>
        <div style="margin-left:auto;">{edit_btn}</div>
    </div>
    
    <div style="border-bottom: 1px solid var(--border-color); margin-bottom: 25px; display:flex; gap:25px;">
        <a href="#" style="color:#fff; padding-bottom:12px; border-bottom:3px solid var(--accent-color); font-size:18px; font-weight:700;">Посты</a>
    </div>
    
    <div class="feed-grid">
        {posts_html}
    </div>
    """
    return HTMLResponse(content=render_layout(content, current_user, "profile"))

@app.get("/edit_profile", response_class=HTMLResponse)
async def edit_profile_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/login")
    
    content = f"""
    <div style="max-width: 600px; margin: 0 auto; background: var(--card-bg); padding: 40px; border-radius: 16px; border: 1px solid var(--border-color); width: 100%;">
        <h2 style="margin-bottom:30px; font-weight:700; font-size:28px;">Редактор профиля</h2>
        <form action="/edit_profile" method="post" enctype="multipart/form-data">
            <div class="input-group">
                <label style="font-size:15px; color:var(--text-muted); margin-bottom:8px; display:block; font-weight:500;">Отображаемое имя</label>
                <input type="text" name="display_name" value="{user['display_name']}" required style="padding:14px;">
            </div>
            <div class="input-group">
                <label style="font-size:15px; color:var(--text-muted); margin-bottom:8px; display:block; font-weight:500;">Аватарка (JPEG/PNG)</label>
                <input type="file" name="avatar" accept="image/*" style="padding: 12px;">
            </div>
            <button type="submit" class="btn-primary" style="width:100%; justify-content:center; margin-top:20px; padding:14px;">Сохранить изменения</button>
        </form>
    </div>
    """
    return HTMLResponse(content=render_layout(content, user, "profile"))

@app.post("/edit_profile")
async def edit_profile(request: Request, display_name: str = Form(...), avatar: UploadFile = File(None)):
    user = get_current_user(request)
    if not user: raise HTTPException(401)
    
    users_db[user['username']]['display_name'] = display_name
    
    if avatar and avatar.filename:
        users_db[user['username']]['avatar'] = await image_to_base64(avatar)
        
    return RedirectResponse(url=f"/@{user['username']}", status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
