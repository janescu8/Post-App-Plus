# =============================================================================
# 🔧 頁面設定 | Page Configuration
# =============================================================================
import streamlit as st
st.set_page_config(page_title="Mini 社群平台 | Mini Social Platform", layout="wide")

# =============================================================================
# 📦 模組載入 | Module Imports
# =============================================================================
import sqlite3
import bcrypt
import io
import os
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =============================================================================
# ☁️ Google Drive 上傳功能
import atexit
from googleapiclient.http import MediaIoBaseDownload

# =============================================================================
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)

DRIVE_SERVICE = get_drive_service()
DRIVE_FOLDER_ID = st.secrets["drive"]["folder_id"]

# 初始化 DB 路徑
DB_PATH = "community.db"

# 嘗試從 Google Drive 下載 DB
@st.cache_resource
def download_db_from_drive(filename="community.db"):
    results = DRIVE_SERVICE.files().list(q=f"'{DRIVE_FOLDER_ID}' in parents and name='{filename}'",
                                         spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    if items:
        file_id = items[0]['id']
        request = DRIVE_SERVICE.files().get_media(fileId=file_id)
        with open(filename, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return file_id
    return None

@st.cache_resource
def connect_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# 嘗試載入 DB
db_file_id = download_db_from_drive()
conn = connect_db()
c = conn.cursor()

# 初始化資料表
c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        image_url TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        UNIQUE(user_id, post_id)
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")
conn.commit()

def upload_db_to_drive(file_id=None, filename="community.db"):
    media = MediaIoBaseUpload(open(filename, 'rb'), mimetype='application/x-sqlite3')
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    if file_id:
        file = DRIVE_SERVICE.files().update(fileId=file_id, media_body=media).execute()
    else:
        file = DRIVE_SERVICE.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return file.get("id")

# 如果第一次沒載到 DB（等於是第一次建立），就立即上傳一份空 DB
if db_file_id is None:
    db_file_id = upload_db_to_drive()
    st.info("📂 已建立並上傳初始資料庫 community.db 至 Google Drive。")

def upload_to_drive(uploaded_file):
    # 上傳圖片到 Google Drive 並回傳直接顯示的圖片網址
    if uploaded_file is None:
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"img_{timestamp}_{uploaded_file.name}"
    file_bytes = uploaded_file.read()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=uploaded_file.type, resumable=True)
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    uploaded = DRIVE_SERVICE.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()
    file_id = uploaded.get("id")

    # 設定檔案為公開可讀
    DRIVE_SERVICE.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
    ).execute()

    return f"https://drive.google.com/uc?export=view&id={file_id}"

# =============================================================================
# 🔐 使用者登入 / 註冊畫面 | Login / Register
# =============================================================================
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 登入 / 註冊 Mini 社群平台")
    auth_mode = st.radio("請選擇操作 | Select action", ["登入 | Login", "註冊 | Register"])

    username = st.text_input("使用者名稱 | Username")
    password = st.text_input("密碼 | Password", type="password")

    if st.button("送出"):
        if auth_mode.startswith("註冊"):
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            try:
                c.execute("INSERT INTO users (username, pw_hash) VALUES (?, ?)", (username, hashed_pw))
                conn.commit()
                upload_db_to_drive(filename=DB_PATH, file_id=db_file_id)
                st.success("✅ 註冊成功！請重新登入。")
            except sqlite3.IntegrityError:
                st.error("⚠️ 使用者名稱已存在")
        else:
            row = c.execute("SELECT id, pw_hash, is_admin FROM users WHERE username = ?", (username,)).fetchone()
            if row and bcrypt.checkpw(password.encode(), row[1].encode()):
                st.session_state.user = {
                    "id": row[0],
                    "username": username,
                    "is_admin": bool(row[2])
                }
                st.session_state["pending_rerun"] = True
                st.stop()
            else:
                st.error("❌ 帳號或密碼錯誤")
    st.stop()

# =============================================================================
# 📬 私訊功能 | Messaging
# =============================================================================
menu = st.sidebar.radio("選單 | Menu", ["首頁 | Home", "私訊 | Messages"])

