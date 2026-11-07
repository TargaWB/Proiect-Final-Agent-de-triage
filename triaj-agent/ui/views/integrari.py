"""Jira & integrari: fluxul automat Jira -> agent -> Jira, jurnalul sincronizarilor,
plus administrarea bazei de date si retentia."""

import random

import pandas as pd
import streamlit as st

import client
from common import short, when
from theme import (flow, inject_theme, kpi_card, kpi_grid, mode_badge, priority_badge, rule_badge,
                   section, source_badge, status_badge)

inject_theme()

try:
    js = client.jira_status()
except client.APIError as e:
    st.error(str(e))
    st.stop()
live = js["mode"] == "live"

st.title("Jira & integrari")
st.markdown(f"{mode_badge(js['mode'])} &nbsp; "
            + (f"<small style='color:#64748b'>{js['base_url']} · proiect <b>{js['project'] or '—'}</b></small>"
               if live else "<small style='color:#64748b'>Fara credentiale Jira: fluxul ruleaza complet, "
                            "iar ce s-ar scrie in Jira apare in jurnalul de mai jos.</small>"),
            unsafe_allow_html=True)

flow([
    ("1 · INTRARE", "Issue nou in Jira", "Webhook la fiecare issue creat sau sincronizare periodica (JQL).", False),
    ("2 · AGENT", "Clasificare", "Cauta 3 tichete similare in istoric si propune prioritate, categorie, echipa.", False),
    ("3 · CONTROL", "Reguli de siguranta", "P1 sau siguranta sub 70% asteapta un om; restul merge automat.", True),
    ("4 · IESIRE", "Scris inapoi in Jira", "Comentariu cu motivarea, prioritate si etichete. Decizia omului la fel.", False),
])

# ── Stare ─────────────────────────────────────────────
poll = js["polling"]
poll_txt = (f"la {poll['interval_s']} s" if poll["running"] else "configurat, oprit") if poll["enabled"] else "oprit"
kpi_grid([
    kpi_card("Issue-uri procesate", js["linked_tickets"], tone="navy",
             hint="Fiecare cheie Jira e clasificata o singura data, oricate webhook-uri vin."),
    kpi_card("Sincronizari reusite", js["sync_ok"] if live else js["linked_tickets"], tone="green",
             hint="Comentariu + etichete + prioritate scrise in Jira." if live else "In mod simulare: doar logate."),
    kpi_card("Sincronizari cu erori", js["sync_errors"], tone="red" if js["sync_errors"] else "slate",
             hint="Se pot retrimite din tabelul de mai jos."),
    kpi_card("Sincronizare periodica", poll_txt, tone="teal",
             hint="JIRA_POLL_SECONDS in .env. Util cand Jira nu poate ajunge la laptop prin webhook."),
])

b1, b2, _ = st.columns([1, 1, 2])
if b1.button("Testeaza conexiunea", icon=":material/link:", use_container_width=True):
    r = client.jira_test()
    (st.success if r["ok"] else st.warning)(r["message"])
if b2.button("Sincronizeaza acum", icon=":material/sync:", use_container_width=True, type="primary",
             disabled=not live, help=None if live else "Disponibil dupa ce completezi JIRA_* in .env."):
    with st.spinner("Caut issue-uri noi in Jira si le clasific..."):
        try:
            r = client.jira_sync()
            (st.success if r["ok"] else st.error)(r["message"])
        except client.APIError as e:
            st.error(str(e))

# ── Demo: trimite un issue ───────────────────────────
section("Trimite un issue de test", "Simuleaza exact ce trimite Jira la crearea unui issue. "
        "Fiecare trimitere primeste o cheie noua, ca sa vezi tot fluxul.", tag="demo")

SAMPLES = {
    "Email cazut — echipa de vanzari": (
        "Email server unresponsive — entire sales team cannot send or receive",
        "Outlook shows disconnected for all 45 sales reps since 8:15 AM. Exchange Online health dashboard "
        "shows service degradation. Multiple client meetings affected.", "Highest"),
    "VPN instabil — lucru remote": (
        "VPN disconnects intermittently for remote workers",
        "Since the last firewall update, 12 remote employees report VPN dropping every 20-30 minutes. "
        "They can reconnect but lose unsaved work.", "High"),
    "Monitor pentru angajat nou": (
        "Request for additional monitor — new hire onboarding",
        "New developer starting Monday needs a second 27-inch monitor for the workstation in Building B, "
        "Room 204. Standard Dell model is fine.", "Low"),
    "Scris de mine": ("", "", "Medium"),
}
choice = st.segmented_control("Exemplu", list(SAMPLES), default=list(SAMPLES)[0], label_visibility="collapsed")
summary0, desc0, prio0 = SAMPLES[choice or list(SAMPLES)[0]]

