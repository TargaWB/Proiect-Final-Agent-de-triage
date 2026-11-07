import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import client  # noqa: E402
from theme import inject_theme, mode_badge  # noqa: E402

st.set_page_config(
    page_title="Agent de triaj IT",
    page_icon=":material/confirmation_number:",
    layout="wide",
)
inject_theme()

try:
    pending = len(client.approvals())
except client.APIError:
    pending = 0

page = st.navigation([
    st.Page("views/clasificare.py", title="Clasificare", icon=":material/confirmation_number:", default=True),
    st.Page("views/kpi.py", title="KPI & cost", icon=":material/analytics:"),
    st.Page("views/integrari.py", title="Jira & integrari", icon=":material/sync_alt:"),
])

with st.sidebar:
    st.markdown("**Agent de triaj IT**  \n<small style='color:#64748b'>Asistentul propune, omul decide.</small>",
                unsafe_allow_html=True)
    st.text_input("Numele tau", key="reviewer", placeholder="ex. Mario",
                  help="Apare in audit: cine a trimis, cine a aprobat sau respins.")
    st.divider()
    if pending:
        st.warning(f"**{pending}** tichete asteapta un om.  \n[Deschide aprobarile]({client.APPROVALS_UI_URL})")
    else:
        st.success("Nicio aprobare in asteptare.")
    st.page_link(client.APPROVALS_UI_URL, label="Aplicatia de aprobari", icon=":material/task_alt:")
    st.page_link(client.PHOENIX_UI_URL, label="Arize Phoenix (trace-uri)", icon=":material/timeline:")

    st.divider()
    try:
        info = client.db_info()
        js = client.jira_status()
        st.markdown(f"<small style='color:#64748b'>Tichete in baza: <b>{info['tickets_total']}</b> · "
                    f"index RAG: <b>{info['index_docs']}</b></small><br>{mode_badge(js['mode'])}",
                    unsafe_allow_html=True)
    except client.APIError:
        pass

page.run()
