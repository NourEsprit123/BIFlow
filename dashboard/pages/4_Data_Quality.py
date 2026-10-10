from pathlib import Path
import sys
import html as html_lib

import streamlit as st


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
    kpi,
    grid,
    card,
    table,
    badge,
    bar,
    donut,
    columns_chart,
)


# ============================================================
# ANALYTICS
# ============================================================

from analytics.data_quality import generate_quality_report


# ============================================================
# PAGE SETUP
# ============================================================

setup("Data Quality")


# ============================================================
# GET SELECTED DATASET
# ============================================================

dataset_param = st.query_params.get("dataset")


if not dataset_param:

    page_header(
        "Data Quality",
        "Select a dataset from the Datasets page to inspect its quality.",
        "",
        "Workspace › <b>Data Quality</b>",
    )

    html(
        card(
            """
            <div style="
                text-align:center;
                padding:3rem;
                color:#64748b;
            ">

                <div style="font-size:3rem">
                    📊
                </div>

                <h2 style="color:#0f172a">
                    No dataset selected
                </h2>

                <p>
                    Go to the <b>Datasets</b> page and click
                    on a dataset to inspect its data quality.
                </p>

            </div>
            """
        )
    )

    st.stop()


# ============================================================
# FIND DATASET
# ============================================================

dataset_path = Path(dataset_param)

raw_dir = ROOT_DIR / "data" / "raw"


# ------------------------------------------------------------
# Security / validity check
# ------------------------------------------------------------

try:

    dataset_path = dataset_path.resolve()
    raw_dir = raw_dir.resolve()

    dataset_path.relative_to(raw_dir)

except ValueError:

    st.error("Invalid dataset selected.")
    st.stop()


if not dataset_path.exists():

    st.error(
        f"Dataset not found: {dataset_path.name}"
    )

    st.stop()


# ============================================================
# RUN QUALITY ANALYSIS
# ============================================================

try:

    with st.spinner(
        f"Analyzing {dataset_path.name}..."
    ):

        report = generate_quality_report(
            str(dataset_path)
        )

except Exception as error:

    st.error(
        f"Unable to analyze the dataset: {error}"
    )

    st.stop()


# ============================================================
# BASIC INFORMATION
# ============================================================

dataset_name = dataset_path.name

quality_score = float(
    report.get("quality_score", 0)
)


summary = report.get(
    "summary",
    {}
)


# ------------------------------------------------------------
# Quality values
# ------------------------------------------------------------

missing_values = summary.get(
    "missing_values",
    0
)

duplicate_rows = summary.get(
    "duplicate_rows",
    0
)

type_issues_count = summary.get(
    "type_issues",
    0
)

inconsistency_issues = summary.get(
    "inconsistency_issues",
    0
)

outlier_issues = summary.get(
    "outlier_issues",
    0
)

date_issues = summary.get(
    "date_issues",
    0
)

constant_columns = summary.get(
    "constant_columns",
    0
)


# ============================================================
# DATASET SIZE
# ============================================================

# Try to retrieve rows / columns from the report.

rows = report.get(
    "rows",
    summary.get("rows", 0)
)

columns = report.get(
    "columns",
    summary.get("columns", 0)
)


# If rows/columns are not directly available,
# try to retrieve them from the dataframe profile.

if not rows or not columns:

    profile = report.get(
        "profile",
        {}
    )

    if isinstance(profile, dict):

        rows = profile.get(
            "rows",
            rows
        )

        columns = profile.get(
            "columns",
            columns
        )


# ============================================================
# QUALITY STATUS
# ============================================================

if quality_score >= 90:

    quality_status = "● Excellent"
    quality_status_type = "green"

elif quality_score >= 70:

    quality_status = "● Needs attention"
    quality_status_type = "amber"

else:

    quality_status = "● Critical"
    quality_status_type = "red"


# ============================================================
# HEADER
# ============================================================

page_header(
    "Data Quality",
    f"Monitor and understand the reliability of {dataset_name}.",
    btn("← Back to datasets"),
    (
        "Workspace › Datasets › "
        f"<b>{html_lib.escape(dataset_name)}</b> "
        "› <b>Data Quality</b>"
    ),
)


# ============================================================
# DATASET INFO
# ============================================================

html(
    f"""
    <div class="bf-box" style="
        margin-bottom:1rem;
        display:flex;
        justify-content:space-between;
        align-items:center;
    ">

        <div>

            <div style="
                font-size:.8rem;
                color:#64748b;
                margin-bottom:.3rem;
            ">
                SELECTED DATASET
            </div>

            <div style="
                font-size:1.2rem;
                font-weight:700;
                color:#0f172a;
            ">
                📄 {html_lib.escape(dataset_name)}
            </div>

        </div>

        <div>
            {badge(
                quality_status,
                quality_status_type
            )}
        </div>

    </div>
    """
)


