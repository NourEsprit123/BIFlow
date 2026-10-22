"""Chat flottant réutilisable et agnostique pour BIFlow.

- Répond aux questions sur le dataset ACTIF avec des chiffres exacts (calculés par le moteur, pas devinés).
- Sait afficher un KPI / graphique / dashboard sur la page principale (st.session_state["injected_view"]).
"""
import os
import re
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from agents.chat_agent import ChatAnalystAgent
from analytics import dashboard_engine as eng

load_dotenv()

CHAT_LANGUAGE = "French"          # langue des réponses du chat et des vues demandées
CLEANED_DIR = "data/cleaned_dataset/"

CHAT_CSS = """
<style>
.st-key-bf_chat_fab{position:fixed!important;right:1.6rem;bottom:1.6rem;z-index:1000;width:auto!important}
.st-key-bf_chat_fab button{
  min-height:3.3rem!important;padding:.6rem 1.4rem!important;border-radius:999px!important;border:0!important;
  color:#fff!important;font-weight:700!important;
  background:linear-gradient(135deg,#6366f1,#8b5cf6 55%,#c026d3)!important;
  box-shadow:0 14px 34px rgba(99,102,241,.45);animation:bfc-ring 2.8s ease-out infinite;
  transition:transform .25s ease}
.st-key-bf_chat_fab button p{color:#fff!important;font-size:.95rem}
.st-key-bf_chat_fab button:hover{transform:translateY(-3px) scale(1.04)}
@keyframes bfc-ring{
  0%{box-shadow:0 14px 34px rgba(99,102,241,.45),0 0 0 0 rgba(139,92,246,.5)}
  70%{box-shadow:0 14px 34px rgba(99,102,241,.45),0 0 0 18px rgba(139,92,246,0)}
  100%{box-shadow:0 14px 34px rgba(99,102,241,.45),0 0 0 0 rgba(139,92,246,0)}}

.st-key-bf_chat_panel{
  position:fixed!important;right:1.6rem;bottom:1.6rem;z-index:1001;
  width:min(410px,calc(100vw - 2rem))!important;max-height:calc(100vh - 3rem);
  gap:0!important;padding:0!important;overflow:hidden;background:#fff;
  border:1px solid #e3e8fb;border-radius:26px;
  box-shadow:0 34px 90px rgba(30,41,99,.32);
  transform-origin:bottom right;animation:bfc-pop .4s cubic-bezier(.2,.9,.3,1.15) both}
@keyframes bfc-pop{from{opacity:0;transform:translateY(24px) scale(.92)}to{opacity:1;transform:none}}

.bfc-head{position:relative;overflow:hidden;display:flex;align-items:center;gap:.9rem;
  padding:1.2rem 5.2rem 1.35rem 1.3rem;color:#fff;
  background:linear-gradient(135deg,#4338ca,#7c3aed 58%,#c026d3)}
.bfc-head .av{position:relative;z-index:1;width:46px;height:46px;border-radius:15px;flex:none;display:grid;
  place-items:center;font-size:1.4rem;background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.35)}
.bfc-head b{display:block;font-size:1.05rem}
.bfc-head small{display:flex;align-items:center;gap:.45rem;font-size:.74rem;opacity:.92;margin-top:.15rem}
.bfc-head small i{width:8px;height:8px;border-radius:50%;background:#4ade80}

.st-key-bf_chat_close{position:absolute!important;top:.9rem;right:1rem;z-index:6;width:auto!important}
.st-key-bf_chat_clear{position:absolute!important;top:.9rem;right:3.6rem;z-index:6;width:auto!important}
.st-key-bf_chat_close button,.st-key-bf_chat_clear button{
  width:34px!important;height:34px!important;min-height:0!important;padding:0!important;border-radius:50%!important;
  border:1px solid rgba(255,255,255,.35)!important;background:rgba(255,255,255,.18)!important;color:#fff!important}

.st-key-bf_chat_msgs{background:linear-gradient(180deg,#f3f5ff,#f8faff);padding:1rem .9rem .2rem}
.bfc-row{display:flex;gap:.55rem;margin-bottom:.75rem;align-items:flex-end}
.bfc-row.me{justify-content:flex-end}
.bfc-av{width:28px;height:28px;border-radius:9px;flex:none;display:grid;place-items:center;font-size:.85rem;
  color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7)}
.bfc-bub{max-width:82%;padding:.65rem .9rem;font-size:.86rem;line-height:1.55;border-radius:18px;word-wrap:break-word}
.bfc-bub.bot{background:#fff;color:#1e293b;border:1px solid #e8ecfb;border-bottom-left-radius:6px}
.bfc-bub.me{color:#fff;border-bottom-right-radius:6px;background:linear-gradient(135deg,#6366f1,#8b5cf6)}
.bfc-bub em{display:block;font-style:normal;font-size:.62rem;opacity:.55;margin-top:.3rem;text-align:right}

.st-key-bf_chat_sugg{background:#f8faff;padding:.1rem .9rem .8rem;gap:.4rem!important}
.bfc-hint{font-size:.66rem;letter-spacing:.12em;font-weight:700;color:#94a3b8;margin:0 0 .1rem .15rem}
.st-key-bf_chat_sugg button{
  min-height:0!important;padding:.42rem .95rem!important;border-radius:999px!important;justify-content:flex-start;
  background:#fff!important;border:1px solid #dfe5fb!important;color:#4338ca!important;font-size:.8rem}

.st-key-bf_chat_form{background:#fff;border-top:1px solid #eef0fb;padding:.8rem .9rem .3rem}
.bfc-foot{text-align:center;font-size:.64rem;color:#94a3b8;padding:.2rem 0 .5rem}
</style>
"""

