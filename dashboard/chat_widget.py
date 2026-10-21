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


# Importation de vos ressources découplées (Style, Script et LLM)
from chat_style import SUGGESTIONS, CHAT_CSS
from chat_script import SCROLL_JS
from llm_manager import executer_requete_llm


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