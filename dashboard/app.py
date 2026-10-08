import streamlit as st
from style import load_css
from components import html

st.set_page_config(page_title="BIFlow · Sign in", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
load_css()
st.markdown("<style>section[data-testid='stSidebar'],[data-testid='collapsedControl']{display:none}"
            ".block-container{padding:0!important;max-width:100%!important}</style>", unsafe_allow_html=True)

left, right = st.columns(2, gap="small")
with left:
    html('''<div class="bf-login-left">
      <div class="bf-brand"><div class="logo">B</div><div><b style="color:#fff">BIFlow</b><small>Intelligent Business Intelligence</small></div></div>
      <div style="margin-top:3.5rem"><span class="bf-badge" style="background:#0f1a33;color:#cbd5e1;border:1px solid #1e2a4a">● AI-POWERED BUSINESS INTELLIGENCE</span></div>
      <h1>Turn your data<br>into decisions.</h1>
      <p>BIFlow transforms raw business data into reliable insights using AI-powered Business Intelligence.</p>
      <div style="margin-top:8rem;border:1px solid #1e2a4a;border-radius:18px;padding:2rem;display:flex;gap:1rem;align-items:center">
        <div style="background:#111a33;padding:.8rem 1rem;border-radius:12px"><small style="color:#94a3b8">SOURCE</small><br>Customer data</div>
        <span style="color:#38bdf8">- - - -</span>
        <div style="background:#1e2a5a;padding:1rem;border-radius:12px;border:1px solid #4f46e5">✨ BIFlow intelligence</div></div>
    </div>''')
with right:
    st.write(""); st.write("")
    _, mid, _ = st.columns([0.1, 0.8, 0.1])
    with mid:
        html('<h1 style="margin:3rem 0 0;font-size:2.2rem">Welcome back</h1>'
             '<p style="color:#64748b">Sign in to continue to your BIFlow workspace.</p>')
        st.text_input("Email", value="sarah@northstarlabs.com")
        st.text_input("Password", value="•" * 19, type="password")
        c1, c2 = st.columns(2)
        c1.checkbox("Remember me", value=True)
        c2.markdown("<div style='text-align:right;color:#4f46e5;padding-top:.4rem'>Forgot password?</div>", unsafe_allow_html=True)
        if st.button("Sign in", type="primary", use_container_width=True):
            st.switch_page("pages/1_Overview.py")
        st.markdown("<div style='text-align:center;color:#94a3b8;margin:.6rem'>OR</div>", unsafe_allow_html=True)
        st.button("Continue with Google", use_container_width=True)
        html("<p style='text-align:center;color:#64748b'>Don't have an account? <b style='color:#4f46e5'>Create account</b></p>")