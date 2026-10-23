"""
Agent BI autonome.

Pipeline :
1. Profilage du dataset.
2. Planification des KPIs et graphiques par le LLM.
3. Exécution du plan par dashboard_engine.
4. Réparation limitée du plan si nécessaire.
5. Génération des insights, avec fallback Python si le LLM échoue.

Le dataset est supposé déjà nettoyé par l'Agent Data Engineering.
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
  "business_context": "<dataset domain and one row meaning>",
  "derived_columns": [
    {
      "name": "<new column>",
      "operation": "<operation>",
      "columns": ["<existing column>"],
      "reasoning": "<reason>"
    }
  ],
  "kpis": [
    {
      "title": "<title>",
      "kind": "aggregate",
      "column": "<column>",
      "aggregation": "<aggregation>",
      "filters": [],
      "format": "integer|decimal|currency|percent",
      "unit": "",
      "subtitle": "<short description>",
      "icon": "<emoji>"
    },
    {
      "title": "<title>",
      "kind": "ratio",
      "numerator": {
        "column": "<column>",
        "aggregation": "<aggregation>",
        "filters": []
      },
      "denominator": {
        "column": "<column>",
        "aggregation": "<aggregation>",
        "filters": []
      },
      "scale": 1,
      "format": "<format>",
      "unit": "<unit>",
      "subtitle": "<short description>",
      "icon": "<emoji>"
    },
    {
      "title": "<title>",
      "kind": "top_item",
      "dimension": "<categorical column>",
      "column": "<numeric column or null>",
      "aggregation": "<aggregation>",
      "top_n": 1,
      "filters": [],
      "format": "<format>",
      "unit": "<unit>",
      "subtitle": "<short description>",
      "icon": "<emoji>"
    }
  ],
  "charts": [
    {
      "title": "<title>",
      "type": "bar|line|area|donut|histogram|scatter|table",
      "x": "<column>",
      "y": "<column or null>",
      "aggregation": "<aggregation>",
      "series": null,
      "time_grain": null,
      "top_n": 10,
      "sort": "desc|asc|x",
      "filters": [],
      "subtitle": "<short description>",
      "reasoning": "<reason>"
    }
  ]
}
"""


PLAN_RULES = """
RULES:
1. Use only columns present in the profile or derived_columns.
2. The dataset is already clean. Do not add cleaning logic.
3. Generate 3-5 meaningful KPIs when the available columns permit.
4. Generate at least 4 useful charts when the available data permits.
   Prefer 4-7 charts, covering different analytical questions.
5. Never return an empty charts array if at least one valid chart
   can be created from the available columns.
6. Before returning the plan, verify that every chart has:
   - a valid existing x column;
   - a valid y column when required;
   - an appropriate aggregation;
   - a supported chart type;
   - a meaningful analytical purpose.
7. Choose charts based on the actual dataset profile, not generic templates.
8. Time series: line/area with a valid date column.
   Rankings: bar. Shares: donut when appropriate.
   Numeric distributions: histogram. Numeric relationships: scatter.
   Details: table when useful.
9. Prefer useful numeric aggregations over row counts when possible.
10. Do not sum identifiers, rates, or non-additive measures.
11. Use sort="x" for chronological axes.
12. KPI kinds: aggregate, ratio, top_item.
13. Never use percent formatting for a raw count.
14. Ratio numerator and denominator must use comparable rows.
15. {currency_hint}
16. Allowed aggregations: {aggs}
17. Allowed filter operators: {ops}
18. Allowed derived operations: {derived}
19. Titles and subtitles must be in {language}.
20. Return compact valid JSON only, without Markdown.
"""


