import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
import bcrypt
import datetime
import os
import json
from google.oauth2 import service_account

# --- GCP 認證（透過 secrets.toml） ---
creds_info = st.secrets["gcp_service_account"]
creds = service_account.Credentials.from_service_account_info(creds_info)

# --- 資料庫模型 ---
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id        = Column(Integer, primary_key=True)
    username  = Column(String, unique=True, nullable=False)
    pw_hash   = Column(String, nullable=False)
    is_admin  = Column(Boolean, default=False)

class Post(Base):
    __tablename__ = "posts"
    id        = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    content   = Column(Text, nullable=True)
    image     = Column(String, nullable=True)
    created   = Column(DateTime, default=datetime.datetime.utcnow)
    author    = relationship("User")

class Comment(Base):
    __tablename__ = "comments"
    id        = Column(Integer, primary_key=True)
    post_id   = Column(Integer, ForeignKey("posts.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    content   = Column(Text, nullable=False)
    created   = Column(DateTime, default=datetime.datetime.utcnow)
    author    = relationship("User")
    post      = relationship("Post")

class Like(Base):
    __tablename__ = "likes"
    id        = Column(Integer, primary_key=True)
    post_id   = Column(Integer, ForeignKey("posts.id"))
    user_id   = Column(Integer, ForeignKey("users.id"))
    post      = relationship("Post")
    user      = relationship("User")

class Message(Base):
    __tablename__ = "messages"
    id        = Column(Integer, primary_key=True)
    from_id   = Column(Integer, ForeignKey("users.id"))
    to_id     = Column(Integer, ForeignKey("users.id"))
    content   = Column(Text, nullable=False)
    created   = Column(DateTime, default=datetime.datetime.utcnow)
    sender    = relationship("User", foreign_keys=[from_id])
    receiver  = relationship("User", foreign_keys=[to_id])

# 初始化 DB
engine = create_engine("sqlite:///community.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# 上傳資料夾
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Session state
if "user_id" not in st.session_state:
    st.session_state.user_id = None

# --- 回呼函式 ---
def rerun():
    st.experimental_rerun()

def handle_signup(username, password):
    if db.query(User).filter_by(username=username).first():
        st.error("帳號已存在")
    else:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        db.add(User(username=username, pw_hash=pw_hash))
        db.commit()
        st.success("註冊成功，請登入！")


def handle_login(username, password):
    user = db.query(User).filter_by(username=username).first()
    if user and bcrypt.checkpw(password.encode(), user.pw_hash.encode()):
        st.session_state.user_id = user.id
        rerun()
    else:
        st.error("帳號或密碼錯誤")


def handle_post():
    content = st.session_state.get("new_content")
    image_file = st.session_state.get("new_image")
    img_path = None
    if image_file:
        ts = int(datetime.datetime.utcnow().timestamp() * 1000)
        img_path = os.path.join(UPLOAD_DIR, f"{ts}_{image_file.name}")
        with open(img_path, "wb") as f:
            f.write(image_file.getbuffer())
    db.add(Post(author_id=st.session_state.user_id, content=content, image=img_path))
    db.commit()
    st.session_state.new_content = ""
    st.session_state.new_image = None
    rerun()


def handle_like(post_id):
    uid = st.session_state.user_id
    if not db.query(Like).filter_by(post_id=post_id, user_id=uid).first():
        db.add(Like(post_id=post_id, user_id=uid))
        db.commit()
    rerun()


def handle_comment(post_id):
    key = f"new_comment_{post_id}"
    content = st.session_state.get(key)
    if content:
        db.add(Comment(post_id=post_id, author_id=st.session_state.user_id, content=content))
        db.commit()
        st.session_state[key] = ""
    rerun()


def handle_delete_post(post_id):
    p = db.query(Post).get(post_id)
    if p:
        db.delete(p)
        db.commit()
    rerun()


def handle_toggle_admin(user_id):
    u = db.query(User).get(user_id)
    u.is_admin = not u.is_admin
    db.commit()
    rerun()


def handle_send_message(to_username):
    content = st.session_state.get("message_text")
    if content:
        to_user = db.query(User).filter_by(username=to_username).first()
        db.add(Message(from_id=st.session_state.user_id, to_id=to_user.id, content=content))
        db.commit()
        st.session_state.message_text = ""
    rerun()

# --- UI 邏輯 ---
menu = ["登入","註冊"] if st.session_state.user_id is None else ["主頁","私訊","後台","登出"]
choice = st.sidebar.selectbox("選單", menu)

# 未登入
if st.session_state.user_id is None:
    if choice == "登入":
        st.subheader("🔑 登入")
        st.text_input("帳號", key="login_username")
        st.text_input("密碼", type="password", key="login_password")
        st.button("登入", on_click=handle_login, args=(st.session_state.get("login_username"), st.session_state.get("login_password")))
    else:
        st.subheader("🆕 註冊")
        st.text_input("帳號", key="signup_username")
        st.text_input("密碼", type="password", key="signup_password")
        st.button("註冊", on_click=handle_signup, args=(st.session_state.get("signup_username"), st.session_state.get("signup_password")))
    st.stop()

# 已登入
user = db.query(User).get(st.session_state.user_id)
st.sidebar.write(f"👤 {user.username} {'(Admin)' if user.is_admin else ''}")
if choice == "登出":
    st.session_state.user_id = None
    rerun()

# 主頁
if choice == "主頁":
    st.title("社群廣場")
    with st.form("post_form", clear_on_submit=False):
        st.text_area("聊點什麼？", key="new_content")
        st.file_uploader("上傳圖片", type=["png","jpg","jpeg"], key="new_image")
        st.form_submit_button("貼文", on_click=handle_post)
    st.markdown("---")
    for p in db.query(Post).order_by(Post.created.desc()).all():
        st.write(f"**{p.author.username}** 於 {p.created:%Y-%m-%d %H:%M}")
        if p.content: st.write(p.content)
        if p.image: st.image(p.image, use_column_width=True)
        count = db.query(Like).filter_by(post_id=p.id).count()
        st.button(f"👍 {count}", key=f"like_{p.id}", on_click=handle_like, args=(p.id,))
        for c in db.query(Comment).filter_by(post_id=p.id).order_by(Comment.created).all():
            st.write(f"> **{c.author.username}**: {c.content}")
        st.text_input("回應...", key=f"new_comment_{p.id}")
        st.button("送出", key=f"comm_btn_{p.id}", on_click=handle_comment, args=(p.id,))
        st.markdown("---")

# 私訊
elif choice == "私訊":
    st.title("📩 私訊")
    users = db.query(User).filter(User.id != st.session_state.user_id).all()
    names = [u.username for u in users]
    st.selectbox("選擇對象", names, key="msg_to")
    st.text_area("訊息", key="message_text")
    st.button("送出", on_click=handle_send_message, args=(st.session_state.get("msg_to"),))
    st.markdown("---")
    to_user = db.query(User).filter_by(username=st.session_state.get("msg_to")).first()
    for m in db.query(Message).filter(
        ((Message.from_id==st.session_state.user_id)&(Message.to_id==to_user.id))|
        ((Message.from_id==to_user.id)&(Message.to_id==st.session_state.user_id))
    ).order_by(Message.created).all():
        sender = "我" if m.from_id==st.session_state.user_id else to_user.username
        st.write(f"**{sender}** ({m.created:%Y-%m-%d %H:%M})")
        st.write(m.content)

# 後台管理
elif choice == "後台":
    if not user.is_admin:
        st.error("只有 Admin 能進入！")
        st.stop()
    st.title("🔧 Admin 後台")
    st.subheader("使用者管理")
    for u2 in db.query(User).all():
        cols = st.columns([3,1])
        cols[0].write(u2.username)
        cols[1].button("切換Admin", key=f"adm_{u2.id}", on_click=handle_toggle_admin, args=(u2.id,))
    st.markdown("---")
    st.subheader("文章管理")
    for p2 in db.query(Post).
