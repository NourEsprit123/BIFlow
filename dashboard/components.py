"""Blocs réutilisables : layout (sidebar/topbar/header) + petits composants HTML."""
from html import escape
from pathlib import Path

import streamlit as st
from style import load_css
from workspace import (
    CLEANING_STATE_KEY,
    DATASET_STATE_KEY,
    PROFILE_STATE_KEY,
    dataset_label,
    dataset_signature,
    list_datasets,
    selected_dataset_path,
)

NAV = [
    ("Overview", "pages/1_Overview.py", "🏠"),
    ("Datasets", "pages/2_Datasets.py", "🗄"),
    ("Workflows", "pages/3_Workflows.py", "⛓"),
]

# Pipeline order. Agents are named by role: the profiling and cleaning agents replace the
# single Data Engineering agent, and the BI and XAI pages keep their own numbering inside.
AGENTS = [
    ("Data Profiling", "agent1", "⚙", "#4f46e5",
     [("📊 Profiling",    "pages/A1_Profiling.py"),
      ("✅ Quality Check", "pages/A1_Quality.py")]),
    ("Data Cleaning", "cleaning", "🧹", "#0d9488",
     [("🧪 Cleaning run", "pages/A1_Cleaning.py")]),
    ("BI Analyst", "agent2", "📊", "#0ea5e9",
     [("📈 KPI & Dashboards",  "pages/5_BI_Analysis.py")]),
    ("XAI Auditor", "agent3", "🧠", "#a855f7",
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
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (ValueError, TypeError):
        p = 0.0
    return f'<div class="bf-bar"><span style="width:{p}%;background:{color}"></span></div>'

def donut(pct, color="#4f46e5", label="OF TOTAL", size=150):
    return (f'<div class="bf-donut" style="--p:{pct};--c:{color};width:{size}px;height:{size}px">'
            f'<div><b>{pct}%</b><small>{label}</small></div></div>')

def card(body, title="", subtitle="", right=""):
    head = f'<div class="ch"><div><h3>{title}</h3><div class="subt">{subtitle}</div></div>{right}</div>' if title else ""
    return f'<div class="bf-card">{head}{body}</div>'

def grid(items, cls="g2"):
    return f'<div class="bf-grid {cls}">{"".join(items)}</div>'

def table(headers, rows, max_height: int = 0):
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    style_scroll = f"max-height:{max_height}px;overflow-y:auto;border-radius:12px;border:1px solid #eef2ff;" if max_height > 0 else ""
    return (
        f'<div style="overflow-x:auto;width:100%;{style_scroll}">'
        f'<table class="bf-table" style="width:100%;min-width:max-content">'
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
    # Détection automatique du mode d'agent selon le fichier appelant
    import inspect
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller_file = frame.f_back.f_code.co_filename
        if "A1_Cleaning" in caller_file:
            st.session_state.sidebar_mode = "cleaning"
        elif "A1_" in caller_file:
            st.session_state.sidebar_mode = "agent1"
        elif "5_BI_Analysis" in caller_file or "A2_" in caller_file:
            st.session_state.sidebar_mode = "agent2"
        elif "6_Audit_XAI" in caller_file or "A3_" in caller_file:
            st.session_state.sidebar_mode = "agent3"
        elif any(f in caller_file for f in ["1_Overview", "2_Datasets", "3_Workflows", "7_Agent_Ops"]):
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
        st.session_state._sidebar_expanded = True

    # ── Restore session from cookie if session_state was wiped (page reload) ─
    if not st.session_state.get("authenticated_user"):
        import streamlit.components.v1 as _cv1
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
        params = st.query_params
        token = params.get("bf_token", "")
        if token:
            from auth import get_user_from_session
            user = get_user_from_session(token)
            if user:
                st.session_state["authenticated_user"] = user
                st.session_state["session_token"] = token
                st.query_params.clear()
                st.rerun()

    # Agent sidebar animation CSS + Masquage de la navigation native Streamlit
    st.markdown("""
    <style>
    /* Masquer la liste native des fichiers de Streamlit pour une sidebar 100% propre */
    [data-testid="stSidebarNav"] {
        display: none !important;
    }
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

                # Bouton retour menu général
                if st.button("← Menu général / Workflows", width="stretch"):
                    st.session_state.sidebar_mode = "nav"
                    st.switch_page("pages/3_Workflows.py")

                # Agent header
                html(
                    f'<div class="bf-sidebar-agent-header" style="background:linear-gradient(135deg,{color}18,{color}08);'
                    f'border:1px solid {color}33">'
                    f'<span style="width:38px;height:38px;border-radius:10px;background:{color};color:#fff;'
                    f'display:grid;place-items:center;font-size:1.1rem;flex:none">{icon}</span>'
                    f'<div><b style="font-size:.95rem;color:#0f172a">{label}</b><br>'
                    f'<small style="color:#64748b">Espace de travail actif</small></div></div>'
                )
                html('<div class="bf-nav-label">PAGES DE L\'AGENT</div>')
                for page_label, page_path in pages:
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
        if st.button("Sign out", width="stretch"):
            from auth import delete_session
            delete_session(st.session_state.get("session_token", ""))
            st.session_state.pop("authenticated_user", None)
            st.session_state.pop("session_token", None)
            st.session_state.sidebar_mode = "nav"
            st.markdown(
                '<script>document.cookie="bf_session=;path=/;max-age=0"</script>',
                unsafe_allow_html=True,
            )
            st.switch_page("app.py")

    active = sync_active_dataset()

    # ── PIPELINE STEPPER INTERACTIF (BARRE DU HAUT) ───────────────────────────
    wf_st      = st.session_state.get("wf_graph_state") or {}
    wf_reports = wf_st.get("reports") or {}
    pipe_res   = st.session_state.get("pipeline_results") or {}
    wf_state   = st.session_state.get("wf_state", "idle")

    # Un agent n'est vert/terminé QUE si le pipeline est actif ou terminé et que cet agent a effectivement produit un rapport
    if wf_state in ("running", "hitl_pause", "done"):
        engineer = wf_reports.get("data_engineer") or {}
        a1_done = bool(engineer or pipe_res.get("agent1"))
        clean_done = (engineer.get("cleaning") or {}).get("status") not in (None, "not_run", "error")
        a2_done = bool(wf_reports.get("bi_analyst") or pipe_res.get("agent2") or st.session_state.get("current_bi_report"))
        a3_done = bool(wf_reports.get("xai_auditor") or pipe_res.get("agent3"))
    else:
        # En mode idle (nouveau pipeline / accueil), rien n'a encore été exécuté pour ce run
        a1_done = False
        clean_done = False
        a2_done = False
        a3_done = False
    # Profiling and cleaning also run on their own pages, for the active dataset.
    a1_done = a1_done or _has_result(PROFILE_STATE_KEY, active)
    clean_done = clean_done or _has_result(CLEANING_STATE_KEY, active)

    AGENT_STEPS = [
        ("1", "Data Profiling", "⚙",  "#4f46e5", "agent1",   a1_done,    "pages/A1_Profiling.py"),
        ("2", "Data Cleaning",  "🧹", "#0d9488", "cleaning", clean_done, "pages/A1_Cleaning.py"),
        ("3", "BI Analyst",     "📊", "#0ea5e9", "agent2",   a2_done,    "pages/5_BI_Analysis.py"),
        ("4", "XAI Auditor",    "🧠", "#a855f7", "agent3",   a3_done,    "pages/6_Audit_XAI.py"),
    ]

    st.markdown("""
    <style>
    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] button {
      height: 48px !important;
      border-radius: 12px !important;
      font-weight: 600 !important;
      font-size: 0.85rem !important;
      transition: all 0.2s ease !important;
      border: 1px solid #e2e8f0 !important;
      background: #ffffff !important;
      color: #475569 !important;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05) !important;
    }
    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] button p {
      font-size: 0.85rem !important;
      font-weight: 600 !important;
    }
    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] button:hover {
      transform: translateY(-2px) !important;
      box-shadow: 0 4px 14px rgba(79, 70, 229, 0.16) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # A keyed container scopes the stepper styles; a :has(anchor) selector also matched the page
    # body and restyled every button placed in columns.
    with st.container(key="bf_stepper"):
        layout = st.columns([10, 1] * (len(AGENT_STEPS) - 1) + [10], gap="small")
        step_cols = layout[0::2]
        arrow_cols = layout[1::2]

        for arr_col in arrow_cols:
            with arr_col:
                st.markdown(
                    '<div style="display:flex;align-items:center;justify-content:center;height:48px;'
                    'font-size:1.3rem;color:#94a3b8;font-weight:800">➔</div>',
                    unsafe_allow_html=True
                )

        for idx, (short, role, icon, color, a_key, is_done, target_page) in enumerate(AGENT_STEPS):
            target_col = step_cols[idx]
            is_active  = (sidebar_mode == a_key)

            if is_active:
                btn_label = f"📍 {icon} {short} · {role} (Actif)"
            elif is_done:
                btn_label = f"✓ {icon} {short} · {role} (Prêt)"
            else:
                btn_label = f"{icon} {short} · {role}"

            with target_col:
                clicked = st.button(
                    btn_label,
                    key=f"agent_pipeline_top_btn_{a_key}",
                    width="stretch",
                )
                if clicked:
                    st.session_state.sidebar_mode = a_key
                    st.switch_page(target_page)

                css_nth = (idx * 2) + 1  # 1, 3, 5
                if is_active:
                    st.markdown(f"""
                    <style>
                    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child({css_nth}) button {{
                      border: 2px solid {color} !important;
                      background: linear-gradient(135deg, {color}14, #ffffff) !important;
                      box-shadow: 0 0 14px {color}33 !important;
                      color: {color} !important;
                    }}
                    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child({css_nth}) button p {{
                      color: {color} !important;
                      font-weight: 700 !important;
                    }}
                    </style>""", unsafe_allow_html=True)
                elif is_done:
                    st.markdown(f"""
                    <style>
                    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child({css_nth}) button {{
                      border-color: #86efac !important;
                      background: linear-gradient(135deg, #f0fdf4, #ffffff) !important;
                      border-left: 4px solid #22c55e !important;
                      color: #166534 !important;
                    }}
                    .st-key-bf_stepper div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child({css_nth}) button p {{
                      color: #166534 !important;
                      font-weight: 600 !important;
                    }}
                    </style>""", unsafe_allow_html=True)

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

    #html(f'''<div class="bf-top"><div class="crumb">Workspace › <b>{hub}</b></div>
    #  <div class="bf-search"><span>🔍 Search BIFlow...</span><span>⌘ K</span></div><span>🔔</span>
    #  <div class="bf-org">Northstar Labs <span class="bf-badge">Enterprise</span></div>
    #  <div class="bf-avatar">👤</div></div>''')

def _has_result(key, active):
    """A result in this session for the active dataset; no disk reads, this runs on every page."""
    state = st.session_state.get(key)
    try:
        return bool(active and isinstance(state, dict) and state.get("signature") == dataset_signature(active))
    except OSError:
        return False


def sync_active_dataset():
    """One active dataset for every page. The team's pages use current_dataset_path (which may point
    to a cleaned file after a pipeline run); the profiling and cleaning pages use DATASET_STATE_KEY."""
    theirs = st.session_state.get("current_dataset_path")
    if theirs and theirs != st.session_state.get("_synced_dataset_path"):
        candidate = Path(theirs).resolve()
        if candidate in list_datasets():
            st.session_state[DATASET_STATE_KEY] = str(candidate)
    active = selected_dataset_path()
    if active and (not theirs or Path(theirs).resolve() in list_datasets()):
        st.session_state["current_dataset_path"] = str(active)
    st.session_state["_synced_dataset_path"] = st.session_state.get("current_dataset_path")
    return active


def _select_dataset():
    chosen = st.session_state["workspace_dataset_picker"]
    st.session_state[DATASET_STATE_KEY] = chosen
    st.session_state["current_dataset_path"] = chosen
    st.session_state["_synced_dataset_path"] = chosen


def dataset_picker():
    """Active-dataset selector for the profiling and cleaning pages; returns the active path."""
    datasets = list_datasets()
    active = selected_dataset_path()
    with st.container(key="dataset_toolbar"):
        picker, manage = st.columns([4, 1], vertical_alignment="bottom")
        with picker:
            if datasets:
                st.session_state["workspace_dataset_picker"] = str(active)
                st.selectbox(
                    "Active dataset", [str(p) for p in datasets], key="workspace_dataset_picker",
                    format_func=lambda value: f"{dataset_label(Path(value))} · {Path(value).name}",
                    on_change=_select_dataset,
                    help="Type a filename to search. Your selection is used by every agent and page.",
                )
            else:
                st.info("Upload your first dataset to enable the agents.")
        with manage:
            st.page_link("pages/2_Datasets.py", label="Datasets", icon="📁", width="stretch")
    return active


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