class BIAnalystAgent:
    MAX_REPAIRS = 1

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
            self.model = os.getenv(
                "GEMINI_MODEL", "gemini-3.8-flash"
            )

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

    # ---------------------------------------------------------
    # Appels LLM et JSON
    # ---------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse un objet JSON, même si le LLM ajoute des balises Markdown."""

        if not isinstance(text, str) or not text.strip():
            raise ValueError("La réponse du LLM est vide.")

        text = re.sub(
            r"^\s*```(?:json)?\s*|\s*```\s*$",
            "",
            text.strip(),
            flags=re.IGNORECASE | re.MULTILINE,
        ).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")

            if start < 0 or end <= start:
                raise ValueError("La réponse du LLM ne contient pas de JSON.")

            data = json.loads(text[start:end + 1])

        if not isinstance(data, dict):
            raise ValueError("Le JSON du LLM doit être un objet.")

        return data

    def _chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        retries: int = 1,
        max_tokens: int = 850,
    ) -> dict:
        """
        Appel LLM à consommation contrôlée.

        Une erreur 429, 401 ou 403 arrête immédiatement les tentatives.
        Si le fournisseur refuse le mode JSON, une tentative sans ce mode
        est autorisée si une tentative supplémentaire est disponible.
        """

        last_err = None
        use_json_mode = True
        attempt = 0
        max_attempts = retries + 1

        while attempt < max_attempts:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if "gpt-oss" in self.model.lower():
                kwargs["extra_body"] = {
                    "reasoning_effort": "low"
                }

            if use_json_mode:
                kwargs["response_format"] = {
                    "type": "json_object"
                }

            try:
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                return self._parse_json(content)

            except BadRequestError as exc:
                last_err = exc

                if use_json_mode and attempt + 1 < max_attempts:
                    use_json_mode = False
                    attempt += 1
                    continue

                break

            except ValueError as exc:
                last_err = exc
                break

            except Exception as exc:
                last_err = exc
                status_code = getattr(exc, "status_code", None)

                if status_code in (401, 403, 429):
                    break

                attempt += 1
                if attempt >= max_attempts:
                    break
                continue

        raise RuntimeError(
            f"Échec de l'appel LLM ({self.model}) : {last_err}"
        ) from last_err

    def _rules(self, language: str, currency: str = None) -> str:
        if currency:
            hint = (
                f"The currency is {currency}. Use it as the unit "
                "for relevant monetary KPIs."
            )
        else:
            hint = (
                "Use a currency unit only when the dataset clearly "
                "supports it; otherwise leave the unit empty."
            )

        return PLAN_RULES.format(
            currency_hint=hint,
            chart_types=eng.CHART_TYPES,
            aggs=eng.AGGREGATIONS,
            ops=eng.OPERATORS,
            derived=eng.DERIVED_OPS,
            language=language,
        )

    # ---------------------------------------------------------
    # Planification
    # ---------------------------------------------------------

    def _plan(
        self,
        profile: dict,
        language: str,
        currency: str = None,
        dashboard_focus: str = "overview",
    ) -> dict:
        """Génère le plan LLM d'un dashboard spécialisé."""

        focus_instructions = {
            "overview": (
                "Create an executive overview: high-level KPIs, "
                "overall performance and the most important indicators."
            ),
            "comparison": (
                "Create a comparative analysis: compare categories, "
                "segments or groups using only available columns."
            ),
            "trends": (
                "Create a trends and patterns dashboard. Use time analysis "
                "if a valid date column exists. Otherwise analyze distributions, "
                "relationships or other useful patterns."
            ),
        }

        focus_instruction = focus_instructions.get(
            dashboard_focus,
            focus_instructions["overview"],
        )

        system = (
            "You are a senior Business Intelligence analyst. "
            "Build a dashboard from the supplied dataset profile. "
            "Never invent column names, data, KPIs or results. "
            "Select only charts supported by the actual dataset. "
            "Return valid JSON matching the required schema."
        )

        user = (
            "DATASET PROFILE:\n"
            + json.dumps(
                profile,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\nDASHBOARD OBJECTIVE:\n"
            + focus_instruction
            + "\n\n"
            + "Generate 3 to 5 relevant KPIs and at least 4 useful charts "
            "when the available columns permit them. "
            + "Choose chart types and columns according to the data. "
            + "Do not repeat the same analysis across dashboards. "
            + "If the data does not support a chart, do not invent one. "
            + "\n\nReturn this JSON structure:\n"
            + PLAN_SCHEMA
            + "\n"
            + self._rules(language, currency)
        )

        return self._chat_json(
            system,
            user,
            temperature=0.1,
            retries=0,
            max_tokens=350,
        )

    def _complete_missing_charts(
        self,
        profile: dict,
        plan: dict,
        language: str,
        currency: str = None,
    ) -> dict:
        """Demande au LLM de compléter un plan sans graphiques."""

        if plan.get("charts"):
            return plan

        system = (
            "You are a senior BI analyst. Generate useful charts "
            "from the supplied dataset profile. "
            "Use only existing columns and valid aggregations. "
            "Never return an empty charts array if a valid chart "
            "can be created."
        )

        user = (
            "The previous dashboard plan contains no charts. "
            "Generate 3 to 5 relevant KPIs and at least 4 useful charts. "
            "Analyze the dataset schema and select at least 4 meaningful charts. "
            "Use different chart types when appropriate, such as bar, line, area, ""donut, scatter, or histogram. "
            "Choose only columns that exist in the dataset. "
            "Do not invent column names. "
            "Each chart must have a clear analytical purpose and should not duplicate "
            "another chart. "
            "Return the chart specifications in the required JSON format. "
            "Choose different analytical questions based on the actual "
            "columns, data types, and statistics. Do not invent columns. "
            "Return a complete JSON object with business_context, "
            "derived_columns, kpis, and charts. Preserve the existing "
            "plan fields and KPI definitions.\n\n"
            "Dataset profile:\n"
            + json.dumps(
                profile,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\nPrevious plan:\n"
            + json.dumps(
                plan,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\nRequired JSON structure:\n"
            + PLAN_SCHEMA
            + "\n"
            + self._rules(language, currency)
        )

        completed = self._chat_json(
            system,
            user,
            temperature=0.1,
            retries=0,
            max_tokens=850,
        )

        if not isinstance(completed.get("charts"), list):
            return plan

        if not completed["charts"]:
            return plan

        return completed

    def _repair(
        self,
        profile: dict,
        plan: dict,
        errors: list,
        language: str,
        currency: str = None,
    ) -> dict:
        """Répare le plan une seule fois au maximum."""

        system = (
            "You are a senior BI analyst. Correct the dashboard plan. "
            "Preserve valid items, use existing columns only, and return JSON."
        )

        compact_plan = {
            "business_context": plan.get("business_context", ""),
            "derived_columns": plan.get("derived_columns", []),
            "kpis": plan.get("kpis", []),
            "charts": plan.get("charts", []),
        }

        compact_errors = [str(error)[:200] for error in errors[:5]]

        user = (
            "Dataset profile:\n"
            + json.dumps(
                profile, default=str, ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\nPrevious plan:\n"
            + json.dumps(
                compact_plan, default=str, ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\nExecution errors:\n"
            + json.dumps(compact_errors, ensure_ascii=False)
            + "\nCorrect invalid items while preserving valid ones. "
            "Return the complete corrected JSON plan.\n"
            + self._rules(language, currency)
        )

        return self._chat_json(
            system,
            user,
            temperature=0.1,
            retries=0,
            max_tokens=900,
        )

    # ---------------------------------------------------------
    # Insights
    # ---------------------------------------------------------

    def _insights(
        self,
        result: dict,
        plan: dict,
        language: str,
    ) -> dict:
        system = (
            "You are a BI analyst. Explain computed results accurately "
            "and provide practical recommendations. Never invent numbers."
        )

        digest = eng.results_digest(result)

        user = (
            "Business context: "
            + str(plan.get("business_context", ""))
            + "\nComputed results (the only source of numbers):\n"
            + json.dumps(
                digest, default=str, ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\nWrite 3 concise, useful insights when the data permits. "
            "Every numeric claim must appear in the supplied results. "
            "Each insight should include a practical recommendation. "
            "Do not calculate new statistics. "
            "Be cautious about incomplete time periods. "
            f"Write in {language}. Return JSON only with this structure: "
            '{"summary":"<one-sentence summary>",'
            '"insights":[{"tag":"<CATEGORY>","title":"<title>",'
            '"text":"<recommendation>","confidence":0}]}'
        )

        return self._chat_json(
            system,
            user,
            temperature=0.2,
            retries=0,
            max_tokens=750,
        )

    @staticmethod
    def _as_text(value) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        return json.dumps(value, default=str, ensure_ascii=False)

    @staticmethod
    def _normalize_insights(insights) -> dict:
        """Normalise la réponse JSON des insights."""

        if isinstance(insights, list):
            insights = {"insights": insights}

        if not isinstance(insights, dict):
            return {"summary": "", "insights": []}

        items = insights.get("insights", [])

        if isinstance(items, dict):
            items = [items]

        if not isinstance(items, list):
            items = []

        valid_items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            text = item.get("text")

            if not title or not text:
                continue

            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0

            item["confidence"] = max(0, min(100, confidence))
            item["tag"] = str(item.get("tag") or "ANALYSE")
            valid_items.append(item)

        return {
            "summary": BIAnalystAgent._as_text(
                insights.get("summary")
            ),
            "insights": valid_items,
        }

    @staticmethod
    def _fallback_insights(
        result: dict,
        language: str = "English",
    ) -> dict:
        """
        Produit des insights prudents sans nouvel appel LLM.
        Ils décrivent les résultats présents sans inventer de tendances.
        """

        kpis = result.get("kpis") or []
        charts = result.get("charts") or []

        def get_field(item, *names):
            if not isinstance(item, dict):
                return None

            for name in names:
                value = item.get(name)
                if value is not None and value != "":
                    return value

            return None

        french = str(language).lower().startswith("fr")
        insights = []

        for kpi in kpis[:3]:
            title = get_field(kpi, "title", "label", "name")
            value = get_field(kpi, "value", "formatted_value")

            if not title:
                continue

            if french:
                if value is not None:
                    message = (
                        f"La valeur calculée pour « {title} » est "
                        f"{value}. Suivez cet indicateur dans le temps "
                        "pour évaluer son évolution."
                    )
                else:
                    message = (
                        f"L'indicateur « {title} » est disponible. "
                        "Suivez son évolution pour repérer les changements."
                    )
            else:
                if value is not None:
                    message = (
                        f"The computed value for '{title}' is {value}. "
                        "Track this indicator over time to assess changes."
                    )
                else:
                    message = (
                        f"The '{title}' indicator is available. "
                        "Track it over time to identify changes."
                    )

            insights.append({
                "tag": "INDICATOR",
                "title": str(title),
                "text": message,
                "confidence": 100,
            })

        chart_titles = []

        for chart in charts:
            title = get_field(chart, "title", "name", "label")
            if title:
                chart_titles.append(str(title))

        if chart_titles and len(insights) < 5:
            if french:
                message = (
                    "Consultez les graphiques "
                    + ", ".join(chart_titles[:3])
                    + " pour explorer les répartitions ou évolutions "
                    "visibles. Vérifiez les axes et les périodes "
                    "avant de prendre une décision."
                )
                title = "Analyses disponibles"
            else:
                message = (
                    "Review the charts "
                    + ", ".join(chart_titles[:3])
                    + " to explore the displayed distributions or trends. "
                    "Check axes and periods before making decisions."
                )
                title = "Available analyses"

            insights.append({
                "tag": "ANALYSIS",
                "title": title,
                "text": message,
                "confidence": 100,
            })

        if french:
            summary = (
                f"{len(kpis)} KPI(s) et {len(charts)} graphique(s) "
                "ont été générés. Les insights détaillés du modèle "
                "ne sont pas disponibles pour cette exécution."
            )
        else:
            summary = (
                f"{len(kpis)} KPI(s) and {len(charts)} chart(s) "
                "were generated. Detailed model insights are unavailable "
                "for this run."
            )

        return {
            "summary": summary,
            "insights": insights,
        }

    # ---------------------------------------------------------
    # Exécution du plan
    # ---------------------------------------------------------

    def _execute(self, df, raw_plan):
        """Normalise puis exécute le plan BI avec traces de diagnostic."""

        print("\n[BI TRACE] ===== DIAGNOSTIC DASHBOARD =====")

        raw_charts = raw_plan.get("charts") or []
        print("[BI TRACE] Graphiques proposés par le LLM :", len(raw_charts))

        for chart in raw_charts:
            print("[BI TRACE] Graphique brut :", chart)

        plan, normalization_errors = eng.normalize_plan(raw_plan)

        normalized_charts = plan.get("charts") or []
        print("[BI TRACE] Graphiques après normalisation :", len(normalized_charts))

        if normalization_errors:
            print("[BI TRACE] Erreurs de normalisation :", normalization_errors)

        result, execution_errors = eng.run_plan(df, plan)

        result_charts = result.get("charts") or []
        print("[BI TRACE] Graphiques réellement calculés :", len(result_charts))

        for chart in result_charts:
            print(
                "[BI TRACE] Résultat graphique :",
                chart.get("title", "Sans titre")
                if isinstance(chart, dict)
                else str(chart),
            )

        if execution_errors:
            print("[BI TRACE] Erreurs d'exécution :", execution_errors)

        print("[BI TRACE] ===== FIN DIAGNOSTIC =====\n")

        errors = list(normalization_errors or [])
        errors.extend(list(execution_errors or []))

        return plan, result, errors

    # ---------------------------------------------------------
    # Construction du dashboard
    # ---------------------------------------------------------

    def build_dashboard(
        self,
        df_raw: pd.DataFrame,
        language: str = "English",
        currency: str = None,
    ) -> dict:
        """Construit trois dashboards spécialisés avec le LLM."""

        if not isinstance(df_raw, pd.DataFrame):
            raise TypeError("df_raw doit être un pandas DataFrame.")

        if df_raw.empty:
            raise ValueError("Le dataset est vide.")

        df = eng.coerce_types(df_raw)
        profile = eng.profile_dataset(df, max_cat_values=4)

        dashboard_specs = [
            {
                "id": "overview",
                "title": "Vue d'ensemble",
                "focus": "overview",
            },
            {
                "id": "comparison",
                "title": "Analyse comparative",
                "focus": "comparison",
            },
            {
                "id": "trends",
                "title": "Tendances et patterns",
                "focus": "trends",
            },
        ]

        dashboards = []
        all_errors = []
        repair_attempts = []

        for spec in dashboard_specs:
            print(
                f"\n[BI TRACE] Génération du dashboard : "
                f"{spec['title']}"
            )

            dashboard_errors = []
            plan = {}
            result = {"kpis": [], "charts": []}

            try:
                raw_plan = self._plan(
                    profile=profile,
                    language=language,
                    currency=currency,
                    dashboard_focus=spec["focus"],
                )

                if not isinstance(raw_plan, dict):
                    raise ValueError(
                        "Le LLM n'a pas retourné un plan JSON valide."
                    )

                if not raw_plan.get("charts"):
                    print(
                        "[BI TRACE] Aucun graphique proposé. "
                        "Tentative de complétion par le LLM."
                    )

                    completed = self._complete_missing_charts(
                        profile,
                        raw_plan,
                        language,
                        currency,
                    )

                    if isinstance(completed, dict):
                        raw_plan = completed

                plan, result, errors = self._execute(df, raw_plan)
                dashboard_errors.extend(errors or [])

                if dashboard_errors:
                    try:
                        repaired_plan = self._repair(
                            profile,
                            raw_plan,
                            dashboard_errors,
                            language,
                            currency,
                        )

                        new_plan, new_result, new_errors = self._execute(
                            df,
                            repaired_plan,
                        )

                        old_chart_count = len(result.get("charts") or [])
                        new_chart_count = len(new_result.get("charts") or [])

                        if (
                            new_chart_count >= old_chart_count
                            and len(new_errors or [])
                            <= len(dashboard_errors)
                        ):
                            plan = new_plan
                            result = new_result
                            dashboard_errors = list(new_errors or [])

                        repair_attempts.append({
                            "dashboard": spec["title"],
                            "errors": list(dashboard_errors),
                        })

                    except Exception as repair_exc:
                        dashboard_errors.append(
                            f"Réparation impossible : {repair_exc}"
                        )

                try:
                    generated = self._insights(
                        result,
                        plan,
                        language,
                    )
                    normalized = self._normalize_insights(generated)

                    if (
                        not normalized.get("summary")
                        or not normalized.get("insights")
                    ):
                        fallback = self._fallback_insights(
                            result,
                            language,
                        )

                        if not normalized.get("summary"):
                            normalized["summary"] = fallback.get(
                                "summary", ""
                            )

                        if not normalized.get("insights"):
                            normalized["insights"] = fallback.get(
                                "insights", []
                            )

                except Exception as insight_exc:
                    print(
                        "[BI TRACE] Échec des insights :",
                        repr(insight_exc),
                    )
                    normalized = self._fallback_insights(
                        result,
                        language,
                    )

                dashboard = {
                    "id": spec["id"],
                    "title": spec["title"],
                    "focus": spec["focus"],
                    "summary": normalized.get("summary", ""),
                    "insights": normalized.get("insights", []),
                    "kpis": result.get("kpis") or [],
                    "charts": result.get("charts") or [],
                    "errors": dashboard_errors,
                    "business_context": plan.get(
                        "business_context", ""
                    ),
                    "derived_columns": plan.get(
                        "derived_columns", []
                    ),
                }

                dashboards.append(dashboard)
                all_errors.extend(
                    f"{spec['title']} : {error}"
                    for error in dashboard_errors
                )

                print(
                    f"[BI TRACE] {spec['title']} : "
                    f"{len(dashboard['kpis'])} KPIs, "
                    f"{len(dashboard['charts'])} graphiques."
                )

            except Exception as exc:
                message = f"{spec['title']} : {exc}"
                print("[BI TRACE] Erreur :", message)
                all_errors.append(message)

                dashboards.append({
                    "id": spec["id"],
                    "title": spec["title"],
                    "focus": spec["focus"],
                    "summary": "",
                    "insights": [],
                    "kpis": [],
                    "charts": [],
                    "errors": [str(exc)],
                    "business_context": "",
                    "derived_columns": [],
                })

        primary = dashboards[0]

        return {
            "dashboards": dashboards,
            "summary": primary["summary"],
            "insights": primary["insights"],
            "kpis": primary["kpis"],
            "charts": primary["charts"],
            "errors": all_errors,
            "business_context": primary["business_context"],
            "derived_columns": primary["derived_columns"],
            "repair_attempts": repair_attempts,
            "total_rows": len(df),
        }
