"""KPI live, cost (FinOps) si rezultatele evaluarii offline — fiecare cifra cu eticheta intreaga
si o propozitie care spune ce inseamna."""

import pandas as pd
import streamlit as st

import client
from common import RULE_LABEL
from theme import inject_theme, kpi_card, kpi_grid, section

inject_theme()
st.title("KPI & cost")
st.caption("Cifre live din tichetele trimise in aplicatie, costul agentului si rezultatele testelor pe 100 de "
           "tichete pe care modelul nu le-a vazut.")

try:
    data = client.kpis()
except client.APIError as e:
    st.error(str(e))
    st.stop()
live, fin, ev = data["live"], data["finops"], data["evaluation"]


def pct(v):
    return None if v is None else f"{v:.0f}"


def duration(h):
    if h is None:
        return None, ""
    s = h * 3600
    if s < 60:
        return f"{s:.1f}", "s"
    if s < 3600:
        return f"{s / 60:.1f}", "min"
    return f"{h:.1f}", "h"


# ── Live ──────────────────────────────────────────────
section("Live, din tichetele trimise", f"{live['classified']} tichete clasificate de agent "
        f"(plus {live['duplicates']} duplicate recunoscute fara AI).", tag="live")

if not live["classified"]:
    st.info("Inca nu exista tichete. Trimite cateva din pagina **Clasificare** sau din **Jira & integrari**.")