# ============================================================
# KPI CARDS
# ============================================================

html(
    grid(
        [
            kpi(
                "Quality Score",
                f"{quality_score:.2f}%",
                quality_status,
                "🛡",
            ),

            kpi(
                "Missing Values",
                f"{missing_values:,}",
                "Detected missing values",
                "⚠",
                "blue",
                "gray",
            ),

            kpi(
                "Duplicates",
                f"{duplicate_rows:,}",
                (
                    "No duplicates found"
                    if duplicate_rows == 0
                    else "Duplicate rows detected"
                ),
                "⧉",
                "blue",
            ),

            kpi(
                "Type Issues",
                f"{type_issues_count:,}",
                "Columns requiring review",
                "{}",
            ),
        ],
        "g4",
    )
)


# ============================================================
# QUALITY DIMENSIONS
# ============================================================

total_cells = 0

if rows and columns:

    total_cells = (
        int(rows)
        * int(columns)
    )


# ------------------------------------------------------------
# Completeness
# ------------------------------------------------------------

if total_cells > 0:

    completeness = max(
        0,
        100 - (
            missing_values
            / total_cells
            * 100
        )
    )

else:

    completeness = 100


# ------------------------------------------------------------
# Uniqueness
# ------------------------------------------------------------

uniqueness = 100

if duplicate_rows > 0 and rows:

    uniqueness = max(
        0,
        100 - (
            duplicate_rows
            / int(rows)
            * 100
        )
    )


# ------------------------------------------------------------
# Validity
# ------------------------------------------------------------

validity = max(
    0,
    100 - (
        type_issues_count
        + date_issues
    ) * 5
)


# ------------------------------------------------------------
# Consistency
# ------------------------------------------------------------

consistency = max(
    0,
    100 - (
        inconsistency_issues
        + outlier_issues
    ) * 2
)


# ============================================================
# DIMENSIONS
# ============================================================

dims = [

    (
        "Completeness",
        round(completeness, 1),
        "#38bdf8",
    ),

    (
        "Validity",
        round(validity, 1),
        "#4f46e5",
    ),

    (
        "Uniqueness",
        round(uniqueness, 1),
        "#075985",
    ),

    (
        "Consistency",
        round(consistency, 1),
        "#6d28d9",
    ),

]


# ============================================================
# DIMENSIONS HTML
# ============================================================

dim_html = "".join(

    f"""
    <div style="margin-bottom:1rem">

        <div style="
            display:flex;
            justify-content:space-between;
        ">

            <span>
                {name}
            </span>

            <span class="mono">
                {value}%
            </span>

        </div>

        {bar(
            value,
            color
        )}

    </div>
    """

    for name, value, color in dims

)


# ============================================================
# QUALITY OVERVIEW CARD
# ============================================================

overview = card(

    f"""
    <div style="
        display:flex;
        gap:2rem;
        align-items:center;
    ">

        {donut(
            quality_score,
            "#4f46e5",
            size=190
        )}

        <div style="flex:1">

            {dim_html}

        </div>

    </div>
    """,

    "Quality overview",

    "Overview of the main data quality dimensions.",

)


# ============================================================
# ISSUE COUNTS
# ============================================================

# ------------------------------------------------------------
# High severity
# ------------------------------------------------------------

high_count = 0


# ------------------------------------------------------------
# Medium severity
# ------------------------------------------------------------

medium_count = (
    type_issues_count
    + inconsistency_issues
    + date_issues
)


# ------------------------------------------------------------
# Low severity
# ------------------------------------------------------------

low_count = (
    constant_columns
    + outlier_issues
)


# ============================================================
# SEVERITY GRAPH
# ============================================================

severity = card(

    columns_chart(

        [
            low_count,
            medium_count,
            high_count
        ],

        [
            "Low",
            "Medium",
            "High"
        ],

        [
            "#dbeafe",
            "#38bdf8",
            "#dbeafe"
        ],

        150

    )

    +

    f"""
    <div style="
        display:flex;
        gap:.4rem;
        margin-top:1rem;
    ">

        {badge(
            f"High · {high_count}",
            "red"
        )}

        {badge(
            f"Medium · {medium_count}",
            "blue"
        )}

        {badge(
            f"Low · {low_count}",
            "gray"
        )}

    </div>
    """,

    "Issues by severity",

    (
        f"{medium_count + high_count} "
        "actionable issues detected."
    ),

)


