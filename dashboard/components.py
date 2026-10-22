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
    ("Agent 1 · Data Engineering", "agent1", "⚙", "#4f46e5",
     [("📊 Profiling",    "pages/A1_Profiling.py"),
      ("✅ Quality Check", "pages/A1_Quality.py"),
      ("🔧 ETL & Cleaning", "pages/A1_ETL_Cleaning.py")]),
    ("Agent 2 · BI Analyst", "agent2", "📊", "#0ea5e9",
     [("📈 KPI Analysis",  "pages/5_BI_Analysis.py")]),
    ("Agent 3 · XAI Auditor", "agent3", "🧠", "#a855f7",
     [("🧠 Audit & XAI",  "pages/6_Audit_XAI.py")]),
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
    return (
        f'<div style="overflow-x:auto;width:100%">'
        f'<table class="bf-table" style="min-width:max-content">'
        f'<thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'
        f'</div>'
    )

def columns_chart(values, labels, colors, height=130):
    cols = "".join(f'<div style="height:{v}%;background:{c}"><small>{l}</small></div>' for v, l, c in zip(values, labels, colors))
    return f'<div class="bf-cols" style="height:{height}px;margin-bottom:1.6rem">{cols}</div>'

def svg_line(path, color="#4f46e5", w=260, h=90):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}"><path d="{path} L{w},{h} L0,{h} Z" fill="{color}" opacity=".08"/>'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/></svg>')