SCROLL_JS = """
<script>
try {
  const doc = window.parent.document;
  const box = doc.querySelector('.st-key-bf_chat_msgs');
  if (box) {
    const nodes = [box, ...box.querySelectorAll('div')];
    const scroller = nodes.find(e => e.scrollHeight > e.clientHeight + 5);
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }
} catch (e) {}
</script>
"""


# ----------------------------------------------------------------------------
# Dataset actif
# ----------------------------------------------------------------------------
def get_active_dataset():
    """(nom, chemin, date de modification) du dataset sélectionné sur la page, sinon None."""
    if not os.path.isdir(CLEANED_DIR):
        return None
    files = sorted(f for f in os.listdir(CLEANED_DIR) if f.endswith(".csv"))
    if not files:
        return None
    name = st.session_state.get("active_dataset_filename")
    if name not in files:
        name = files[0]
    path = os.path.join(CLEANED_DIR, name)
    return name, path, os.path.getmtime(path)


@st.cache_resource(show_spinner=False)
def get_typed_dataset(file_path: str, mtime: float):
    """DataFrame typé (nombres / dates détectés) + profil, mis en cache par fichier. Lecture seule."""
    df = None
    for enc in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(file_path, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        df = pd.read_csv(file_path, encoding="cp1252", encoding_errors="replace")
    df = eng.coerce_types(df)
    return df, eng.profile_dataset(df)


def dynamic_suggestions(profile: dict) -> list:
    """Exemples de questions construits à partir des colonnes réelles du dataset (aucun exemple figé)."""
    cols = profile["columns"]
    num = [c["name"] for c in cols if c["kind"] == "numeric" and not re.search(r"(id|code)$", c["name"], re.I)]
    cat = [c["name"] for c in cols if c["kind"] == "categorical" and 2 <= c["n_unique"] <= 60]
    dates = [c["name"] for c in cols if c["kind"] == "datetime"]
    out = []
    if num:
        out.append(f"Donne-moi les statistiques de {num[0]}")
    if cat:
        out.append(f"Quelle est la répartition de {cat[0]} ?")
    if num and cat:
        out.append(f"Affiche un graphique de {num[0]} par {cat[0]}")
    if num and dates:
        out.append(f"Affiche l'évolution mensuelle de {num[0]}")
    return out[:3] or ["Résume ce dataset", "Affiche un dashboard sur ce dataset"]


# ----------------------------------------------------------------------------
# Traitement d'une question
# ----------------------------------------------------------------------------
def process_chat_query(question: str, history: list):
    """Retourne (réponse texte, vue à afficher ou None)."""
    if not os.getenv("GROQ_API_KEY"):
        return "⚠️ Clé API Groq introuvable dans le fichier .env.", None
    active = get_active_dataset()
    if not active:
        return "⚠️ Aucun dataset actif trouvé.", None
    name, path, mtime = active
    try:
        df, profile = get_typed_dataset(path, mtime)
        ctx = st.session_state.get("dashboard_context") or {}
        if ctx.get("file") != name:        # contexte d'un autre dataset : on l'ignore
            ctx = {}
        out = ChatAnalystAgent().respond(question, df, profile, history, ctx, language=CHAT_LANGUAGE)
    except Exception as e:
        return f"⚠️ Erreur lors de l'analyse : {e}", None
    view = out.get("view")
    if view:
        view["file"] = name
    return out["reply"], view


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
def _format(text: str) -> str:
    safe = escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"`(.+?)`", r"<code>\1</code>", safe)
    return safe.replace("\n", "<br>")


