"""Blocs réutilisables : layout (sidebar/topbar/header) + petits composants HTML."""
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
    with st.sidebar:
        html('<div class="bf-brand"><div class="logo">B</div><div><b>BIFlow</b><small>Intelligent Business Intelligence</small></div></div>'
             '<div class="bf-nav-label">ANALYTICAL CORE</div>')
        for label, path, icon in NAV:
            st.page_link(path, label=label, icon=icon)
        html('<div class="bf-user"><div class="av">SC</div><div><b>Sarah Chen</b><small>Analytics Lead</small></div></div>')
    html(f'''<div class="bf-top"><div class="crumb">Workspace › <b>{hub}</b></div>
      <div class="bf-search"><span>🔍 Search BIFlow...</span><span>⌘ K</span></div><span>🔔</span>
      <div class="bf-org">Northstar Labs <span class="bf-badge">Enterprise</span></div><div class="bf-avatar">👤</div></div>''')

def page_header(title, subtitle="", actions="", crumbs=""):
    html(f'''{f'<div class="bf-crumbs">{crumbs}</div>' if crumbs else ''}
    <div class="bf-head"><div><h1>{title}</h1><p>{subtitle}</p></div><div class="bf-actions">{actions}</div></div>''')