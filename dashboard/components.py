"""Blocs réutilisables : layout (sidebar/topbar/header) + petits composants HTML."""
from html import escape

import streamlit as st
from style import load_css

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
    ("Agent 1 · Data Engineering", "agent1", [
        ("Data Profiling", "profiling"),
        ("Data Quality", "quality"),
    ]),
    ("Agent 2 · BI Analyst", "agent2", [
        ("KPIs", "kpis"),
        ("Dashboards", "dashboards"),
    ]),
    ("Agent 3 · XAI Auditor", "agent3", [
        ("XAI", "xai"),
    ]),
]


# ---------- helpers HTML ----------
def html(s: str):
    st.markdown("\n".join(l.strip() for l in s.splitlines() if l.strip()), unsafe_allow_html=True)

def badge(text, tone="indigo"):
    return f'<span class="bf-badge {tone}">{text}</span>'

def btn(label, primary=False):
    return f'<span class="bf-btn{" primary" if primary else ""}">{label}</span>'

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
    st.set_page_config(page_title=f"BIFlow · {title}", page_icon="📈", layout="wide")
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
        full_name = escape(user["full_name"])
        initials = escape("".join(part[0] for part in user["full_name"].split()[:2]).upper())
        html(f'<div class="bf-user"><div class="av">{initials}</div><div><b>{full_name}</b>'
             f'<small>{escape(user["email"])}</small></div></div>')
        if st.button("Sign out", use_container_width=True):
            st.session_state.pop("authenticated_user", None)
            st.switch_page("app.py")
    agent_columns = st.columns(len(AGENTS))
    for column, (agent, key_prefix, tasks) in zip(agent_columns, AGENTS):
        with column:
            with st.popover(agent, use_container_width=True):
                selected_tasks = [
                    label for label, task in tasks
                    if st.checkbox(label, key=f"{key_prefix}_{task}")
                ]
                if selected_tasks:
                    st.caption("Sélection : " + " + ".join(selected_tasks))
    html(f'''<div class="bf-top"><div class="crumb">Workspace › <b>{hub}</b></div>
      <div class="bf-search"><span>🔍 Search BIFlow...</span><span>⌘ K</span></div><span>🔔</span>
      <div class="bf-org">Northstar Labs <span class="bf-badge">Enterprise</span></div><div class="bf-avatar">👤</div></div>''')

def page_header(title, subtitle="", actions="", crumbs=""):
    html(f'''{f'<div class="bf-crumbs">{crumbs}</div>' if crumbs else ''}
    <div class="bf-head"><div><h1>{title}</h1><p>{subtitle}</p></div><div class="bf-actions">{actions}</div></div>''')