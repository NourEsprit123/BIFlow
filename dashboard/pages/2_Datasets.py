<<<<<<< Updated upstream
from pathlib import Path
import sys
import json

import streamlit as st
from urllib.parse import quote


# ============================================================
# PATH
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# ============================================================
# UI COMPONENTS
# ============================================================

from components import (
    setup,
    page_header,
    btn,
    html,
    card,
    table,
    badge,
    bar,
)


# ============================================================
# ANALYTICS
# ============================================================

from analytics.dataset_loader import list_datasets
from analytics.profiler import profile_dataset
from analytics.data_quality import generate_quality_report


# ============================================================
# PERSISTENT ANALYSIS CACHE
# ============================================================

ANALYSIS_CACHE_FILE = (
    ROOT_DIR
    / "data"
    / "analysis_cache.json"
)


def load_analysis_cache():
    """
    Charge les analyses sauvegardées sur disque.
    """

    if not ANALYSIS_CACHE_FILE.exists():
        return {}

    try:
        with open(
            ANALYSIS_CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):
            return data

        return {}

    except Exception:
        return {}


def save_analysis_cache(cache):
    """
    Sauvegarde les analyses sur disque.
    """

    ANALYSIS_CACHE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        ANALYSIS_CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            cache,
            file,
            indent=4,
            ensure_ascii=False
        )


def get_persistent_key(file_path):
    """
    Génère une clé basée sur le chemin et la date
    de modification du fichier.

    Si le dataset est modifié, sa clé change et
    BIFlow considérera qu'une nouvelle analyse
    est nécessaire.
    """

    file_path = Path(file_path)

    try:
        modified = file_path.stat().st_mtime
    except FileNotFoundError:
        modified = 0

    return f"{file_path.resolve()}::{modified}"


# ============================================================
# PAGE SETUP
# ============================================================

setup("Datasets")


# ============================================================
# SESSION STATE
# ============================================================

if "dataset_analysis" not in st.session_state:
    st.session_state.dataset_analysis = load_analysis_cache()


if "last_uploaded_dataset" not in st.session_state:
    st.session_state.last_uploaded_dataset = None


if "last_upload_signature" not in st.session_state:
    st.session_state.last_upload_signature = None


# ============================================================
# HELPERS
# ============================================================

def fmt(value):
    return (
        f'<span class="mono" '
        f'style="color:#166534;'
        f'background:#dcfce7;'
        f'padding:.1rem .4rem;'
        f'border-radius:6px">'
        f'{value}'
        f'</span>'
    )


def format_size(size_bytes):

    if size_bytes < 1024:
        return f"{size_bytes} B"

    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"

    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"

    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def get_status(quality_score):

    if quality_score >= 90:
        return "● Ready", "green"

    if quality_score >= 70:
        return "● Needs attention", "amber"

    return "● Critical", "red"


def get_quality_color(quality_score):

    if quality_score >= 90:
        return "#10b981"

    if quality_score >= 70:
        return "#f59e0b"

    return "#ef4444"


def filter_chip(label, active=False):

    active_class = " on" if active else ""

    return (
        f'<span class="bf-chip{active_class}">'
        f'{label}'
        f'</span>'
    )


# ============================================================
# DATASET ANALYSIS
# ============================================================

def analyze_dataset(file_path):

    file_path = str(file_path)

    # --------------------------------------------------------
    # PROFILING
    # --------------------------------------------------------

    profile = profile_dataset(file_path)

    # --------------------------------------------------------
    # DATA QUALITY
    # --------------------------------------------------------

    quality = generate_quality_report(file_path)

    quality_score = float(
        quality["quality_score"]
    )

    status_text, status_type = get_status(
        quality_score
    )

    return {
        "rows": profile["rows"],
        "columns": profile["columns"],
        "quality": quality_score,
        "status_text": status_text,
        "status_type": status_type,
        "profile": profile,
        "quality_report": quality,
    }


def get_or_analyze_dataset(file_path):

    file_path = Path(file_path)

    key = get_persistent_key(file_path)

    # --------------------------------------------------------
    # EXISTING ANALYSIS
    # --------------------------------------------------------

    if key in st.session_state.dataset_analysis:

        return st.session_state.dataset_analysis[key]

    # --------------------------------------------------------
    # NEW ANALYSIS
    # --------------------------------------------------------

    with st.spinner(
        f"Analyzing {file_path.name}..."
    ):

        result = analyze_dataset(file_path)

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    st.session_state.dataset_analysis[key] = result

    # --------------------------------------------------------
    # PERSISTENCE
    # --------------------------------------------------------

    save_analysis_cache(
        st.session_state.dataset_analysis
    )

    return result