# ============================================================
# DISPLAY QUALITY OVERVIEW + SEVERITY
# ============================================================

html(

    f"""
    <div class="bf-grid g21">

        {overview}

        {severity}

    </div>
    """

)


# ============================================================
# DETECTED ISSUES
# ============================================================

issue_rows = []


# ============================================================
# MISSING VALUES
# ============================================================

missing_report = report.get(
    "missing_values",
    {}
)


if isinstance(
    missing_report,
    dict
):

    for column, info in missing_report.items():

        if isinstance(info, dict):

            count = info.get(
                "count",
                0
            )

        elif isinstance(
            info,
            (int, float)
        ):

            count = info

        else:

            count = 0


        if count > 0:

            issue_rows.append(

                [

                    badge(
                        "● Medium",
                        "blue"
                    ),

                    (
                        "<span class='mono'>"
                        + html_lib.escape(
                            str(column)
                        )
                        + "</span>"
                    ),

                    "Missing values",

                    f"{int(count):,} missing values",

                    "Impute or treat missing values ›",

                ]

            )


# ============================================================
# TYPE ISSUES
# ============================================================

type_report = report.get(
    "type_issues",
    {}
)


if isinstance(
    type_report,
    dict
):

    for column, info in type_report.items():

        if not isinstance(
            info,
            dict
        ):
            continue


        current_type = info.get(
            "current_type",
            "unknown"
        )

        expected_type = info.get(
            "expected_type",
            "numeric"
        )

        numeric_ratio = info.get(
            "numeric_ratio",
            0
        )


        issue_rows.append(

            [

                badge(
                    "● Medium",
                    "blue"
                ),

                (
                    "<span class='mono'>"
                    + html_lib.escape(
                        str(column)
                    )
                    + "</span>"
                ),

                "Incorrect data type",

                (
                    f"{numeric_ratio}% "
                    "numeric-compatible values"
                ),

                (
                    f"Convert to "
                    f"{html_lib.escape(str(expected_type))} ›"
                ),

            ]

        )


# ============================================================
# DUPLICATES
# ============================================================

if duplicate_rows > 0:

    issue_rows.append(

        [

            badge(
                "● Medium",
                "blue"
            ),

            "<span class='mono'>Dataset</span>",

            "Duplicate rows",

            (
                f"{duplicate_rows:,} "
                "duplicate rows"
            ),

            "Review and remove duplicates ›",

        ]

    )


# ============================================================
# INCONSISTENCIES
# ============================================================

inconsistency_report = report.get(
    "inconsistencies",
    {}
)


if isinstance(
    inconsistency_report,
    dict
):

    for column, info in inconsistency_report.items():

        if isinstance(
            info,
            dict
        ):

            count = info.get(
                "count",
                0
            )

        elif isinstance(
            info,
            (int, float)
        ):

            count = info

        else:

            count = 0


        if count > 0:

            issue_rows.append(

                [

                    badge(
                        "● Medium",
                        "blue"
                    ),

                    (
                        "<span class='mono'>"
                        + html_lib.escape(
                            str(column)
                        )
                        + "</span>"
                    ),

                    "Inconsistent values",

                    (
                        f"{int(count):,} "
                        "inconsistent values"
                    ),

                    "Normalize values ›",

                ]

            )


# ============================================================
# OUTLIERS
# ============================================================

outlier_report = report.get(
    "outliers",
    {}
)


if isinstance(
    outlier_report,
    dict
):

    for column, info in outlier_report.items():

        if isinstance(
            info,
            dict
        ):

            count = info.get(
                "count",
                0
            )

        elif isinstance(
            info,
            (int, float)
        ):

            count = info

        else:

            count = 0


        if count > 0:

            issue_rows.append(

                [

                    badge(
                        "● Low",
                        "gray"
                    ),

                    (
                        "<span class='mono'>"
                        + html_lib.escape(
                            str(column)
                        )
                        + "</span>"
                    ),

                    "Potential outliers",

                    (
                        f"{int(count):,} "
                        "values"
                    ),

                    (
                        "Review outliers "
                        "before cleaning ›"
                    ),

                ]

            )


# ============================================================
# DATE ISSUES
# ============================================================

date_report = report.get(
    "date_issues",
    {}
)


