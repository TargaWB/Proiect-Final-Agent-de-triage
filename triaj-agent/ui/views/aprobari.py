"""Coada omului. Ajung aici doar tichetele pe care regulile de siguranta nu le lasa automat."""

from html import escape

import streamlit as st

import client
from common import when
from theme import (inject_theme, kpi_card, kpi_grid, priority_badge, priority_scale, rule_badge, section,
                   source_badge, status_badge)

inject_theme()
st.title("Aprobari")
st.caption("Tichetele pe care agentul nu le directioneaza singur: P1, siguranta sub 70%, text in afara "
           "domeniului IT sau potrivire slaba cu istoricul. Cele mai urgente sunt primele.")

try:
    cfg, queue = client.config(), client.approvals()
    history = [t for t in client.tickets(200) if t["status"] in ("approved", "rejected")]
    jira_keys = {r["ticket_id"]: r["jira_key"] for r in client.jira_tickets(200)}
except client.APIError as e:
    st.error(str(e))
    st.stop()

kpi_grid([
    kpi_card("In asteptare", len(queue), tone="amber" if queue else "green"),
    kpi_card("Aprobate", sum(t["status"] == "approved" for t in history), tone="blue"),
    kpi_card("Respinse (triaj manual)", sum(t["status"] == "rejected" for t in history), tone="red"),
])

reviewer = (st.session_state.get("reviewer") or "").strip()
if not reviewer:
    st.info("Scrie-ti numele in bara din stanga ca sa poti aproba sau respinge.")
if not queue:
    st.success("Nimic de aprobat.")
else:
    st.markdown(priority_scale(), unsafe_allow_html=True)

for t in queue:
    with st.container(border=True):
        head = (f"{priority_badge(t.get('priority'))} &nbsp;<b>{escape(t['category'] or 'neclasificat')}</b>"
                f" → {escape(t['team'] or '—')} &nbsp; {rule_badge(t['decision_rule'])}")
        if t["id"] in jira_keys:
            head += " " + source_badge("Jira " + jira_keys[t["id"]])
        left, right = st.columns([4, 1])
        left.markdown(head, unsafe_allow_html=True)
        right.markdown(f"<div style='text-align:right;color:#64748b;font-size:13px'>{t['code']} · "
                       f"{when(t['created_at'])}</div>", unsafe_allow_html=True)
        st.markdown(f"> {t['text']}")
        if t["confidence"] is not None:
            st.progress(min(max(t["confidence"], 0.0), 1.0),
                        text=f"Siguranta agentului: {round(t['confidence'] * 100)}% (prag: 70%)")
        st.caption(f"De ce e aici: {t['decision_reason']}")

        with st.expander("Motivarea agentului si precedentele"):
            st.write(t["reasoning"] or "—")
            if t["citations"]:
                st.caption("Citari: " + ", ".join(t["citations"]))

        needs_fix = t["priority"] is None or t["team"] not in cfg["teams"]
        with st.expander("Corecteaza inainte de aprobare", expanded=needs_fix):
            c1, c2 = st.columns(2)
            prios, teams = cfg["priorities"], cfg["teams"]
            prio = c1.selectbox("Prioritate", prios, key=f"p_{t['id']}",
                                index=prios.index(t["priority"]) if t["priority"] in prios else None)
            team = c2.selectbox("Echipa", teams, key=f"t_{t['id']}",
                                index=teams.index(t["team"]) if t["team"] in teams else None)

        note = st.text_input("Comentariu", key=f"n_{t['id']}", label_visibility="collapsed",
                             placeholder="Comentariu (optional) — ajunge si in Jira, daca tichetul vine de acolo")
        b1, b2 = st.columns(2)
        try:
            if b1.button("Aproba", key=f"a_{t['id']}", type="primary", icon=":material/check:",
                         use_container_width=True, disabled=not reviewer):
                r = client.review(t["id"], True, reviewer, note, prio, team)
                st.toast(f"{t['code']} aprobat — {r['final_team']}")
                st.rerun()
            if b2.button("Respinge", key=f"r_{t['id']}", icon=":material/close:",
                         use_container_width=True, disabled=not reviewer):
                client.review(t["id"], False, reviewer, note)
                st.toast(f"{t['code']} respins — triaj manual")
                st.rerun()
        except client.APIError as e:
            st.error(str(e))

if history:
    section("Istoric decizii")
    rows = []
    for t in history[:50]:
        changed = (t.get("final_priority") and t["final_priority"] != t["priority"]) or \
                  (t.get("final_team") and t["final_team"] != t["team"])
        rows.append(
            f'<div class="tk-row"><code>{t["code"]}</code>'
            f'<span>{priority_badge(t.get("final_priority") or t.get("priority"))}</span>'
            f'<span>{escape(t.get("final_team") or "triaj manual")}'
            f'{" <small style=color:#d97706>(corectat)</small>" if changed else ""}'
            f'{(" — <small>" + escape(t["review_note"]) + "</small>") if t.get("review_note") else ""}</span>'
            f'<span class="hide-sm">{status_badge(t["status"])}</span>'
            f'<span class="muted hide-sm">{escape(t.get("reviewed_by") or "—")} · {when(t.get("reviewed_at"))}</span></div>')
    with st.container(border=True):
        st.markdown("".join(rows), unsafe_allow_html=True)
