"""Trimiti un tichet, vezi ce a decis agentul si pe ce baza."""

import streamlit as st

import client
from html import escape

from common import short, when
from theme import (inject_theme, kpi_card, kpi_grid, priority_badge, priority_scale, rule_badge, section,
                   source_badge, status_badge)

inject_theme()
st.title("Agent de triaj pentru tichete IT")
st.markdown("Scrii problema ca un angajat. Agentul cauta tichete asemanatoare rezolvate deja si propune "
            "**prioritatea, categoria si echipa**. Cazurile riscante ajung la un om.")
st.markdown(priority_scale(), unsafe_allow_html=True)

EXAMPLES = {
    # formularea conteaza: „Tot clusterul de productie din AWS e cazut...” are distanta 0.655 la istoric
    # (index in engleza) si trece de pragul out_of_scope 0.65; varianta de mai jos are 0.48
    "Serverele AWS sunt cazute": "Serverele din AWS sunt cazute, aplicatia de plati nu merge pentru niciun client.",
    "Outlook nu sincronizeaza": "Outlook nu mai sincronizeaza mailurile de ieri, nu e urgent.",
    "Cont blocat": "Mi s-a blocat contul dupa 3 parole gresite si nu ma pot loga in laptop.",
    "Nimic de-a face cu IT": "Ma doare capul si as vrea o pizza.",
}

with st.container(border=True):
    pick = st.pills("Exemple rapide", list(EXAMPLES), selection_mode="single", key="ex_pick")
    with st.form("ticket_form", border=False):
        text = st.text_area("Descriere tichet", value=EXAMPLES.get(pick, ""), height=110,
                            placeholder="Ex: Serverul de baze de date nu raspunde de 15 minute, "
                                        "toata echipa de vanzari e blocata.")
        submitted = st.form_submit_button("Clasifica", type="primary", icon=":material/send:")


def run(ticket_text, force_new=False):
    with st.spinner("Caut precedente si clasific..."):
        try:
            st.session_state.last = client.submit(ticket_text, st.session_state.get("reviewer"), force_new)
            st.session_state.last_text = ticket_text
        except client.APIError as e:
            st.error(str(e))


if submitted and text.strip():
    run(text)

last = st.session_state.get("last")
if last:
    try:
        t = client.ticket(last["ticket"]["id"])
    except client.APIError as e:
        st.error(str(e))
        st.stop()

    if last.get("duplicate_of"):
        o = last["duplicate_of"]
        st.info(f"**Tichet deja trimis** — identic cu **{o['code']}** din {when(o['created_at'])}. "
                "Am refolosit clasificarea, fara apel AI (0 tokeni).")
        if st.button("Clasifica oricum ca tichet nou", icon=":material/add:"):
            run(st.session_state.last_text, force_new=True)
            st.rerun()

    p_val = t.get("final_priority") or t.get("priority")
    section("Rezultat", tag=t["code"])
    with st.container(border=True):
        top = f"{status_badge(t['status'])} {rule_badge(t['decision_rule'])}"
        if t.get("jira"):
            top += " " + source_badge("Jira " + t["jira"]["jira_key"])
        st.markdown(top, unsafe_allow_html=True)
        st.markdown(f"> {short(t['text'], 300)}")
        conf = t.get("confidence")
        kpi_grid([
            f'<div class="kpi" style="--tone:#0f172a"><div class="label">Prioritate</div>'
            f'<div class="value" style="font-size:22px;margin-top:6px">{priority_badge(p_val)}</div></div>',
            kpi_card("Categorie", t.get("category") or "—", tone="navy"),
            kpi_card("Echipa", t.get("final_team") or t.get("team") or "—", tone="teal"),
            kpi_card("Siguranta agentului", None if conf is None else f"{conf:.0%}",
                     tone="green" if (conf or 0) >= 0.7 else "amber",
                     hint="Sub 70% → decide un om."),
        ])
        if t.get("reasoning"):
            st.markdown(f"**De ce:** {t['reasoning']}")
        if t["citations"]:
            st.caption("Precedente citate: " + ", ".join(t["citations"]))

        if t["status"] == "pending_approval":
            st.warning(f"**Asteapta un om** — {t['decision_reason']}  \n"
                       f"Se decide in [aplicatia de aprobari]({client.APPROVALS_UI_URL}).")
        elif t["status"] == "auto_routed":
            st.success(f"**Directionat automat** catre {t['final_team']} — {t['decision_reason']}")
        elif t["status"] in ("approved", "rejected"):
            label = "Aprobat" if t["status"] == "approved" else "Respins (triaj manual)"
            st.success(f"**{label}** de {t['reviewed_by']} la {when(t['reviewed_at'])}.")
        elif t["status"] == "duplicate":
            st.info(t["decision_reason"])

    c1, c2 = st.columns(2)
    with c1:
        if last.get("similar"):
            with st.expander(f"Cele {len(last['similar'])} tichete istorice folosite ca exemple"):
                for s in last["similar"]:
                    st.markdown(f"{priority_badge(s['priority'])} **{s['subject']}**  \n"
                                f"<small style='color:#64748b'>{s['category']} · {s['team']} · "
                                f"asemanare {max(0, 1 - s['distance']):.0%}</small>", unsafe_allow_html=True)
                    if s.get("resolution"):
                        st.caption(f"Rezolvat atunci prin: {short(s['resolution'], 160)}")
        if last.get("previous"):
            with st.expander(f"Ai mai trimis {len(last['previous'])} tichet(e) asemanator(e)"):
                for p in last["previous"]:
                    st.markdown(f"`{p['code']}` {priority_badge(p.get('final_priority') or p.get('priority'))} "
                                f"{escape(short(p['text'], 90))} {status_badge(p['status'])}", unsafe_allow_html=True)
    with c2:
        with st.expander("Audit: ce s-a intamplat, cine, cand"):
            st.caption(f"Model: {t['model'] or '—'} · incercari AI: {t['attempts']} · "
                       f"timp agent: {(t['latency_ms'] or 0) / 1000:.1f} s")
            for e in t["audit"]:
                st.markdown(f"<small>{when(e['at'])} · <b>{e['actor']}</b> · {e['event']}</small>",
                            unsafe_allow_html=True)
            for u in t["usage"]:
                st.caption(f"AI {u['model']}: {u['prompt_tokens']} + {u['completion_tokens']} tokeni, "
                           f"cost echivalent ${u['cost_usd']:.6f}")
            if t.get("trace_id"):
                st.caption(f"Trace Phoenix: sesiunea `{t['code']}`")

# ── Ultimele tichete ─────────────────────────────────
try:
    recent = client.tickets(12)
except client.APIError as e:
    st.error(str(e))
    recent = []
if recent:
    section("Ultimele tichete")
    rows = "".join(
        f'<div class="tk-row"><code>{r["code"]}</code>'
        f'<span>{priority_badge(r.get("final_priority") or r.get("priority"))}</span>'
        f'<span>{escape(short(r["text"], 90))}</span>'
        f'<span class="hide-sm">{status_badge(r["status"])}</span>'
        f'<span class="muted hide-sm">{r.get("final_team") or r.get("team") or "—"} · {when(r["created_at"])}</span></div>'
        for r in recent)
    with st.container(border=True):
        st.markdown(rows, unsafe_allow_html=True)
    st.caption("Reguli: P1 → om · siguranta sub 70% → om · in afara domeniului IT → om · restul automat.")
