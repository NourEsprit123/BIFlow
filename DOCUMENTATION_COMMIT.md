Voici une documentation Markdown détaillée pour les modifications apportées au fichier `8_Infrastructure_Test.py` :

```markdown
# Documentation des modifications de 8_Infrastructure_Test.py

## Résumé des modifications

Les modifications apportées au fichier `8_Infrastructure_Test.py` visent à améliorer la gestion du mode d'exécution du modèle de langage (LLM) et à simplifier l'expérience utilisateur. Voici un aperçu des modifications :

1. **Ajout de la gestion des Session States** : Utilisation de `st.session_state` pour maintenir le choix d'exécution persistant.
2. **Utilisation de `st.radio` pour sélectionner le mode** : Remplacement de la méthode précédente par un `st.radio` pour une interface utilisateur plus intuitive.
3. **Synchronisation stricte avec l'environnement système** : Assurez-vous que le mode sélectionné est appliqué immédiatement à l'environnement système.
4. **Modification du prompt de test** : Ajout d'un exemple de prompt pour le test.

## Diff détaillé

### Avant
```python
# --- 1. Sélecteur d'infrastructure visuel ---
st.markdown("---")
mode_actuel = os.getenv("LLM_MODE", "LOCAL").upper()
# Application dynamique du choix en mémoire
if "Ollama" in mode_choisi:
    os.environ["LLM_MODE"] = "LOCAL"
    st.success("🤖 Routage configuré sur : **Ollama Local (Qwen2.5)**")
else:
    os.environ["LLM_MODE"] = "API"
    st.warning("☁️ Routage configuré sur : **Gemini Cloud (API)**")
```

### Après
```python
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
```

### Modifications du test de l'Agent / LLM
```python
# --- 2. Zone de test de l'Agent / LLM ---
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
```

## Explications

1. **Ajout de la gestion des Session States** : Utilisation de `st.session_state` pour maintenir le choix d'exécution persistant.
2. **Utilisation de `st.radio` pour sélectionner le mode** : Remplacement de la méthode précédente par un `st.radio` pour une interface utilisateur plus intuitive.
3. **Synchronisation stricte avec l'environnement système** : Assurez-vous que le mode sélectionné est appliqué immédiatement à l'environnement système.
4. **Modification du prompt de test** : Ajout d'un exemple de prompt pour le test.

Cette documentation fournit une vue d'ensemble des modifications apportées, explique les changements détaillés et fournit des explications pour chaque section modifiée.
```

Ce document Markdown détaillé permet de comprendre les modifications apportées et leur impact sur l'interface utilisateur et la logique du code.