"""
Rendu partagé (page BI Analysis + vues demandées depuis le chat).
Reçoit les KPIs / graphiques calculés par le moteur et les affiche, quel que soit leur type.
"""
from html import escape

import altair as alt
import streamlit as st

from components import html, kpi, bar, donut


def fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def format_number(value: float, kind: str, unit: str) -> str:
    unit = unit or ""
    if kind == "percent":
        return f"{value:,.1f}%"
    s = f"{value:,.0f}" if (kind == "integer" or abs(value) >= 100_000) else f"{value:,.2f}"
    return f"{unit}{s}" if kind == "currency" else f"{s} {unit}".strip()


def kpi_texts(k: dict):
    """(valeur affichée, ligne de détail). Un libellé trop long pour la carte passe en détail
    et la carte affiche le chiffre associé."""
    detail = k.get("detail") or k["subtitle"]
    label = k.get("value_text")
    if label and len(label) <= 16:
        return label, detail
    if label:
        return format_number(k["value"], k["format"], k["unit"]), f"{label} · {detail}".strip(" ·")
    return format_number(k["value"], k["format"], k["unit"]), detail


def render_kpis(kpis: list) -> None:
    if not kpis:
        return
    per_row = -(-len(kpis) // -(-len(kpis) // 4))      # répartition équilibrée (5 -> 3+2, 6 -> 3+3)
    for i in range(0, len(kpis), per_row):
        row = kpis[i:i + per_row]
        for col, k in zip(st.columns(max(len(row), 3)), row):
            with col:
                value_txt, detail_txt = kpi_texts(k)
                html(kpi(k["title"], value_txt, detail_txt, k["icon"], "blue", "blue"))


def render_chart(c: dict) -> None:
    data, t = c["data"], c["type"]

    if t == "table":
        st.dataframe(data.rename(columns={"x": c["x_label"], "value": c["y_label"]}),
                     use_container_width=True, hide_index=True)
        return

    if t == "donut":
        total = data["value"].sum()
        pct = round(data["value"].iloc[0] / total * 100) if total else 0
        rows = "".join(
            f'<p style="margin:.2rem 0">● {escape(str(r.x))} <b style="float:right">{fmt(r.value)} '
            f'({r.value / total * 100:.1f}%)</b></p>' for r in data.itertuples())
        html(f'<div style="display:flex;gap:2rem;align-items:center">{donut(pct, "#4f46e5", size=130)}'
             f'<div style="flex:1">{rows}</div></div>')
        return

    if t == "scatter":
        tip = [alt.Tooltip("x:Q", format=",.2f"), alt.Tooltip("y:Q", format=",.2f")]
        if "label" in data.columns:
            tip.insert(0, alt.Tooltip("label:N"))
        ch = (alt.Chart(data).mark_circle(size=60, opacity=0.6)
              .encode(x=alt.X("x:Q", title=c["x_label"]), y=alt.Y("y:Q", title=c["y_label"]), tooltip=tip)
              .interactive().properties(height=300))
        st.altair_chart(ch, use_container_width=True)
        return

    # bar / histogram / line / area
    tooltip = [alt.Tooltip("x", title=c["x_label"]), alt.Tooltip("value:Q", format=",.2f", title=c["y_label"])]
    color = {}
    if c["has_series"]:
        color = {"color": alt.Color("series:N", title=c.get("series_label"))}
        tooltip.insert(1, alt.Tooltip("series:N"))

    horizontal = (t == "bar" and not c["is_time"]
                  and (data["x"].nunique() > 6 or data["x"].astype(str).str.len().max() > 14))
    if horizontal:
        enc = {"y": alt.Y("x:N", sort=None, title=None), "x": alt.X("value:Q", title=c["y_label"])}
    elif c["is_time"]:
        enc = {"x": alt.X("x:T", title=c["x_label"]), "y": alt.Y("value:Q", title=c["y_label"])}
    else:
        enc = {"x": alt.X("x:N", sort=None, title=c["x_label"], axis=alt.Axis(labelAngle=-30)),
               "y": alt.Y("value:Q", title=c["y_label"])}

    base = alt.Chart(data)
    mark = {"line": base.mark_line(point=True), "area": base.mark_area(opacity=0.6)}.get(t, base.mark_bar())
    st.altair_chart(mark.encode(**enc, **color, tooltip=tooltip).properties(height=300),
                    use_container_width=True)


def render_chart_grid(charts: list) -> None:
    for i in range(0, len(charts), 2):
        row = charts[i:i + 2]
        for col, c in zip(st.columns(len(row)), row):
            with col:
                with st.container(border=True):
                    st.markdown(f"#### {c['title']}")
                    if c["subtitle"]:
                        st.caption(c["subtitle"])
                    render_chart(c)
                    if c["note"]:
                        st.caption(c["note"])
                    if c["reasoning"]:
                        with st.expander("🧠 Pourquoi ce graphique ?"):
                            st.write(c["reasoning"])


def insight_component(tag, title, text, conf) -> str:
    conf = int(conf) if str(conf).isdigit() else 90
    text = str(text).replace("**", "")      # le LLM met parfois les recommandations en **gras**
    return f'''<div class="bf-card"><span class="bf-badge blue" style="float:right">● {conf}% confidence</span>
      <small style="color:#4338ca"><b>{escape(str(tag))}</b></small><h3 style="font-size:1.1rem;margin:.5rem 0">{escape(str(title))}</h3>
      <p style="color:#64748b;font-size:.85rem">{escape(str(text))}</p>Confidence <b style="float:right">{conf}%</b>{bar(conf, "#075985")}
      </div>'''