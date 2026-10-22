"""
Agent BI autonome.

Boucle : PROFIL des données -> le LLM PLANIFIE (nettoyage, colonnes dérivées, KPIs, graphiques)
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

PLAN_SCHEMA = """{
  "business_context": "<1-3 sentences: what this dataset is about, what one row represents, the business domain>",
  "data_quality_findings": ["<problem you noticed in the profile, or empty list>"],
  "cleaning": {
    "reasoning": "<why these filters>",
    "filters": [{"column": "<existing column>", "operator": "<operator>", "value": <value>}]
  },
  "derived_columns": [
    {"name": "<new column name>", "operation": "<derived op>", "columns": ["<existing column>", "..."], "reasoning": "<why>"}
  ],
  "kpis": [
    // A KPI is ONE number (or one leading item). Three kinds:
    {"title": "<short title>", "kind": "aggregate", "column": "<column or null>", "aggregation": "<aggregation>", "filters": [],
     "scope": "cleaned | all_rows", "format": "integer | decimal | currency | percent", "unit": "<symbol or empty>", "subtitle": "<short>", "icon": "<one emoji>", "reasoning": "<why>"},
    {"title": "<short title>", "kind": "ratio",
     "numerator":   {"column": "<column or null>", "aggregation": "<aggregation>", "filters": [], "absolute": false},
     "denominator": {"column": "<column or null>", "aggregation": "<aggregation>", "filters": [], "absolute": false},
     "scale": <1, or 100 for a percentage>, "format": "...", "unit": "...", "subtitle": "...", "icon": "...", "reasoning": "..."},
    {"title": "<short title>", "kind": "top_item", "dimension": "<category column>", "column": "<numeric column or null>",
     "aggregation": "<aggregation>", "top_n": <integer>, "label_column": "<optional readable-name column>", "filters": [], "format": "...", "unit": "...", "subtitle": "...", "icon": "...", "reasoning": "..."}
  ],
  "charts": [
    {"title": "<title>", "subtitle": "<short>", "type": "<chart type>",
     "x": "<column: category, date, or numeric for histogram/scatter>",
     "y": "<numeric column to aggregate, or null to count rows>",
     "aggregation": "<aggregation>", "series": "<optional column to split into several series, or null>",
     "group_by": "<scatter only: entity column, or null>", "time_grain": "<day|week|month|quarter|year, only when x is a date>",
     "x_aggregation": "<scatter only: aggregation for the x axis, or null>",
     "label_column": "<optional: column holding the readable name of x, e.g. a description for a code>",
     "top_n": <integer>, "sort": "desc | asc | x", "scope": "cleaned | all_rows", "filters": [],
     "reasoning": "<why this chart and this type for THIS data>"}
  ]
}"""

PLAN_RULES = """
RULES:
- Use ONLY column names that exist in the profile, or names you define in "derived_columns". Never invent a column.
- Reason like a senior BI analyst: understand the domain first, then decide what matters for a decision maker.
- Decide yourself how many KPIs (3 to 6) and charts (4 to 8) are useful. Do not pad.
- Choose each chart type from what the data calls for: evolution over time -> line or area (x = a date column);
  ranking of categories -> bar; share of a whole with few categories -> donut; distribution of a numeric
  column -> histogram; relationship between two numeric measures -> scatter; precise detail -> table.
  Mix the types; never produce two charts with the same x, y and aggregation.
- When a meaningful numeric measure exists, aggregate it (sum, mean...) instead of counting rows.
  If the measure you need does not exist as a column but can be computed from two columns, create it in "derived_columns".
- Never sum or average identifier/code columns; use "nunique" to count distinct entities.
- Data quality: look at the profile (values <= 0 in columns that should be positive, nulls in key columns,
  duplicates...). Add cleaning filters only when justified, stay conservative, and explain why in "reasoning".
- Use "top_n" and "sort" to keep charts readable. "sort": "desc" = top N by value, "asc" = bottom N by value,
  "x" = natural order of x (REQUIRED for months, years, or any ordered x so that nothing is cut or reordered).
  Line and area charts are always drawn in the natural order of x.
- KPIs: a KPI is a single number. A rate, a share or an average PER ENTITY must use kind "ratio"
  (average order value = sum of the amount / nunique of the order id; a return rate = absolute value of the amount
  where it is negative / amount where it is positive, with scale 100). A "top N" ranking must use kind "top_item"
  (or be a chart). Never format a raw count or sum as "percent": a "percent" KPI must lie between 0 and 100.
- Never sum or average non-additive columns across entities (unit prices, rates, percentages, scores): use mean or
  median, or sum a computed total (e.g. unit price x quantity). For a scatter, use "x_aggregation" to aggregate the
  x axis differently from the y axis (e.g. x: mean price, y: sum of quantity).