else:
    route_v, route_u = duration(live["mean_time_to_route_hours"])
    kpi_grid([
        kpi_card("Directionate automat", pct(live["auto_resolution_rate_pct"]), unit="%", tone="green",
                 hint="Tichete trimise direct la echipa, fara sa astepte un om (risc scazut)."),
        kpi_card("Ajung la un om", pct(live["human_intervention_pct"]), unit="%", tone="amber",
                 hint="P1, siguranta sub 70%, text in afara domeniului IT sau potrivire slaba."),
        kpi_card("Corectate de om", pct(live["human_override_pct"]), unit="%", tone="red",
                 hint="Din cele revizuite: respinse sau aprobate cu alta prioritate / echipa."),
        kpi_card("Timp pana la directionare", route_v, unit=route_u, tone="teal",
                 hint="Automat = latenta agentului. Cu aprobare = pana la decizia omului."),
    ])
    kpi_grid([
        kpi_card("Tichete procesate", live["tickets_total"], tone="navy", hint="Total, inclusiv duplicatele."),
        kpi_card("Duplicate prinse", live["duplicates"], tone="slate",
                 hint="Acelasi text trimis din nou: clasificare refolosita, 0 tokeni."),
        kpi_card("Latenta agent (mediana)", None if live["agent_latency_ms_p50"] is None
                 else f"{live['agent_latency_ms_p50'] / 1000:.1f}", unit="s", tone="blue",
                 hint="Jumatate din tichete sunt clasificate mai repede de atat."),
        kpi_card("Latenta agent (p95)", None if live["agent_latency_ms_p95"] is None
                 else f"{live['agent_latency_ms_p95'] / 1000:.1f}", unit="s", tone="blue",
                 hint="95% din tichete sunt clasificate mai repede de atat."),
    ])

    if live["by_rule"]:
        st.markdown("**Ce regula a decis soarta fiecarui tichet**")
        total = sum(live["by_rule"].values())
        st.dataframe(
            pd.DataFrame([{"Regula": RULE_LABEL.get(k, k), "Tichete": v, "Pondere": v / total}
                          for k, v in sorted(live["by_rule"].items(), key=lambda kv: -kv[1])]),
            hide_index=True, use_container_width=True,
            column_config={"Regula": st.column_config.TextColumn(width="large"),
                           "Pondere": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
        )

# ── Cost ──────────────────────────────────────────────
section("Cost (FinOps)", "Cost echivalent la pretul de lista Groq. Pe free tier, costul platit efectiv e $0.",
        tag="masurat")
kpi_grid([
    kpi_card("Cost la 1.000 de tichete", f"${fin['projected_cost_per_1000_tickets_usd']:.2f}", tone="green", hero=True,
             hint="Proiectat din costul mediu real per tichet."),
    kpi_card("Tokeni per tichet", f"{fin['avg_tokens_per_ticket']:.0f}" if fin["avg_tokens_per_ticket"] else None,
             tone="teal", hint="Prompt mic: doar 3 exemple istorice, nu tot istoricul."),
    kpi_card("Apeluri LLM", fin["llm_calls"], tone="navy",
             hint=f"Din care reincercari dupa JSON invalid: {fin['retries']}."),
    kpi_card("Tokeni economisiti de cache", fin["tokens_saved_by_cache"], tone="slate",
             hint=f"{fin['duplicates_served_from_cache']} duplicate servite fara apel LLM."),
])
if fin["by_model"]:
    with st.expander("Consum pe model"):
        st.dataframe(pd.DataFrame([{
            "Model": f"{m['provider']}:{m['model']}", "Apeluri": m["calls"],
            "Tokeni intrare": m["p"], "Tokeni iesire": m["c"],
            "Latenta medie (s)": round((m["lat"] or 0) / 1000, 2),
            "Cost echivalent ($)": round(m["cost"] or 0, 5),
        } for m in fin["by_model"]]), hide_index=True, use_container_width=True)

# ── Evaluare offline ─────────────────────────────────
cls = ev.get("classification")
if cls:
    section("Few-shot vs. model antrenat (LoRA)",
            f"Testat pe {cls['test_size']} tichete nevazute, acelasi model de baza. "
            "Metrica grea e prioritatea: categoria o nimeresc toate abordarile.", tag="test offline")
    models = cls["models"]
    best = max(models, key=lambda m: m["priority_accuracy"])
    prod = next((m for m in models if "groq" in m["name"]), models[0])
    kpi_grid([
        kpi_card("Acuratete prioritate — productie (few-shot)", f"{prod['priority_accuracy'] * 100:.0f}", unit="%",
                 tone="amber", hint=f"{prod['name']}; vede 3 exemple istorice la fiecare tichet."),
        kpi_card("Acuratete prioritate — cel mai bun", f"{best['priority_accuracy'] * 100:.0f}", unit="%",
                 tone="green", hint=f"{best['name']}; antrenat pe toate cele 400 de tichete istorice."),
        kpi_card("Acuratete categorie", f"{best['category_accuracy'] * 100:.0f}", unit="%", tone="teal",
                 hint="Subiectul tichetului: aproape mereu corect, la toate modelele."),
        kpi_card("Latenta — cel mai bun", f"{best['latency_ms_p50'] / 1000:.1f}", unit="s", tone="blue",
                 hint=f"Fata de {prod['latency_ms_p50'] / 1000:.1f} s la modelul din productie."),
    ])
    st.dataframe(pd.DataFrame([{
        "Model": m["name"],
        "Prioritate": m["priority_accuracy"], "Prioritate macro-F1": m["priority_macro_f1"],
        "Categorie": m["category_accuracy"], "Echipa": m["team_accuracy"],
        "Latenta (s)": round(m["latency_ms_p50"] / 1000, 1), "Tokeni / tichet": m["tokens_per_ticket"],
        "Cost / 1000 ($)": m["cost_per_1000_usd"],
        "Ajung la om (%)": m.get("human_intervention_pct"),
    } for m in models]), hide_index=True, use_container_width=True, column_config={
        "Model": st.column_config.TextColumn(width="large"),
        "Prioritate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Categorie": st.column_config.NumberColumn(format="percent"),
        "Echipa": st.column_config.NumberColumn(format="percent"),
        "Prioritate macro-F1": st.column_config.NumberColumn(format="%.2f"),
    })
    with st.expander("Unde greseste cel mai bun model (matrice de confuzie pe prioritate)"):
        st.caption("Randuri = prioritatea reala, coloane = ce a prezis modelul. Diagonala = corect.")
        st.dataframe(pd.DataFrame(best["confusion_priority"],
                                  index=[f"real {p}" for p in cls["labels"]],
                                  columns=[f"prezis {p}" for p in cls["labels"]]), use_container_width=True)
else:
    st.caption("Inca nu exista rezultate de evaluare. Ruleaza `python scripts/evaluate.py` (vezi docs/evaluation.md).")

sim = ev.get("kpi_simulation")
if sim:
    section("Manual vs. cu agent", "Simulare pe cele 100 de tichete de test, cu presupuneri documentate "
            "(rata de eroare manuala 20%, timpi de triaj estimati). Nu sunt masuratori din productie.",
            tag="simulare", warn=True)
    man = next(r for r in sim["rows"] if r["scenario"].lower().startswith("manual"))
    ag = next(r for r in sim["rows"] if r is not man)
    gain = lambda a, b: None if not a else f"{(b - a) / a * 100:+.0f}"  # noqa: E731
    kpi_grid([
        kpi_card("Timp pana la directionare", gain(man["time_to_route_h"], ag["time_to_route_h"]), unit="%",
                 tone="green", hint=f"{man['time_to_route_h']:.2f} h manual → {ag['time_to_route_h'] * 60:.1f} min."),
        kpi_card("Tichete trimise gresit", f"{ag['misroute_pct']:.1f}", unit="%", tone="green",
                 hint=f"Fata de {man['misroute_pct']:.0f}% presupus la triajul manual."),
        kpi_card("Decizii care cer un om", f"{ag['human_decisions_pct']:.0f}", unit="%", tone="amber",
                 hint="Fata de 100% manual. Omul ramane doar unde greseala costa."),
    ])

rg = ev.get("ragas")
if rg:
    names = {"category_hit@3": ("Macar un exemplu din categoria corecta", "pct"),
             "category_precision@3": ("Exemple din categoria corecta", "pct"),
             "priority_precision@3": ("Exemple cu prioritatea corecta", "pct"),
             "mean_top1_distance": ("Distanta medie pana la cel mai apropiat precedent", "num"),
             "faithfulness": ("Motivare sustinuta de exemple (RAGAS)", "pct"),
             "llm_context_precision_with_reference": ("Exemplele relevante sunt primele (RAGAS)", "pct"),
             "context_recall": ("Eticheta corecta se gaseste in context (RAGAS)", "pct")}
    with st.expander(f"Calitatea cautarii in istoric (RAG) — {rg['n']} tichete"):
        rows = [{"Metrica": names.get(k, (k,))[0], "Cod": k,
                 "Valoare": f"{v * 100:.0f}%" if names.get(k, ("", "pct"))[1] == "pct" else f"{v:.3f}"}
                for k, v in {**rg.get("retrieval", {}), **rg.get("ragas", {})}.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Subiectul se gaseste aproape mereu in exemple; prioritatea nu se poate copia de la vecini — "
                   "de aceea P1 trece mereu pe la un om.")
