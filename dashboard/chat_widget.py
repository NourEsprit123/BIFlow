"""Chat flottant réutilisable pour toutes les pages BIFlow.

Utilisation, à la fin de chaque page :

    from chat_widget import render_chat
    render_chat("Datasets")
"""
import re
from datetime import datetime
from html import escape

import streamlit as st
import streamlit.components.v1 as components

# Suggestions rapides affichées dans le chat selon la page
SUGGESTIONS = {
    "Overview": ["Summarize my workspace", "Which dataset needs attention?", "What are the top insights?"],
    "Datasets": ["Which datasets need attention?", "How do I upload a dataset?", "What is the storage usage?"],
    "Data Quality": ["Why is quality 94%?", "What does the cleaning rule do?", "Explain the TotalCharges issue"],
    "BI Analysis": ["Why is churn at 26.5%?", "Which contract type is riskiest?", "Explain the pricing insight"],
    "Audit & XAI": ["How was churn calculated?", "Is this result verified?", "Show the lineage"],
    "Agent Operations": ["Are all agents healthy?", "Which agent is slowest?", "Any errors in the last 24h?"],
}

CHAT_CSS = """
<style>
/* ================= Bouton flottant (chat fermé) ================= */
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

/* ================= Fenêtre de chat ================= */
.st-key-bf_chat_panel{
  position:fixed!important;right:1.6rem;bottom:1.6rem;z-index:1001;
  width:min(410px,calc(100vw - 2rem))!important;max-height:calc(100vh - 3rem);
  gap:0!important;padding:0!important;overflow:hidden;background:#fff;
  border:1px solid #e3e8fb;border-radius:26px;
  box-shadow:0 34px 90px rgba(30,41,99,.32);
  transform-origin:bottom right;animation:bfc-pop .4s cubic-bezier(.2,.9,.3,1.15) both}
@keyframes bfc-pop{from{opacity:0;transform:translateY(24px) scale(.92)}to{opacity:1;transform:none}}
.st-key-bf_chat_panel iframe{display:block;height:0;border:0}

/* En-tête */
.bfc-head{position:relative;overflow:hidden;display:flex;align-items:center;gap:.9rem;
  padding:1.2rem 5.2rem 1.35rem 1.3rem;color:#fff;
  background:linear-gradient(135deg,#4338ca,#7c3aed 58%,#c026d3)}
.bfc-head::before{content:"";position:absolute;width:190px;height:190px;border-radius:50%;
  right:-60px;top:-90px;background:radial-gradient(circle,rgba(255,255,255,.28),transparent 70%)}
.bfc-head::after{content:"";position:absolute;inset:0;opacity:.35;pointer-events:none;
  background-image:radial-gradient(rgba(255,255,255,.35) 1px,transparent 1px);background-size:16px 16px;
  -webkit-mask-image:linear-gradient(120deg,transparent 40%,#000);mask-image:linear-gradient(120deg,transparent 40%,#000)}
.bfc-head .av{position:relative;z-index:1;width:46px;height:46px;border-radius:15px;flex:none;display:grid;
  place-items:center;font-size:1.4rem;background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.35);
  backdrop-filter:blur(6px)}
.bfc-head .txt{position:relative;z-index:1}
.bfc-head b{display:block;font-size:1.05rem;letter-spacing:-.01em}
.bfc-head small{display:flex;align-items:center;gap:.45rem;font-size:.74rem;opacity:.92;margin-top:.15rem}
.bfc-head small i{width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.7);
  animation:bfc-live 2s ease-in-out infinite}
@keyframes bfc-live{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.7)}50%{box-shadow:0 0 0 6px rgba(74,222,128,0)}}

/* Boutons X (fermer) et corbeille, placés dans l'en-tête */
.st-key-bf_chat_close{position:absolute!important;top:.9rem;right:1rem;z-index:6;width:auto!important}
.st-key-bf_chat_clear{position:absolute!important;top:.9rem;right:3.6rem;z-index:6;width:auto!important}
.st-key-bf_chat_close button,.st-key-bf_chat_clear button{
  width:34px!important;height:34px!important;min-height:0!important;padding:0!important;border-radius:50%!important;
  border:1px solid rgba(255,255,255,.35)!important;background:rgba(255,255,255,.18)!important;
  color:#fff!important;transition:all .25s ease}
.st-key-bf_chat_close button p,.st-key-bf_chat_clear button p{color:#fff!important;font-size:1rem;line-height:1}
.st-key-bf_chat_close button:hover{background:rgba(255,255,255,.38)!important;transform:rotate(90deg)}
.st-key-bf_chat_clear button:hover{background:rgba(255,255,255,.38)!important;transform:scale(1.1)}

/* Zone des messages */
.st-key-bf_chat_msgs{background:linear-gradient(180deg,#f3f5ff,#f8faff);padding:1rem .9rem .2rem}
.bfc-row{display:flex;gap:.55rem;margin-bottom:.75rem;align-items:flex-end}
.bfc-row.me{justify-content:flex-end}
.bfc-av{width:28px;height:28px;border-radius:9px;flex:none;display:grid;place-items:center;font-size:.85rem;
  color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7);box-shadow:0 4px 10px rgba(99,102,241,.3)}
.bfc-bub{max-width:82%;padding:.65rem .9rem;font-size:.86rem;line-height:1.55;border-radius:18px;word-wrap:break-word}
.bfc-bub.bot{background:#fff;color:#1e293b;border:1px solid #e8ecfb;border-bottom-left-radius:6px;
  box-shadow:0 2px 10px rgba(30,41,99,.06)}
.bfc-bub.me{color:#fff;border-bottom-right-radius:6px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  box-shadow:0 8px 18px rgba(99,102,241,.32)}
.bfc-bub em{display:block;font-style:normal;font-size:.62rem;opacity:.55;margin-top:.3rem;text-align:right}
.bfc-bub code{background:#eef2ff;color:#4338ca;padding:.05rem .35rem;border-radius:6px;font-size:.78rem}
.bfc-bub.me code{background:rgba(255,255,255,.22);color:#fff}
.bfc-bub.new{animation:bfc-in .4s ease both}
@keyframes bfc-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

/* Suggestions (pastilles) */
.st-key-bf_chat_sugg{background:#f8faff;padding:.1rem .9rem .8rem;gap:.4rem!important}
.bfc-hint{font-size:.66rem;letter-spacing:.12em;font-weight:700;color:#94a3b8;margin:0 0 .1rem .15rem}
.st-key-bf_chat_sugg button{
  min-height:0!important;padding:.42rem .95rem!important;border-radius:999px!important;justify-content:flex-start;
  background:#fff!important;border:1px solid #dfe5fb!important;color:#4338ca!important;
  font-size:.8rem;font-weight:600;transition:all .2s ease}
.st-key-bf_chat_sugg button p{color:#4338ca!important;font-size:.8rem}
.st-key-bf_chat_sugg button:hover{background:#eef2ff!important;border-color:#a5b4fc!important;transform:translateX(4px)}

/* Saisie */
.st-key-bf_chat_form{background:#fff;border-top:1px solid #eef0fb;padding:.8rem .9rem .3rem;gap:.3rem!important}
.st-key-bf_chat_form [data-testid="stForm"]{border:0!important;padding:0!important}
.st-key-bf_chat_form [data-baseweb="input"],.st-key-bf_chat_form [data-baseweb="base-input"]{
  border-radius:999px!important;background:#f1f4fd!important;border:1px solid transparent!important}
.st-key-bf_chat_form [data-baseweb="input"]:focus-within{border-color:#818cf8!important;
  box-shadow:0 0 0 3px rgba(129,140,248,.2)}
.st-key-bf_chat_form input{background:transparent!important;color:#1e293b!important;padding-left:1rem!important;font-size:.88rem}
.st-key-bf_chat_form button{
  width:42px!important;height:42px!important;min-height:0!important;padding:0!important;border-radius:50%!important;
  border:0!important;background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;
  box-shadow:0 8px 18px rgba(99,102,241,.4);transition:transform .2s ease}
.st-key-bf_chat_form button p{color:#fff!important;font-size:1.05rem}
.st-key-bf_chat_form button:hover{transform:scale(1.1) rotate(-8deg)}
.bfc-foot{text-align:center;font-size:.64rem;color:#94a3b8;padding:.2rem 0 .5rem}
</style>
"""

