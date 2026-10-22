"""
Moteur d'exécution GÉNÉRIQUE pour les dashboards pilotés par un LLM.

Aucune connaissance d'un dataset particulier : il profile n'importe quel DataFrame et exécute
de façon sûre (pas d'eval, pas de code généré) le plan déclaratif décidé par le LLM.
"""
import re
import warnings
import numpy as np
import pandas as pd

AGGREGATIONS = ["sum", "mean", "median", "min", "max", "count", "nunique"]
OPERATORS = [">", ">=", "<", "<=", "==", "!=", "in", "not_in", "not_null", "is_null", "contains"]
DERIVED_OPS = ["multiply", "add", "subtract", "divide",
               "year", "month", "year_month", "weekday", "hour", "date"]
TIME_GRAINS = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
CHART_TYPES = ["bar", "line", "area", "donut", "scatter", "histogram", "table"]
KPI_KINDS = ["aggregate", "ratio", "top_item"]
ADDITIVE = ("sum", "count")
MAX_POINTS = 60

DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d",
                "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y"]


# ----------------------------------------------------------------------------
# 1. Typage automatique + profilage
# ----------------------------------------------------------------------------
def _is_text(s: pd.Series) -> bool:
    # Compatible pandas 2 (object) et pandas 3 (dtype "str")
    return s.dtype == "object" or pd.api.types.is_string_dtype(s)


def coerce_types(df: pd.DataFrame, sample: int = 500) -> pd.DataFrame:
    """Convertit les colonnes texte en numérique / date quand c'est évident."""
    df = df.copy()
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s) \
                or pd.api.types.is_bool_dtype(s) or not _is_text(s):
            continue
        non_null = s.dropna()
        if non_null.empty:
            continue
        samp = non_null.sample(min(sample, len(non_null)), random_state=0).astype(str)

        if pd.to_numeric(samp, errors="coerce").notna().mean() > 0.95:
            converted = pd.to_numeric(s, errors="coerce")
            # on n'accepte la conversion que si AUCUNE valeur n'est perdue
            # (ex. des numéros de facture comme "C536379" ne doivent pas devenir NaN)
            if converted.notna().sum() == s.notna().sum():
                df[c] = converted
            continue

        if samp.str.contains(r"\d").mean() > 0.9:
            # on teste des formats explicites (évite l'ambiguïté jour/mois) puis le format libre
            best_fmt, best_rate = None, 0.0
            for f in DATE_FORMATS:
                rate = pd.to_datetime(samp, format=f, errors="coerce").notna().mean()
                if rate > best_rate:
                    best_fmt, best_rate = f, rate
            converted = None
            if best_rate > 0.9:
                converted = pd.to_datetime(s, format=best_fmt, errors="coerce")
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if pd.to_datetime(samp, errors="coerce").notna().mean() > 0.9:
                        converted = pd.to_datetime(s, errors="coerce")
            if converted is not None and converted.notna().sum() >= 0.99 * s.notna().sum():
                df[c] = converted
    return df


def _num(v):
    return None if pd.isna(v) else float(round(float(v), 4))


