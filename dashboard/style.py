import streamlit as st

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
html,body,.stApp,[class*="css"]{font-family:'Inter',sans-serif;color:#0f172a}
.stApp{background:#f8fafc}
footer,#MainMenu,[data-testid="stSidebarNav"]{display:none}
[data-testid="stHeader"]{background:transparent}
[data-testid="collapsedControl"]{display:flex!important;visibility:visible!important}
.block-container{padding:1rem 2rem 3rem;max-width:1280px}
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e5e7eb;min-width:260px}
a[data-testid="stPageLink-NavLink"]{border-radius:10px;padding:.5rem .75rem;color:#334155!important}
a[data-testid="stPageLink-NavLink"] p{color:#334155!important}
a[data-testid="stPageLink-NavLink"][aria-current="page"]{background:#4f46e5}
a[data-testid="stPageLink-NavLink"][aria-current="page"] p{color:#fff!important}
a[data-testid="stPageLink-NavLink"][aria-current="page"] *{color:#fff!important}
section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] b,section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] div{color:#334155}
section[data-testid="stSidebar"] button p{color:#334155!important}
button[kind="secondary"]{background:#fff!important;color:#334155!important;border:1px solid #e5e7eb!important;border-radius:10px;font-weight:600}
button[kind="secondary"] p{color:#334155!important}
button[kind="secondary"]:hover{border-color:#a5b4fc!important;color:#4338ca!important}
button[kind="primary"]{background:#4f46e5!important;border:none;border-radius:10px;font-weight:600;color:#fff!important}
button[kind="primary"] p{color:#fff!important}
.mono{font-family:'JetBrains Mono',monospace}
.bf-brand{display:flex;gap:.6rem;align-items:center;margin-bottom:1.2rem}
.bf-brand .logo{width:38px;height:38px;border-radius:10px;background:#4f46e5;color:#fff;display:grid;place-items:center;font-weight:800}
.bf-brand small{display:block;color:#64748b;font-size:.7rem}
.bf-nav-label{font-size:.68rem;letter-spacing:.08em;color:#64748b;margin:.5rem 0}
.bf-user{display:flex;gap:.6rem;align-items:center;background:#eef2ff;border-radius:12px;padding:.6rem;margin-top:2rem}
.bf-user .av{width:34px;height:34px;border-radius:50%;background:#5b21b6;color:#fff;display:grid;place-items:center;font-weight:700;font-size:.8rem}
.bf-user small{display:block;color:#64748b;font-size:.7rem}
div[data-testid="stPopover"]>button{width:100%;border:1px solid #e3e8fb!important;border-radius:16px!important;background:linear-gradient(135deg,#ffffff 55%,#f5f7ff)!important;color:#1e293b!important;font-weight:600;box-shadow:0 2px 6px rgba(15,23,42,.05);transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
div[data-testid="stPopover"]>button:hover{border-color:#a5b4fc!important;color:#4338ca!important;transform:translateY(-3px);box-shadow:0 14px 30px rgba(99,102,241,.18)}
div[data-testid="stPopover"]>button p{color:#1e293b!important;font-weight:600}
.bf-top{display:flex;align-items:center;gap:1rem;margin-bottom:1.2rem}
.bf-top .crumb{color:#475569;font-size:.9rem}
.bf-search{flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.55rem .9rem;color:#94a3b8;font-size:.85rem;display:flex;justify-content:space-between}
.bf-org{background:#eef2ff;border-radius:999px;padding:.3rem .8rem;font-size:.8rem;display:flex;gap:.5rem;align-items:center}
.bf-avatar{width:34px;height:34px;border-radius:50%;background:#4f46e5;color:#fff;display:grid;place-items:center}
.bf-head{display:flex;justify-content:space-between;align-items:flex-end;margin:.5rem 0 1.2rem;gap:1rem}
.bf-head h1{font-size:2.1rem;font-weight:700;margin:0;line-height:1.1;letter-spacing:-.02em}
.bf-head p{color:#475569;margin:.3rem 0 0}
.bf-crumbs{font-size:.85rem;color:#475569}.bf-crumbs b{color:#4338ca;font-weight:500}
.bf-actions{display:flex;gap:.6rem}
.bf-btn{border-radius:10px;padding:.6rem 1rem;font-weight:600;font-size:.9rem;border:1px solid #e5e7eb;background:#fff;white-space:nowrap}
.bf-btn.primary{background:#4f46e5;color:#fff;border-color:#4f46e5}
.bf-card{background:#fff;border-radius:16px;padding:1.3rem;box-shadow:0 1px 3px rgba(15,23,42,.06);border:1px solid #f1f5f9}
.bf-card h3{margin:0;font-size:1.2rem;font-weight:700}
.bf-card .subt{color:#64748b;font-size:.85rem;margin:.2rem 0 1rem}
.bf-card .ch{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}
.bf-grid{display:grid;gap:1rem;margin-bottom:1rem}
.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.g21{grid-template-columns:2fr 1fr}.g12{grid-template-columns:1fr 1.2fr}
.bf-kpi .row{display:flex;justify-content:space-between;align-items:center;color:#334155;font-size:.9rem}
.bf-kpi .val{font-size:2.3rem;font-weight:700;margin:.8rem 0 .2rem;letter-spacing:-.02em}
.bf-kpi .sub{font-size:.82rem;color:#0369a1}.bf-kpi .sub.red{color:#b91c1c}.bf-kpi .sub.gray{color:#64748b}
.ico{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-style:normal}
.ico.indigo{background:#ede9fe}.ico.blue{background:#dbeafe}.ico.red{background:#fee2e2}
.bf-badge{display:inline-block;border-radius:999px;padding:.15rem .6rem;font-size:.72rem;font-weight:600;background:#eef2ff;color:#4338ca}
.bf-badge.green{background:#dcfce7;color:#166534}.bf-badge.amber{background:#fef3c7;color:#b45309}
.bf-badge.blue{background:#e0f2fe;color:#0369a1}.bf-badge.red{background:#fee2e2;color:#b91c1c}
.bf-badge.gray{background:#f1f5f9;color:#475569}.bf-badge.purple{background:#f3e8ff;color:#7e22ce}
.bf-bar{height:8px;border-radius:99px;background:#e0e7ff;overflow:hidden;min-width:70px}
.bf-bar span{display:block;height:100%;border-radius:99px}
.bf-donut{border-radius:50%;background:conic-gradient(var(--c) calc(var(--p)*1%),#e0e7ff 0);display:grid;place-items:center}
.bf-donut>div{width:76%;height:76%;background:#fff;border-radius:50%;display:grid;place-content:center;text-align:center}
.bf-donut b{font-size:1.9rem}.bf-donut small{font-size:.65rem;color:#64748b;letter-spacing:.08em}
.bf-cols{display:flex;align-items:flex-end;gap:.6rem}
.bf-cols div{flex:1;border-radius:6px 6px 0 0;position:relative}
.bf-cols small{position:absolute;bottom:-1.4rem;left:0;right:0;text-align:center;color:#64748b;font-size:.7rem}
table.bf-table{width:100%;border-collapse:collapse;font-size:.88rem}
.bf-table th{background:#eef2ff;text-align:left;font-size:.7rem;letter-spacing:.06em;color:#475569;padding:.8rem 1rem;font-weight:600}
.bf-table td{padding:.9rem 1rem;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.bf-table small{display:block;color:#64748b}
.bf-chip{border-radius:999px;padding:.4rem .9rem;font-size:.85rem;background:#f1f5f9;margin-right:.4rem;display:inline-block}
.bf-chip.on{background:#4f46e5;color:#fff}
/* task checkbox alignment */
[data-testid="stCheckbox"]{margin-top:.55rem}
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
.bf-login-left{background:#0b1020;color:#fff;min-height:92vh;padding:4rem 4.5rem}
.bf-login-left h1{font-size:3.4rem;line-height:1.05;font-weight:800;margin:2.5rem 0 1rem;color:#fff}
.bf-login-left p{color:#94a3b8;font-size:1.15rem}
.stApp:has(.bf-landing){background:#071633}
.block-container:has(.bf-landing){padding:0!important;max-width:100%!important}
.block-container>div[data-testid="stHorizontalBlock"]:first-child{position:relative;z-index:2;min-height:76px;align-items:center;padding:.5rem clamp(1rem,5vw,5rem);background:linear-gradient(100deg,#071633,#0b2250 58%,#10326b);border-bottom:1px solid #7dd3fc22}
.bf-site-brand{height:62px;display:flex;align-items:center;gap:.7rem}
.bf-site-brand .bf-landing-logo{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(145deg,#818cf8,#4f46e5);font-size:1.3rem;font-weight:800;color:#fff;box-shadow:0 8px 24px #4f46e544}
.bf-site-brand b{display:block;font-size:1.08rem;letter-spacing:-.03em;color:#f8fbff}
.bf-site-brand small{display:block;color:#9db5dc;font-size:.57rem;letter-spacing:.14em;margin-top:.1rem}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button{min-height:2.65rem;border-radius:11px;border:1px solid #8cb8ff55;background:#ffffff0a;color:#edf5ff;font-weight:650;white-space:nowrap;transition:transform .2s ease,box-shadow .2s ease,background .2s ease}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="secondary"],.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="secondary"] p{background:#ffffff0a!important;color:#edf5ff!important}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="primary"] p{color:#fff!important}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button:hover{transform:translateY(-2px);background:#ffffff18;box-shadow:0 8px 26px #38bdf833}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="primary"]{background:linear-gradient(110deg,#2563eb,#4f46e5 55%,#0ea5e9);border:1px solid #93c5fd77;box-shadow:0 7px 24px #2563eb55}
.stApp:has(.bf-landing) button[kind="secondary"],.stApp:has(.bf-landing) button[kind="secondary"] p{background:linear-gradient(145deg,#12315f,#0d2450)!important;color:#edf5ff!important;border-color:#7dd3fc66!important}
.stApp:has(.bf-landing) button[kind="primary"]{color:#fff!important;background:linear-gradient(110deg,#2563eb,#4f46e5 55%,#0ea5e9)!important;border:1px solid #93c5fd77!important;box-shadow:0 7px 24px #2563eb55}
.stApp:has(.bf-landing) button[kind="primary"] p{color:#fff!important}
div[data-testid="stDialog"] [role="dialog"]{border:1px solid #7dd3fc55;border-radius:22px;background:linear-gradient(150deg,#102754,#0b1c3d);box-shadow:0 28px 100px #020617aa;color:#eef6ff}
div[data-testid="stDialog"] [role="dialog"] h2,div[data-testid="stDialog"] [role="dialog"] label,div[data-testid="stDialog"] [role="dialog"] p{color:#eef6ff}
div[data-testid="stDialog"] button[kind="primary"]{color:#fff!important;background:linear-gradient(110deg,#2563eb,#4f46e5 55%,#0ea5e9)!important;border:1px solid #93c5fd77!important;box-shadow:0 7px 24px #2563eb55}
div[data-testid="stDialog"] button[kind="primary"] p{color:#fff!important}
div[data-testid="stDialog"] input{background:#0a1a39!important;border:1px solid #6993cc55!important;border-radius:10px!important;color:#f8fbff!important}
div[data-testid="stDialog"] [data-testid="stWidgetLabel"] p{font-size:.78rem;font-weight:600}
.bf-landing{color:#fff;background:#071633}
.bf-hero{min-height:calc(100vh - 76px);position:relative;overflow:hidden;box-sizing:border-box;padding:2rem clamp(1.5rem,7vw,7rem) 1.5rem;background:radial-gradient(ellipse at 65% 35%,rgba(37,99,235,.48),transparent 42%),radial-gradient(ellipse at 88% 75%,rgba(14,165,233,.24),transparent 32%),linear-gradient(145deg,#081633,#0a2050 55%,#0d3470);display:grid;grid-template-columns:minmax(0,1.08fr) minmax(340px,.92fr);grid-template-rows:1fr auto;align-items:center;column-gap:clamp(2rem,6vw,6rem)}
.bf-hero:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(125,211,252,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(125,211,252,.055) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(#000,transparent 90%);pointer-events:none}
.bf-hero-orb{position:absolute;width:520px;height:520px;border-radius:50%;border:1px solid #7dd3fc22;top:50%;left:72%;transform:translate(-50%,-50%);box-shadow:0 0 0 65px #38bdf811,0 0 0 130px #38bdf809;pointer-events:none;animation:bf-orb-pulse 8s ease-in-out infinite}
.bf-hero-content{position:relative;max-width:620px;grid-column:1;grid-row:1;text-align:left}
.bf-landing-eyebrow{display:inline-flex;align-items:center;gap:.55rem;color:#c7d2fe;font-size:.67rem;font-weight:700;letter-spacing:.13em}
.bf-landing-eyebrow i,.bf-preview-head i{width:7px;height:7px;border-radius:50%;background:#4ade80;box-shadow:0 0 12px #4ade80;display:inline-block}
.bf-hero-content h1{font-size:clamp(3.5rem,5.6vw,5.5rem);line-height:.99;letter-spacing:-.075em;margin:1.2rem 0 1.15rem;color:#fff;font-weight:700}
.bf-hero-content h1 em{font-style:normal;background:linear-gradient(90deg,#bfdbfe,#67e8f9,#93c5fd);background-size:180% 100%;background-clip:text;-webkit-background-clip:text;color:transparent;animation:bf-gradient 5s ease infinite}
.bf-hero-content p{max-width:590px;margin:0;color:#b6c1d8;line-height:1.8;font-size:clamp(.95rem,1.2vw,1.08rem)}
.bf-hero-actions{display:flex;justify-content:flex-start;flex-wrap:wrap;gap:.55rem;margin-top:1.5rem}
.bf-hero-actions span{border:1px solid #ffffff20;background:#ffffff09;color:#dbeafe;border-radius:999px;padding:.55rem .9rem;font-size:.68rem}
.bf-preview{position:relative;width:100%;max-width:620px;box-sizing:border-box;grid-column:2;grid-row:1;margin:0 auto;border-radius:22px;padding:1.15rem 1.3rem 1rem;background:linear-gradient(145deg,#164080cc,#10295bcc 55%,#0b1e42dd);border:1px solid #93c5fd55;box-shadow:0 26px 70px #02061788,0 0 35px #2563eb22;backdrop-filter:blur(16px);animation:bf-float 7s ease-in-out infinite;transition:transform .3s ease,box-shadow .3s ease}
.bf-preview:hover{transform:translateY(-7px) scale(1.012);box-shadow:0 34px 80px #02061799,0 0 44px #38bdf844}
.bf-preview-head,.bf-preview-foot{display:flex;align-items:center;justify-content:space-between;color:#9eabc5;font-size:.58rem;letter-spacing:.1em}
.bf-preview-head span:first-child{display:flex;align-items:center;gap:.45rem}
.bf-preview-head i{width:6px;height:6px}
.bf-preview-title{font-size:.95rem;font-weight:600;margin:1rem 0 .85rem;color:#f8fafc}
.bf-preview-title b{float:right;color:#818cf8}
.bf-preview-stats{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}
.bf-preview-stats>div{background:linear-gradient(145deg,#ffffff12,#38bdf80d);border:1px solid #bfdbfe24;border-radius:13px;padding:.7rem .8rem;transition:transform .25s ease,border-color .25s ease}
.bf-preview-stats>div:hover{transform:translateY(-3px);border-color:#7dd3fc88}
.bf-preview-stats small,.bf-preview-stats strong,.bf-preview-stats i{display:block}
.bf-preview-stats small{font-size:.55rem;letter-spacing:.08em;color:#9eabc5}
.bf-preview-stats strong{font-size:1.55rem;line-height:1.3;color:#fff}
.bf-preview-stats strong span{font-size:.9rem;color:#c7d2fe}
.bf-preview-stats i{font-style:normal;color:#6ee7b7;font-size:.58rem}
.bf-preview-chart{height:76px;display:flex;align-items:flex-end;gap:3.2%;padding:.8rem .25rem .25rem;border-bottom:1px solid #ffffff20;background:repeating-linear-gradient(to bottom,transparent 0,transparent 24px,#ffffff0b 25px)}
.bf-preview-chart span{flex:1;border-radius:4px 4px 1px 1px;background:linear-gradient(0deg,#2563eb,#67e8f9);opacity:.9;transform-origin:bottom;animation:bf-chart-in .8s cubic-bezier(.2,.8,.2,1) both}
.bf-preview-chart span:nth-child(2n){animation-delay:.08s}.bf-preview-chart span:nth-child(3n){animation-delay:.16s}
.bf-preview-foot{padding-top:.4rem;font-size:.52rem;letter-spacing:0}
.bf-hero-bottom{position:relative;width:100%;grid-column:1/-1;grid-row:2;display:flex;justify-content:space-between;margin-top:auto;padding-top:1.5rem;color:#9eabc5;font-size:.65rem}
.bf-features{position:relative;overflow:hidden;padding:clamp(3rem,8vw,6rem) clamp(1.2rem,8vw,8rem);background:radial-gradient(ellipse at 50% 0%,#17458a 0%,transparent 55%),linear-gradient(160deg,#0b2250,#081936 72%);color:#f8fbff}
.bf-features-heading{text-align:center;max-width:650px;margin:0 auto 2.5rem}
.bf-features-heading>span{color:#7dd3fc;font-size:.65rem;font-weight:700;letter-spacing:.13em}
.bf-features-heading h2{font-size:clamp(2rem,4vw,3rem);letter-spacing:-.055em;margin:.65rem 0;color:#f8fbff}
.bf-features-heading p{color:#b7c9e5;font-size:.92rem;line-height:1.7}
.bf-feature-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;max-width:1180px;margin:auto}
.bf-feature-grid article{position:relative;overflow:hidden;padding:1.5rem;border:1px solid #7dd3fc30;border-radius:20px;background:linear-gradient(145deg,#15417acc,#0e2a58dd 58%,#10234dcc);box-shadow:0 16px 45px #02061744;transition:transform .28s ease,border-color .28s ease,box-shadow .28s ease}
.bf-feature-grid article:before{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 20%,#ffffff0c 45%,transparent 70%);transform:translateX(-120%);transition:transform .7s ease}
.bf-feature-grid article:hover{transform:translateY(-9px);border-color:#67e8f988;box-shadow:0 24px 54px #02061777,0 0 28px #2563eb33}
.bf-feature-grid article:hover:before{transform:translateX(120%)}
.bf-feature-icon{width:46px;height:46px;border-radius:14px;display:grid;place-items:center;font-size:1.35rem;margin-bottom:1.4rem;box-shadow:0 8px 24px #02061730}
.bf-feature-icon.blue{background:linear-gradient(145deg,#38bdf8,#2563eb);color:#fff}.bf-feature-icon.violet{background:linear-gradient(145deg,#818cf8,#4f46e5);color:#fff}.bf-feature-icon.teal{background:linear-gradient(145deg,#2dd4bf,#0284c7);color:#fff}
.bf-feature-grid article>small{font-size:.58rem;font-weight:700;letter-spacing:.1em;color:#9cc8fa}
.bf-feature-grid h3{margin:.55rem 0;font-size:1.1rem;letter-spacing:-.025em;color:#f8fbff}
.bf-feature-grid p{margin:0;color:#c2d2e9;font-size:.83rem;line-height:1.7}
.bf-features-foot{max-width:1180px;margin:2.2rem auto 0;padding-top:1rem;border-top:1px solid #7dd3fc30;display:flex;justify-content:space-between;gap:1rem;color:#a9bfdf;font-size:.68rem}
@keyframes bf-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}
@keyframes bf-orb-pulse{0%,100%{opacity:.55;transform:translate(-50%,-50%) scale(.98)}50%{opacity:1;transform:translate(-50%,-50%) scale(1.04)}}
@keyframes bf-gradient{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
@keyframes bf-chart-in{from{transform:scaleY(.05);opacity:.2}to{transform:scaleY(1);opacity:.9}}
@media(max-width:760px){.block-container>div[data-testid="stHorizontalBlock"]:first-child{padding:.45rem .7rem}.bf-site-brand{height:60px;padding-left:.1rem}.block-container>div[data-testid="stHorizontalBlock"]:first-child button{min-width:0;padding:.35rem .5rem;font-size:.78rem}.bf-hero{min-height:auto;grid-template-columns:1fr;grid-template-rows:auto auto auto;gap:2rem;padding:4rem 1.5rem 1.4rem}.bf-hero-content{grid-column:1;grid-row:1;max-width:700px;margin:auto;text-align:center}.bf-hero-content h1{font-size:clamp(3rem,9vw,5rem)}.bf-hero-content p{margin:auto}.bf-hero-actions{justify-content:center}.bf-preview{grid-column:1;grid-row:2;width:min(620px,100%);margin:auto}.bf-hero-bottom{grid-column:1;grid-row:3}.bf-feature-grid{grid-template-columns:1fr}.bf-features-foot{flex-direction:column}.bf-hero-actions span{font-size:.62rem}}
@media(max-width:520px){.block-container>div[data-testid="stHorizontalBlock"]:first-child{gap:.25rem}.bf-site-brand{padding-left:0}.bf-site-brand .bf-landing-logo{width:32px;height:32px}.bf-site-brand small{font-size:.43rem}.block-container>div[data-testid="stHorizontalBlock"]:first-child button{font-size:.7rem}.bf-hero{padding:3rem 1rem 1.2rem}.bf-preview{padding:.9rem}.bf-preview-stats{gap:.4rem}.bf-preview-stats>div{padding:.6rem}.bf-features{padding:3rem 1rem}}
"""


def load_css():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)