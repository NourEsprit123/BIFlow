"""Blocs réutilisables : layout (sidebar/topbar/header) + petits composants HTML."""
from html import escape
from pathlib import Path

import streamlit as st
from style import load_css
from workspace import (
    ANALYSIS_STATE_KEY,
    DATASET_STATE_KEY,
    PROFILE_STATE_KEY,
    analyze_dataframe,
    clean_profiled_dataset,
    dataset_label,
    get_workspace_result,
    list_datasets,
    load_selected_dataset,
    profile_dataset_for_workspace,
    selected_dataset_path,
    verify_profiling_report,
)

NAV = [
    ("Overview", "pages/1_Overview.py", "🏠"),
    ("Datasets", "pages/2_Datasets.py", "🗄"),
    ("Workflows", "pages/3_Workflows.py", "⛓"),
    ("Data Quality", "pages/4_Data_Quality.py", "✅"),
    ("BI Analysis", "pages/5_BI_Analysis.py", "📊"),
    ("Audit & XAI", "pages/6_Audit_XAI.py", "🧠"),
    ("Agent Ops", "pages/7_Agent_Ops.py", "🤖"),
]

AGENTS = [
    ("Agent 1 · Data Profiling", "agent1", "Run profiling and quality audit"),
    ("Agent 2 · Data Cleaning", "agent2", "Run safe cleaning plan"),
    ("Agent 3 · BI Analyst", "agent3", "Run dataset analysis"),
    ("Agent 4 · XAI Auditor", "agent4", "Verify profiling report"),
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

    with st.sidebar:
        html('<div class="bf-brand"><div class="logo">B</div><div><b>BIFlow</b><small>Intelligent Business Intelligence</small></div></div>'
             '<div class="bf-nav-label">ANALYTICAL CORE</div>')
        for label, path, icon in NAV:
            st.page_link(path, label=label, icon=icon)
        selected_dataset_path()
        datasets = list_datasets()
        if datasets:
            current = st.session_state.get(DATASET_STATE_KEY)
            options = [str(path) for path in datasets]
            if current not in options:
                current = options[0]
                st.session_state[DATASET_STATE_KEY] = current
            st.selectbox(
                "Active dataset",
                options,
                index=options.index(current),
                format_func=lambda value: dataset_label(Path(value)),
                key=DATASET_STATE_KEY,
            )
        else:
            st.info("Upload a dataset to get started.")

        full_name = escape(user["full_name"])
        initials = escape("".join(part[0] for part in user["full_name"].split()[:2]).upper())
        html(f'<div class="bf-user"><div class="av">{initials}</div><div><b>{full_name}</b>'
             f'<small>{escape(user["email"])}</small></div></div>')
        if st.button("Sign out", use_container_width=True):
            st.session_state.pop("authenticated_user", None)
            st.switch_page("app.py")
    agent_columns = st.columns(len(AGENTS))
    for column, (agent, key_prefix, action_label) in zip(agent_columns, AGENTS):
        with column:
            with st.popover(agent, use_container_width=True):
                st.caption(action_label)
                if st.button(action_label, key=f"{key_prefix}_run", type="primary"):
                    path, frame = load_selected_dataset()
                    if path is None or frame is None:
                        st.error("Upload a dataset before running an agent.")
                    elif key_prefix == "agent1":
                        result = profile_dataset_for_workspace(path, refresh=True)
                        st.success(
                            f"Profiling complete: {result['profile']['rows']:,} rows, "
                            f"{result['profile']['columns']} columns."
                        )
                    elif key_prefix == "agent2":
                        cleaning = clean_profiled_dataset(path)
                        st.success(
                            f"Cleaning run complete: {len(cleaning.change_log.successful_ops())} "
                            "changes applied; original data preserved."
                        )
                    elif key_prefix == "agent3":
                        result = analyze_dataframe(frame, path)
                        st.success(
                            f"Analysis complete: {result['rows']:,} rows and "
                            f"{result['numeric_columns']} numeric columns."
                        )
                    else:
                        profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
                        if profile_result is None:
                            st.warning("Run Data Profiling first to create an auditable report.")
                        else:
                            verification = verify_profiling_report(path, profile_result)
                            if verification["verified"]:
                                st.success(
                                    f"Report verified. SHA-256: {verification['sha256']}"
                                )
                            else:
                                st.error(verification["reason"])

    top = st.columns([1.4, 2.6, 0.7, 1.3, 0.7], vertical_alignment="center")
    with top[0]:
        st.markdown(f"Workspace › **{escape(hub)}**")
    with top[1]:
        st.text_input("Search datasets", key="workspace_search_query", placeholder="Search datasets...")
    with top[2]:
        with st.popover("🔔", help="Recent workspace activity"):
            active_path = selected_dataset_path()
            if active_path and get_workspace_result(PROFILE_STATE_KEY, active_path):
                st.write("Latest dataset profiling is complete.")
            if active_path and get_workspace_result(ANALYSIS_STATE_KEY, active_path):
                st.write("Latest dataset analysis is complete.")
            if not active_path or not any(
                get_workspace_result(key, active_path)
                for key in (PROFILE_STATE_KEY, ANALYSIS_STATE_KEY)
            ):
                st.caption("No analysis activity yet.")
    with top[3]:
        user_name = escape(user["full_name"])
        st.caption(f"**{user_name}**")
    with top[4]:
        with st.popover("👤", help="Account"):
            st.write(user["email"])
            if st.button("Sign out", key="workspace_sign_out", use_container_width=True):
                st.session_state.pop("authenticated_user", None)
                st.switch_page("app.py")

def page_header(title, subtitle="", actions="", crumbs=""):
    html(f'''{f'<div class="bf-crumbs">{crumbs}</div>' if crumbs else ''}
    <div class="bf-head"><div><h1>{title}</h1><p>{subtitle}</p></div><div class="bf-actions">{actions}</div></div>''')