def _unusual_values(s: pd.Series, max_items: int = 10):
    """
    Pour les colonnes de type "code" (ex. références produit), repère les valeurs dont le FORMAT
    est très minoritaire (ex. 'POST', 'BANK CHARGES' parmi des codes numériques). Souvent des lignes
    qui ne sont pas des articles (frais, ajustements...). Totalement générique : on compare des formats.
    """
    vc = s.dropna().astype(str).value_counts()
    if len(vc) < 20 or len(vc) > 50000:
        return None
    sig = pd.Series([re.sub(r"(.)\1+", r"\1", re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", v)))
                     for v in vc.index], index=vc.index)
    shares = sig.value_counts(normalize=True)
    if "9" not in shares.index[0] or shares.iloc[0] < 0.5:      # colonne "code" : format dominant avec chiffres
        return None
    rare = shares[shares < 0.02].index
    odd = vc[sig.isin(rare)]
    if odd.empty:
        return None
    return {"dominant_format": shares.index[0], "n_unusual_values": int(len(odd)),
            "rows_affected": int(odd.sum()), "examples": {k: int(v) for k, v in odd.head(max_items).items()}}


def profile_dataset(df: pd.DataFrame, max_cat_values: int = 6) -> dict:
    """Résumé statistique compact et générique, destiné au LLM."""
    cols = []
    for c in df.columns:
        s = df[c]
        info = {"name": c, "dtype": str(s.dtype),
                "null_pct": round(float(s.isna().mean() * 100), 2),
                "n_unique": int(s.nunique(dropna=True))}
        if pd.api.types.is_datetime64_any_dtype(s):
            info.update(kind="datetime", min=str(s.min()), max=str(s.max()))
        elif pd.api.types.is_numeric_dtype(s):
            info.update(kind="numeric", min=_num(s.min()), max=_num(s.max()),
                        mean=_num(s.mean()), median=_num(s.median()),
                        p01=_num(s.quantile(0.01)), p99=_num(s.quantile(0.99)),
                        negatives=int((s < 0).sum()), zeros=int((s == 0).sum()))
        else:
            info["kind"] = "categorical"
            info["top_values"] = {str(k): int(v) for k, v in s.value_counts().head(max_cat_values).items()}
            odd = _unusual_values(s)
            if odd:
                info["unusual_values"] = odd
        info["examples"] = s.dropna().astype(str).unique()[:2].tolist()
        cols.append(info)
    return {"n_rows": int(len(df)), "n_columns": int(df.shape[1]),
            "duplicate_rows": int(df.duplicated().sum()), "columns": cols}


# ----------------------------------------------------------------------------
# 2. Filtres et colonnes dérivées (déclaratifs, sans eval)
# ----------------------------------------------------------------------------
def _coerce_value(series, value):
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(value)
    if pd.api.types.is_numeric_dtype(series):
        return float(value)
    return str(value)


def apply_filters(df: pd.DataFrame, filters) -> pd.DataFrame:
    if not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for f in filters:
        col, op, val = f.get("column"), f.get("operator"), f.get("value")
        if col not in df.columns:
            raise ValueError(f"filter column '{col}' does not exist")
        if op not in OPERATORS:
            raise ValueError(f"unknown filter operator '{op}' (allowed: {OPERATORS})")
        s = df[col]
        if op == "not_null":
            m = s.notna()
        elif op == "is_null":
            m = s.isna()
        elif op in ("in", "not_in"):
            vals = val if isinstance(val, list) else [val]
            m = s.isin([_coerce_value(s, v) for v in vals])
            if op == "not_in":
                m = ~m
        elif op == "contains":
            m = s.astype(str).str.contains(str(val), case=False, na=False, regex=False)
        else:
            v = _coerce_value(s, val)
            m = {">": lambda: s > v, ">=": lambda: s >= v, "<": lambda: s < v,
                 "<=": lambda: s <= v, "==": lambda: s == v, "!=": lambda: s != v}[op]()
        mask &= m.fillna(False)
    return df[mask]


def add_derived_columns(df: pd.DataFrame, derived) -> pd.DataFrame:
    if not derived:
        return df
    df = df.copy()
    for d in derived:
        name, op, cols = d.get("name"), d.get("operation"), d.get("columns") or []
        if not name:
            raise ValueError("derived column without a name")
        if name in df.columns:
            raise ValueError(f"derived column '{name}' already exists, choose another name")
        if op not in DERIVED_OPS:
            raise ValueError(f"unknown derived operation '{op}' (allowed: {DERIVED_OPS})")
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"derived column '{name}': source column '{c}' does not exist")

        if op in ("multiply", "add", "subtract", "divide"):
            if len(cols) != 2:
                raise ValueError(f"'{op}' needs exactly 2 columns")
            a = pd.to_numeric(df[cols[0]], errors="coerce")
            b = pd.to_numeric(df[cols[1]], errors="coerce")
            df[name] = {"multiply": lambda: a * b, "add": lambda: a + b,
                        "subtract": lambda: a - b,
                        "divide": lambda: a / b.replace(0, np.nan)}[op]()
        else:
            if len(cols) != 1:
                raise ValueError(f"'{op}' needs exactly 1 column")
            dt = pd.to_datetime(df[cols[0]], errors="coerce")
            if op == "year":
                df[name] = dt.dt.year
            elif op == "month":
                df[name] = dt.dt.month
            elif op == "year_month":
                df[name] = dt.dt.to_period("M").astype(str)
            elif op == "weekday":
                df[name] = dt.dt.day_name()
            elif op == "hour":
                df[name] = dt.dt.hour
            else:
                df[name] = dt.dt.normalize()
    return df


