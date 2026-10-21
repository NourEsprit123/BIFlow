import importlib
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth import (
    UserAlreadyExistsError,
    authenticate_user,
    register_user,
    validate_email,
    validate_password,
)
from components import html
import style

importlib.reload(style)
load_dotenv(PROJECT_ROOT / ".env")

st.set_page_config(
    page_title="BIFlow · Your data, in focus",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)
style.load_css()

LANDING_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap');
section[data-testid='stSidebar'],[data-testid='collapsedControl'],header[data-testid='stHeader']{display:none}
.stApp{background:#070b1f;font-family:'Inter',sans-serif}
.block-container{padding:0!important;max-width:100%!important}

/* ---------- Top bar (Streamlit buttons) ---------- */
.block-container>div[data-testid="stHorizontalBlock"]:first-child{
  position:sticky;top:0;z-index:50;min-height:76px;align-items:center;
  padding:14px clamp(1rem,5vw,4rem);
  background:rgba(7,11,31,.72)!important;backdrop-filter:blur(14px);
  border-bottom:1px solid rgba(255,255,255,.07)}
.stButton button{border-radius:12px;font-weight:600;font-family:'Inter',sans-serif;transition:all .25s ease}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="secondary"],
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="secondary"] p{
  background:transparent!important;color:#e2e8f0!important;border-color:rgba(255,255,255,.18)!important}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="secondary"]:hover{
  border-color:#818cf8!important;background:rgba(129,140,248,.12)!important}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="primary"],
.stButton button[kind="primary"]{
  background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;border:0!important;
  box-shadow:0 8px 24px rgba(99,102,241,.35)}
.block-container>div[data-testid="stHorizontalBlock"]:first-child button[kind="primary"] p{color:#fff!important}
.stButton button[kind="primary"]:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(99,102,241,.5)}

/* ---------- Brand ---------- */
.bf2-brand{display:flex;align-items:center;gap:12px}
.bf2-logo{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;color:#fff;font-weight:800;
  font-size:1.2rem;background:linear-gradient(135deg,#6366f1,#a855f7);box-shadow:0 6px 20px rgba(99,102,241,.5)}
.bf2-brand b{display:block;color:#fff;font-size:1.15rem;letter-spacing:-.01em}
.bf2-brand small{display:block;color:#818cf8;font-size:.62rem;letter-spacing:.18em;font-weight:600}

/* ---------- Hero ---------- */
.bf2-hero{position:relative;overflow:hidden;display:grid;grid-template-columns:1.1fr .9fr;gap:56px;align-items:center;
  padding:96px 64px 72px;min-height:88vh;
  background:radial-gradient(ellipse at 15% 0%,rgba(99,102,241,.28),transparent 55%),
             radial-gradient(ellipse at 90% 40%,rgba(168,85,247,.22),transparent 55%)}
.bf2-hero::before{content:"";position:absolute;inset:0;opacity:.5;pointer-events:none;
  background-image:radial-gradient(rgba(255,255,255,.09) 1px,transparent 1px);background-size:28px 28px;
  -webkit-mask-image:radial-gradient(ellipse at center,#000 30%,transparent 75%);mask-image:radial-gradient(ellipse at center,#000 30%,transparent 75%)}
.bf2-orb{position:absolute;border-radius:50%;filter:blur(80px);pointer-events:none;animation:bf2float 12s ease-in-out infinite}
.bf2-orb.a{width:380px;height:380px;background:#4f46e5;opacity:.35;top:-120px;left:-80px}
.bf2-orb.b{width:320px;height:320px;background:#9333ea;opacity:.28;bottom:-100px;right:8%;animation-delay:-5s}
@keyframes bf2float{0%,100%{transform:translateY(0)}50%{transform:translateY(28px)}}
@keyframes bf2up{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:none}}
@keyframes bf2grow{from{transform:scaleY(.05)}to{transform:scaleY(1)}}
.bf2-content{position:relative;z-index:2;animation:bf2up .8s ease both}
.bf2-eyebrow{display:inline-flex;align-items:center;gap:10px;padding:8px 16px;border-radius:999px;
  background:rgba(99,102,241,.14);border:1px solid rgba(129,140,248,.35);color:#c7d2fe;
  font-size:.72rem;font-weight:600;letter-spacing:.14em}
.bf2-eyebrow i{width:8px;height:8px;border-radius:50%;background:#34d399;box-shadow:0 0 10px #34d399}
.bf2-hero h1{margin:26px 0 22px;color:#fff;font-size:clamp(2.6rem,5.2vw,4.6rem);line-height:1.05;
  font-weight:800;letter-spacing:-.035em}
.bf2-hero h1 em{font-style:normal;background:linear-gradient(120deg,#818cf8,#c084fc 50%,#f0abfc);
  -webkit-background-clip:text;background-clip:text;color:transparent}
.bf2-hero p{color:#94a3b8;font-size:1.12rem;line-height:1.75;max-width:560px;margin:0 0 34px}
.bf2-steps{display:flex;flex-wrap:wrap;gap:12px}
.bf2-steps span{padding:10px 18px;border-radius:12px;color:#cbd5e1;font-size:.85rem;font-weight:500;
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);transition:all .25s}
.bf2-steps span:hover{background:rgba(129,140,248,.16);border-color:rgba(129,140,248,.5);transform:translateY(-3px)}
.bf2-steps b{color:#818cf8;margin-right:8px;font-family:'JetBrains Mono',monospace}

/* ---------- Preview card ---------- */
.bf2-visual{position:relative;z-index:2;animation:bf2up 1s .15s ease both}
.bf2-card{padding:26px;border-radius:24px;background:linear-gradient(160deg,rgba(255,255,255,.11),rgba(255,255,255,.04));
  border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(18px);
  box-shadow:0 40px 90px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.15);
  transform:perspective(1200px) rotateY(-6deg) rotateX(2deg);transition:transform .5s ease}
.bf2-card:hover{transform:perspective(1200px) rotateY(0) rotateX(0)}
.bf2-card-head{display:flex;justify-content:space-between;color:#94a3b8;font-size:.68rem;letter-spacing:.14em;font-weight:600}
.bf2-card-head i{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399;margin-right:8px}
.bf2-card h4{margin:14px 0 20px;color:#fff;font-size:1.25rem;font-weight:700}
.bf2-stats{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:22px}
.bf2-stats div{padding:16px;border-radius:16px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08)}
.bf2-stats small{display:block;color:#94a3b8;font-size:.62rem;letter-spacing:.12em;font-weight:600}
.bf2-stats strong{display:block;color:#fff;font-size:2.1rem;margin:6px 0 2px;letter-spacing:-.03em}
.bf2-stats strong span{font-size:1.1rem;color:#a5b4fc}
.bf2-stats i{font-style:normal;color:#34d399;font-size:.74rem;font-weight:600}
.bf2-chart{display:flex;align-items:flex-end;gap:8px;height:130px;padding-top:8px}
.bf2-chart span{flex:1;border-radius:7px 7px 3px 3px;transform-origin:bottom;
  background:linear-gradient(180deg,#a78bfa,#4f46e5);animation:bf2grow 1s ease both}
.bf2-chart span:nth-child(odd){opacity:.75}
.bf2-chart span:nth-child(1){animation-delay:.1s}.bf2-chart span:nth-child(2){animation-delay:.15s}
.bf2-chart span:nth-child(3){animation-delay:.2s}.bf2-chart span:nth-child(4){animation-delay:.25s}
.bf2-chart span:nth-child(5){animation-delay:.3s}.bf2-chart span:nth-child(6){animation-delay:.35s}
.bf2-chart span:nth-child(7){animation-delay:.4s}.bf2-chart span:nth-child(8){animation-delay:.45s}
.bf2-chart span:nth-child(9){animation-delay:.5s}.bf2-chart span:nth-child(10){animation-delay:.55s}
.bf2-chart span:nth-child(11){animation-delay:.6s}.bf2-chart span:nth-child(12){animation-delay:.65s}
.bf2-months{display:flex;justify-content:space-between;margin-top:10px;color:#64748b;font-size:.7rem}
.bf2-chip{position:absolute;padding:11px 16px;border-radius:14px;color:#e2e8f0;font-size:.8rem;font-weight:600;
  background:rgba(15,23,42,.85);border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(12px);
  box-shadow:0 16px 40px rgba(0,0,0,.45);animation:bf2float 7s ease-in-out infinite}
.bf2-chip.one{top:-22px;right:-12px}
.bf2-chip.two{bottom:-24px;left:-24px;animation-delay:-3s}

/* ---------- Trust strip ---------- */
.bf2-strip{display:flex;justify-content:center;flex-wrap:wrap;gap:14px 44px;padding:26px 48px;
  border-top:1px solid rgba(255,255,255,.07);border-bottom:1px solid rgba(255,255,255,.07);
  background:rgba(255,255,255,.02);color:#64748b;font-size:.78rem;letter-spacing:.16em;font-weight:600}

/* ---------- Features ---------- */
.bf2-features{padding:110px 64px 70px;text-align:center}
.bf2-kicker{color:#818cf8;font-size:.74rem;letter-spacing:.2em;font-weight:700}
.bf2-features h2{margin:16px 0 14px;color:#fff;font-size:clamp(2rem,3.6vw,3rem);font-weight:800;letter-spacing:-.03em}
.bf2-features>p{color:#94a3b8;font-size:1.05rem;max-width:620px;margin:0 auto 56px}
.bf2-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;max-width:1180px;margin:0 auto;text-align:left}
.bf2-feature{position:relative;padding:34px;border-radius:22px;overflow:hidden;
  background:linear-gradient(160deg,rgba(255,255,255,.07),rgba(255,255,255,.02));
  border:1px solid rgba(255,255,255,.09);transition:all .35s ease}
.bf2-feature::after{content:"";position:absolute;inset:0;opacity:0;transition:opacity .35s;pointer-events:none;
  background:radial-gradient(circle at 0% 0%,rgba(129,140,248,.22),transparent 60%)}
.bf2-feature:hover{transform:translateY(-8px);border-color:rgba(129,140,248,.5);box-shadow:0 30px 60px rgba(0,0,0,.4)}
.bf2-feature:hover::after{opacity:1}
.bf2-icon{width:54px;height:54px;border-radius:16px;display:grid;place-items:center;font-size:1.5rem;color:#fff;margin-bottom:22px}
.bf2-icon.blue{background:linear-gradient(135deg,#3b82f6,#6366f1)}
.bf2-icon.violet{background:linear-gradient(135deg,#8b5cf6,#d946ef)}
.bf2-icon.teal{background:linear-gradient(135deg,#14b8a6,#06b6d4)}
.bf2-feature small{display:block;color:#818cf8;font-size:.66rem;letter-spacing:.16em;font-weight:700;margin-bottom:10px}
.bf2-feature h3{margin:0 0 10px;color:#fff;font-size:1.35rem;font-weight:700}
.bf2-feature p{margin:0;color:#94a3b8;line-height:1.7;font-size:.96rem}

/* ---------- Metrics ---------- */
.bf2-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;max-width:1180px;margin:26px auto 0;padding:0 64px}
.bf2-metrics div{text-align:center;padding:28px 12px;border-radius:18px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07)}
.bf2-metrics strong{display:block;font-size:2.3rem;font-weight:800;letter-spacing:-.03em;
  background:linear-gradient(120deg,#a5b4fc,#e879f9);-webkit-background-clip:text;background-clip:text;color:transparent}
.bf2-metrics span{color:#94a3b8;font-size:.82rem}

/* ---------- CTA + footer ---------- */
.bf2-cta{margin:90px 64px 28px;padding:64px 32px 40px;text-align:center;border-radius:28px;
  background:radial-gradient(ellipse at 50% 0%,rgba(139,92,246,.35),transparent 70%),rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.1)}
.bf2-cta h2{margin:0 0 12px;color:#fff;font-size:clamp(1.8rem,3vw,2.6rem);font-weight:800;letter-spacing:-.03em}
.bf2-cta p{margin:0;color:#94a3b8;font-size:1.02rem}
.bf2-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;padding:26px 64px 40px;color:#64748b;font-size:.8rem}

@media (max-width:900px){
  .bf2-hero{grid-template-columns:1fr;padding:64px 24px 56px}
  .bf2-grid,.bf2-metrics{grid-template-columns:1fr}
  .bf2-features{padding:70px 24px 40px}.bf2-metrics{padding:0 24px}
  .bf2-cta{margin:60px 20px 20px}.bf2-foot{padding:20px 24px 32px}
  .bf2-card{transform:none}
  .block-container>div[data-testid="stHorizontalBlock"]:first-child{padding:12px 16px}
}
</style>
"""
st.markdown(LANDING_CSS, unsafe_allow_html=True)


@st.dialog("Sign in to BIFlow")
def show_login_dialog():
    if st.session_state.get("signup_complete"):
        st.success("Your account has been created. Sign in to continue.")
    with st.form("login_form"):
        email = st.text_input(
            "Work email",
            value=st.session_state.get("login_email_value", ""),
            placeholder="you@company.com",
            help="Enter a valid email address.",
        )
        password = st.text_input("Password", placeholder="Enter your password", type="password")
        submitted = st.form_submit_button(
            "Sign in to BIFlow", type="primary", use_container_width=True
        )
    if submitted:
        if not email.strip() or not password:
            st.error("Enter your email and password to continue.")
        else:
            user = authenticate_user(email, password)
            if user is None:
                st.error("The email or password is incorrect.")
            else:
                st.session_state.pop("signup_complete", None)
                st.session_state.pop("login_email_value", None)
                st.session_state["authenticated_user"] = user
                st.switch_page("pages/1_Overview.py")


@st.dialog("Create your BIFlow account")
def show_signup_dialog():
    with st.form("signup_form"):
        name = st.text_input("Full name", placeholder="Your name")
        email = st.text_input(
            "Work email",
            placeholder="you@company.com",
            help="Enter a valid email address.",
        )
        password = st.text_input(
            "Create a password",
            placeholder="At least 8 characters",
            help="Use at least 8 characters, one uppercase letter, and one special character.",
            type="password",
        )
        confirm_password = st.text_input("Confirm password", placeholder="Enter your password again", type="password")
        accepted_terms = st.checkbox("I agree to the Terms of Service and Privacy Policy")
        submitted = st.form_submit_button(
            "Create your account", type="primary", use_container_width=True
        )
    if submitted:
        if not name.strip() or not email.strip() or not password:
            st.error("Complete all fields to continue.")
        elif not confirm_password:
            st.error("Confirm your password to continue.")
        elif password != confirm_password:
            st.error("The passwords do not match.")
        elif not accepted_terms:
            st.error("Please accept the terms to continue.")
        else:
            try:
                validate_email(email)
                validate_password(password)
                register_user(name, email, password)
            except UserAlreadyExistsError as error:
                st.error(str(error))
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["signup_complete"] = True
                st.session_state["login_email_value"] = email.strip()
                st.session_state["open_login_after_signup"] = True
                st.rerun()


# ---------- Top bar ----------
brand, login_column, signup_column = st.columns([7, 1.2, 1.5])
with brand:
    html("""<div class="bf2-brand"><span class="bf2-logo">B</span>
<span><b>BIFlow</b><small>INTELLIGENCE, IN FLOW</small></span></div>""")

with login_column:
    if st.button("Sign in", use_container_width=True):
        show_login_dialog()

with signup_column:
    if st.button("Sign up", type="primary", use_container_width=True):
        show_signup_dialog()

if st.session_state.pop("open_login_after_signup", False):
    show_login_dialog()

# ---------- Hero + features ----------
html("""<main>
<section class="bf2-hero">
<div class="bf2-orb a"></div><div class="bf2-orb b"></div>
<div class="bf2-content">
<span class="bf2-eyebrow"><i></i>YOUR BUSINESS, IN BETTER FOCUS</span>
<h1>Make your data<br>work <em>for you.</em></h1>
<p>BIFlow brings data profiling, quality, cleaning, business analytics and explainable AI into one clear workspace, so every decision starts with understanding.</p>
<div class="bf2-steps"><span><b>01</b>Understand your data</span><span><b>02</b>Find what matters</span><span><b>03</b>Act with confidence</span></div>
</div>
<div class="bf2-visual">
<div class="bf2-chip one">✨ 18 new insights</div>
<div class="bf2-card">
<div class="bf2-card-head"><span><i></i>WORKSPACE OVERVIEW</span><span>LAST 30 DAYS ⌄</span></div>
<h4>Your business at a glance</h4>
<div class="bf2-stats">
<div><small>DATA QUALITY</small><strong>94<span>%</span></strong><i>↑ 3.2% this month</i></div>
<div><small>INSIGHTS FOUND</small><strong>127</strong><i>Across 12 datasets</i></div>
</div>
<div class="bf2-chart"><span style="height:34%"></span><span style="height:50%"></span><span style="height:42%"></span><span style="height:67%"></span><span style="height:57%"></span><span style="height:76%"></span><span style="height:63%"></span><span style="height:91%"></span><span style="height:72%"></span><span style="height:100%"></span><span style="height:84%"></span><span style="height:96%"></span></div>
<div class="bf2-months"><span>Jan</span><span>Mar</span><span>May</span><span>Jul</span><span>Sep</span><span>Oct</span></div>
</div>
<div class="bf2-chip two">🛡 Lineage verified</div>
</div>
</section>
<div class="bf2-strip"><span>PROFILING</span><span>QUALITY</span><span>ANALYTICS</span><span>EXPLAINABILITY</span></div>
<section class="bf2-features">
<span class="bf2-kicker">ONE WORKSPACE, FROM DATA TO DECISION</span>
<h2>Clarity at every step.</h2>
<p>Move from raw data to business understanding with a connected, explainable workflow.</p>
<div class="bf2-grid">
<article class="bf2-feature"><span class="bf2-icon blue">⌕</span><small>01 · DATA FOUNDATION</small><h3>Know your data</h3><p>Profile datasets, spot quality issues and prepare cleaner data with confidence.</p></article>
<article class="bf2-feature"><span class="bf2-icon violet">↗</span><small>02 · BUSINESS INTELLIGENCE</small><h3>See what matters</h3><p>Bring key metrics, dashboards and business insights together in one view.</p></article>
<article class="bf2-feature"><span class="bf2-icon teal">✳</span><small>03 · TRUSTED AI</small><h3>Understand every answer</h3><p>Trace analysis decisions with explainability and clear data lineage.</p></article>
</div>
</section>
<div class="bf2-metrics">
<div><strong>94%</strong><span>Average data quality</span></div>
<div><strong>127</strong><span>Insights surfaced</span></div>
<div><strong>12</strong><span>Datasets connected</span></div>
<div><strong>100%</strong><span>Explainable results</span></div>
</div>
<section class="bf2-cta">
<h2>Ready to see your data clearly?</h2>
<p>Create your free account and start your first analysis in minutes.</p>
</section>
</main>""")

# Bouton d'appel à l'action (ouvre la fenêtre d'inscription)
_, cta_column, _ = st.columns([4, 2, 4])
with cta_column:
    if st.button("Get started for free →", type="primary", use_container_width=True, key="cta_signup"):
        show_signup_dialog()

html("""<div class="bf2-foot"><span>⌁ Built for clearer decisions</span><span>BIFlow © 2026</span></div>""")