from pathlib import Path
import sys


import streamlit as st
import json

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




ANALYSIS_CACHE_FILE = ROOT_DIR / "data" / "analysis_cache.json"


def load_analysis_cache():
    """
    Charge les analyses précédemment sauvegardées.
    """
    if not ANALYSIS_CACHE_FILE.exists():
        return {}

    try:
        with open(
            ANALYSIS_CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception:
        return {}


# ============================================================
# PAGE SETUP
# ============================================================

setup("Datasets")


# ============================================================
# SESSION STATE
# ============================================================

# ============================================================
# SESSION STATE
# ============================================================

if "dataset_analysis" not in st.session_state:
    st.session_state.dataset_analysis = load_analysis_cache()

if "last_uploaded_dataset" not in st.session_state:
    st.session_state.last_uploaded_dataset = None


# ============================================================
# HELPERS
# ============================================================

def fmt(value):
    return (
        f'<span class="mono" '
        f'style="color:#166534;background:#dcfce7;'
        f'padding:.1rem .4rem;border-radius:6px">'
        f'{value}</span>'
    )


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"

    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"

    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"

    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def get_file_key(file_path):
    """
    Clé unique permettant de détecter si le fichier
    a changé depuis la dernière analyse.
    """
    file_path = Path(file_path)

    try:
        modified = file_path.stat().st_mtime
    except FileNotFoundError:
        modified = 0

    return f"{file_path.resolve()}::{modified}"


# ============================================================
# PERSISTENT ANALYSIS CACHE
# ============================================================




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
    Clé basée sur le chemin + date de modification.
    
    Si le fichier est modifié, la clé change et le dataset
    sera automatiquement réanalysé.
    """
    file_path = Path(file_path)

    try:
        modified = file_path.stat().st_mtime
    except FileNotFoundError:
        modified = 0

    return f"{file_path.resolve()}::{modified}"


def get_status(quality_score):
    if quality_score >= 90:
        return "● Ready", "green"

    if quality_score >= 70:
        return "● Needs attention", "amber"

    return "● Critical", "red"


# ============================================================
# DATASET ANALYSIS
# ============================================================

def analyze_dataset(file_path):
    """
    Analyse complète d'un dataset.
    """
    file_path = str(file_path)

    profile = profile_dataset(file_path)

    quality = generate_quality_report(file_path)

    quality_score = float(quality["quality_score"])

    status_text, status_type = get_status(quality_score)

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
    """
    Retourne l'analyse depuis le cache persistant.

    Si elle n'existe pas encore :
    → analyse le dataset
    → sauvegarde immédiatement le résultat.
    """

    file_path = Path(file_path)

    key = get_persistent_key(file_path)

    # --------------------------------------------------------
    # CACHE EXISTANT
    # --------------------------------------------------------

    if key in st.session_state.dataset_analysis:
        return st.session_state.dataset_analysis[key]

    # --------------------------------------------------------
    # NOUVELLE ANALYSE
    # --------------------------------------------------------

    with st.spinner(
        f"Analyzing {file_path.name}..."
    ):

        result = analyze_dataset(file_path)

    # --------------------------------------------------------
    # SAVE IN SESSION
    # --------------------------------------------------------

    st.session_state.dataset_analysis[key] = result

    # --------------------------------------------------------
    # SAVE ON DISK
    # --------------------------------------------------------

    save_analysis_cache(
        st.session_state.dataset_analysis
    )

    return result


# ============================================================
# HEADER
# ============================================================

page_header(
    "Datasets",
    "Manage, inspect, and streamline your business intelligence assets and data ingest pipelines.",
    btn("⟳ Refresh") + btn("☁ + Upload dataset", True),
    "Workspace › <b>Datasets</b>",
)


# ============================================================
# UPLOAD
# ============================================================

uploaded_file = st.file_uploader(
    "☁ + Upload dataset",
    type=["csv", "xlsx", "xls"],
    label_visibility="collapsed",
)


# ============================================================
# HANDLE UPLOAD
# ============================================================

if uploaded_file is not None:

    raw_dir = ROOT_DIR / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    file_name = uploaded_file.name

    # Protection contre les noms du type fichier.csv.csv
    while file_name.lower().endswith(".csv.csv"):
        file_name = file_name[:-4]

    destination = raw_dir / file_name

    # Sauvegarde
    with open(destination, "wb") as file:
        file.write(uploaded_file.getbuffer())

    st.session_state.last_uploaded_dataset = str(destination)

    st.success(
        f"Dataset '{file_name}' uploaded successfully."
    )

    # ========================================================
    # AUTOMATIC ANALYSIS
    # ========================================================

    st.markdown("### 🔎 Dataset Analysis")

    analysis_placeholder = st.empty()

    with analysis_placeholder.container():

        try:

            with st.spinner(
                f"Analyzing {file_name}..."
            ):

                result = analyze_dataset(destination)

                key = get_persistent_key(destination)

                st.session_state.dataset_analysis[key] = result
                # Persistance permanente
                save_analysis_cache(
                   st.session_state.dataset_analysis
)

            st.success("Analysis completed successfully.")

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

            status_text = result["status_text"]

            st.markdown(
                f"""
                **Dataset:** `{file_name}`
                
                **Status:** **{status_text}**
                """
            )

        except Exception as error:

            st.error(
                f"Analysis failed for '{file_name}': {error}"
            )


# ============================================================
# GET ALL DATASETS
# ============================================================

datasets = list_datasets()


# ============================================================
# SEARCH
# ============================================================

search_col, filter_col = st.columns([1.3, 1])

with search_col:

    search = st.text_input(
        "Search",
        placeholder="🔍 Search datasets by title, tag, or owner",
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
# BUILD DATASET TABLE
# ============================================================

dataset_rows = []

ready_count = 0
attention_count = 0
processing_count = 0


for dataset_path in datasets:

    dataset_name = dataset_path.name

    # Search
    if search:
        if search.lower() not in dataset_name.lower():
            continue

    key = get_persistent_key(dataset_path)

    result = st.session_state.dataset_analysis.get(key)

    # --------------------------------------------------------
    # NOT ANALYZED
    # --------------------------------------------------------

    if result is None:

        status_text = "● Not analyzed"
        status_type = "blue"

        rows_value = "—"
        columns_value = "—"
        quality_value = "<i>Not analyzed</i>"
        last_analysis = "Not analyzed"

    else:

        rows_value = f"{result['rows']:,}"
        columns_value = f"{result['columns']:,}"

        quality_score = result["quality"]

        status_text = result["status_text"]
        status_type = result["status_type"]

        quality_value = (
            f"<b>{quality_score:.1f}%</b> "
            f"{bar(quality_score, '#10b981')}"
        )

        last_analysis = "Recently analyzed"

        if status_type == "green":
            ready_count += 1

        elif status_type == "amber":
            attention_count += 1

    # --------------------------------------------------------
    # FILTER STATUS
    # --------------------------------------------------------

    if filter_status == "Ready" and status_type != "green":
        continue

    if filter_status == "Needs attention" and status_type != "amber":
        continue

    if filter_status == "Critical" and status_type != "red":
        continue

    if filter_status == "Not analyzed" and result is not None:
        continue

    # --------------------------------------------------------
    # FORMAT
    # --------------------------------------------------------

    extension = dataset_path.suffix.upper().replace(".", "")

    if extension == "XLS":
        extension = "XLS"

    if extension == "XLSX":
        extension = "XLSX"

    if extension == "CSV":
        extension = "CSV"

    dataset_rows.append(
        [
            f"""
            <b>{dataset_name}</b>
            <small>
                Local dataset · data/raw
            </small>
            """,

            fmt(extension),

            rows_value,

            columns_value,

            quality_value,

            last_analysis,

            badge(status_text, status_type),
        ]
    )


# ============================================================
# FILTER COUNTS
# ============================================================

total_datasets = len(datasets)

# ============================================================
# FILTER CHIPS
# ============================================================

filters = "".join(
    [
        f'<span class="bf-chip{" on" if filter_status == "All" else ""}">'
        f'All {total_datasets}</span>',

        f'<span class="bf-chip{" on" if filter_status == "Ready" else ""}">'
        f'● Ready {ready_count}</span>',

        f'<span class="bf-chip{" on" if filter_status == "Needs attention" else ""}">'
        f'● Needs attention {attention_count}</span>',

        f'<span class="bf-chip{" on" if filter_status == "Not analyzed" else ""}">'
        f'● Not analyzed</span>',
    ]
)


# ============================================================
# SEARCH + FILTER CARD
# ============================================================

html(
    card(
        f"""
        <div style="
            display:flex;
            gap:1rem;
            align-items:center;
        ">

            <div style="flex:1">
                <b style="color:#0f172a">
                    Dataset workspace
                </b>

                <div style="
                    color:#64748b;
                    font-size:.85rem;
                    margin-top:.2rem;
                ">
                    {total_datasets} dataset(s) detected in data/raw
                </div>
            </div>

            <div>
                {filters}
            </div>

        </div>
        """
    )
)

html("<br>")


# ============================================================
# DATASET TABLE
# ============================================================

if dataset_rows:

    html(
        card(
            table(
                [
                    "DATASET",
                    "FORMAT",
                    "ROWS",
                    "COLUMNS",
                    "QUALITY SCORE",
                    "LAST ANALYSIS",
                    "STATUS",
                ],
                dataset_rows,
            )
            +
            f"""
            <div style="
                display:flex;
                justify-content:space-between;
                margin-top:1rem;
                color:#475569;
            ">
                <span>
                    Showing <b>{len(dataset_rows)}</b>
                    of <b>{total_datasets}</b> datasets
                </span>

                <span>
                    <span class="bf-chip">Previous</span>
                    <span class="bf-chip on">1</span>
                    <span class="bf-chip">Next</span>
                </span>
            </div>
            """
        )
    )

else:

    html(
        card(
            """
            <div style="
                text-align:center;
                padding:2rem;
                color:#64748b;
            ">
                <div style="font-size:2rem">📂</div>

                <h3 style="color:#0f172a">
                    No datasets found
                </h3>

                <p>
                    Upload a CSV, XLSX or XLS dataset
                    to start the analysis.
                </p>
            </div>
            """
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

# On garde une capacité virtuelle de 20 GB
storage_percentage = min(
    100,
    (total_size_gb / 20) * 100
)

storage = f"""
<div class="ch">

    <div>
        <h3>Workspace storage</h3>

        <div class="subt">
            Real-time analytical cache & blob storage limit
        </div>
    </div>

    {badge("Healthy", "green")}

</div>

<div style="
    font-size:2.2rem;
    font-weight:700;
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
        {storage_percentage:.1f}% capacity used
    </span>

</div>

{bar(storage_percentage, "#4f46e5")}

<p style="
    color:#64748b;
    font-size:.85rem
">

    {max(0, 20 - total_size_gb):.2f} GB remaining

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

sources = f"""
<div class="ch">

    <div>
        <h3>Connected sources</h3>

        <div class="subt">
            Active connections & streaming endpoints
        </div>
    </div>

    {btn("+ Add source")}

</div>

<div style="
    font-size:2.2rem;
    font-weight:700
">

    {len(datasets)} active

    {badge("● All connectors synced", "blue")}

</div>

<div class="bf-box" style="margin-top:.8rem">

    📄 CSV uploads · Excel files · Local datasets

</div>
"""


# ============================================================
# BOTTOM CARDS
# ============================================================

html(
    f"""
    <div class="bf-grid g2">

        {card(storage)}

        {card(sources)}

    </div>
    """
)