# ----------------------------------------------------------------------------
# 3. Utilitaires d'agrégation
# ----------------------------------------------------------------------------
def _require_col(df, col, role):
    if not col or col not in df.columns:
        raise ValueError(f"{role} column '{col}' does not exist")


def _values_for(d, y, agg):
    if agg not in AGGREGATIONS:
        raise ValueError(f"unknown aggregation '{agg}' (allowed: {AGGREGATIONS})")
    if agg == "count" or y is None:
        return pd.Series(1, index=d.index), "sum"
    if agg == "nunique":
        return d[y], "nunique"
    vals = pd.to_numeric(d[y], errors="coerce")
    if vals.notna().sum() == 0:
        raise ValueError(f"column '{y}' is not numeric, cannot apply '{agg}'")
    return vals, agg


def _int_like(s: pd.Series) -> pd.Series:
    """14646.0 -> 14646 (identifiants stockés en float à cause des NaN)."""
    if pd.api.types.is_float_dtype(s):
        nn = s.dropna()
        if len(nn) and (nn == nn.round()).all():
            return s.astype("Int64")
    return s


def _label_map(d, key_col, label_col):
    """clé -> libellé le plus fréquent (ex. code produit -> description)."""
    tmp = pd.DataFrame({"k": _int_like(d[key_col]).astype(str), "l": d[label_col]}).dropna(subset=["l"])
    tmp["l"] = tmp["l"].astype(str).str.strip()
    cnt = tmp.groupby(["k", "l"]).size().reset_index(name="n").sort_values("n", ascending=False).drop_duplicates("k")
    return dict(zip(cnt["k"], cnt["l"]))


def _relabel(keys: pd.Series, mapping: dict) -> pd.Series:
    """Remplace les clés par leurs libellés ; si deux clés partagent un libellé, on ajoute la clé pour les distinguer."""
    uk = pd.Series(pd.unique(keys))
    lab = uk.map(lambda k: mapping.get(k, k))
    dup = lab.duplicated(keep=False)
    lab = lab.where(~dup, lab + " (" + uk + ")")
    return keys.map(dict(zip(uk, lab)))


def _agg_scalar(df, spec, allow_empty=False):
    """Une agrégation unique sur tout le DataFrame, avec filtres optionnels."""
    d = apply_filters(df, spec.get("filters"))
    agg = spec.get("aggregation") or "sum"
    col = spec.get("column") or None
    if agg not in AGGREGATIONS:
        raise ValueError(f"unknown aggregation '{agg}' (allowed: {AGGREGATIONS})")
    if col is not None:
        _require_col(d, col, "KPI")
    if d.empty:
        if allow_empty:
            return 0.0
        raise ValueError("no rows left after KPI filters")

    if agg == "count":
        value = float(d[col].notna().sum()) if col else float(len(d))
    elif agg == "nunique":
        if col is None:
            raise ValueError("nunique needs a column")
        value = float(d[col].nunique())
    else:
        if col is None:
            raise ValueError(f"'{agg}' needs a column")
        s = pd.to_numeric(d[col], errors="coerce")
        if s.notna().sum() == 0:
            raise ValueError(f"column '{col}' is not numeric, cannot apply '{agg}'")
        value = float(getattr(s, agg)())
    if pd.isna(value):
        raise ValueError("metric evaluates to NaN")
    return abs(value) if spec.get("absolute") else value