- If the dataset only has separate numeric year and month columns (no datetime), use x = month, series = year, sort = "x".
- Cleaning vs scope: the "cleaning" filters apply by default (scope "cleaned") to EVERY KPI and chart. If an item
  measures something that the cleaning removes (e.g. a return/cancellation rate when returns were filtered out),
  set "scope": "all_rows" on that item and give it its own filters. Never leave a KPI that is 0 or empty because of your cleaning.
- Items vs non-items: in a ranking of products/items, exclude lines that are not real items (shipping, fees, bank
  charges, manual adjustments, samples...). Look at "unusual_values" in the profile: values whose format differs
  from the dominant one are often such lines. Exclude them with a "not_in" filter on that chart/KPI.
- Time evolution: use the datetime column directly with "time_grain" (a continuous axis). Never split a date into
  separate year and month columns for a time chart unless no datetime column exists.
- Readable labels: when a dimension is a code or identifier and another column holds its readable name (e.g. a
  product code and its description), group by the code and set "label_column" to the name column. Labels become
  readable and distinct entities are not merged.
- Same population: in a ratio such as "revenue per customer", numerator and denominator must cover the SAME rows.
  If the denominator counts non-null values of a column, add a "not_null" filter on that column to the numerator too.
- KPI titles and subtitles must name exactly what is computed ("average revenue per customer" is not "customer
  concentration"; concentration = share of the total held by the top N).
- Reversals and outliers: if a numeric column has symmetrical extreme min and max (an operation and its exact
  reversal, e.g. +80995 and -80995) or values far above p99, removing the negative lines keeps the inflated originals.
  Mention it in "data_quality_findings" and either keep the negative lines (net totals) or state the limitation in
  "cleaning.reasoning".
- Donut charts only for a dimension with FEW categories whose top values cover most of the total (>= 60%).
  A long tail (hundreds of products, customers...) must be a bar chart (ranking), never a donut.
- Titles must describe exactly what is plotted: do not call a column by a name it does not have
  (e.g. do not say "category" if the column is an individual product description or code).
- Do not produce two charts with the same x and the same measure, even with different chart types.
- {currency_hint}
- Use a time chart only if a datetime column exists; choose "time_grain" from the date range.
- Allowed chart types: {chart_types}
- Allowed aggregations: {aggs}
- Allowed filter operators: {ops}
- Allowed derived operations: {derived}
- Titles, subtitles and reasoning must be written in {language}.
- Return ONLY valid JSON following the schema, no markdown.
"""


class BIAnalystAgent:
    MAX_REPAIRS = 2

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("La clé GROQ_API_KEY est introuvable dans le fichier .env")
        self.client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    # ------------------------------------------------------------------ LLM
    @staticmethod
    def _parse_json(text: str) -> dict:
        text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start:end + 1])
            raise ValueError("réponse du LLM non JSON")

    def _chat_json(self, system: str, user: str, temperature: float = 0.2, retries: int = 3) -> dict:
        """
        Appel robuste :
        - max_tokens élevé + reasoning_effort faible (les modèles gpt-oss dépensent sinon tout leur
          budget en raisonnement et renvoient une sortie vide)
        - si Groq rejette le mode JSON strict (400 json_validate_failed), on retente sans ce mode
          et on parse le JSON nous-mêmes
        """
        last_err = None
        use_json_mode = True
        for _ in range(retries + 1):
            kwargs = dict(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=8000,
            )
            if "gpt-oss" in self.model:
                kwargs["extra_body"] = {"reasoning_effort": "low"}
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                resp = self.client.chat.completions.create(**kwargs)
                return self._parse_json(resp.choices[0].message.content)
            except BadRequestError as e:
                last_err = e
                use_json_mode = False
            except ValueError as e:      # sortie vide ou JSON invalide
                last_err = e
        raise ValueError(f"Le LLM n'a pas renvoyé de JSON valide après {retries + 1} essais : {last_err}")

    def _rules(self, language: str, currency: str = None) -> str:
        hint = (f"The currency of monetary values is {currency}: use it as the KPI unit." if currency else
                "Use a currency symbol as unit only if the data clearly implies it (e.g. a dominant country); otherwise leave unit empty.")
        return PLAN_RULES.format(currency_hint=hint, chart_types=eng.CHART_TYPES, aggs=eng.AGGREGATIONS,
                                 ops=eng.OPERATORS, derived=eng.DERIVED_OPS, language=language)

    # --------------------------------------------------------------- étapes
    def _plan(self, profile: dict, language: str, currency: str = None) -> dict:
        system = "You are an autonomous senior BI analyst who designs dashboards by reasoning on the data."
        user = ("Here is the statistical profile of a dataset:\n"
                + json.dumps(profile, default=str)
                + "\n\nDesign the best dashboard for it. Return JSON with exactly this structure:\n"
                + PLAN_SCHEMA + "\n" + self._rules(language, currency))
        return self._chat_json(system, user)

    def _repair(self, profile: dict, plan: dict, errors: list, language: str, currency: str = None) -> dict:
        system = "You are an autonomous senior BI analyst. Your previous dashboard plan failed on some items."
        user = ("Dataset profile:\n" + json.dumps(profile, default=str)
                + "\n\nYour previous plan:\n" + json.dumps(plan, default=str)
                + "\n\nErrors raised when executing it:\n- " + "\n- ".join(errors)
                + "\n\nReturn the FULL corrected plan (same JSON structure). Fix or replace only what is broken, "
                  "keep what works." + "\n" + self._rules(language, currency))
        return self._chat_json(system, user)

    def _insights(self, result: dict, plan: dict, language: str) -> dict:
        system = "You are an analyst who explains computed results with precision and without inventing anything."
        user = ("Business context: " + str(plan.get("business_context", ""))
                + "\nCleaning applied: " + json.dumps((plan.get("cleaning") or {}), default=str)
                + "\n\nComputed results (the ONLY source of numbers you may use):\n"
                + json.dumps(eng.results_digest(result), default=str)
                + "\n\nWrite 3 to 5 insights a decision maker would care about (concentration, trend, anomaly, "
                  "opportunity, risk...). Every number you cite must appear in the results above. "
                  "Do NOT do any arithmetic yourself: use only the pre-computed fields (value, share_pct, total_all_categories, "
                  "shown_total, shown_share_pct, distribution_stats). A histogram bin labelled 'a – b' covers values from a to b: "
                  "never call a bin negative unless both bounds are below 0 (use distribution_stats for negatives). "
                  "Qualify something as 'high' or 'low' only if the shares justify it. Use the KPI units as given. "
                  "Beware of partial periods (the last time bucket may be incomplete)."
                  f"\nWrite in {language}. Return JSON: "
                  '{"summary": "<one-sentence executive summary>", "insights": [{"tag": "<SHORT UPPERCASE CATEGORY you choose>", '
                  '"title": "<title>", "text": "<2 sentences max>", '
                  '"confidence": <0-100, how strongly the computed data supports this insight>}]}')
        return self._chat_json(system, user, temperature=0.3)

    # ----------------------------------------------------------- orchestration
    @staticmethod
    def _as_text(x) -> str:
        return x if isinstance(x, str) else ("" if x is None else json.dumps(x, default=str, ensure_ascii=False))

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
        """Tolère un JSON d'insights mal formé (liste au lieu d'objet, éléments non-objets...)."""
        if isinstance(ins, list):
            ins = {"insights": ins}
        if not isinstance(ins, dict):
            return {"summary": "", "insights": []}
        items = ins.get("insights")
        if isinstance(items, dict):
            items = [items]
        items = [i for i in (items if isinstance(items, list) else []) if isinstance(i, dict)]
        return {"summary": BIAnalystAgent._as_text(ins.get("summary")), "insights": items}

    def _execute(self, df, raw_plan):
        """Normalise puis exécute le plan ; retourne (plan_normalisé, résultat, erreurs)."""
        plan, norm_errors = eng.normalize_plan(raw_plan)
        result, errors = eng.run_plan(df, plan)
        return plan, result, norm_errors + errors

    def build_dashboard(self, df_raw: pd.DataFrame, language: str = "English", currency: str = None) -> dict:
        df = eng.coerce_types(df_raw)
        profile = eng.profile_dataset(df)

        raw_plan = self._plan(profile, language, currency)
        plan, result, errors = self._execute(df, raw_plan)

        attempts = 0
        while errors and attempts < self.MAX_REPAIRS:
            attempts += 1
            try:
                raw_plan = self._repair(profile, raw_plan, errors, language, currency)
            except Exception:
                break
            plan, result, errors = self._execute(df, raw_plan)

        try:
            ins = self._normalize_insights(self._insights(result, plan, language))
        except Exception:
            ins = {"summary": "", "insights": []}

        cleaning = plan.get("cleaning") or {}
        return {
            "business_context": self._as_text(plan.get("business_context")),
            "data_quality_findings": self._as_str_list(plan.get("data_quality_findings")),
            "cleaning": {"reasoning": cleaning.get("reasoning", ""), "filters": cleaning.get("filters") or [],
                         "rows_before": result["rows_before"], "rows_after": result["rows_after"]},
            "derived_columns": plan.get("derived_columns") or [],
            "kpis": result["kpis"],
            "charts": result["charts"],
            "summary": ins["summary"],
            "insights": ins["insights"],
            "errors": errors,          # erreurs restantes après réparation (affichées à l'utilisateur)
            "repair_attempts": attempts,
        }