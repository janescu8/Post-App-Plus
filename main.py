import streamlit as st
import sqlite3
import bcrypt
import io
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -----------------------
# 1. 讀取 GCP & Drive
# -----------------------
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)

DRIVE_SERVICE = get_drive_service()
DRIVE_FOLDER_ID = st.secrets["drive"]["folder_id"]

def upload_to_drive(uploaded_file):
    filename = uploaded_file.name
    media = MediaIoBaseUpload(io.BytesIO(uploaded_file.read()),
                              mimetype=uploaded_file.type,
                              resumable=True)
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    file = DRIVE_SERVICE.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()
    return file.get("webViewLink")

# -----------------------
# 2. 初始化 SQLite
# -----------------------
DB_PATH = "/mnt/data/community.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        image_url TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_id) REFERENCES users(id)
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        UNIQUE(user_id, post_id)
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

init_db()

# -----------------------
# 3. CRUD 函式
# -----------------------
def register_user(username, password):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        c.execute("INSERT INTO users (username,pw_hash) VALUES (?,?)",
                  (username, pw_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def authenticate_user(username, password):
    c.execute("SELECT id,pw_hash,is_admin FROM users WHERE username=?", (username,))
    row = c.fetchone()
    if row and bcrypt.checkpw(password.encode(), row[1].encode()):
        return {"id": row[0], "username": username, "is_admin": bool(row[2])}
    return None

def create_post(author_id, content, image_url=None):
    c.execute("INSERT INTO posts (author_id,content,image_url) VALUES (?,?,?)",
              (author_id, content, image_url))
    conn.commit()

def get_posts():
    c.execute("""
    SELECT p.id, u.username, p.content, p.image_url, p.created
      FROM posts p JOIN users u ON p.author_id=u.id
     ORDER BY p.created DESC
    """)
    return c.fetchall()

def has_liked(user_id, post_id):
    c.execute("SELECT 1 FROM likes WHERE user_id=? AND post_id=?", (user_id, post_id))
    return c.fetchone() is not None

def like_post(user_id, post_id):
    try:
        c.execute("INSERT INTO likes (user_id,post_id) VALUES (?,?)", (user_id, post_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass

def unlike_post(user_id, post_id):
    c.execute("DELETE FROM likes WHERE user_id=? AND post_id=?", (user_id, post_id))
    conn.commit()

def get_like_count(post_id):
    c.execute("SELECT COUNT(*) FROM likes WHERE post_id=?", (post_id,))
    return c.fetchone()[0]

def add_comment(user_id, post_id, content):
    c.execute("INSERT INTO comments (user_id,post_id,content) VALUES (?,?,?)",
              (user_id, post_id, content))
    conn.commit()

def get_comments(post_id):
    c.execute("""
    SELECT u.username, c.content, c.created
      FROM comments c JOIN users u ON c.user_id=u.id
     WHERE c.post_id=?
     ORDER BY c.created
    """, (post_id,))
    return c.fetchall()

def send_message(sender_id, receiver_id, content):
    c.execute("INSERT INTO messages (sender_id,receiver_id,content) VALUES (?,?,?)",
              (sender_id, receiver_id, content))
    conn.commit()

def get_messages(user_id):
    c.execute("""
    SELECT m.id, u1.username, u2.username, m.content, m.created
      FROM messages m
      JOIN users u1 ON m.sender_id=u1.id
      JOIN users u2 ON m.receiver_id=u2.id
     WHERE m.sender_id=? OR m.receiver_id=?
     ORDER BY m.created DESC
    """, (user_id, user_id))
    return c.fetchall()

def toggle_admin(user_id):
    c.execute("UPDATE users SET is_admin = 1 - is_admin WHERE id=?", (user_id,))
    conn.commit()

def delete_post(post_id):
    c.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()

# -----------------------
# 4. Streamlit UI
# -----------------------
st.set_page_config(page_title="Mini 社群平台", layout="wide")
if "user" not in st.session_state:
    st.session_state.user = None

# 登入 / 註冊
if st.session_state.user is None:
    st.title("🎉 歡迎來到 Mini 社群平台")
    choice = st.sidebar.selectbox("選擇動作", ["登入", "註冊"])
    if choice == "註冊":
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("註冊"):
            if register_user(u, p):
                st.success("註冊成功，請切換到登入")
            else:
                st.error("帳號已存在")
    else:
        u = st.text_input("帳號", key="login_u")
        p = st.text_input("密碼", type="password", key="login_p")
        if st.button("登入"):
            user = authenticate_user(u, p)
            if user:
                st.session_state.user = user
                st.experimental_rerun()
            else:
                st.error("帳號或密碼錯誤")
    st.stop()

# 已登入
user = st.session_state.user
st.sidebar.write(f"👤 {user['username']} {'(Admin)' if user['is_admin'] else ''}")
action = st.sidebar.radio("功能選單",
    ["主頁", "私訊", "後台管理", "登出"])

if action == "登出":
    st.session_state.user = None
    st.experimental_rerun()

# 主頁：貼文、按讚、留言
if action == "主頁":
    st.title("社群廣場")
    with st.expander("發表新貼文"):
        text = st.text_area("內容")
        img = st.file_uploader("上傳圖片（選填）", type=["png","jpg","jpeg"])
        if st.button("貼文", on_click=lambda: create_post(
                user["id"], text,
                upload_to_drive(img) if img else None
            )):
            st.experimental_rerun()

    for pid, author, content, img_url, created in get_posts():
        st.markdown("---")
        st.write(f"**{author}** 於 {created}")
        st.write(content)
        if img_url:
            st.image(img_url, use_column_width=True)
        # 按讚 / 取消
        liked = has_liked(user["id"], pid)
        like_label = "❤️" if liked else "🤍"
        st.button(f"{like_label} {get_like_count(pid)}",
                  key=f"like_{pid}",
                  on_click=lambda p=pid: (
                    like_post(user["id"], p) if not has_liked(user["id"], p)
                    else unlike_post(user["id"], p),
                    st.experimental_rerun()
                  ))
        # 留言
        with st.expander("💬 留言"):
            for u2, cmt, ct in get_comments(pid):
                st.write(f"- **{u2}** ({ct}): {cmt}")
            new_c = st.text_input("新增留言", key=f"cmt_{pid}")
            if st.button("送出", key=f"sendc_{pid}",
                         on_click=lambda p=pid, nc=new_c: (
                             add_comment(user["id"], p, nc),
                             st.experimental_rerun()
                         )):
                pass

# 私訊
elif action == "私訊":
    st.title("📨 私訊")
    users = [r[0] for r in c.execute("SELECT username FROM users").fetchall()]
    to = st.selectbox("選擇對象", [u for u in users if u != user["username"]])
    msg = st.text_area("內容")
    if st.button("送出"):
        c.execute("SELECT id FROM users WHERE username=?", (to,))
        rid = c.fetchone()[0]
        send_message(user["id"], rid, msg)
        st.success("已送出")
        st.experimental_rerun()
    st.markdown("----")
    for mid, su, ru, mc, mct in get_messages(user["id"]):
        st.write(f"**{su}→{ru}** ({mct}): {mc}")

# Admin 後台
elif action == "後台管理":
    if not user["is_admin"]:
        st.error("只有 Admin 能進入")
        st.stop()
    st.title("🔧 Admin 後台")
    st.subheader("使用者管理")
    for uid, uname, isadm in c.execute(
        "SELECT id,username,is_admin FROM users"
    ).fetchall():
        cols = st.columns([3,1,1])
        cols[0].write(uname)
        cols[1].write("Admin" if isadm else "User")
        if cols[2].button("切換", key=f"tog_{uid}",
                          on_click=lambda u=uid: (
                              toggle_admin(u), st.experimental_rerun()
                          )):
            pass

    st.subheader("文章管理")
    for pid, author, content, img_url, created in get_posts():
        cols = st.columns([4,1])
        cols[0].write(f"{author}: {content[:30]}")
        if cols[1].button("刪除", key=f"del_{pid}",
                          on_click=lambda p=pid: (
                              delete_post(p), st.experimental_rerun()
                          )):
            pass