# Fait défiler la zone de messages vers le bas (best effort : sans effet si la structure change)
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


def generate_reply(question: str, page: str, user: dict) -> str:
    """Réponse de démonstration basée sur des mots-clés.

    >>> Remplace le contenu de cette fonction pour brancher ton vrai LLM
    >>> ou ton orchestration (orchestration/graph.py).
    """
    q = question.lower()
    if "churn" in q:
        return ("Churn is **26.5%** (1,869 of 7,043 customers). Month-to-month contracts are the strongest "
                "risk driver, with a churn rate of 42.7% versus 11.3% for one-year contracts.")
    if "quality" in q or "totalcharges" in q or "clean" in q:
        return ("The quality score is **94%**. Two medium issues remain on `TotalCharges`: an incorrect data type "
                "and 11 empty values. BIFlow recommends converting it to numeric and treating blanks as missing.")
    if "dataset" in q or "upload" in q or "storage" in q:
        return ("You have **12 datasets** and use **4.8 GB of 20 GB**. *Customer Transactions* needs attention "
                "because of 3 null schema collisions.")
    if "agent" in q or "latency" in q or "slow" in q or "error" in q or "health" in q:
        return ("All **4 agents** are operational (99.94% health). The slowest is the BI Analyst agent at 520 ms. "
                "There were 0 fatal exceptions in the last 24 hours.")
    if "verify" in q or "lineage" in q or "audit" in q or "calculated" in q:
        return ("Run **#BF-2026-0284** is verified. The XAI Auditor confirmed the calculation was reproducible "
                "and that no sensitive fields were exposed.")
    return (f"I'm your BIFlow assistant on the **{page}** page. Ask me about your datasets, data quality, "
            "business insights, audit trail or agent health.")


