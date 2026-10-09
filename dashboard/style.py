import streamlit as st

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
html,body,.stApp,[class*="css"]{font-family:'Inter',sans-serif;color:#0f172a}
.stApp{background:#f8fafc}
header[data-testid="stHeader"],footer,#MainMenu,[data-testid="stSidebarNav"]{display:none}
.block-container{padding:1rem 2rem 3rem;max-width:1280px}
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e5e7eb;min-width:260px}

/* Sidebar nav links */
a[data-testid="stPageLink-NavLink"]{border-radius:10px;padding:.5rem .75rem;color:#334155;display:flex;align-items:center;gap:.5rem;text-decoration:none;transition:background .15s;margin-bottom:2px}
a[data-testid="stPageLink-NavLink"]:hover{background:#f1f5f9;color:#0f172a}
a[data-testid="stPageLink-NavLink"] p,a[data-testid="stPageLink-NavLink"] span{color:#334155!important;font-weight:500;font-size:.92rem;margin:0}
a[data-testid="stPageLink-NavLink"][aria-current="page"]{background:#4f46e5!important}
a[data-testid="stPageLink-NavLink"][aria-current="page"] p,
a[data-testid="stPageLink-NavLink"][aria-current="page"] span{color:#fff!important}

/* Streamlit buttons - fix black button issue */
.stButton > button{background:#fff;color:#0f172a;border:1px solid #e2e8f0;border-radius:10px;font-weight:600;font-size:.9rem;padding:.5rem 1.1rem;transition:background .15s,border-color .15s}
.stButton > button:hover{background:#f1f5f9;border-color:#cbd5e1}
.stButton > button:active{background:#e2e8f0}
.stButton > button[kind="primary"]{background:#4f46e5;color:#fff;border-color:#4f46e5}
.stButton > button[kind="primary"]:hover{background:#4338ca;border-color:#4338ca}

/* Typography */
.mono{font-family:'JetBrains Mono',monospace}

/* Brand / Sidebar */
.bf-brand{display:flex;gap:.6rem;align-items:center;margin-bottom:1.2rem}
.bf-brand .logo{width:38px;height:38px;border-radius:10px;background:#4f46e5;color:#fff;display:grid;place-items:center;font-weight:800}
.bf-brand small{display:block;color:#64748b;font-size:.7rem}
.bf-nav-label{font-size:.68rem;letter-spacing:.08em;color:#64748b;margin:.5rem 0}
.bf-user{display:flex;gap:.6rem;align-items:center;background:#eef2ff;border-radius:12px;padding:.6rem;margin-top:2rem}
.bf-user .av{width:34px;height:34px;border-radius:50%;background:#5b21b6;color:#fff;display:grid;place-items:center;font-weight:700;font-size:.8rem}
.bf-user small{display:block;color:#64748b;font-size:.7rem}

/* Top bar */
.bf-top{display:flex;align-items:center;gap:1rem;margin-bottom:1.2rem}
.bf-top .crumb{color:#475569;font-size:.9rem}
.bf-search{flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.55rem .9rem;color:#94a3b8;font-size:.85rem;display:flex;justify-content:space-between}
.bf-org{background:#eef2ff;border-radius:999px;padding:.3rem .8rem;font-size:.8rem;display:flex;gap:.5rem;align-items:center}
.bf-avatar{width:34px;height:34px;border-radius:50%;background:#4f46e5;color:#fff;display:grid;place-items:center}

/* Page header */
.bf-head{display:flex;justify-content:space-between;align-items:flex-end;margin:.5rem 0 1.2rem;gap:1rem}
.bf-head h1{font-size:2.1rem;font-weight:700;margin:0;line-height:1.1;letter-spacing:-.02em}
.bf-head p{color:#475569;margin:.3rem 0 0}
.bf-crumbs{font-size:.85rem;color:#475569}.bf-crumbs b{color:#4338ca;font-weight:500}
.bf-actions{display:flex;gap:.6rem}
.bf-btn{border-radius:10px;padding:.6rem 1rem;font-weight:600;font-size:.9rem;border:1px solid #e5e7eb;background:#fff;white-space:nowrap;cursor:pointer}
.bf-btn.primary{background:#4f46e5;color:#fff;border-color:#4f46e5}

/* Cards */
.bf-card{background:#fff;border-radius:16px;padding:1.3rem;box-shadow:0 1px 3px rgba(15,23,42,.06);border:1px solid #f1f5f9}
.bf-card h3{margin:0;font-size:1.2rem;font-weight:700}
.bf-card .subt{color:#64748b;font-size:.85rem;margin:.2rem 0 1rem}
.bf-card .ch{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}

/* Grid */
.bf-grid{display:grid;gap:1rem;margin-bottom:1rem}
.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.g21{grid-template-columns:2fr 1fr}.g12{grid-template-columns:1fr 1.2fr}

/* KPI */
.bf-kpi .row{display:flex;justify-content:space-between;align-items:center;color:#334155;font-size:.9rem}
.bf-kpi .val{font-size:2.3rem;font-weight:700;margin:.8rem 0 .2rem;letter-spacing:-.02em}
.bf-kpi .sub{font-size:.82rem;color:#0369a1}.bf-kpi .sub.red{color:#b91c1c}.bf-kpi .sub.gray{color:#64748b}
.ico{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-style:normal}
.ico.indigo{background:#ede9fe}.ico.blue{background:#dbeafe}.ico.red{background:#fee2e2}

/* Badges */
.bf-badge{display:inline-block;border-radius:999px;padding:.15rem .6rem;font-size:.72rem;font-weight:600;background:#eef2ff;color:#4338ca}
.bf-badge.green{background:#dcfce7;color:#166534}.bf-badge.amber{background:#fef3c7;color:#b45309}
.bf-badge.blue{background:#e0f2fe;color:#0369a1}.bf-badge.red{background:#fee2e2;color:#b91c1c}
.bf-badge.gray{background:#f1f5f9;color:#475569}.bf-badge.purple{background:#f3e8ff;color:#7e22ce}

/* Bar / Donut */
.bf-bar{height:8px;border-radius:99px;background:#e0e7ff;overflow:hidden;min-width:70px}
.bf-bar span{display:block;height:100%;border-radius:99px}
.bf-donut{border-radius:50%;background:conic-gradient(var(--c) calc(var(--p)*1%),#e0e7ff 0);display:grid;place-items:center}
.bf-donut>div{width:76%;height:76%;background:#fff;border-radius:50%;display:grid;place-content:center;text-align:center}
.bf-donut b{font-size:1.9rem}.bf-donut small{font-size:.65rem;color:#64748b;letter-spacing:.08em}

/* Columns chart */
.bf-cols{display:flex;align-items:flex-end;gap:.6rem}
.bf-cols div{flex:1;border-radius:6px 6px 0 0;position:relative}
.bf-cols small{position:absolute;bottom:-1.4rem;left:0;right:0;text-align:center;color:#64748b;font-size:.7rem}

/* Table */
table.bf-table{width:100%;border-collapse:collapse;font-size:.88rem}
.bf-table th{background:#eef2ff;text-align:left;font-size:.7rem;letter-spacing:.06em;color:#475569;padding:.8rem 1rem;font-weight:600}
.bf-table td{padding:.9rem 1rem;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.bf-table small{display:block;color:#64748b}

/* Chips */
.bf-chip{border-radius:999px;padding:.4rem .9rem;font-size:.85rem;background:#f1f5f9;margin-right:.4rem;display:inline-block}
.bf-chip.on{background:#4f46e5;color:#fff}

/* Task / Insight / Box */
.bf-task{border-radius:14px;padding:1.1rem;background:#fff;border:1px solid #f1f5f9}
.bf-task.on{background:#eef2ff}.bf-task h4{margin:.6rem 0 .2rem}.bf-task p{color:#475569;font-size:.85rem;margin:0 0 .8rem}
.bf-task .chk{float:right;width:22px;height:22px;border-radius:6px;border:2px solid #c7d2fe}.bf-task.on .chk{background:#3730a3;border-color:#3730a3}
.bf-insight{background:#eef2ff;border-radius:14px;padding:1rem;margin-bottom:.8rem}
.bf-tl{display:flex;gap:.8rem;margin-bottom:1rem}
.bf-tl i{width:30px;height:30px;border-radius:50%;background:#ede9fe;display:grid;place-items:center;flex:none;font-style:normal}
.bf-tl.act>div:last-child{background:#eef2ff;border-radius:10px;padding:.3rem .6rem;flex:1}
.bf-tl .t{float:right;color:#64748b;font-family:'JetBrains Mono',monospace;font-size:.75rem}
.bf-box{background:#eef2ff;border-radius:12px;padding:.8rem 1rem;margin-bottom:.7rem}
.bf-box small{display:block;font-size:.68rem;letter-spacing:.08em;color:#64748b}

/* Spinner - clean light style */
.stSpinner > div{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:1rem 1.5rem;box-shadow:0 4px 16px rgba(15,23,42,.08)}
.stSpinner > div > div{border-color:#4f46e5 transparent transparent transparent}
.stSpinner p{color:#475569;font-size:.9rem;font-weight:500}

/* Login */
.bf-login-left{background:#0b1020;color:#fff;min-height:92vh;padding:4rem 4.5rem}
.bf-login-left h1{font-size:3.4rem;line-height:1.05;font-weight:800;margin:2.5rem 0 1rem;color:#fff}
.bf-login-left p{color:#94a3b8;font-size:1.15rem}
"""


def load_css():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)