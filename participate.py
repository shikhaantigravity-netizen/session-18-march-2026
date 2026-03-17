import streamlit as st
import random
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import gspread
import os

# --- Configuration & Secrets ---
GSHEET_URL = st.secrets.get("GSHEET_URL") or os.environ.get("GSHEET_URL", "")

st.set_page_config(page_title="EngageIQ - Participate", page_icon="✍️", layout="wide")

st.markdown("""
<style>
    .stApp {
        background-color: #f8fafc;
        color: #0f172a;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem;
    }
    .glass-card {
        background: white;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
        padding: 1.5rem;
        border-radius: 1rem;
        margin-bottom: 1rem;
        color: #0f172a;
    }
    .stTextInput>div>div>input, .stTextArea>div>div>textarea {
        color: #0f172a !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-header">EngageIQ</h1>', unsafe_allow_html=True)

# Secure GSheets Connection
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    gs_creds = st.secrets.get("connections", {}).get("gsheets", {})
    gc = gspread.service_account_from_dict(gs_creds) if gs_creds else None
except Exception as e:
    st.error(f"❌ Connection Error: {e}")
    st.info("💡 Make sure your Streamlit Secrets contain the [connections.gsheets] section and GSHEET_URL.")
    conn = None
    gc = None

# Helper: Get Registry
@st.cache_data(ttl=1)
def get_registry():
    cols = ["id", "title", "status", "created_at"]
    if conn is None or gc is None or not GSHEET_URL: 
        return pd.DataFrame(columns=cols)
    try:
        sh = gc.open_by_url(GSHEET_URL)
        ws = sh.worksheet("Registry")
        df = pd.DataFrame(ws.get_all_records())
        if df.empty:
            return pd.DataFrame(columns=cols)
        return df
    except Exception as e:
        return pd.DataFrame(columns=cols)

# Routing Logic
target_quiz_id = st.query_params.get("quiz")
if isinstance(target_quiz_id, list): 
    target_quiz_id = target_quiz_id[0]

if not target_quiz_id:
    st.warning("📭 Please use the link provided by your presenter to join a quiz.")
    st.stop()

# Load Quiz Data
registry = get_registry()
if registry.empty:
    st.error("❌ Registry not found or database is empty.")
    st.info("💡 The presenter needs to generate and activate at least one quiz first.")
    st.stop()

target_quiz = registry[registry['title'] == target_quiz_id]

if target_quiz.empty:
    st.error(f"❌ Quiz '{target_quiz_id}' not found.")
    st.stop()

target_quiz = target_quiz.iloc[0]

if target_quiz['status'] != "ON":
    st.warning(f"🔒 The quiz '{target_quiz_id}' is currently inactive. Please wait for the presenter.")
    if st.button("Check Again"): st.rerun()
    st.stop()

st.info(f"👉 Joining Session: **{target_quiz['title']}**")

# Quiz State Management
if "quiz_started" not in st.session_state:
    st.session_state.quiz_started = False
    st.session_state.answers = {}

if not st.session_state.quiz_started:
    with st.form("join_form"):
        st.subheader("Join the Quiz")
        name = st.text_input("Full Name")
        email = st.text_input("Email Address")
        if st.form_submit_button("Start Quiz"):
            if name and email and conn is not None:
                st.session_state.user_data = {"name": name, "email": email}
                try:
                    qs_df = conn.read(spreadsheet=GSHEET_URL, worksheet=f"{target_quiz['title']}_QS", ttl=0)
                    indices = random.sample(range(len(qs_df)), min(5, len(qs_df)))
                    st.session_state.questions = qs_df.iloc[indices].to_dict('records')
                    st.session_state.quiz_started = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to load questions: {e}")
            elif not name or not email:
                st.error("Please fill in both name and email.")
            else:
                st.error("Google Sheets connection is offline.")
else:
    with st.form("active_quiz"):
        st.subheader("Answer the Questions")
        for idx, q in enumerate(st.session_state.questions):
            st.markdown(f"**Q{idx+1}:** {q['text']}")
            opts = str(q['options']).split("|")
            st.session_state.answers[idx] = st.radio("choice", opts, key=f"ans_{idx}", label_visibility="collapsed")
            st.divider()
        
        rating = st.select_slider("How was this session?", [1,2,3,4,5], value=5)
        comments = st.text_area("Additional Feedback")
        
        if st.form_submit_button("Submit Final Answers"):
            score = 0
            if "questions" in st.session_state and st.session_state.answers:
                for idx, q in enumerate(st.session_state.questions):
                    if st.session_state.answers.get(idx) == q['correct_answer']:
                        score += 1
            
            new_sub = pd.DataFrame([{
                "name": st.session_state.user_data['name'],
                "email": st.session_state.user_data['email'],
                "score": score,
                "rating": rating,
                "comments": comments,
                "ts": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            }])
            
            s_sheet = f"{target_quiz['title']}_SUBS"
            try:
                if gc is None:
                    st.error("GSheets connection offline.")
                    st.stop()
                # Direct update for reliability
                sh = gc.open_by_url(GSHEET_URL)
                ws = sh.worksheet(s_sheet)
                ws.append_row(new_sub.values.tolist()[0])
                
                st.balloons()
                st.success(f"🎊 Submitted! Your Score: {score}/5. Thank you for participating!")
                # Reset for next person or next try if allowed
                for key in ["quiz_started", "user_data", "questions", "answers"]:
                    if key in st.session_state: del st.session_state[key]
            except Exception as e:
                st.error(f"Failed to save results: {e}")