if menu == "私訊 | Messages":
    st.title("📨 私訊 | Direct Messages")
    all_users = [r[0] for r in c.execute("SELECT username FROM users").fetchall() if r[0] != st.session_state.user["username"]]
    to_user = st.selectbox("選擇收件人 | Choose recipient", all_users)
    message_content = st.text_area("內容 | Message")
    if st.button("送出 | Send"):
        to_id = c.execute("SELECT id FROM users WHERE username = ?", (to_user,)).fetchone()[0]
        send_message(st.session_state.user["id"], to_id, message_content)
        st.success("✅ 訊息已送出")

    st.markdown("---")
    st.subheader("📨 歷史訊息 | Message History")
    for mid, sender, receiver, content, created in get_messages(st.session_state.user["id"]):
        st.markdown(f"**{sender} → {receiver}** ({created})\n> {content}")
    st.stop()

# =============================================================================
# 🏠 首頁內容 | Home Interface: 發文 / 圖片 / 留言 / 按讚
# =============================================================================
st.title("📝 發佈貼文 | Create a Post")

with st.form("post_form"):
    content = st.text_area("說些什麼... | What's on your mind?", max_chars=300)
    image_file = st.file_uploader("上傳圖片 | Upload Image", type=["png", "jpg", "jpeg"])
    submitted = st.form_submit_button("發佈 | Post")
    if submitted and content:
        image_url = upload_to_drive(image_file) if image_file else None
        c.execute("INSERT INTO posts (author_id, content, image_url) VALUES (?, ?, ?)",
                  (st.session_state.user["id"], content, image_url))
        conn.commit()
        upload_db_to_drive(filename=DB_PATH, file_id=db_file_id)
        st.success("貼文已發佈！")

st.markdown("---")
st.header("📰 最新貼文 | Latest Posts")

posts = c.execute("SELECT posts.id, users.username, posts.content, posts.image_url, posts.created FROM posts JOIN users ON posts.author_id = users.id ORDER BY posts.created DESC").fetchall()

for post in posts:
    post_id, author, content, image_url, created = post
    st.subheader(f"{author}  🕒 {created}")
    st.write(content)
    if image_url:
        st.image(image_url, use_container_width=True)

    # Like button
    if st.button(f"👍 按讚 | Like", key=f"like_{post_id}"):
        try:
            c.execute("INSERT INTO likes (user_id, post_id) VALUES (?, ?)",
                      (st.session_state.user["id"], post_id))
            conn.commit()
            upload_db_to_drive(filename=DB_PATH, file_id=db_file_id)  # ✅ 縮排正確，放在 try 裡
        except sqlite3.IntegrityError:
            st.warning("你已經按過讚了！")


    like_count = c.execute("SELECT COUNT(*) FROM likes WHERE post_id = ?", (post_id,)).fetchone()[0]
    st.caption(f"❤️ {like_count} 個讚")

    # 刪除貼文（只有作者能看到）
    if st.session_state.user["username"] == author:
        if st.button("🗑️ 刪除貼文 | Delete Post", key=f"delete_{post_id}"):
            c.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            c.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
            c.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
            conn.commit()
            upload_db_to_drive(filename=DB_PATH, file_id=db_file_id)
            st.success("✅ 貼文已刪除")
            st.session_state["pending_rerun"] = True

    # 留言顯示與新增
    with st.expander("💬 留言 / Comments"):
        comments = c.execute("SELECT users.username, comments.content, comments.created FROM comments JOIN users ON comments.user_id = users.id WHERE comments.post_id = ? ORDER BY comments.created ASC", (post_id,)).fetchall()
        for username, text, ctime in comments:
            st.markdown(f"**{username}**：{text} _(🕒 {ctime})_")

        comment_input = st.text_input("留言內容 | Your comment", key=f"comment_{post_id}")
        if st.button("送出留言 | Submit", key=f"submit_comment_{post_id}") and comment_input:
            c.execute("INSERT INTO comments (user_id, post_id, content) VALUES (?, ?, ?)",
                      (st.session_state.user["id"], post_id, comment_input))
            conn.commit()
            upload_db_to_drive(filename=DB_PATH, file_id=db_file_id)
            st.session_state["pending_rerun"] = True

    st.markdown("---")

# ✅ 安全統一觸發 rerun（避免 AttributeError）
if st.session_state.get("pending_rerun") and st.session_state.user is not None:
    st.session_state["pending_rerun"] = False
    st.rerun()