# ----------------------------------------------------------------------------
# 4. KPIs : aggregate / ratio / top_item
# ----------------------------------------------------------------------------
def execute_kpi(df: pd.DataFrame, spec: dict) -> dict:
    kind = spec.get("kind") or "aggregate"
    if kind not in KPI_KINDS:
        raise ValueError(f"unknown KPI kind '{kind}' (allowed: {KPI_KINDS})")

    out = {"title": spec.get("title", "Metric"), "subtitle": spec.get("subtitle", ""),
           "icon": spec.get("icon", "📊"), "format": spec.get("format", "decimal"),
           "unit": spec.get("unit", ""), "reasoning": spec.get("reasoning", ""),
           "value_text": None, "detail": ""}

    if kind == "top_item":
        d = apply_filters(df, spec.get("filters"))
        if d.empty:
            raise ValueError("no rows left after KPI filters")
        dim = spec.get("dimension")
        _require_col(d, dim, "dimension")
        col = spec.get("column") or None
        if col:
            _require_col(d, col, "KPI")
        agg = spec.get("aggregation") or ("count" if col is None else "sum")
        k = max(1, min(int(spec.get("top_n") or 5), 10))
        values, how = _values_for(d, col, agg)
        g = values.groupby(_int_like(d[dim])).agg(how).dropna().sort_values(ascending=False)
        if g.empty:
            raise ValueError("top_item aggregation returned no data")
        labels = [str(i) for i in g.index[:k]]
        if spec.get("label_column"):
            _require_col(d, spec["label_column"], "label_column")
            mapping = _label_map(d, dim, spec["label_column"])
            labels = [mapping.get(l, l) for l in labels]
        out["value"] = float(g.iloc[0])
        out["value_text"] = labels[0]
        parts = []
        if how == "sum" and g.sum() > 0:
            parts.append(f"{g.iloc[0] / g.sum() * 100:.1f}% of total")
        if len(labels) > 1:
            parts.append("then " + ", ".join(labels[1:]))
        out["detail"] = " · ".join(parts)
        return out

    if kind == "ratio":
        num = spec.get("numerator")
        den = spec.get("denominator")
        if not isinstance(num, dict) or not isinstance(den, dict):
            raise ValueError("ratio KPI needs 'numerator' and 'denominator' objects")
        if apply_filters(df, num.get("filters")).empty:
            raise ValueError("ratio numerator matches no rows. If it concerns rows that the cleaning step removed "
                             "(e.g. returns), set \"scope\": \"all_rows\" on this KPI and give it its own filters; "
                             "otherwise choose another KPI")
        dcol = den.get("column")
        if den.get("aggregation") in ("nunique", "count") and dcol in df.columns:
            nd = apply_filters(df, num.get("filters"))
            null_share = float(nd[dcol].isna().mean()) if len(nd) else 0.0
            guarded = any(f.get("column") == dcol and f.get("operator") == "not_null"
                          for f in (num.get("filters") or []))
            if null_share > 0.01 and not guarded:
                raise ValueError(
                    f"ratio populations differ: {null_share:.0%} of the numerator rows have a null '{dcol}', but the "
                    f"denominator only counts non-null '{dcol}', which inflates the result. Add the filter "
                    f"{{\"column\": \"{dcol}\", \"operator\": \"not_null\"}} to the numerator (and the denominator) "
                    "so both cover the same rows")
        n = _agg_scalar(df, num, allow_empty=True)
        m = _agg_scalar(df, den)
        if m == 0:
            raise ValueError("ratio denominator is 0")
        value = n / m * float(spec.get("scale", 1))
    else:
        value = _agg_scalar(df, spec)

    if out["format"] == "percent" and not (0 <= value <= 100):
        raise ValueError(f"KPI '{out['title']}' has format 'percent' but evaluates to {value:,.2f}, outside 0-100. "
                         "A rate must be a ratio: use kind 'ratio' with scale 100 (numerator / denominator). "
                         "A raw count or sum must not use the 'percent' format")
    out["value"] = float(value)
    return out


