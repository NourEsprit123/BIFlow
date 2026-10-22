"""
Agent conversationnel BIFlow.

Pour chaque message, le LLM décide LUI-MÊME de l'intention :
  - "answer"  : question sur les données -> il écrit les calculs sous forme de specs (KPI / tableaux),
                le moteur les EXÉCUTE (chiffres exacts), puis le LLM rédige la réponse à partir des résultats.
  - "display" : l'utilisateur demande d'afficher un KPI / graphique / dashboard -> même exécution,
                et la vue est renvoyée pour être affichée sur la page principale.
  - "chat"    : salutations, aide... aucune donnée à calculer.

Aucun mot-clé codé en dur, aucun code généré : le LLM ne fait que planifier, le moteur calcule.
"""
import json
import uuid

from analytics import dashboard_engine as eng
from agents.bi_analyst_agent import BIAnalystAgent, PLAN_SCHEMA

ROUTER_HEAD = """{
  "intent": "answer | display | chat",
  "reasoning": "<one short sentence on how you understood the request>",
  "title": "<display only: short title of what is shown>",
  "placement": "<display only: add | replace>",
  "reply": "<chat intent only: your complete answer to the user>",
"""
# on réutilise le schéma des specs (derived_columns / kpis / charts) du dashboard
ROUTER_SCHEMA = ROUTER_HEAD + PLAN_SCHEMA[PLAN_SCHEMA.index('  "derived_columns"'):]

CHAT_RULES = """
HOW TO DECIDE:
- intent "answer": the user asks a question about the data (a number, a comparison, a ranking, a trend...).
  Compute it: express EVERY number you need as KPI specs (kind aggregate, ratio or top_item) and/or chart specs
  (type "table" for rankings, breakdowns and lists; "line" for an evolution over time). 6 items at most.
- intent "display": the user asks to show, create or display a KPI, a chart/graph or a dashboard on the interface.
  Build exactly what was asked: 1 item for a specific KPI or chart, 4 to 8 items for a whole dashboard.
  Set "title" and "placement": "add" for one or a few items, "replace" when a full dashboard is requested.
- intent "chat": greetings, thanks, questions about how BIFlow works, or anything that needs no computation.
  Put your complete answer in "reply" and leave kpis and charts empty.
- Reuse the DEFAULT CLEANING (scope "cleaned") so that answers match the dashboard. Use "scope": "all_rows"
  with explicit filters only when the question concerns rows the cleaning removed (e.g. returns, cancellations).
- Use the conversation to resolve references ("and for France?", "the same by month").
- Derived columns already available can be used directly; define a new derived column only if needed, with a new name.
- Only use columns of the profile or the available derived columns. Never invent a column or a value.

RULES FOR SPECS:
- Allowed chart types: {chart_types}. Allowed aggregations: {aggs}. Allowed filter operators: {ops}.
  Allowed derived operations: {derived}.
- To focus on one entity use a filter with operator "==" or "in", with the exact spelling seen in the profile.
- Never sum or average non-additive columns (unit prices, rates...): sum a computed total (e.g. price x quantity).
- A rate, a share or an average per entity is kind "ratio"; numerator and denominator must cover the SAME rows
  (add a "not_null" filter on the counted column to the numerator). A "percent" KPI lies between 0 and 100 (scale 100).
- When a dimension is a code and another column holds its readable name, group by the code and set "label_column".
- In rankings of items, exclude non-item lines listed in "unusual_values" (shipping, fees, adjustments) when relevant.
- Use "time_grain" on a datetime column for evolutions, sort "x" for ordered x, donut only for few categories.
- Titles must name exactly what is computed. Write titles, subtitles and replies in {language}.
- Return ONLY valid JSON following the structure.
"""


