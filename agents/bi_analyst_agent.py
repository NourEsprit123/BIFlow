
"""
Agent BI autonome.

Le dataset reçu est déjà nettoyé (travail de l'Agent 1 Data Engineering).
Boucle : PROFIL des données -> le LLM PLANIFIE (colonnes dérivées, KPIs, graphiques)
-> le moteur EXÉCUTE -> si erreur, le LLM CORRIGE son plan (jusqu'à MAX_REPAIRS fois)
-> le LLM rédige les INSIGHTS à partir des résultats réellement calculés.

Rien n'est codé en dur sur un dataset : ni colonnes, ni types de graphiques, ni nombre de KPIs.
"""

import os
import re
import json

import pandas as pd
from openai import OpenAI, BadRequestError
from dotenv import load_dotenv

from analytics import dashboard_engine as eng

load_dotenv()


PLAN_SCHEMA = """
{
  "business_context": "<what this dataset is, one row represents, business domain>",
  "derived_columns": [{"name":"<new col>","operation":"<op>","columns":["<col>"],"reasoning":"<why>"}],
  "kpis": [
    {"title":"<title>","kind":"aggregate","column":"<col>","aggregation":"<agg>","filters":[],"format":"integer|decimal|currency|percent","unit":"<unit or empty>","subtitle":"<short>","icon":"<emoji>"},
    {"title":"<title>","kind":"ratio","numerator":{"column":"<col>","aggregation":"<agg>","filters":[]},"denominator":{"column":"<col>","aggregation":"<agg>","filters":[]},"scale":1,"format":"<fmt>","unit":"<unit>","subtitle":"<sub>","icon":"<emoji>"},
    {"title":"<title>","kind":"top_item","dimension":"<cat col>","column":"<num col or null>","aggregation":"<agg>","top_n":1,"filters":[],"format":"<fmt>","unit":"<unit>","subtitle":"<sub>","icon":"<emoji>"}
  ],
  "charts": [
    {"title":"<title>","type":"bar|line|area|donut|histogram|scatter|table","x":"<col>","y":"<col or null>","aggregation":"<agg>","series":null,"time_grain":"month","top_n":10,"sort":"desc|asc|x","filters":[],"subtitle":"<short>","reasoning":"<why>"}
  ]
}
"""


PLAN_RULES = """
RULES (follow strictly):
1. Use ONLY columns from the profile or from "derived_columns". Never invent a column.
2. Dataset is already clean — no cleaning filters. Focus on KPIs and charts only.
3. Produce 3-5 KPIs and 4-7 charts. Do not pad with redundant items.
4. Chart types: time series -> line/area; ranking -> bar; share (few cats) -> donut; distribution -> histogram; correlation -> scatter; detail -> table. Never two charts with same x+y+aggregation.
5. Prefer aggregating a numeric measure over counting rows. Create derived columns if needed.
6. Never sum/average non-additive columns (prices, rates, IDs) — use mean/median or nunique.
7. sort="x" is REQUIRED for time axes (months, years) and any naturally ordered x.
8. KPI kinds: "aggregate"=single number; "ratio"=rate/average per entity (scale=100 for %, scale=1 otherwise); "top_item"=best dimension value. Never use format="percent" on a raw count.
9. Donut only for dimensions with <10 categories where top values cover >=60% of total.
10. Ratio: numerator and denominator must cover the SAME rows (matching filters).
11. {currency_hint}
12. Only use time_grain when x is a datetime column.
13. Allowed chart types: {chart_types}
14. Allowed aggregations: {aggs}
15. Allowed filter operators: {ops}
16. Allowed derived operations: {derived}
17. Titles and subtitles in {language}. Return ONLY valid compact JSON, no markdown.
"""