def _bubble(message: dict, is_new: bool) -> str:
    text = _format(message["content"])
    stamp = message.get("time", "")
    new = " new" if is_new else ""
    if message["role"] == "user":
        return f'<div class="bfc-row me"><div class="bfc-bub me{new}">{text}<em>{stamp}</em></div></div>'
    return f'<div class="bfc-row"><span class="bfc-av">✨</span><div class="bfc-bub bot{new}">{text}<em>{stamp}</em></div></div>'


def render_chat(page: str) -> None:
    user = st.session_state.get("authenticated_user") or {}
    first_name = (user.get("full_name") or "").split()[0] if user.get("full_name") else "there"

    history_key = f"chat_history_{page}"
    if history_key not in st.session_state:
        st.session_state[history_key] = [{
            "role": "assistant",
            "content": (f"Bonjour {first_name} ! 👋 Posez-moi une question sur votre dataset, "
                        "ou demandez-moi d'afficher un KPI, un graphique ou un dashboard."),
            "time": datetime.now().strftime("%H:%M"),
        }]
    history = st.session_state[history_key]

    st.markdown(CHAT_CSS, unsafe_allow_html=True)

    if not st.session_state.get("bf_chat_open", False):
        with st.container(key="bf_chat_fab"):
            st.button("💬 Ask BIFlow", key="bf_chat_open_btn",
                      on_click=lambda: st.session_state.update({"bf_chat_open": True}))
        return

    with st.container(key="bf_chat_panel"):
        st.markdown(
            f'<div class="bfc-head"><span class="av">✨</span>'
            f'<div class="txt"><b>BIFlow Assistant</b><small><i></i>Online · {escape(page)}</small></div></div>',
            unsafe_allow_html=True,
        )
        with st.container(key="bf_chat_close"):
            st.button("✕", key="bf_chat_close_btn", on_click=lambda: st.session_state.update({"bf_chat_open": False}))
        if len(history) > 1:
            with st.container(key="bf_chat_clear"):
                st.button("🗑", key="bf_chat_clear_btn", on_click=lambda: st.session_state.pop(history_key, None))

        messages_box = st.container(height=310, border=False, key="bf_chat_msgs")

        pending = None
        if len(history) == 1:
            active = get_active_dataset()
            suggestions = []
            if active:
                try:
                    suggestions = dynamic_suggestions(get_typed_dataset(active[1], active[2])[1])
                except Exception:
                    suggestions = []
            if suggestions:
                with st.container(key="bf_chat_sugg"):
                    st.markdown('<div class="bfc-hint">EXEMPLES DE QUESTIONS</div>', unsafe_allow_html=True)
                    for index, suggestion in enumerate(suggestions):
                        if st.button(suggestion, key=f"bf_chat_sugg_{index}", use_container_width=True):
                            pending = suggestion

        with st.container(key="bf_chat_form"):
            with st.form("bf_chat_form_inner", clear_on_submit=True, border=False):
                col_in, col_send = st.columns([6, 1], vertical_alignment="center")
                with col_in:
                    text = st.text_input("Message", placeholder="Posez une question...", label_visibility="collapsed")
                with col_send:
                    sent = st.form_submit_button("➤")
            st.markdown('<div class="bfc-foot">BIFlow AI Engine</div>', unsafe_allow_html=True)

        question = text.strip() if (sent and text) else (pending or "")
        if question:
            now = datetime.now().strftime("%H:%M")
            history.append({"role": "user", "content": question, "time": now})

            with st.spinner("BIFlow analyse vos données..."):
                reply_text, view = process_chat_query(question, history[:-1])

            if view:
                st.session_state["injected_view"] = view
                reply_text += "\n\n📌 C'est affiché sur la page principale."

            history.append({"role": "assistant", "content": reply_text, "time": now})
            st.rerun()

        with messages_box:
            last_index = len(history) - 1
            bubbles = "".join(_bubble(m, is_new=(i >= last_index - 1 and len(history) > 1)) for i, m in enumerate(history))
            st.markdown(bubbles, unsafe_allow_html=True)

        components.html(SCROLL_JS, height=0)