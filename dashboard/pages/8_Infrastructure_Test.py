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

# --- 1. Sélecteur d'infrastructure visuel ---
st.markdown("---")
mode_actuel = os.getenv("LLM_MODE", "LOCAL").upper()
index_defaut = 0 if mode_actuel == "LOCAL" else 1

mode_choisi = st.radio(
    "Moteur d'exécution sélectionné :",
    ["Ollama Local (Qwen 2.5)", "Gemini Cloud (API)"],
    index=index_defaut,
    horizontal=True
)

# Application dynamique du choix en mémoire
if "Ollama" in mode_choisi:
    os.environ["LLM_MODE"] = "LOCAL"
    st.success("🤖 Routage configuré sur : **Ollama Local (Qwen2.5)**")
else:
    os.environ["LLM_MODE"] = "API"
    st.warning("☁️ Routage configuré sur : **Gemini Cloud (API)**")

# --- 2. Zone de test de l'Agent / LLM ---
st.markdown("---")
st.write("### 💬 Tester l'Agent en direct")
prompt = st.text_input("Saisissez une question ou un ordre système (ex: 'git status') :", placeholder="Demandez une action...")

if st.button("Envoyer à l'agent") and prompt:
    with st.spinner("L'agent traite votre demande..."):
        reponse = executer_requete_llm(prompt)
    
    st.write("#### 📥 Réponse de l'Agent :")
    st.code(reponse, language="text")