class BIAnalystAgent:
    MAX_REPAIRS = 2

    def __init__(self):
        provider = os.getenv("LLM_PROVIDER", "gemini").lower()

        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError(
                    "La clé GEMINI_API_KEY est absente du fichier .env"
                )

            self.client = OpenAI(
                api_key=api_key,
                base_url=(
                    "https://generativelanguage.googleapis.com/v1beta/openai/"
                ),
            )
            self.model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError(
                    "La clé GROQ_API_KEY est absente du fichier .env"
                )

            self.client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key,
            )
            self.model = os.getenv(
                "GROQ_MODEL", "llama-3.1-8b-instant"
            )

        elif provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError(
                    "La clé OPENROUTER_API_KEY est absente du fichier .env"
                )

            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
            self.model = os.getenv("OPENROUTER_MODEL")
            if not self.model:
                raise ValueError(
                    "OPENROUTER_MODEL doit être défini dans le fichier .env"
                )

        else:
            raise ValueError(
                f"Fournisseur inconnu : {provider}. "
                "Valeurs possibles : gemini, groq, openrouter."
            )

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = re.sub(
            r"^```(?:json)?|```$",
            "",
            (text or "").strip(),
            flags=re.MULTILINE,
        ).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end > start:
                return json.loads(text[start:end + 1])

            raise ValueError("réponse du LLM non JSON")

    def _chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        retries: int = 3,
        max_tokens: int = 750,
    ) -> dict:
        """
        Appel robuste :
        - max_tokens élevé + reasoning_effort faible pour les modèles gpt-oss.
        - si le mode JSON strict est rejeté, retente sans ce mode et parse le JSON.
        """
        last_err = None
        use_json_mode = True

        for _ in range(retries + 1):
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if "gpt-oss" in self.model:
                kwargs["extra_body"] = {"reasoning_effort": "low"}

            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            try:
                resp = self.client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content
                return self._parse_json(content)

            except BadRequestError as e:
                last_err = e
                use_json_mode = False

            except ValueError as e:
                last_err = e

        raise ValueError(
            f"Le LLM n'a pas renvoyé de JSON valide après "
            f"{retries + 1} essais : {last_err}"
        )

    def _rules(self, language: str, currency: str = None) -> str:
        if currency:
            hint = (
                f"The currency of monetary values is {currency}: "
                "use it as the KPI unit."
            )
        else:
            hint = (
                "Use a currency symbol as unit only if the data clearly "
                "implies it (e.g. a dominant country); otherwise leave "
                "unit empty."
            )

        return PLAN_RULES.format(
            currency_hint=hint,
            chart_types=eng.CHART_TYPES,
            aggs=eng.AGGREGATIONS,
            ops=eng.OPERATORS,
            derived=eng.DERIVED_OPS,
            language=language,
        )

    # ---------------------------------------------------------------
    # Étapes de planification
    # ---------------------------------------------------------------

    def _plan(
        self,
        profile: dict,
        language: str,
        currency: str = None,
    ) -> dict:
        system = (
            "You are an autonomous senior BI analyst who designs "
            "dashboards by reasoning on the data. "
            "The dataset has already been cleaned by a Data Engineering agent — "
            "do NOT add any cleaning or filtering logic."
        )

        user = (
            "Here is the statistical profile of a pre-cleaned dataset:\n"
            + json.dumps(profile, default=str)
            + "\n\nDesign the best KPI dashboard for it. "
            "Focus only on derived columns, KPIs and charts. "
            "Return JSON with exactly this structure:\n"
            + PLAN_SCHEMA
            + "\n"
            + self._rules(language, currency)
        )

        return self._chat_json(system, user)

    def _repair(
        self,
        profile: dict,
        plan: dict,
        errors: list,
        language: str,
        currency: str = None,
    ) -> dict:
        system = (
            "You are an autonomous senior BI analyst. "
            "Your previous dashboard plan failed on some items."
        )

        user = (
            "Dataset profile:\n"
            + json.dumps(profile, default=str)
            + "\n\nYour previous plan:\n"
            + json.dumps(plan, default=str)
            + "\n\nErrors raised when executing it:\n- "
            + "\n- ".join(errors)
            + "\n\nReturn the FULL corrected plan (same JSON structure). "
            "Fix or replace only what is broken, keep what works."
            + "\n"
            + self._rules(language, currency)
        )

        return self._chat_json(system, user)

    def _insights(
        self,
        result: dict,
        plan: dict,
        language: str,
    ) -> dict:
        system = (
            "You are an analyst who explains computed results with precision "
            "and provides actionable recommendations."
        )

        user = (
            "Business context: "
            + str(plan.get("business_context", ""))
            + "\n\nComputed results (the ONLY source of numbers you may use):\n"
            + json.dumps(eng.results_digest(result), default=str)
            + "\n\nWrite 3 to 5 insights a decision maker would care about "
            "(concentration, trend, anomaly, opportunity, risk...). "
            "Every number you cite must appear in the results above. "
            "IMPORTANT: Each insight must include a clear, actionable "
            "recommendation for the business. "
            "Do NOT do any arithmetic yourself: use only the pre-computed "
            "fields (value, share_pct, total_all_categories, shown_total, "
            "shown_share_pct, distribution_stats, highest, lowest). "
            "A histogram bin labelled 'a – b' covers values from a to b: "
            "never call a bin negative unless both bounds are below 0 "
            "(use distribution_stats for negatives). "
            "Qualify something as 'high' or 'low' only if the shares justify it. "
            "Use the KPI units as given. "
            "Beware of partial periods (the last time bucket may be incomplete). "
            f"\nWrite in {language}. Return JSON: "
            '{"summary": "<one-sentence executive summary>", '
            '"insights": [{"tag": "<SHORT UPPERCASE CATEGORY>", '
            '"title": "<title>", '
            '"text": "<2 sentences max, including a clear business recommendation>", '
            '"confidence": <0-100, how strongly the computed data supports this insight>}]}'
        )

        return self._chat_json(system, user, temperature=0.3, max_tokens=750)

    # -----------------------------------------------------------
    # Orchestration et normalisation
    # -----------------------------------------------------------

    @staticmethod
    def _as_text(x) -> str:
        if isinstance(x, str):
            return x
        if x is None:
            return ""
        return json.dumps(x, default=str, ensure_ascii=False)

    @staticmethod
    def _as_str_list(x) -> list:
        if x is None:
            return []

        if isinstance(x, str):
            return [x]

        if isinstance(x, list):
            return [BIAnalystAgent._as_text(i) for i in x]

        return [BIAnalystAgent._as_text(x)]

    @staticmethod
    def _normalize_insights(ins) -> dict:
        """Tolère un JSON d'insights mal formé."""
        if isinstance(ins, list):
            ins = {"insights": ins}

        if not isinstance(ins, dict):
            return {"summary": "", "insights": []}

        items = ins.get("insights")

        if isinstance(items, dict):
            items = [items]

        items = [
            item
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        ]

        return {
            "summary": BIAnalystAgent._as_text(ins.get("summary")),
            "insights": items,
        }

    def _execute(self, df, raw_plan):
        """Normalise puis exécute le plan ; retourne (plan, résultat, erreurs)."""
        plan, norm_errors = eng.normalize_plan(raw_plan)
        result, errors = eng.run_plan(df, plan)

        return plan, result, norm_errors + errors

    # -----------------------------------------------------------
    # Construction du dashboard
    # -----------------------------------------------------------

    def build_dashboard(
        self,
        df_raw: pd.DataFrame,
        language: str = "English",
        currency: str = None,
    ) -> dict:
        # Dataset is already clean — just coerce types for the engine
        df = eng.coerce_types(df_raw)
        # Compact profile: max 4 cat values, 2 examples — keeps input tokens small
        profile = eng.profile_dataset(df, max_cat_values=4)

        raw_plan = self._plan(profile, language, currency)
        plan, result, errors = self._execute(df, raw_plan)

        attempts = 0

        while errors and attempts < self.MAX_REPAIRS:
            attempts += 1

            try:
                raw_plan = self._repair(
                    profile,
                    raw_plan,
                    errors,
                    language,
                    currency,
                )
            except Exception:
                break

            plan, result, errors = self._execute(df, raw_plan)

        try:
            insights = self._normalize_insights(
                self._insights(result, plan, language)
            )
        except Exception:
            insights = {"summary": "", "insights": []}

        return {
            "business_context": self._as_text(plan.get("business_context")),
            "derived_columns":  plan.get("derived_columns") or [],
            "total_rows":       result["rows_before"],
            "kpis":             result["kpis"],
            "charts":           result["charts"],
            "summary":          insights["summary"],
            "insights":         insights["insights"],
            "errors":           errors,
            "repair_attempts":  attempts,
        }