# ----------------------------------------------------------------------------
# 5. Graphiques
# ----------------------------------------------------------------------------
def execute_chart(df: pd.DataFrame, spec: dict) -> dict:
    ctype = spec.get("type")
    if ctype not in CHART_TYPES:
        raise ValueError(f"unknown chart type '{ctype}' (allowed: {CHART_TYPES})")

    d = apply_filters(df, spec.get("filters"))
    if d.empty:
        raise ValueError("no rows left after chart filters")

    x = spec.get("x")
    y = spec.get("y") or None
    if isinstance(y, str) and y.lower() in ("null", "none", ""):
        y = None
    agg = spec.get("aggregation") or ("count" if y is None else "sum")
    _require_col(d, x, "x")
    if y is not None:
        _require_col(d, y, "y")
    top_n = max(1, min(int(spec.get("top_n") or (6 if ctype == "donut" else 10)), 30))
    sort = str(spec.get("sort") or "desc").lower()
    y_label = f"{agg} of {y}" if y and agg != "count" else ("rows" if agg == "count" else agg)

    base = {"type": ctype, "title": spec.get("title", "Chart"), "subtitle": spec.get("subtitle", ""),
            "reasoning": spec.get("reasoning", ""), "x_label": x, "y_label": y_label,
            "is_time": False, "has_series": False, "note": ""}

    # ---- histogramme -------------------------------------------------------
    if ctype == "histogram":
        s = pd.to_numeric(d[x], errors="coerce").dropna().astype(float)
        if s.empty:
            raise ValueError(f"column '{x}' is not numeric, cannot build a histogram")
        base["stats"] = {"min": round(float(s.min()), 4), "max": round(float(s.max()), 4),
                         "median": round(float(s.median()), 4),
                         "pct_negative": round(float((s < 0).mean() * 100), 2),
                         "pct_zero": round(float((s == 0).mean() * 100), 2)}
        lo, hi = s.quantile([0.01, 0.99])
        s = s[(s >= lo) & (s <= hi)] if hi > lo else s
        counts, edges = np.histogram(s, bins=min(20, max(5, int(np.sqrt(len(s))))))
        labels = [f"{edges[i]:,.4g} – {edges[i + 1]:,.4g}" for i in range(len(counts))]
        base.update(data=pd.DataFrame({"x": labels, "value": counts}), y_label="rows",
                    note="Values between the 1st and 99th percentile (outliers hidden).")
        return base

    # ---- nuage de points ---------------------------------------------------
    if ctype == "scatter":
        if y is None:
            raise ValueError("scatter needs both x and y numeric columns")
        xs = pd.to_numeric(d[x], errors="coerce")
        ys = pd.to_numeric(d[y], errors="coerce")
        group = spec.get("group_by")
        if group:
            _require_col(d, group, "group_by")
            tmp = pd.DataFrame({"label": _int_like(d[group]).astype(str), "x": xs, "y": ys}).dropna()
            ok = ("sum", "mean", "median", "min", "max")
            yhow = agg if agg in ok else "sum"
            xhow = spec.get("x_aggregation") if spec.get("x_aggregation") in ok else yhow
            data = tmp.groupby("label").agg(x=("x", xhow), y=("y", yhow)).reset_index()
            data = data.sort_values("y", ascending=False)
            shown = min(len(data), 300)
            full_len = len(data)
            base["note"] = (f"One point per {group} (x: {xhow}, y: {yhow})"
                            + (f"; the {shown} largest of {full_len:,} shown." if full_len > 300 else "."))
            data = data.head(300)
            base["x_label"] = f"{xhow} of {x}"
            base["y_label"] = f"{yhow} of {y}"
        else:
            data = pd.DataFrame({"x": xs, "y": ys}).dropna()
            if len(data) > 2000:
                data = data.sample(2000, random_state=0)
                base["note"] = "Random sample of 2,000 rows."
            base["y_label"] = y
        if data.empty:
            raise ValueError("scatter has no numeric data")
        base["data"] = data.reset_index(drop=True)
        return base

    # ---- bar / line / area / donut / table ---------------------------------
    is_time = pd.api.types.is_datetime64_any_dtype(d[x])
    x_numeric = (not is_time) and pd.api.types.is_numeric_dtype(d[x])
    if is_time:
        grain = spec.get("time_grain") if spec.get("time_grain") in TIME_GRAINS else "month"
        xs = d[x].dt.to_period(TIME_GRAINS[grain]).dt.to_timestamp()
        base["note"] = f"Grouped by {grain}."
        base["grain"] = grain
    elif x_numeric:
        xs = d[x]                      # on garde le numérique pour trier correctement (2 avant 10)
    else:
        xs = d[x].astype(str)
    xs = xs.rename("x")

    # ordre naturel de x : séries temporelles, lignes/aires, ou demandé explicitement
    natural = is_time or ctype in ("line", "area") or sort in ("x", "x_asc", "natural", "chronological")
    ascending = sort in ("asc", "value_asc")

    series_col = spec.get("series") or spec.get("group_by")
    ss = None
    if series_col and series_col != x and ctype in ("bar", "line", "area"):
        _require_col(d, series_col, "series")
        ss = _int_like(d[series_col]).astype(str).rename("series")

    values, how = _values_for(d, y, agg)
    keys = [xs] + ([ss] if ss is not None else [])
    data = values.groupby(keys).agg(how).rename("value").reset_index()
    data = data.dropna(subset=["value"])
    if data.empty:
        raise ValueError("aggregation returned no data")

    if ss is None:
        if how == "sum":                                   # total de TOUTES les catégories (avant top_n)
            base["total_all"] = float(data["value"].sum())
            base["n_categories"] = int(len(data))
        if natural:
            if not is_time and len(data) > MAX_POINTS:
                data = data.nlargest(MAX_POINTS, "value")
            data = data.sort_values("x")
        else:
            data = data.sort_values("value", ascending=ascending)
            if len(data) > top_n:
                head = data.head(top_n)
                if ctype == "donut" and how == "sum":
                    covered = data["value"].head(top_n).sum() / data["value"].sum() if data["value"].sum() else 0
                    if covered < 0.6:
                        raise ValueError(
                            f"a donut of '{x}' is not readable: the top {top_n} of {len(data):,} categories cover only "
                            f"{covered:.0%} of the total (long tail). Use a bar chart for the ranking instead, or a donut "
                            "on a dimension with few categories")
                    other = data["value"].iloc[top_n:].sum()
                    head = pd.concat([head, pd.DataFrame({"x": ["Other"], "value": [other]})])
                data = head
    else:
        totals = data.groupby("x")["value"].sum()
        if natural:
            keep_x = totals.index if (is_time or len(totals) <= MAX_POINTS) else totals.nlargest(MAX_POINTS).index
        else:
            keep_x = totals.sort_values(ascending=ascending).head(top_n).index
        n_series_total = data["series"].nunique()
        top_series = data.groupby("series")["value"].sum().sort_values(ascending=False).head(5).index
        if n_series_total > 5:
            base["note"] = (base["note"] + " " if base["note"] else "") + \
                f"Top 5 of {n_series_total} {series_col} values shown; the others are omitted."
        data = data[data["x"].isin(keep_x) & data["series"].isin(top_series)]
        if natural:
            data = data.sort_values(["x", "series"])
        else:
            order = totals.rank(ascending=ascending, method="first")
            data = data.assign(_o=data["x"].map(order)).sort_values(["_o", "series"]).drop(columns="_o")
        base["has_series"] = True
        base["series_label"] = series_col

    data = data.reset_index(drop=True)
    if x_numeric:                      # étiquettes propres : 14646.0 -> 14646 (ordre déjà fixé)
        data["x"] = _int_like(data["x"]).astype(str)
    if spec.get("label_column") and not is_time:
        _require_col(d, spec["label_column"], "label_column")
        data["x"] = _relabel(data["x"], _label_map(d, x, spec["label_column"]))
        base["x_label"] = spec["label_column"]
    base.update(data=data, is_time=is_time)
    return base


