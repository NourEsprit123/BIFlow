import os
import streamlit as st

# 1. Importation des composants graphiques de votre collègue et de votre LLM
from components import setup, page_header, html
from llm_manager import executer_requete_llm
from chat_widget import render_chat

# 2. Appel de la configuration en TOUTE PREMIÈRE LIGNE (Injecte le CSS et la Sidebar)
setup("Infrastructure")

# 3. Affichage du chat flottant configuré pour cette page
render_chat("Agent Operations")

# 4. En-tête de la page avec le style natif de BIFlow
page_header(
    title="⚙️ Banc d'Essai - Infrastructure IA", 
    subtitle="Gestion Hybride & Agent Actif (Function Calling) pour l'orchestration locale."
)

# 1. Utiliser le Session State de Streamlit pour forcer la persistance du choix
if "llm_mode_selection" not in st.session_state:
    # Mode initial basé sur le système ou par défaut LOCAL
    st.session_state["llm_mode_selection"] = os.getenv("LLM_MODE", "LOCAL").upper()

mode_actuel = st.session_state["llm_mode_selection"]
index_defaut = 0 if mode_actuel == "LOCAL" else 1

# 2. Le bouton radio écrit directement dans st.session_state["llm_mode_selection"]
mode_choisi = st.radio(
    "Moteur d'exécution sélectionné :",
    ["Ollama Local (Qwen 2.5)", "Gemini Cloud (API)"],
    index=index_defaut,
    horizontal=True,
    key="radio_llm_selector"
)

# 3. Synchronisation stricte et immédiate avec l'environnement système avant tout appel
if "Ollama" in mode_choisi:
    st.session_state["llm_mode_selection"] = "LOCAL"
    os.environ["LLM_MODE"] = "LOCAL"
    st.success("🤖 Routage configuré sur : **Ollama Local (Qwen2.5)**")
else:
    st.session_state["llm_mode_selection"] = "API"
    os.environ["LLM_MODE"] = "API"
    st.warning("☁️ Routage configuré sur : **Gemini Cloud (API)**")

st.markdown("---")
st.write("### 💬 Tester l'Agent en direct")
prompt = st.text_input("Saisissez une question ou un ordre système (ex: 'bonjour') :", placeholder="Demandez une action...")

if st.button("Envoyer à l'agent") and prompt:
    # RE-VERIFICATION DE SÉCURITÉ : On force la variable juste avant l'exécution
    if "Ollama" in st.session_state["radio_llm_selector"]:
        os.environ["LLM_MODE"] = "LOCAL"
    else:
        os.environ["LLM_MODE"] = "API"
        
    with st.spinner("L'agent traite votre demande..."):
        reponse = executer_requete_llm(prompt)
    
    st.write("#### 📥 Réponse de l'Agent :")
    st.code(reponse, language="text")