if isinstance(
    date_report,
    dict
):

    for column, info in date_report.items():

        if isinstance(
            info,
            dict
        ):

            count = info.get(
                "count",
                0
            )

        elif isinstance(
            info,
            (int, float)
        ):

            count = info

        else:

            count = 0


        if count > 0:

            issue_rows.append(

                [

                    badge(
                        "● Medium",
                        "blue"
                    ),

                    (
                        "<span class='mono'>"
                        + html_lib.escape(
                            str(column)
                        )
                        + "</span>"
                    ),

                    "Date issues",

                    (
                        f"{int(count):,} "
                        "invalid date values"
                    ),

                    "Review and normalize dates ›",

                ]

            )


# ============================================================
# DISPLAY DETECTED ISSUES
# ============================================================

if issue_rows:

    issues_table = table(

        [

            "SEVERITY",
            "COLUMN",
            "ISSUE",
            "DETECTED VALUES",
            "RECOMMENDATION",

        ],

        issue_rows

    )

else:

    issues_table = """

    <div style="
        text-align:center;
        padding:2rem;
        color:#64748b;
    ">

        <div style="font-size:2rem">
            ✅
        </div>

        <h3 style="color:#0f172a">
            No significant issues detected
        </h3>

        <p>
            This dataset passed the current
            data quality checks.
        </p>

    </div>

    """


html(

    card(

        issues_table,

        "Detected issues",

        (
            "Review each detected issue "
            "before applying remediation."
        ),

    )

)


# ============================================================
# CLEANING RECOMMENDATION
# ============================================================

if issue_rows:

    recommendations = []


    # --------------------------------------------------------
    # Missing values
    # --------------------------------------------------------

    if missing_values > 0:

        recommendations.append(

            f"treat {missing_values:,} "
            "missing value(s)"

        )


    # --------------------------------------------------------
    # Type issues
    # --------------------------------------------------------

    if type_issues_count > 0:

        recommendations.append(

            f"review {type_issues_count} "
            "type issue(s)"

        )


    # --------------------------------------------------------
    # Duplicates
    # --------------------------------------------------------

    if duplicate_rows > 0:

        recommendations.append(

            f"review {duplicate_rows:,} "
            "duplicate row(s)"

        )


    # --------------------------------------------------------
    # Inconsistencies
    # --------------------------------------------------------

    if inconsistency_issues > 0:

        recommendations.append(

            f"normalize {inconsistency_issues} "
            "inconsistent column(s)"

        )


    # --------------------------------------------------------
    # Outliers
    # --------------------------------------------------------

    if outlier_issues > 0:

        recommendations.append(

            f"review {outlier_issues} "
            "potential outlier column(s)"

        )


    # --------------------------------------------------------
    # Date issues
    # --------------------------------------------------------

    if date_issues > 0:

        recommendations.append(

            f"review {date_issues} "
            "date issue(s)"

        )


    # --------------------------------------------------------
    # Build recommendation sentence
    # --------------------------------------------------------

    recommendation_text = ", ".join(
        recommendations[:3]
    )


    if len(recommendations) > 3:

        recommendation_text += (
            " and other detected issues"
        )


    # ========================================================
    # RECOMMENDATION CARD
    # ========================================================

    html(

        f"""
        <br>

        <div class="bf-card"
             style="
                background:#eef2ff;
                display:flex;
                gap:1rem;
                align-items:center;
             ">

            <div style="
                font-size:1.8rem;
                min-width:35px;
            ">
                🪄
            </div>


            <div style="flex:1">

                <div style="
                    display:flex;
                    align-items:center;
                    gap:.5rem;
                    margin-bottom:.35rem;
                ">

                    <b style="
                        font-size:1.1rem;
                    ">
                        BIFlow cleaning recommendation
                    </b>

                    {badge(
                        "Data Quality",
                        "blue"
                    )}

                </div>


                <div style="
                    color:#475569;
                ">

                    BIFlow recommends:

                    <b>
                        {html_lib.escape(
                            recommendation_text
                        )}
                    </b>.

                    <br>

                    The original dataset will be
                    preserved before any cleaning
                    operation.

                </div>

            </div>


            {btn(
                "Preview changes"
            )}


            {btn(
                "✨ Apply recommended cleaning",
                True
            )}

        </div>
        """

    )


else:

    # ========================================================
    # NO CLEANING REQUIRED
    # ========================================================

    html(

        """
        <br>

        <div class="bf-card"
             style="
                background:#ecfdf5;
                display:flex;
                gap:1rem;
                align-items:center;
             ">

            <div style="
                font-size:1.8rem;
            ">
                ✅
            </div>


            <div>

                <b style="
                    font-size:1.1rem;
                ">
                    No cleaning required
                </b>

                <br>

                <span style="
                    color:#475569;
                ">
                    BIFlow did not detect significant
                    data quality issues in this dataset.
                </span>

            </div>

        </div>
        """

    )