# ----------------------------------------------------------------------------
# 6. Exécution complète d'un plan
# ----------------------------------------------------------------------------
def _clean_list(items, name, errors):
    """Garde uniquement les éléments de type objet (dict) ; signale le reste au LLM."""
    if items is None:
        return []
    if isinstance(items, dict):
        errors.append(f'"{name}" must be a list of objects, not a single object')
        return [items]
    if not isinstance(items, list):
        errors.append(f'"{name}" must be a list of objects, got {type(items).__name__}')
        return []
    out = []
    for i, it in enumerate(items):
        if isinstance(it, dict):
            out.append(it)
        else:
            errors.append(f'{name}[{i}] must be a JSON object, got {type(it).__name__}: {str(it)[:60]}')
    return out


def normalize_plan(plan):
    """
    Remet en forme un plan LLM mal formé (liste au lieu d'objet, filtres en texte...) sans jamais lever
    d'exception. Retourne (plan_normalisé, erreurs_lisibles_par_le_LLM).
    """
    errors = []
    if isinstance(plan, list):
        errors.append("the plan must be one JSON object, not a list")
        plan = next((p for p in plan if isinstance(p, dict)), {})
    if not isinstance(plan, dict):
        return {"cleaning": {"filters": []}, "derived_columns": [], "kpis": [], "charts": []}, \
               ["the plan must be one JSON object"]

    out = dict(plan)

    c = plan.get("cleaning")
    if isinstance(c, list):
        errors.append('"cleaning" must be an object {"reasoning": ..., "filters": [...]}, not a list')
        c = {"filters": c}
    elif not isinstance(c, dict):
        if c not in (None, "", []):
            errors.append('"cleaning" must be an object {"reasoning": ..., "filters": [...]}')
        c = {}
    c = dict(c)
    c["filters"] = _clean_list(c.get("filters"), "cleaning.filters", errors)
    c["reasoning"] = str(c.get("reasoning") or "")
    out["cleaning"] = c

    out["derived_columns"] = _clean_list(plan.get("derived_columns"), "derived_columns", errors)

    def fix_item(spec, label):
        spec = dict(spec)
        spec["filters"] = _clean_list(spec.get("filters"), f"{label}.filters", errors)
        for part in ("numerator", "denominator"):
            sub = spec.get(part)
            if sub is None:
                continue
            if not isinstance(sub, dict):
                errors.append(f'{label}.{part} must be a JSON object, got {type(sub).__name__}')
                spec[part] = None
            else:
                sub = dict(sub)
                sub["filters"] = _clean_list(sub.get("filters"), f"{label}.{part}.filters", errors)
                spec[part] = sub
        return spec

    out["kpis"] = [fix_item(k, f"kpis[{i}]") for i, k in enumerate(_clean_list(plan.get("kpis"), "kpis", errors))]
    out["charts"] = [fix_item(k, f"charts[{i}]") for i, k in enumerate(_clean_list(plan.get("charts"), "charts", errors))]
    return out, errors


