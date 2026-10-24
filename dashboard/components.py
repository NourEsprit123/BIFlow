"""Blocs réutilisables : layout (sidebar/topbar/header) + petits composants HTML."""
from html import escape
from pathlib import Path

import streamlit as st
from dashboard.cleaning_review import run_cleaning_with_progress
from style import load_css
from dashboard.pipeline import pipeline_html
from workspace import (
    CLEANING_STATE_KEY,
    DATASET_STATE_KEY,
    PROFILE_STATE_KEY,
    dataset_label,
    get_workspace_result,
    list_datasets,
    profile_dataset_for_workspace,
    profiling_execution_status,
    selected_dataset_path,
)

NAV = [
    ("Overview", "pages/1_Overview.py", "🏠"),
    ("Datasets", "pages/2_Datasets.py", "🗄"),
    ("Workflows", "pages/3_Workflows.py", "⛓"),
    ("Data Quality", "pages/4_Data_Quality.py", "✅"),
    ("Agent Ops", "pages/7_Agent_Ops.py", "🤖"),
]

# ---------- helpers HTML ----------
def html(s: str):
    st.markdown("\n".join(l.strip() for l in s.splitlines() if l.strip()), unsafe_allow_html=True)

def badge(text, tone="indigo"):
    return f'<span class="bf-badge {tone}">{text}</span>'

def kpi(label, value, sub="", icon="📊", tone="indigo", sub_tone=""):  # Remplacé "▦" par un emoji valide
    return (f'<div class="bf-card bf-kpi"><div class="row"><span>{label}</span><i class="ico {tone}">{icon}</i></div>'
            f'<div class="val">{value}</div><div class="sub {sub_tone}">{sub}</div></div>')

def bar(pct, color="#38bdf8"):
    return f'<div class="bf-bar"><span style="width:{pct}%;background:{color}"></span></div>'

def donut(pct, color="#4f46e5", label="OF TOTAL", size=150):
    return (f'<div class="bf-donut" style="--p:{pct};--c:{color};width:{size}px;height:{size}px">'
            f'<div><b>{pct}%</b><small>{label}</small></div></div>')

def card(body, title="", subtitle="", right=""):
    head = f'<div class="ch"><div><h3>{title}</h3><div class="subt">{subtitle}</div></div>{right}</div>' if title else ""
    return f'<div class="bf-card">{head}{body}</div>'

def grid(items, cls="g2"):
    return f'<div class="bf-grid {cls}">{"".join(items)}</div>'

def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="bf-table"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'

def columns_chart(values, labels, colors, height=130):
    cols = "".join(f'<div style="height:{v}%;background:{c}"><small>{l}</small></div>' for v, l, c in zip(values, labels, colors))
    return f'<div class="bf-cols" style="height:{height}px;margin-bottom:1.6rem">{cols}</div>'

def svg_line(path, color="#4f46e5", w=260, h=90):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}"><path d="{path} L{w},{h} L0,{h} Z" fill="{color}" opacity=".08"/>'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/></svg>')