with st.form("jira_demo", border=True):
    summary = st.text_input("Titlu (summary)", value=summary0)
    description = st.text_area("Descriere", value=desc0, height=90)
    c1, c2 = st.columns(2)
    jira_prio = c1.selectbox("Prioritate setata in Jira de reporter", ["Highest", "High", "Medium", "Low"],
                             index=["Highest", "High", "Medium", "Low"].index(prio0))
    reporter = c2.text_input("Reporter", value=st.session_state.get("reviewer") or "Ana Popescu")
    sent = st.form_submit_button("Trimite prin webhook", icon=":material/send:", type="primary")

if sent:
    key = f"{(js['project'] or 'DEMO')}-{random.randint(1000, 9999)}"
    payload = {"webhookEvent": "jira:issue_created", "issue": {"key": key, "fields": {
        "summary": summary, "description": description, "priority": {"name": jira_prio},
        "reporter": {"displayName": reporter}, "issuetype": {"name": "Incident"}}}}
    with st.spinner(f"{key}: agentul clasifica..."):
        try:
            st.session_state.jira_last = client.jira_webhook(payload)
        except client.APIError as e:
            st.error(str(e))

res = st.session_state.get("jira_last")
if res:
    t = client.ticket(res["ticket"]["id"])
    p = t.get("final_priority") or t.get("priority")
    with st.container(border=True):
        st.markdown(f"{source_badge('Jira ' + res['jira_key'])} → `{t['code']}` &nbsp; {priority_badge(p)} "
                    f"&nbsp; **{t.get('category') or '—'}** · {t.get('final_team') or t.get('team') or '—'} &nbsp; "
                    f"{status_badge(t['status'])} {rule_badge(t.get('decision_rule'))}", unsafe_allow_html=True)
        if t.get("decision_reason"):
            st.caption(t["decision_reason"])
        ev = (t.get("jira") or {}).get("events", [])
        out = sorted((e for e in ev if e["direction"] == "out"), key=lambda e: e["id"])
        if out:
            st.markdown("**Ce s-a scris inapoi in Jira**" + ("" if live else " _(simulare)_"))
            for e in out:
                d = e["detail"]
                if "text" in d:
                    st.markdown("> " + "  \n> ".join(d["text"]))
                elif "add" in d:
                    st.caption("Etichete: " + ", ".join(f"+{x}" for x in d["add"]) +
                               ("; " + ", ".join(f"−{x}" for x in d.get("remove", [])) if d.get("remove") else ""))
                elif "value" in d:
                    st.caption(f"Prioritate Jira setata: {d['value']}")
                elif "error" in d:
                    st.error(f"{e['action']}: {d['error']}")
        elif t["status"] != "duplicate":
            st.caption("Scrierea in Jira ruleaza in fundal — reincarca pagina peste o secunda.")
        if t["status"] == "pending_approval":
            st.info(f"Asteapta un om in [aplicatia de aprobari]({client.APPROVALS_UI_URL}). "
                    "Dupa decizie, rezultatul ajunge automat si in Jira.")

# ── Issue-uri procesate ──────────────────────────────
try:
    linked = client.jira_tickets(40)
    events = client.jira_events(60)
except client.APIError as e:
    st.error(str(e))
    linked, events = [], []

section("Issue-uri Jira procesate", "Ultimele issue-uri primite si starea sincronizarii inapoi.")
if not linked:
    st.caption("Niciun issue inca. Trimite unul de test mai sus.")
else:
    SYNC = {"ok": "scris in Jira", "simulated": "simulat", "partial": "partial", "error": "eroare", None: "in curs"}
    df = pd.DataFrame([{
        "Jira": r["jira_key"], "Tichet": f"INC-{r['ticket_id']:04d}",
        "Prioritate": r.get("final_priority") or r.get("priority") or "—",
        "Echipa": r.get("final_team") or r.get("team") or "—",
        "Status": {"auto_routed": "directionat automat", "pending_approval": "asteapta un om",
                   "approved": "aprobat", "rejected": "respins", "duplicate": "duplicat"}.get(r["status"], r["status"]),
        "Sursa": r["source"], "Sincronizare": SYNC.get(r["sync_status"], r["sync_status"]),
        "Ultima sincronizare": when(r["last_sync"]), "Eroare": r.get("last_error") or "",
    } for r in linked])
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"Eroare": st.column_config.TextColumn(width="medium")})
    failed = [r for r in linked if r["sync_status"] in ("error", "partial")]
    if failed:
        pick = st.selectbox("Retrimite in Jira", [r["jira_key"] for r in failed])
        if st.button("Retrimite", icon=":material/replay:"):
            tid = next(r["ticket_id"] for r in failed if r["jira_key"] == pick)
            r = client.jira_push(tid)
            (st.error if r.get("errors") else st.success)("; ".join(r.get("errors") or []) or "Retrimis.")