def run_plan(df: pd.DataFrame, plan: dict):
    """
    Exécute le plan du LLM. Retourne (résultat, liste d'erreurs lisibles par le LLM).
    Le nettoyage s'applique par défaut à tous les KPIs/graphiques ; un élément peut déclarer
    "scope": "all_rows" pour travailler sur TOUTES les lignes (ex. taux de retour quand les retours
    ont été exclus du nettoyage).
    """
    plan, errors = normalize_plan(plan)
    rows_before = len(df)
    cleaning = plan.get("cleaning") or {}

    full = df
    try:
        full = add_derived_columns(df, plan.get("derived_columns"))
    except Exception as e:
        errors.append(f"derived_columns: {e}")

    work = full
    try:
        work = apply_filters(full, cleaning.get("filters"))
        if rows_before and len(work) < 0.3 * rows_before:
            errors.append(f"cleaning: the filters remove {100 - 100 * len(work) / rows_before:.0f}% "
                          "of the rows, which is too aggressive; make them more conservative")
            work = full
    except Exception as e:
        errors.append(f"cleaning: {e}")
        work = full

    kpis, charts = [], []
    for i, spec in enumerate(plan.get("kpis") or []):
        try:
            kpis.append(execute_kpi(full if spec.get("scope") == "all_rows" else work, spec))
        except Exception as e:
            errors.append(f"kpis[{i}] '{spec.get('title')}': {e}")
    for i, spec in enumerate(plan.get("charts") or []):
        try:
            charts.append(execute_chart(full if spec.get("scope") == "all_rows" else work, spec))
        except Exception as e:
            errors.append(f"charts[{i}] '{spec.get('title')}': {e}")

    if not kpis and not charts:
        errors.append("the plan produced no usable KPI or chart")

    return {"rows_before": rows_before, "rows_after": int(len(work)), "kpis": kpis, "charts": charts}, errors