# ---------- layout ----------
def setup(title, hub="Enterprise Analytics Hub"):
    """À appeler en PREMIER dans chaque page."""
    st.set_page_config(
        page_title=f"BIFlow · {title}",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()
    user = st.session_state.get("authenticated_user")
    if not user:
        st.warning("Connectez-vous pour accéder à votre espace BIFlow.")
        st.page_link("app.py", label="Aller à la page de connexion", icon="🔐")
        st.stop()

    # Keep the selected value separate from the widget's page lifecycle.
    active = selected_dataset_path()
    datasets = list_datasets()
    with st.sidebar:
        html('<div class="bf-brand"><div class="logo">B</div><div><b>BIFlow</b><small>Data to decisions</small></div></div>')
        html('<div class="bf-nav-label">WORKSPACE</div>')
        for label, path, icon in NAV:
            st.page_link(path, label=label, icon=icon)
        html('<div class="bf-nav-label">AGENT WORKBENCH</div>')
        st.page_link("pages/A1_Profiling.py", label="Profiling report", icon="🔎")
        st.page_link("pages/A1_Quality.py", label="Quality findings", icon="✅")
        html('<div class="bf-nav-label">COMING FROM THE TEAM</div>')
        st.button("BI Analysis · Locked", key="locked_bi_analysis", icon="🔒", disabled=True,
                  use_container_width=True, help="The BI Analyst is being developed by your teammates.")
        st.button("Explainability · Locked", key="locked_xai", icon="🔒", disabled=True,
                  use_container_width=True, help="The Auditor / XAI agent is being developed by your teammates.")
        html('<div class="bf-team-note"><i></i><div><b>Academic workspace</b><small>2 agents integrated · 6 in development</small></div></div>')
        full_name = escape(user["full_name"])
        initials = escape("".join(part[0] for part in user["full_name"].split()[:2]).upper())
        html(f'<div class="bf-user"><div class="av">{initials}</div><div><b>{full_name}</b><small>{escape(user["email"])}</small></div></div>')
        if st.button("Sign out", key="workspace_sign_out", use_container_width=True):
            st.session_state.pop("authenticated_user", None)
            st.switch_page("app.py")

    html(f'<div class="bf-workspace-heading"><span>WORKSPACE</span><b>{escape(title)}</b></div>')
    with st.container(key="dataset_toolbar"):
        picker, manage = st.columns([4, 1], vertical_alignment="bottom")
        with picker:
            if datasets:
                options = [str(p) for p in datasets]
                st.session_state["workspace_dataset_picker"] = str(active)
                st.selectbox(
                    "Active dataset", options, key="workspace_dataset_picker",
                    format_func=lambda value: f"{dataset_label(Path(value))} · {Path(value).name}",
                    on_change=_select_dataset,
                    help="Type a filename to search. Your selection is used by every agent and page.",
                )
            else:
                st.info("Upload your first dataset to enable the agents.")
        with manage:
            st.page_link("pages/2_Datasets.py", label="Datasets", icon="📁", use_container_width=True)

    _agent_controls(active)


def _select_dataset():
    st.session_state[DATASET_STATE_KEY] = st.session_state["workspace_dataset_picker"]


def _agent_controls(active):
    profile = get_workspace_result(PROFILE_STATE_KEY, active) if active else None
    cleaning = get_workspace_result(CLEANING_STATE_KEY, active) if active else None
    pipeline_slot = st.empty()
    pipeline_slot.markdown(pipeline_html(profile, cleaning), unsafe_allow_html=True)
    actions = st.columns([1, 1, 1, 1])
    with actions[0]:
        profile_clicked = st.button("Run profiling", key="profiler_run", type="primary", use_container_width=True, disabled=active is None)
    with actions[1]:
        cleaning_clicked = st.button("Run cleaning", key="cleaner_run", use_container_width=True, disabled=active is None)
    with actions[2]:
        st.page_link("pages/A1_Profiling.py", label="Profiling report", icon="📄", use_container_width=True)
    with actions[3]:
        st.page_link("pages/4_Data_Quality.py", label="Cleaning trace", icon="🧪", use_container_width=True)
    if profile_clicked:
        pipeline_slot.markdown(pipeline_html(profile, cleaning, running="profiler"), unsafe_allow_html=True)
        try:
            with st.status("Profiling the active dataset...", expanded=True) as progress:
                result = profile_dataset_for_workspace(active, refresh=True)
                used_llm, message = profiling_execution_status(result)
                st.write(message)
                profile = result
                cleaning = None
                pipeline_slot.markdown(pipeline_html(profile, cleaning), unsafe_allow_html=True)
                st.caption("Profile ready" if used_llm else "Fallback report")
                progress.update(label="Profiling complete" if used_llm else "Profiling complete with fallback", state="complete")
        except Exception as exc:
            pipeline_slot.markdown(pipeline_html(profile, cleaning), unsafe_allow_html=True)
            st.error(f"Profiling could not complete: {exc}")
    if cleaning_clicked:
        pipeline_slot.markdown(pipeline_html(profile, cleaning, running="cleaner"), unsafe_allow_html=True)
        try:
            result = run_cleaning_with_progress(active)
            profile = get_workspace_result(PROFILE_STATE_KEY, active)
            pipeline_slot.markdown(pipeline_html(profile, result), unsafe_allow_html=True)
        except Exception as exc:
            pipeline_slot.markdown(pipeline_html(profile, cleaning), unsafe_allow_html=True)
            st.error(f"Cleaning could not complete: {exc}")


def page_header(title, subtitle="", actions="", crumbs=""):
    html(f'''{f'<div class="bf-crumbs">{crumbs}</div>' if crumbs else ''}
    <div class="bf-head"><div><h1>{title}</h1><p>{subtitle}</p></div><div class="bf-actions">{actions}</div></div>''')

def locked_feature(name):
    page_header(f"{escape(name)} · Locked", "This agent is being developed by your teammates and is not integrated yet.")
    st.info("Available now: Data Profiling and Data Cleaning. Use the pipeline above to run them and review their results.")
    st.stop()