with st.expander(f"Jurnal Jira — ultimele {len(events)} actiuni"):
    if events:
        def detail(e):
            d = e["detail"]
            if "text" in d:
                return short(d["text"][0], 120)
            if "add" in d:
                return "+" + ", +".join(d["add"])
            return d.get("error") or d.get("value") or d.get("summary") or d.get("event") or ""
        st.dataframe(pd.DataFrame([{
            "Cand": when(e["at"]), "Sens": "Jira → agent" if e["direction"] == "in" else "agent → Jira",
            "Issue": e["jira_key"] or "—", "Tichet": e["ticket_code"] or "—", "Actiune": e["action"],
            "Rezultat": ("ok" if e["ok"] else "EROARE") + (" (simulare)" if e["simulated"] else ""),
            "Detalii": detail(e)} for e in events]), hide_index=True, use_container_width=True,
            column_config={"Detalii": st.column_config.TextColumn(width="large")})
    else:
        st.caption("Gol.")

with st.expander("Cum conectezi un Jira real"):
    st.markdown("""
**1. Credentiale** — in `.env` (apoi `docker compose up -d` ca sa le preia):
```
JIRA_BASE_URL=https://firma-ta.atlassian.net
JIRA_EMAIL=contul-tau@firma.ro
JIRA_API_TOKEN=...        # id.atlassian.com → Security → API tokens
JIRA_PROJECT_KEY=ITSM
```
**2. Alege cum intra issue-urile**

- **Sincronizare periodica (recomandat pe laptop)** — `JIRA_POLL_SECONDS=30`. Agentul intreaba Jira la 30 s
  ce issue-uri noi au aparut (JQL implicit: proiectul tau, ultima zi, fara eticheta `triaj-ai`).
  Merge si din spatele unui router, fara adresa publica.
- **Webhook (instant)** — Jira → Settings → System → WebHooks → Create, eveniment *Issue created*,
  URL `https://<adresa-publica>/webhooks/jira`. Jira Cloud nu poate apela `localhost`, deci pe laptop
  ai nevoie de un tunel (ex. `ngrok http 8000`). Pune un secret si seteaza-l si in `JIRA_WEBHOOK_SECRET`.

**3. Ce scrie agentul in issue** — un comentariu cu decizia si motivarea, prioritatea Jira
(P1→Highest, P2→High, P3→Medium, P4→Low; `JIRA_SET_PRIORITY=false` daca proiectul nu permite) si
etichete: `triaj-ai`, `triaj-auto` / `triaj-review`, `echipa-…`. Dupa aprobarea omului: alt comentariu,
cu corectiile facute.
""")
    st.code("POST http://localhost:8000/webhooks/jira", language="text")

# ── Administrare ─────────────────────────────────────
section("Administrare", "Baza de date, indexul de cautare si retentia datelor.")
c1, c2 = st.columns(2)
with c1.container(border=True):
    try:
        info = client.db_info()
        st.markdown("**Baza de date & index RAG**")
        kpi_grid([kpi_card("Tichete", info["tickets_total"], tone="navy"),
                  kpi_card("Documente in index", info["index_docs"], tone="teal"),
                  kpi_card("Marime", info["db_size_mb"], unit="MB", tone="slate")])
        if info.get("by_status"):
            st.markdown(" ".join(f"{status_badge(s)} **{n}**" for s, n in info["by_status"].items()),
                        unsafe_allow_html=True)
    except client.APIError as e:
        st.error(str(e))
    if st.button("Reconstruieste indexul", icon=":material/refresh:", use_container_width=True):
        with st.spinner("Reconstruiesc indexul..."):
            r = client.rebuild_index()
            st.success(f"Index reconstruit: {r['history']} istorice + {r['submitted']} trimise.")

with c2.container(border=True):
    st.markdown("**Retentie**")
    st.caption("Dupa N zile se sterg log-urile detaliate; dupa M zile textul tichetului devine un rezumat "
               "(etichetele raman, utile pentru reantrenare).")
    a, b = st.columns(2)
    archive_days = a.number_input("Log-uri sterse dupa (zile)", 30, 730, 90, 30)
    purge_days = b.number_input("Text rezumat dupa (zile)", 90, 1825, 365, 30)
    x, y = st.columns(2)
    if x.button("Simuleaza", icon=":material/preview:", use_container_width=True):
        r = client.run_retention(archive_days, purge_days, dry_run=True)
        st.info(f"S-ar sterge log-urile a {r['audit_logs_to_delete']} tichete; "
                f"{r['tickets_to_purge_text']} tichete ar deveni rezumat.")
    if y.button("Executa", icon=":material/delete_sweep:", use_container_width=True):
        r = client.run_retention(archive_days, purge_days, dry_run=False)
        st.success(f"Gata: {r.get('audit_logs_to_delete', 0)} tichete curatate, "
                   f"{r.get('tickets_to_purge_text', 0)} rezumate.")
