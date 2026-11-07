# Evaluare: few-shot vs LoRA, RAG, KPI

Toate evaluările rulează pe `data/test_tickets.csv`: 100 de tichete din dataset-ul Kaggle,
stratificate pe prioritate. Nu sunt indexate în ChromaDB și nu intră în antrenarea LoRA.

## Date

Sursa e [Synthetic ITSM Ticket Dataset](https://www.kaggle.com/datasets/avii3301/synthetic-itsm-ticket-dataset):
9.980 de tichete, 8 categorii, 4 priorități, cu rezolvare și timp real de rezolvare.
`scripts/import_kaggle.py` păstrează doar tichetele rezolvate și ia un eșantion de 500,
stratificat pe prioritate × categorie:

| Set | Tichete | Folosit pentru |
|---|---|---|
| `data/tickets.csv` | 400 | RAG (precedente + exemple few-shot), antrenarea LoRA |
| `data/test_tickets.csv` | 100 (P1 14 · P2 23 · P3 38 · P4 25) | evaluare |

Mapare: Critical → P1, High → P2, Medium → P3, Low → P4. Categoria determină echipa.

## 1. Few-shot vs fine-tuned cu LoRA

Ca comparația să fie corectă, ambele abordări folosesc **același model de bază**
(Llama 3.2 3B) și **aceleași 400 de tichete etichetate**:

| Abordare | Cum „învață” cele 400 de tichete | Prompt la inferență |
|---|---|---|
| few-shot | RAG: cele mai apropiate 3 tichete intră în prompt ca exemple | sistem + 3 exemple + tichet |
| LoRA | fine-tuning pe toate 400 (3 epoci, r=16, Unsloth, Colab T4) | sistem + tichet, fără exemple |

Plus o linie de referință: few-shot pe `openai/gpt-oss-20b` (Groq), modelul folosit în producție.

**Pași:**

```bash
# 1. setul de antrenare (deja generat în repo)
python scripts/build_lora_dataset.py

# 2. în Google Colab (GPU T4 gratuit): finetune/lora_finetune.ipynb
#    urci train.jsonl + test.jsonl, rulezi celulele, descarci triaj-lora.Q4_K_M.gguf în finetune/

# 3. modelul în Ollama
ollama pull llama3.2
ollama create triaj-lora -f finetune/Modelfile

# 4. comparația
python scripts/evaluate.py --models \
    fewshot:groq:openai/gpt-oss-20b \
    fewshot:ollama:llama3.2 \
    lora:ollama:triaj-lora
```

Din Docker: `docker compose exec api python scripts/evaluate.py --models ...` (Ollama de
pe laptop se vede din container ca `host.docker.internal`).

**Metrici** (în `eval/results/REPORT.md` și în pagina KPI):

| Metrică | Ce spune |
|---|---|
| Prioritate: acuratețe, **macro-F1** | macro-F1 e metrica principală: clasele sunt dezechilibrate, iar P1 contează la fel de mult ca P3 |
| Matrice de confuzie pe prioritate | unde greșește (de ex. P1 confundat cu P2) |
| Categorie / echipă: acuratețe | rutarea corectă |
| JSON invalid % | cât de des nu respectă formatul |
| **P1 ratate fără om** | P1 reale clasificate mai jos ȘI rutate automat: riscul real al sistemului |
| Intervenție umană % | cât ajunge la om (doar few-shot are confidence) |
| Latență p50, tokeni/tichet, cost/1000 tichete | FinOps |

Notă din dataset: categoria se învață ușor, pentru că fiecare categorie are vocabular propriu
(autorul raportează F1 ≈ 1.00 cu TF-IDF). **Prioritatea e provocarea reală**: depinde de
frazele de urgență („all work has stopped”, „whenever you get a chance”), iar autorul
raportează F1 0.88 cu TF-IDF + LR și 0.87 cu DistilBERT, care sunt referința de comparat.

### Rezultate (100 tichete de test)

| Model | Prioritate acc. | macro-F1 | Categorie acc. | Echipă acc. | Latență p50 | Tokeni/tichet | Cost/1000 | Intervenție umană | P1 ratate fără om |
|---|---|---|---|---|---|---|---|---|---|
| few-shot · gpt-oss-20b (Groq) | 0.59 | 0.58 | 0.97 | 0.97 | 7541 ms | 996 | $0.1039 | 19% | 5 |
| few-shot · llama3.2 3B (Ollama) | 0.53 | 0.521 | 0.99 | 0.99 | 2601 ms | 955 | $0 | 37% | 4 |
| **LoRA · llama3.2 3B (Ollama)** | **0.87** | **0.857** | 0.99 | 0.99 | 1112 ms | 221 | $0 | n/a | n/a |

Matrice de confuzie LoRA (rânduri = real, coloane = prezis; P1..P4):

| Real \ Prezis | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| P1 | 9 | 2 | 3 | 0 |
| P2 | 0 | 20 | 2 | 1 |
| P3 | 0 | 2 | 35 | 1 |
| P4 | 0 | 0 | 2 | 23 |

Concluzii și limite, spuse direct:

- Pe același model de bază, LoRA bate few-shot la prioritate (macro-F1 0.857 vs 0.521) și e de ~2,3× mai rapid, cu ~4,5× mai puțini tokeni. Categoria e ușoară pentru toate abordările.
- Few-shot nu poate copia prioritatea de la vecini (priority_precision@3 = 0.30, vezi secțiunea 2); LoRA învață din toate cele 400 de tichete semnalele de urgență.
- Colab a raportat macro-F1 0.876; după cuantizare Q4_K_M în Ollama: 0.857. Cifra de raportat e cea din Ollama.
- LoRA nu dă confidence, citări sau motivare, deci nu poate alimenta singur guardrail-ul și RAG-ul. De aceea producția rămâne few-shot cu RAG, iar LoRA e o direcție de îmbunătățire (de ex. ca prim clasificator, cu agentul LLM pentru motivare).
- P1: 9 din 14 recuperate de LoRA (precizie P1 9/9), 9 din 14 la gpt-oss, 10 din 14 la llama3.2. Cu regula `p1_always_human`, cele 5 P1 ratate de gpt-oss au ajuns automat la echipă (analiză post-hoc: trimiterea la om și a predicțiilor P2 ar fi redus la 2 P1 ratate, cu 43% intervenție umană; nu e implementat).
- Setul de test e mic (100; doar 14 P1), deci diferențele mici nu sunt semnificative statistic. Cifrele autorului dataset-ului (F1 0.87–0.88) sunt pe alt split și nu sunt direct comparabile.

## 2. RAG: retrieval + RAGAS

```bash
python scripts/ragas_eval.py --n 20            # retrieval + RAGAS cu judecător Groq (gpt-oss-120b)
python scripts/ragas_eval.py --n 100 --no-llm  # doar metricile de retrieval
```

**Retrieval** (fără LLM, pe toate cele 100 de tichete de test; rezultat în `eval/results/retrieval_only_n100.json`):

| Metrică | Valoare | Interpretare |
|---|---|---|
| category_hit@3 | 1.00 | în toate cazurile, cel puțin un exemplu adus are categoria corectă |
| category_precision@3 | 0.91 | 91% din exemple sunt din categoria corectă |
| priority_precision@3 | 0.30 | doar 30% din exemple au prioritatea corectă |
| mean_top1_distance | 0.096 | cel mai apropiat precedent e foarte similar |

Concluzie: RAG-ul aduce subiectul corect aproape mereu, dar prioritatea nu se poate copia
de la vecini. Modelul trebuie să o deducă din urgența descrisă. De aceea P1 trece mereu
pe la om și de aceea macro-F1 pe prioritate e metrica de urmărit.

**RAGAS** (judecător LLM):

| Metrică RAGAS | Întrebarea |
|---|---|
| `faithfulness` | Motivarea agentului e susținută de exemplele primite sau e inventată? |
| `llm_context_precision_with_reference` | Exemplele relevante sunt primele în listă? |
| `context_recall` | Eticheta corectă e susținută de contextul adus? |

**RAGAS rulat** (n=20 tichete, judecător `openai/gpt-oss-120b`, `eval/results/ragas_latest.json`):

| Metrică | Valoare |
|---|---|
| faithfulness | 0.62 |
| llm_context_precision_with_reference | 0.279 |
| context_recall | 0.50 |
| category_hit@3 / category_precision@3 | 1.00 / 0.867 |
| priority_precision@3 / mean_top1_distance | 0.217 / 0.138 |

Interpretare: referința RAGAS include și prioritatea, iar prioritatea nu se deduce din similaritate, deci precizia și recall-ul contextului ies mici chiar dacă categoria e mereu corectă (recall = 1 doar dacă prioritatea corectă apare printre vecini). Faithfulness 0.62 înseamnă că o parte din motivări conțin afirmații nesusținute de exemple. 2 din 60 de joburi RAGAS au expirat (rate limit Groq); mediile sunt pe valorile valide. n=20 e un eșantion mic; cifrele sunt orientative.

Compatibilitate: ragas 0.4.3 importă un modul eliminat din `langchain-community` 0.4. Scriptul
adaugă un înlocuitor minimal (clasa e folosită doar la un `isinstance`); restul ragas e
neatins.

## 3. KPI: baseline manual vs agentic

`scripts/evaluate.py` produce și simularea (`kpi_simulation_latest.json`), pe predicțiile
primului model few-shot.

**Ce e real:** timpul de rezolvare al fiecărui tichet (`time_to_resolution_hours`, proces manual).

**Ce e presupunere** (`agent/config.py → SIM`, ajustabile):

| Parametru | Valoare | Sens |
|---|---|---|
| `manual_triage_hours` | P1 0.25 · P2 0.5 · P3 1 · P4 2 | coadă + citire + decizie la dispecer |
| `manual_misroute_rate` | 20% | tichete trimise la echipa greșită manual |
| `reroute_penalty_hours` | P1 0.5 · P2 1 · P3 2 · P4 4 | timp pierdut la o re-rutare |
| `review_hours` | P1 0.1 · P2 0.25 · P3/P4 0.5 | aprobare umană cu context pregătit de agent |
| `review_catch_rate` | 80% | câte din greșelile agentului prinde omul la aprobare |

**Model:**

```
lucru_efectiv   = rezolvare_reală − triaj_manual − 20% × penalizare_rerutare
MTTR_manual     = rezolvare_reală
MTTR_agentic    = lucru_efectiv + triaj_agent + P(rutare greșită) × penalizare_rerutare
  triaj_agent   = latența măsurată (automat)   | review_hours (cu aprobare)
  P(greșit)     = 1 dacă echipa prezisă e greșită (automat) | 0.2 dacă e greșită și trece pe la om
```

Agentul schimbă doar triajul și rutarea, nu și rezolvarea propriu-zisă. Diferența de MTTR e
deci conservatoare: vine doar din partea de triaj.

KPI raportate: timp până la rutare, % rutări greșite, MTTR simulat (total și pe
prioritate), % decizii umane, % auto-rezolvare.

### Rezultate KPI (simulare pe cele 100 de tichete)

| Scenariu | Timp până la rutare | Rutări greșite | MTTR | Decizii umane | Auto |
|---|---|---|---|---|---|
| Manual | 1.03 h | 20% | 38.14 h | 100% | 0% |
| Agentic | 0.038 h | 2.2% | 36.77 h | 19% | 81% |

MTTR pe prioritate (manual → agentic): P1 3.74 → 3.46 h, P2 13.48 → 12.88 h, P3 37.74 → 36.47 h, P4 80.68 → 77.88 h.

Limite: simularea folosește predicțiile few-shot gpt-oss-20b, nu LoRA; doar echipa greșită contează ca rutare greșită (prioritatea greșită nu); rata manuală de 20% și timpii de triaj sunt presupuneri; câștigul de MTTR (−3,6%) e mic fiindcă agentul schimbă doar triajul, nu rezolvarea. Cele 19% decizii umane vin toate din regula `p1_always_human`.

## 4. Filtru de relevanță (text fără legătură cu IT)

Distanța cosinus la cel mai apropiat precedent din ChromaDB separă tichetele IT de restul:
IT în engleză max 0.454 (100 de tichete de test), IT scurt în română 0.12–0.60, texte fără
legătură cu IT 0.55–0.92 (15 exemple scrise de mână). Zona 0.50–0.65 se suprapune, deci două praguri:
`> 0.65` → `out_of_scope` (fără apel LLM, la om); `0.50–0.65` → `weak_match` (LLM propune, dar
merge la om). Pe setul de test nu se activează (max 0.454), deci rezultatele de mai sus nu se
schimbă. Limite: calibrare pe puține exemple, indexul e în engleză, iar un tichet vag
(„nu merge nimic”) ajunge și el la om.

## KPI live (din aplicație)

Pagina **KPI & FinOps** calculează din SQLite, pe tichetele reale trimise: rată de
auto-rezolvare, % intervenție umană, % corecții umane (override), timp real până la rutare
(latența agentului sau timpul până la decizia omului), latență p50/p95, regula care a decis
fiecare tichet. Consumul e în [finops.md](finops.md).