class ChatAnalystAgent(BIAnalystAgent):
    MAX_REPAIRS = 1

    # ------------------------------------------------------------------ LLM
    @staticmethod
    def _history_text(history) -> str:
        lines = []
        for m in (history or [])[-6:]:
            who = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"{who}: {str(m.get('content', ''))[:400]}")
        return "\n".join(lines) or "(none)"

    def _route(self, question, profile, history, ctx, language, previous=None, errors=None) -> dict:
        derived = [{"name": d.get("name"), "definition": f"{d.get('operation')}({', '.join(d.get('columns') or [])})"}
                   for d in (ctx.get("derived_columns") or []) if isinstance(d, dict)]
        rules = CHAT_RULES.format(chart_types=eng.CHART_TYPES, aggs=eng.AGGREGATIONS, ops=eng.OPERATORS,
                                  derived=eng.DERIVED_OPS, language=language)
        user = (
            "DATASET PROFILE:\n" + json.dumps(profile, default=str)
            + "\n\nDASHBOARD CONTEXT (what the user currently sees):"
            + "\n- default cleaning filters (scope 'cleaned'): " + json.dumps(ctx.get("filters") or [], default=str)
            + "\n- derived columns already available (do not redefine them): " + json.dumps(derived, default=str)
            + "\n- current KPI values: " + json.dumps(ctx.get("kpis") or [], default=str)
            + "\n\nCONVERSATION SO FAR:\n" + self._history_text(history)
            + "\n\nUSER MESSAGE: " + question
            + "\n\nReturn JSON with exactly this structure:\n" + ROUTER_SCHEMA + "\n" + rules
        )
        if previous is not None:
            user += ("\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps(previous, default=str)
                     + "\nIt failed with these errors:\n- " + "\n- ".join(errors or [])
                     + "\nReturn the corrected JSON (same structure).")
        system = ("You are BIFlow's autonomous data assistant. You decide what to compute, and a safe engine "
                  "executes it: you never compute numbers yourself.")
        return self._chat_json(system, user, max_tokens=2000)

    def _compose_reply(self, question, intent, digest, ctx, language) -> str:
        system = "You are BIFlow's data assistant. You answer with precision, using only the computed results you are given."
        user = ("User question: " + question + "\nIntent: " + intent
                + "\n\nComputed results (the ONLY source of numbers): " + json.dumps(digest, default=str)
                + "\nUnless stated otherwise, results use these default cleaning filters: "
                + json.dumps(ctx.get("filters") or [], default=str)
                + "\n\nWrite the answer in " + language + ": direct and precise, 1 to 4 short sentences or a short list "
                  "of lines. Give the exact figures of the results (thousands separators, currency or unit when the "
                  "results give one). Do not show code, do not explain how it was computed, no markdown tables. "
                  "If the intent is display, say in one or two sentences what is now shown and give the key figure. "
                  "If the results do not contain the answer, say so plainly. "
                  'Return JSON: {"reply": "<answer>"}')
        out = self._chat_json(system, user, temperature=0.2, max_tokens=500)
        reply = out.get("reply") if isinstance(out, dict) else None
        return self._as_text(reply).strip()

    # ------------------------------------------------------------ utilitaires
    @staticmethod
    def _decision(raw) -> dict:
        if isinstance(raw, list):
            raw = next((r for r in raw if isinstance(r, dict)), {})
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _merge(plan: dict, ctx: dict) -> dict:
        """Plan exécutable : nettoyage + colonnes dérivées du dashboard, puis ce que demande l'utilisateur."""
        ctx_derived = [d for d in (ctx.get("derived_columns") or []) if isinstance(d, dict)]
        known = {d.get("name") for d in ctx_derived}
        new = [d for d in (plan.get("derived_columns") or []) if d.get("name") not in known]
        return {"cleaning": {"filters": ctx.get("filters") or []},
                "derived_columns": ctx_derived + new,
                "kpis": plan.get("kpis") or [], "charts": plan.get("charts") or []}

    @staticmethod
    def _fallback_reply(result) -> str:
        parts = []
        for k in result["kpis"]:
            val = k["value_text"] or f"{k['value']:,.2f}"
            parts.append(f"{k['title']} : {val} {k['unit']}".strip())
        return "\n".join(parts) or "Voici le résultat demandé."

    # ------------------------------------------------------------- orchestration
    def respond(self, question, df, profile, history, context, language="French") -> dict:
        """Retourne {"reply": str, "view": dict | None}. `view` est à afficher sur la page principale."""
        ctx = context or {}
        raw = self._route(question, profile, history, ctx, language)

        attempt = 0
        while True:
            decision = self._decision(raw)
            intent = str(decision.get("intent") or "").lower()
            if intent == "chat":
                reply = self._as_text(decision.get("reply")).strip()
                if reply:
                    return {"reply": reply, "view": None}

            plan, norm_errors = eng.normalize_plan(decision)
            result, errors = eng.run_plan(df, self._merge(plan, ctx))
            errors = norm_errors + errors
            usable = bool(result["kpis"] or result["charts"])
            if (usable and not errors) or attempt >= self.MAX_REPAIRS:
                break
            attempt += 1
            raw = self._route(question, profile, history, ctx, language,
                              previous=decision, errors=errors or ["no KPI or chart was produced"])

        if not usable:
            detail = f" (détail : {errors[0][:160]})" if errors else ""
            return {"reply": "Je n'ai pas réussi à calculer cette réponse à partir du dataset" + detail
                             + ". Pouvez-vous reformuler ou préciser les colonnes concernées ?", "view": None}

        intent = intent if intent in ("answer", "display") else "answer"
        digest = eng.results_digest(result, max_rows=25)
        try:
            reply = self._compose_reply(question, intent, digest, ctx, language) or self._fallback_reply(result)
        except Exception:
            reply = self._fallback_reply(result)

        view = None
        if intent == "display":
            view = {"id": uuid.uuid4().hex[:8],
                    "title": self._as_text(decision.get("title")) or question[:70],
                    "placement": "replace" if decision.get("placement") == "replace" else "add",
                    "question": question, "reasoning": self._as_text(decision.get("reasoning")),
                    "kpis": result["kpis"], "charts": result["charts"]}
        return {"reply": reply, "view": view}