"""Aplicatia separata pentru oamenii responsabili: vad doar coada de aprobari si istoricul deciziilor.
Ruleaza pe alt port (8502) decat interfata de clasificare (8501)."""

import hmac
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import client  # noqa: E402
from theme import inject_theme  # noqa: E402

st.set_page_config(
    page_title="Aprobari — Agent de triaj IT",
    page_icon=":material/task_alt:",
    layout="wide",
)
inject_theme()

# cod de acces optional (APPROVER_CODE in .env): fara el, cine ajunge la adresa nu vede coada.
CODE = os.environ.get("APPROVER_CODE", "").strip()
if CODE and not st.session_state.get("unlocked"):
    st.title("Aprobari")
    entered = st.text_input("Cod de acces", type="password")
    if entered:
        if hmac.compare_digest(entered, CODE):
            st.session_state["unlocked"] = True
            st.rerun()
        else:
            st.error("Cod gresit.")
    st.stop()

page = st.navigation([st.Page("views/aprobari.py", title="Aprobari",
                               icon=":material/task_alt:")], position="hidden")

with st.sidebar:
    st.text_input("Numele tau", key="reviewer", placeholder="ex. Mario",
                  help="Apare in audit: cine a aprobat sau respins.")
    st.caption(f"[Arize Phoenix]({client.PHOENIX_UI_URL}) — urma fiecarei decizii.")

page.run()