# ---------- layout ----------
def setup(title, hub="Enterprise Analytics Hub"):
    """À appeler en PREMIER dans chaque page."""
    # Auto-detect sidebar mode based on page URL if not explicitly set
    if "sidebar_mode" not in st.session_state:
        # Check current page to determine mode
        current_page = st.query_params.get("page", "")
        if not current_page:
            # Try to get from session path
            import inspect
            frame = inspect.currentframe()
            if frame and frame.f_back:
                caller_file = frame.f_back.f_code.co_filename
                if "A1_" in caller_file:
                    st.session_state.sidebar_mode = "agent1"
                elif "A2_" in caller_file:
                    st.session_state.sidebar_mode = "agent2"
                elif "A3_" in caller_file:
                    st.session_state.sidebar_mode = "agent3"
                else:
                    st.session_state.sidebar_mode = "nav"
            else:
                st.session_state.sidebar_mode = "nav"
    
    sidebar_mode = st.session_state.get("sidebar_mode", "nav")

    st.set_page_config(
        page_title=f"BIFlow · {title}",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()
    
    # Force sidebar open in agent mode via session state
    if sidebar_mode != "nav":
        # This tells Streamlit to keep sidebar expanded
        st.session_state._sidebar_expanded = True

    # ── Restore session from cookie if session_state was wiped (page reload) ─
    if not st.session_state.get("authenticated_user"):
        import streamlit.components.v1 as _cv1
        # Inject JS to read cookie and pass it via query param
        _cv1.html("""
        <script>
        (function() {
          var match = document.cookie.match(/bf_session=([^;]+)/);
          if (match) {
            var token = match[1];
            var url = window.parent.location.href;
            if (url.indexOf('bf_token=') === -1) {
              var sep = url.indexOf('?') !== -1 ? '&' : '?';
              window.parent.location.replace(url + sep + 'bf_token=' + token);
            }
          }
        })();
        </script>
        """, height=0)
        # Check if token was passed as query param
        params = st.query_params
        token = params.get("bf_token", "")
        if token:
            from auth import get_user_from_session
            user = get_user_from_session(token)
            if user:
                st.session_state["authenticated_user"] = user
                st.session_state["session_token"] = token
                # Clean the URL
                st.query_params.clear()
                st.rerun()

    # Agent sidebar animation CSS
    st.markdown("""
    <style>
    @keyframes bf-agent-spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
    @keyframes bf-agent-pulse{0%,100%{box-shadow:0 0 0 0 rgba(99,102,241,.5)}50%{box-shadow:0 0 0 8px rgba(99,102,241,0)}}
    .bf-agent-btn-running{animation:bf-agent-pulse 1.4s ease-in-out infinite!important;border-color:#6366f1!important}
    .bf-agent-btn-done{border-color:#22c55e!important;background:linear-gradient(135deg,#f0fdf4,#dcfce7)!important}
    .bf-agent-btn-done p,.bf-agent-btn-done{color:#166534!important}
    .bf-sidebar-label{font-size:.68rem;letter-spacing:.1em;color:#64748b;font-weight:600;
      padding:.2rem 0;margin:.6rem 0 .3rem}
    .bf-sidebar-back{display:flex;align-items:center;gap:.5rem;color:#4338ca;font-weight:600;
      font-size:.88rem;cursor:pointer;padding:.4rem .2rem;margin-bottom:.8rem}
    .bf-sidebar-agent-header{display:flex;align-items:center;gap:.7rem;padding:.7rem .8rem;
      border-radius:12px;margin-bottom:.8rem}
    </style>
    """, unsafe_allow_html=True)

    user = st.session_state.get("authenticated_user")
    if not user:
        st.warning("Connectez-vous pour accéder à votre espace BIFlow.")
        st.page_link("app.py", label="Aller à la page de connexion", icon="🔐")
        st.stop()

    with st.sidebar:
        if sidebar_mode == "nav":
            # Normal navigation
            html('<div class="bf-brand"><div class="logo">B</div>'
                 '<div><b>BIFlow</b><small>Intelligent Business Intelligence</small></div></div>'
                 '<div class="bf-nav-label">ANALYTICAL CORE</div>')
            for label, path, icon in NAV:
                st.page_link(path, label=label, icon=icon)
        else:
            # Agent sub-navigation
            agent_data = next((a for a in AGENTS if a[1] == sidebar_mode), None)
            if agent_data:
                label, key, icon, color, pages = agent_data

                # Back button
                if st.button("← Back to navigation", use_container_width=True):
                    st.session_state.sidebar_mode = "nav"
                    st.switch_page("pages/3_Workflows.py")

                # Agent header
                html(
                    f'<div class="bf-sidebar-agent-header" style="background:linear-gradient(135deg,{color}18,{color}08);'
                    f'border:1px solid {color}33">'
                    f'<span style="width:38px;height:38px;border-radius:10px;background:{color};color:#fff;'
                    f'display:grid;place-items:center;font-size:1.1rem;flex:none">{icon}</span>'
                    f'<div><b style="font-size:.95rem;color:#0f172a">{label}</b><br>'
                    f'<small style="color:#64748b">Results explorer</small></div></div>'
                )
                html('<div class="bf-nav-label">RESULTS</div>')
                for page_label, page_path in pages:
                    # Strip emoji from label for st.page_link, use icon param instead
                    parts = page_label.split(" ", 1)
                    if len(parts) == 2 and len(parts[0]) <= 2:
                        st.page_link(page_path, label=parts[1], icon=parts[0])
                    else:
                        st.page_link(page_path, label=page_label)

        # User footer (always shown)
        full_name = escape(user["full_name"])
        initials  = escape("".join(p[0] for p in user["full_name"].split()[:2]).upper())
        html(f'<div class="bf-user"><div class="av">{initials}</div><div><b>{full_name}</b>'
             f'<small>{escape(user["email"])}</small></div></div>')
        if st.button("Sign out", use_container_width=True):
            from auth import delete_session
            delete_session(st.session_state.get("session_token", ""))
            st.session_state.pop("authenticated_user", None)
            st.session_state.pop("session_token", None)
            st.session_state.sidebar_mode = "nav"
            # Clear cookie
            st.markdown(
                '<script>document.cookie="bf_session=;path=/;max-age=0"</script>',
                unsafe_allow_html=True,
            )
            st.switch_page("app.py")

    # ── Agent status bar (top) ────────────────────────────────────────────────
    pipeline_state = st.session_state.get("pipeline_state", "idle")
    pipeline_step  = st.session_state.get("pipeline_step", 0)

    AGENT_META = [
        ("Agent 1", "Data Engineering", "⚙", "#4f46e5", "agent1"),
        ("Agent 2", "BI Analyst",        "📊", "#0ea5e9", "agent2"),
        ("Agent 3", "XAI Auditor",       "🧠", "#a855f7", "agent3"),
    ]

    # Inject agent button CSS once
    st.markdown("""
    <style>
    @keyframes bf-agent-shimmer{
      0%{background-position:-200% 0}100%{background-position:200% 0}}
    @keyframes bf-agent-pulse{
      0%,100%{opacity:1}50%{opacity:.6}}
    /* Agent bar wrapper — targets only the agent buttons row via data attribute */
    .bf-agent-bar button{
      height:44px!important;border-radius:12px!important;font-weight:600!important;
      font-size:.82rem!important;transition:all .2s ease!important;
      border:1px solid #e2e8f0!important;background:#fff!important;color:#475569!important;
      box-shadow:0 1px 3px rgba(15,23,42,.06)!important}
    .bf-agent-bar button p{
      color:#475569!important;font-size:.82rem!important;font-weight:600!important}
    .bf-agent-bar button:hover{
      border-color:#a5b4fc!important;color:#4338ca!important;
      transform:translateY(-1px)!important;
      box-shadow:0 4px 12px rgba(79,70,229,.15)!important}
    .bf-agent-bar button:hover p{color:#4338ca!important}
    </style>
    """, unsafe_allow_html=True)

    # Wrap agent buttons in a labelled div so CSS targets only them
    st.markdown('<div class="bf-agent-bar">', unsafe_allow_html=True)

    agent_cols = st.columns(3, gap="small")
    for col_idx, (column, (short, role, icon, color, a_key)) in enumerate(
        zip(agent_cols, AGENT_META)
    ):
        agent_idx = col_idx + 1

        # State
        if pipeline_state == "idle" or pipeline_step == 0:
            a_state = "idle"
        elif pipeline_state == "running" and pipeline_step == agent_idx:
            a_state = "running"
        elif pipeline_step > agent_idx or (pipeline_state == "done" and agent_idx <= 3):
            a_state = "done"
        else:
            a_state = "idle"

        if a_state == "running":
            label = f"⟳  {short} · {role}"
        elif a_state == "done":
            label = f"✓  {short} · {role}"
        else:
            label = f"{icon}  {short} · {role}"

        with column:
            clicked = st.button(
                label,
                key=f"agent_top_btn_{a_key}",
                use_container_width=True,
                disabled=(a_state == "running"),
            )
            if clicked and a_state == "done":
                st.session_state.sidebar_mode = a_key
                _first_page = AGENTS[col_idx][4][0][1]
                st.switch_page(_first_page)

            # Per-agent color accent on left border + done/running state
            if a_state == "done":
                st.markdown(f"""
                <style>
                .bf-agent-bar > div:nth-child({agent_idx}) button{{
                  border-color:#86efac!important;
                  background:linear-gradient(135deg,#f0fdf4,#dcfce7)!important;
                  color:#166534!important;
                  border-left:4px solid #22c55e!important}}
                .bf-agent-bar > div:nth-child({agent_idx}) button p{{color:#166534!important}}
                </style>""", unsafe_allow_html=True)
            elif a_state == "running":
                st.markdown(f"""
                <style>
                .bf-agent-bar > div:nth-child({agent_idx}) button{{
                  border-color:#a5b4fc!important;
                  background:linear-gradient(135deg,#eef2ff,#e0e7ff)!important;
                  color:#4338ca!important;
                  border-left:4px solid {color}!important;
                  animation:bf-agent-pulse 1.4s ease-in-out infinite!important}}
                .bf-agent-bar > div:nth-child({agent_idx}) button p{{color:#4338ca!important}}
                </style>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <style>
                .bf-agent-bar > div:nth-child({agent_idx}) button{{
                  border-left:4px solid {color}!important}}
                </style>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)  # close .bf-agent-bar

    # ── Sidebar visibility control ────────────────────────────────────────────
    # In agent mode: force sidebar visible with CSS only (JS blocked by iframe sandbox)
    if sidebar_mode != "nav":
        st.markdown("""
        <style>
        /* Force sidebar to be visible and stay open */
        section[data-testid="stSidebar"] {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
            position: relative !important;
            transform: translateX(0) !important;
            margin-left: 0 !important;
        }
        
        /* Make collapse button visible and functional */
        button[data-testid="collapsedControl"],
        [data-testid="collapsedControl"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            position: fixed !important;
            left: 0 !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            z-index: 999999 !important;
            background: #4f46e5 !important;
            border-radius: 0 8px 8px 0 !important;
            padding: 8px !important;
            cursor: pointer !important;
            box-shadow: 2px 0 8px rgba(79,70,229,0.3) !important;
            width: 24px !important;
            height: 40px !important;
        }
        
        [data-testid="collapsedControl"]:hover {
            background: #5b5ec7 !important;
        }
        
        [data-testid="collapsedControl"] svg {
            color: #fff !important;
            fill: #fff !important;
        }
        </style>
        """, unsafe_allow_html=True)

    html(f'''<div class="bf-top"><div class="crumb">Workspace › <b>{hub}</b></div>
      <div class="bf-search"><span>🔍 Search BIFlow...</span><span>⌘ K</span></div><span>🔔</span>
      <div class="bf-org">Northstar Labs <span class="bf-badge">Enterprise</span></div>
      <div class="bf-avatar">👤</div></div>''')

def page_header(title, subtitle="", actions="", crumbs=""):
    sidebar_mode = st.session_state.get("sidebar_mode", "nav")
    # In agent mode: show a sidebar open button at the top of content
    if sidebar_mode != "nav":
        agent_data = next((a for a in AGENTS if a[1] == sidebar_mode), None)
        if agent_data:
            a_label, _, a_icon, a_color, a_pages = agent_data
            page_links = " &nbsp;·&nbsp; ".join(
                f'<a href="/{p[1].replace("pages/","").replace(".py","")}" '
                f'style="color:{a_color};text-decoration:none;font-weight:600">{p[0]}</a>'
                for p in a_pages
            )
            html(
                f'<div style="display:flex;align-items:center;gap:.75rem;padding:.5rem .8rem;'
                f'margin-bottom:.75rem;background:linear-gradient(135deg,{a_color}10,{a_color}05);'
                f'border:1px solid {a_color}30;border-radius:10px;font-size:.82rem">'
                f'<span style="width:28px;height:28px;border-radius:8px;background:{a_color};'
                f'color:#fff;display:grid;place-items:center;flex:none;font-size:.85rem">{a_icon}</span>'
                f'<span style="color:#475569">{a_label} &nbsp;›&nbsp; {page_links}</span>'
                f'</div>'
            )
    html(f'''{f'<div class="bf-crumbs">{crumbs}</div>' if crumbs else ''}
    <div class="bf-head"><div><h1>{title}</h1><p>{subtitle}</p></div><div class="bf-actions">{actions}</div></div>''')