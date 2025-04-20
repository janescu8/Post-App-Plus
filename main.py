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
# =============================================================================
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build("drive", "v3", credentials=creds)

DRIVE_SERVICE = get_drive_service()
DRIVE_FOLDER_ID = st.secrets["drive"]["folder_id"]

def upload_to_drive(uploaded_file):
    

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
            st.session_state["pending_rerun"] = True

    st.markdown("---")