# ============================================================
# ============================================================
# HEADER
# ============================================================

page_header(
    "Datasets",
    "Manage, inspect, and streamline your business intelligence assets and data ingest pipelines.",
    btn("⟳ Refresh"),
    "Workspace › <b>Datasets</b>",
)


# ============================================================
# REAL STREAMLIT UPLOADER
# ============================================================

st.markdown(
    """
    <style>

    /* ======================================================
       POSITION DU FILE UPLOADER
       ====================================================== */

    div[data-testid="stFileUploader"] {
        width: 220px !important;

        margin-left: auto !important;
        margin-right: 0 !important;

        margin-top: 0.5rem !important;
        margin-bottom: 1.5rem !important;
    }


    /* ======================================================
       ZONE DU FILE UPLOADER
       ====================================================== */

    div[data-testid="stFileUploaderDropzone"] {
        width: 220px !important;

        min-height: 42px !important;

        padding: 0.35rem !important;

        border: 1px solid #c7d2fe !important;

        border-radius: 8px !important;

        background: #eef2ff !important;
    }


    /* ======================================================
       CACHER LA ZONE DRAG & DROP
       ====================================================== */

    div[data-testid="stFileUploaderDropzone"] > div:first-child {
        display: none !important;
    }


    /* ======================================================
       BOUTON NATIF STREAMLIT
       ====================================================== */

    div[data-testid="stFileUploader"] button {
        width: 100% !important;

        height: 42px !important;

        border-radius: 8px !important;

        border: none !important;

        background: #4f46e5 !important;

        color: white !important;

        font-weight: 600 !important;

        font-size: 0.9rem !important;

        cursor: pointer !important;
    }


    /* ======================================================
       HOVER
       ====================================================== */

    div[data-testid="stFileUploader"] button:hover {
        background: #4338ca !important;
    }


    /* ======================================================
       TEXTE NATIF DU BOUTON
       ====================================================== */

    div[data-testid="stFileUploader"] button span {
        color: white !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


uploaded_file = st.file_uploader(
    "Upload dataset",
    type=["csv", "xlsx", "xls"],
    label_visibility="collapsed",
    key="dataset_file_uploader",
)


# ============================================================
# HANDLE UPLOAD
# ============================================================

if uploaded_file is not None:

    # --------------------------------------------------------
    # CREATE SIGNATURE
    # --------------------------------------------------------

    upload_signature = (
        f"{uploaded_file.name}:"
        f"{uploaded_file.size}"
    )

    # --------------------------------------------------------
    # PROCESS ONLY NEW UPLOAD
    # --------------------------------------------------------

    if (
        st.session_state.last_upload_signature
        != upload_signature
    ):

        raw_dir = (
            ROOT_DIR
            / "data"
            / "raw"
        )

        raw_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        file_name = uploaded_file.name

        # ----------------------------------------------------
        # Protection contre .csv.csv
        # ----------------------------------------------------

        while file_name.lower().endswith(".csv.csv"):
            file_name = file_name[:-4]

        destination = raw_dir / file_name

        # ----------------------------------------------------
        # SAVE FILE
        # ----------------------------------------------------

        with open(
            destination,
            "wb"
        ) as file:

            file.write(
                uploaded_file.getbuffer()
            )

        st.session_state.last_uploaded_dataset = (
            str(destination)
        )

        st.session_state.last_upload_signature = (
            upload_signature
        )

        st.success(
            f"Dataset '{file_name}' uploaded successfully."
        )

        # ====================================================
        # AUTOMATIC ANALYSIS
        # ====================================================

        st.markdown(
            "### 🔎 Dataset Analysis"
        )

        try:

            with st.spinner(
                f"Analyzing {file_name}..."
            ):

                result = analyze_dataset(
                    destination
                )

                key = get_persistent_key(
                    destination
                )

                st.session_state.dataset_analysis[key] = (
                    result
                )

                # --------------------------------------------
                # PERSISTENT STORAGE
                # --------------------------------------------

                save_analysis_cache(
                    st.session_state.dataset_analysis
                )

            st.success(
                "Analysis completed successfully."
            )

            # ------------------------------------------------
            # METRICS
            # ------------------------------------------------

            col1, col2, col3 = st.columns(3)

            with col1:

                st.metric(
                    "Rows",
                    f"{result['rows']:,}"
                )

            with col2:

                st.metric(
                    "Columns",
                    f"{result['columns']:,}"
                )

            with col3:

                st.metric(
                    "Quality Score",
                    f"{result['quality']:.1f}%"
                )

            st.markdown(
                f"""
**Dataset:** `{file_name}`

**Status:** **{result['status_text']}**
"""
            )

        except Exception as error:

            st.error(
                f"Analysis failed for "
                f"'{file_name}': {error}"
            )


# ============================================================
# GET DATASETS
# ============================================================

datasets = list_datasets()

total_datasets = len(datasets)


# ============================================================
# CALCULATE DATASET STATISTICS
# ============================================================

ready_count = 0
attention_count = 0
critical_count = 0
not_analyzed_count = 0


for dataset_path in datasets:

    key = get_persistent_key(dataset_path)

    result = (
        st.session_state
        .dataset_analysis
        .get(key)
    )

    if result is None:

        not_analyzed_count += 1

    else:

        status_type = result["status_type"]

        if status_type == "green":

            ready_count += 1

        elif status_type == "amber":

            attention_count += 1

        elif status_type == "red":

            critical_count += 1


# ============================================================
# SEARCH + FILTER
# ============================================================

search_col, filter_col = st.columns(
    [1.3, 1]
)


with search_col:

    search = st.text_input(
        "Search",
        placeholder=(
            "🔍 Search datasets by title, "
            "tag, or owner"
        ),
        label_visibility="collapsed",
    )


with filter_col:

    filter_status = st.selectbox(
        "Filter",
        [
            "All",
            "Ready",
            "Needs attention",
            "Critical",
            "Not analyzed",
        ],
        label_visibility="collapsed",
    )


# ============================================================
# FILTER CHIPS
# ============================================================

filters = "".join(
    [
        filter_chip(
            f"All {total_datasets}",
            filter_status == "All"
        ),

        filter_chip(
            f"● Ready {ready_count}",
            filter_status == "Ready"
        ),

        filter_chip(
            f"● Needs attention {attention_count}",
            filter_status == "Needs attention"
        ),

        filter_chip(
            f"● Critical {critical_count}",
            filter_status == "Critical"
        ),

        filter_chip(
            f"● Processing {not_analyzed_count}",
            filter_status == "Not analyzed"
        ),
    ]
)


# ============================================================
# SEARCH / FILTER CARD
# ============================================================

search_card_html = f"""
<div style="
    display:flex;
    gap:1rem;
    align-items:center;
">

    <div
        class="bf-search"
        style="flex:.7"
    >

        🔍 Search datasets by title,
        tag, or owner

        <span>⌘ F</span>

    </div>

    <div>
        {filters}
    </div>

</div>
"""


html(
    card(
        search_card_html
    )
)


html("<br>")


# ============================================================
# BUILD TABLE
# ============================================================

trs = []


for dataset_path in datasets:

    dataset_name = dataset_path.name

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    if search:

        if search.lower() not in dataset_name.lower():
            continue

    # --------------------------------------------------------
    # GET ANALYSIS
    # --------------------------------------------------------

    key = get_persistent_key(dataset_path)

    result = (
        st.session_state
        .dataset_analysis
        .get(key)
    )

    # --------------------------------------------------------
    # NOT ANALYZED
    # --------------------------------------------------------

    if result is None:

        status_text = "● Not analyzed"

        status_type = "blue"

        rows_value = "—"

        columns_value = "—"

        quality_value = "<i>— Auditing</i>"

        last_analysis = "Not analyzed"

        description = (
            "Dataset available · "
            "Analysis pending"
        )

    # --------------------------------------------------------
    # ANALYZED
    # --------------------------------------------------------

    else:

        rows_value = f"{result['rows']:,}"

        columns_value = f"{result['columns']:,}"

        quality_score = float(
            result["quality"]
        )

        status_text = result["status_text"]

        status_type = result["status_type"]

        # ----------------------------------------------------
        # QUALITY COLOR
        # ----------------------------------------------------

        quality_color = get_quality_color(
            quality_score
        )

        # ----------------------------------------------------
        # QUALITY BAR
        # ----------------------------------------------------

        quality_bar = bar(
            quality_score,
            quality_color
        )

        quality_value = (
            f"<b>{quality_score:.1f}%</b> "
            f"{quality_bar}"
        )

        last_analysis = "Recently analyzed"

        if status_type == "green":

            description = (
                "Analysis completed · "
                "Dataset ready"
            )

        elif status_type == "amber":

            description = (
                "Data quality issues detected"
            )

        else:

            description = (
                "Critical quality issues detected"
            )

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    if (
        filter_status == "Ready"
        and status_type != "green"
    ):
        continue

    if (
        filter_status == "Needs attention"
        and status_type != "amber"
    ):
        continue

    if (
        filter_status == "Critical"
        and status_type != "red"
    ):
        continue

    if (
        filter_status == "Not analyzed"
        and result is not None
    ):
        continue

    # --------------------------------------------------------
    # FORMAT
    # --------------------------------------------------------

    extension = (
        dataset_path
        .suffix
        .upper()
        .replace(".", "")
    )

    # --------------------------------------------------------
    # TABLE ROW
    # --------------------------------------------------------

        # --------------------------------------------------------
    # TABLE ROW
    # --------------------------------------------------------

    dataset_url = (
        "/Data_Quality?dataset="
        + quote(str(dataset_path))
    )

    dataset_cell = (
        f"""
        <a href="{dataset_url}"
           target="_self"
           style="
               color:#0f172a;
               text-decoration:none;
               font-weight:700;
               display:block;
           ">

            {dataset_name}

        </a>

        <small>
            {description}
        </small>
        """
    )

    status_cell = badge(
        status_text,
        status_type
    )

    trs.append(
        [
            dataset_cell,
            fmt(extension),
            rows_value,
            columns_value,
            quality_value,
            last_analysis,
            status_cell,
        ]
    )

# ============================================================
# DATASET TABLE
# ============================================================

if trs:

    table_html = table(
        [
            "DATASET",
            "FORMAT",
            "ROWS",
            "COLUMNS",
            "QUALITY SCORE",
            "LAST ANALYSIS",
            "STATUS",
        ],
        trs
    )

    pagination_html = f"""
<div style="
    display:flex;
    justify-content:space-between;
    margin-top:1rem;
    color:#475569
">

    <span>
        Showing
        <b>{len(trs)}</b>
        of
        <b>{total_datasets}</b>
        datasets
    </span>

    <span>

        <span class="bf-chip">
            Previous
        </span>

        <span class="bf-chip on">
            1
        </span>

        <span class="bf-chip">
            Next
        </span>

    </span>

</div>
"""

    full_table_html = (
        table_html
        + pagination_html
    )

    html(
        card(
            full_table_html
        )
    )

else:

    empty_state_html = """
<div style="
    text-align:center;
    padding:2rem;
    color:#64748b;
">

    <div style="
        font-size:2rem
    ">
        📂
    </div>

    <h3 style="
        color:#0f172a
    ">
        No datasets found
    </h3>

    <p>
        No dataset matches
        your current filters.
    </p>

</div>
"""

    html(
        card(
            empty_state_html
        )
    )


html("<br>")


# ============================================================
# WORKSPACE STORAGE
# ============================================================

total_size = 0


for dataset_path in datasets:

    try:

        total_size += dataset_path.stat().st_size

    except FileNotFoundError:

        pass


total_size_gb = total_size / (1024 ** 3)


storage_percentage = min(
    100,
    (total_size_gb / 20) * 100
)


remaining_gb = max(
    0,
    20 - total_size_gb
)


# ------------------------------------------------------------
# PRE-CALCULATE COMPONENTS
# ------------------------------------------------------------

storage_status = badge(
    "Healthy",
    "green"
)

storage_bar = bar(
    storage_percentage,
    "#4f46e5"
)


storage = f"""
<div class="ch">

    <div>

        <h3>
            Workspace storage
        </h3>

        <div class="subt">
            Real-time analytical cache
            & blob storage limit
        </div>

    </div>

    {storage_status}

</div>


<div style="
    font-size:2.2rem;
    font-weight:700
">

    {total_size_gb:.2f} GB

    <small style="
        font-size:1rem;
        color:#64748b
    ">
        / 20 GB
    </small>

    <span style="
        float:right;
        font-size:.9rem;
        color:#4338ca
    ">
        {storage_percentage:.1f}%
        capacity used
    </span>

</div>


{storage_bar}


<p style="
    color:#64748b;
    font-size:.85rem
">

    {remaining_gb:.2f} GB remaining

    <b style="
        float:right;
        color:#0f172a
    ">
        Manage quota →
    </b>

</p>
"""


# ============================================================
# CONNECTED SOURCES
# ============================================================

connected_status = badge(
    "● All connectors synced",
    "blue"
)

add_source_button = btn(
    "+ Add source"
)


sources = f"""
<div class="ch">

    <div>

        <h3>
            Connected sources
        </h3>

        <div class="subt">
            Active connections &
            streaming endpoints
        </div>

    </div>

    {add_source_button}

</div>


<div style="
    font-size:2.2rem;
    font-weight:700
">

    {total_datasets} active

    {connected_status}

</div>


<div
    class="bf-box"
    style="margin-top:.8rem"
>

    📄 CSV uploads · Excel files ·
    Local datasets

</div>
"""


# ============================================================
# BOTTOM CARDS
# ============================================================

bottom_cards_html = f"""
<div class="bf-grid g2">

    {card(storage)}

    {card(sources)}

</div>
"""


html(
    bottom_cards_html
)
=======
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
import pandas as pd
from components import setup, page_header, html, card, table, badge, bar
from agents.data_engineering_agent import DataEngineeringAgent

setup("Datasets")

RAW_DIR = "data/raw"
CLEANED_DIR = "data/cleaned"
os.makedirs(RAW_DIR, exist_ok=True)

agent = DataEngineeringAgent()


@st.cache_data(ttl=300, show_spinner=False)
def get_audit(file_path: str):
    return agent.run_audit(file_path)


# ── Discover all datasets already in data/raw/ ──────────────────────────────
def list_raw_datasets():
    supported = (".csv", ".xlsx", ".xls", ".parquet")
    return [
        f for f in os.listdir(RAW_DIR)
        if f.lower().endswith(supported)
    ]


def list_cleaned_datasets():
    if not os.path.isdir(CLEANED_DIR):
        return []
    return sorted(
        f for f in os.listdir(CLEANED_DIR)
        if f.lower().endswith(".csv")
    )


# ── Upload section ────────────────────────────────────────────────────────────
page_header(
    "Datasets",
    "Manage, inspect, and streamline your business intelligence assets.",
    crumbs="Workspace › <b>Datasets</b>"
)

col_refresh, col_upload, col_space = st.columns([1, 1.5, 6])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_upload:
    show_upload = st.button("Upload dataset", type="primary", use_container_width=True)

# Upload expander triggered by button
if show_upload or st.session_state.get("show_upload_panel"):
    st.session_state["show_upload_panel"] = True
    with st.expander("Upload a new dataset", expanded=True):
        uploaded_file = st.file_uploader(
            "Drop a CSV, Excel, or Parquet file here",
            type=["csv", "xlsx", "xls", "parquet"],
            key="dataset_uploader"
        )
        if uploaded_file:
            save_path = os.path.join(RAW_DIR, uploaded_file.name)
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"Saved **{uploaded_file.name}** to `{save_path}`. Running AI profiling...")
            st.cache_data.clear()
            st.session_state["active_dataset"] = save_path
            st.session_state["show_upload_panel"] = False
            st.rerun()

html("<br>")

# ── Build dataset list ────────────────────────────────────────────────────────
raw_files = list_raw_datasets()

if not raw_files:
    st.info("No datasets found in `data/raw/`. Upload a CSV, Excel, or Parquet file above.")
    st.stop()

# ── Profile each file (cached) ───────────────────────────────────────────────
dataset_summaries = []
with st.spinner("Loading dataset profiles..."):
    for fname in raw_files:
        fpath = os.path.join(RAW_DIR, fname)
        try:
            audit = get_audit(fpath)
            p = audit["profile"]
            h = audit["health"]
            score = int(h["overall_health_score"])
            ext = fname.rsplit(".", 1)[-1].upper()
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%b %d, %Y")
            if score >= 95:
                status = badge("● Ready", "green")
            elif score >= 80:
                status = badge("● Needs attention", "amber")
            else:
                status = badge("● Action required", "red")
            dataset_summaries.append({
                "fname": fname, "fpath": fpath,
                "rows": p["rows"], "cols": p["columns"],
                "score": score, "ext": ext,
                "mtime": mtime, "status": status,
                "audit": audit
            })
        except Exception as e:
            dataset_summaries.append({
                "fname": fname, "fpath": os.path.join(RAW_DIR, fname),
                "rows": "—", "cols": "—", "score": 0,
                "ext": fname.rsplit(".", 1)[-1].upper(),
                "mtime": "—", "status": badge("● Error", "red"),
                "audit": None, "error": str(e)
            })

# ── Summary table ─────────────────────────────────────────────────────────────
def fmt_type(t):
    return f'<span class="mono" style="color:#166534;background:#dcfce7;padding:.1rem .4rem;border-radius:6px">{t}</span>'

trs = []
for ds in dataset_summaries:
    score = ds["score"]
    q_html = f'<b>{score}%</b> {bar(score, "#10b981" if score >= 95 else "#f59e0b")}' if score else "<i>Error</i>"
    trs.append([
        f"<b>{ds['fname']}</b><small class='mono'>{ds['fpath']}</small>",
        fmt_type(ds["ext"]),
        f"{ds['rows']:,}" if isinstance(ds["rows"], int) else ds["rows"],
        str(ds["cols"]),
        q_html,
        ds["mtime"],
        ds["status"]
    ])

filter_chips = "".join(
    f'<span class="bf-chip{" on" if i == 0 else ""}">{t}</span>'
    for i, t in enumerate([f"All {len(raw_files)}", f"● Ready {sum(1 for d in dataset_summaries if d['score'] >= 95)}"])
)

html(card(
    f'<div style="display:flex;gap:1rem;align-items:center">'
    f'<div class="bf-search" style="flex:.7">🔍 Search datasets by title or format<span>⌘ F</span></div>'
    f'<div>{filter_chips}</div></div>'
))
html("<br>")
html(card(
    table(["DATASET", "FORMAT", "ROWS", "COLUMNS", "QUALITY SCORE", "LAST MODIFIED", "STATUS"], trs)
    + f'<div style="margin-top:1rem;color:#475569">Showing <b>{len(trs)}</b> dataset(s) — profiled live by Data Engineering Agent</div>'
))
html("<br>")

# ── Cleaned datasets ─────────────────────────────────────────────────────────
cleaned_files = list_cleaned_datasets()
if cleaned_files:
    default_cleaned = st.session_state.get("last_cleaned_dataset")
    default_cleaned_name = os.path.basename(default_cleaned) if default_cleaned else None
    default_cleaned_idx = (
        cleaned_files.index(default_cleaned_name)
        if default_cleaned_name in cleaned_files else 0
    )
    with st.expander("Cleaned datasets", expanded=default_cleaned_name in cleaned_files):
        cleaned_name = st.selectbox(
            "Select a cleaned dataset:",
            options=cleaned_files,
            index=default_cleaned_idx,
            key="cleaned_dataset_select"
        )
        cleaned_path = os.path.join(CLEANED_DIR, cleaned_name)
        cleaned_df = pd.read_csv(cleaned_path)
        st.caption(f"Saved at `{cleaned_path}`")
        st.dataframe(cleaned_df, use_container_width=True)
        with open(cleaned_path, "rb") as cleaned_file:
            st.download_button(
                "Download cleaned dataset",
                data=cleaned_file.read(),
                file_name=cleaned_name,
                mime="text/csv",
                key="download_cleaned_dataset"
            )

# ── Per-dataset detail: selectbox ─────────────────────────────────────────────
selected_name = st.selectbox(
    "Inspect dataset details:",
    options=[ds["fname"] for ds in dataset_summaries],
    index=0
)
selected = next(ds for ds in dataset_summaries if ds["fname"] == selected_name)

if selected["audit"] is None:
    st.error(f"Could not profile this dataset: {selected.get('error', 'Unknown error')}")
    st.stop()

audit    = selected["audit"]
profile  = audit["profile"]
health   = audit["health"]
strategy = audit["cleaning_strategy"]
score    = selected["score"]
col_roles = profile.get("column_roles", {})
missing  = health["missing_info"]["total_missing_cells"]
missing_pct = health["missing_info"]["missing_percentage"]
dup_cnt  = health["duplicate_info"]["count"]
type_issues = len(health["type_issues"])
rec      = strategy.get("recommendation_summary", "No issues detected.")

numeric_cols     = [c for c, r in col_roles.items() if r == "continuous_numeric"]
categorical_cols = [c for c, r in col_roles.items() if r in ("categorical", "boolean")]
id_cols          = [c for c, r in col_roles.items() if r == "primary_key"]
ts_cols          = [c for c, r in col_roles.items() if r == "timestamp"]

col_breakdown = f'''
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
  <div class="bf-box"><b>Numeric ({len(numeric_cols)})</b><br>
    <small class="mono">{", ".join(numeric_cols[:6]) + ("..." if len(numeric_cols) > 6 else "") or "—"}</small></div>
  <div class="bf-box"><b>Categorical ({len(categorical_cols)})</b><br>
    <small class="mono">{", ".join(categorical_cols[:6]) + ("..." if len(categorical_cols) > 6 else "") or "—"}</small></div>
  <div class="bf-box"><b>ID/Key ({len(id_cols)})</b><br>
    <small class="mono">{", ".join(id_cols) or "—"}</small></div>
  <div class="bf-box"><b>Timestamp ({len(ts_cols)})</b><br>
    <small class="mono">{", ".join(ts_cols) or "—"}</small></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
  <div class="bf-box"><b>Missing cells: {missing}</b> ({missing_pct}%)<br>{bar(float(missing_pct), "#f59e0b")}</div>
  <div class="bf-box"><b>Duplicate rows: {dup_cnt}</b><br>{bar(health["duplicate_info"]["percentage"], "#6d28d9")}</div>
</div>'''

if health["type_issues"]:
    issues_rows = [
        [f"<span class='mono'>{col}</span>", info["issue"], info.get("recommendation", "—")]
        for col, info in health["type_issues"].items()
    ]
    issues_table = table(["COLUMN", "ISSUE", "RECOMMENDATION"], issues_rows)
else:
    issues_table = "<p style='color:#16a34a;padding:.5rem 0'>No type issues detected.</p>"

ai_rec = f'''<div style="background:#eef2ff;border-radius:12px;padding:1.2rem;display:flex;gap:1rem;align-items:center">
  <div style="flex:1"><b style="font-size:1.05rem">BIFlow AI Recommendation</b>
  <span class="bf-badge blue" style="margin-left:.5rem">Qwen 2.5 Agent</span>
  <br><span style="color:#334155">{rec}</span></div></div>'''

storage_html = f'''<div class="ch"><div><h3>{selected_name}</h3>
  <div class="subt">Live profile summary</div></div>{selected["status"]}</div>
  <div style="font-size:2.2rem;font-weight:700">{profile["rows"]:,} rows
  <small style="font-size:1rem;color:#64748b">× {profile["columns"]} columns</small></div>
  {bar(score, "#4f46e5")}
  <p style="color:#64748b;font-size:.85rem">Quality: <b style="color:#0f172a">{score}%</b>
  &nbsp;|&nbsp; Missing: <b>{missing}</b>
  &nbsp;|&nbsp; Duplicates: <b>{dup_cnt}</b>
  &nbsp;|&nbsp; Type issues: <b>{type_issues}</b></p>'''

html(f'<div class="bf-grid g21"><div>'
     f'{card(col_breakdown, "Column profile", "Auto-detected column types by Data Engineering Agent.")}'
     f'<br>{card(issues_table, "Type issues", f"{type_issues} column(s) require attention.")}'
     f'<br>{ai_rec}'
     f'</div><div>{card(storage_html)}</div></div>')

html("<br>")

c1, c2 = st.columns(2)
with c1:
    if st.button("Preview cleaning changes", use_container_width=True, key="prev_ds"):
        with st.spinner("Running preview..."):
            preview = agent.execute_cleaning(
                selected["fpath"], strategy=strategy, preview_mode=True
            )
        st.success(f"Health score after cleaning: **{preview['health_after']['overall_health_score']}%**")
with c2:
    if st.button("Apply recommended cleaning", type="primary", use_container_width=True, key="apply_ds"):
        with st.spinner("Cleaning dataset..."):
            res = agent.execute_cleaning(
                selected["fpath"], strategy=strategy, preview_mode=False
            )
        st.session_state["last_cleaned_dataset"] = res["cleaned_file_path"]
        st.session_state["last_cleaned_score"] = res["health_after"]["overall_health_score"]
        st.cache_data.clear()
        st.rerun()
>>>>>>> Stashed changes