def _format(text: str) -> str:
    """Convertit un mini-markdown (gras, italique, code) en HTML sûr."""
    safe = escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"`(.+?)`", r"<code>\1</code>", safe)
    safe = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", safe)
    return safe.replace("\n", "<br>")


def _bubble(message: dict, is_new: bool) -> str:
    text = _format(message["content"])
    stamp = message.get("time", "")
    new = " new" if is_new else ""
    if message["role"] == "user":
        return f'<div class="bfc-row me"><div class="bfc-bub me{new}">{text}<em>{stamp}</em></div></div>'
    return (f'<div class="bfc-row"><span class="bfc-av">✨</span>'
            f'<div class="bfc-bub bot{new}">{text}<em>{stamp}</em></div></div>')


def _open_chat() -> None:
    st.session_state["bf_chat_open"] = True


def _close_chat() -> None:
    st.session_state["bf_chat_open"] = False


def _clear_chat(history_key: str) -> None:
    st.session_state.pop(history_key, None)


def render_chat(page: str) -> None:
    user = st.session_state.get("authenticated_user") or {}
    full_name = (user.get("full_name") or "").strip()
    first_name = full_name.split()[0] if full_name else "there"

    history_key = f"chat_history_{page}"
    if history_key not in st.session_state:
        st.session_state[history_key] = [{
            "role": "assistant",
            "content": f"Hi {first_name}! 👋 I'm your BIFlow assistant. Ask me anything about this page.",
            "time": datetime.now().strftime("%H:%M"),
        }]
    history = st.session_state[history_key]

    st.markdown(CHAT_CSS, unsafe_allow_html=True)

    # ---------- Chat fermé : simple bouton flottant ----------
    if not st.session_state.get("bf_chat_open", False):
        with st.container(key="bf_chat_fab"):
            st.button("💬 Ask BIFlow", key="bf_chat_open_btn", on_click=_open_chat)
        return

    # ---------- Chat ouvert ----------
    with st.container(key="bf_chat_panel"):
        st.markdown(
            f'<div class="bfc-head"><span class="av">✨</span>'
            f'<div class="txt"><b>BIFlow Assistant</b><small><i></i>Online · {escape(page)}</small></div></div>',
            unsafe_allow_html=True,
        )
        with st.container(key="bf_chat_close"):
            st.button("✕", key="bf_chat_close_btn", on_click=_close_chat, help="Close chat")
        if len(history) > 1:
            with st.container(key="bf_chat_clear"):
                st.button("🗑", key="bf_chat_clear_btn", on_click=_clear_chat, args=(history_key,),
                          help="Clear conversation")

        # Zone des messages (remplie après le traitement de la nouvelle question)
        messages_box = st.container(height=310, border=False, key="bf_chat_msgs")

        pending = None
        suggestions = SUGGESTIONS.get(page, [])
        if len(history) == 1 and suggestions:
            with st.container(key="bf_chat_sugg"):
                st.markdown('<div class="bfc-hint">TRY ASKING</div>', unsafe_allow_html=True)
                for index, suggestion in enumerate(suggestions):
                    if st.button(suggestion, key=f"bf_chat_sugg_{index}", use_container_width=True):
                        pending = suggestion

        with st.container(key="bf_chat_form"):
            with st.form("bf_chat_form_inner", clear_on_submit=True, border=False):
                input_col, send_col = st.columns([6, 1], vertical_alignment="center")
                with input_col:
                    text = st.text_input(
                        "Message",
                        placeholder="Ask about your data...",
                        label_visibility="collapsed",
                    )
                with send_col:
                    sent = st.form_submit_button("➤")
            st.markdown('<div class="bfc-foot">Powered by BIFlow agents · Demo responses</div>',
                        unsafe_allow_html=True)

        question = pending or (text.strip() if sent else "")
        if question:
            now = datetime.now().strftime("%H:%M")
            history.append({"role": "user", "content": question, "time": now})
            history.append({"role": "assistant", "content": generate_reply(question, page, user), "time": now})

        with messages_box:
            last_index = len(history) - 1
            bubbles = "".join(_bubble(m, is_new=(i >= last_index - 1 and len(history) > 1))
                              for i, m in enumerate(history))
            st.markdown(bubbles, unsafe_allow_html=True)

        components.html(SCROLL_JS, height=0)