def _fmt_ts(ts, grain="month") -> str:
    if grain in ("day", "week"):
        return ts.strftime("%Y-%m-%d")
    if grain == "quarter":
        return f"{ts.year}-Q{(ts.month - 1) // 3 + 1}"
    if grain == "year":
        return str(ts.year)
    return ts.strftime("%Y-%m")


def results_digest(result: dict, max_rows: int = 15) -> dict:
    """Résultats réellement calculés + parts/totaux/extrêmes PRÉ-CALCULÉS (le LLM ne fait aucun calcul)."""
    def rec(df, total=None, grain="month"):
        out = df.head(max_rows).copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]):
                out[c] = out[c].map(lambda t: _fmt_ts(t, grain))
            elif pd.api.types.is_float_dtype(out[c]):
                out[c] = out[c].round(2)
        if total and "value" in out.columns:
            out["share_pct"] = (out["value"] / total * 100).round(2)
        return out.to_dict("records")

    charts = []
    for c in result["charts"]:
        total = c.get("total_all")
        grain = c.get("grain", "month")
        data = c["data"]
        entry = {"title": c["title"], "type": c["type"], "x": c["x_label"], "measure": c["y_label"],
                 "data": rec(data, total, grain)}
        if total:
            shown = data if c["type"] != "donut" else data[data["x"] != "Other"]
            entry.update(total_all_categories=round(total, 2), n_categories=c["n_categories"],
                         shown_total=round(float(shown["value"].sum()), 2),
                         shown_share_pct=round(float(shown["value"].sum()) / total * 100, 2))
        if c.get("stats"):
            entry["distribution_stats"] = c["stats"]
        if c["is_time"] and len(data):
            entry["period"] = f"{_fmt_ts(data['x'].min(), grain)} to {_fmt_ts(data['x'].max(), grain)}"
        if not c["has_series"] and c["type"] not in ("scatter", "histogram") and len(data):
            def point(i):
                x = data.loc[i, "x"]
                return {"x": _fmt_ts(x, grain) if c["is_time"] else str(x), "value": round(float(data.loc[i, "value"]), 2)}
            entry.update(n_points=int(len(data)), highest=point(data["value"].idxmax()),
                         lowest=point(data["value"].idxmin()))
        charts.append(entry)

    kpis = []
    for k in result["kpis"]:
        e = {"title": k["title"], "value": round(k["value"], 2), "unit": k["unit"], "format": k["format"]}
        if k.get("value_text"):
            e.update(top_item=k["value_text"], detail=k["detail"])
        kpis.append(e)

    return {"rows_before_cleaning": result["rows_before"], "rows_after_cleaning": result["rows_after"],
            "kpis": kpis, "charts": charts}