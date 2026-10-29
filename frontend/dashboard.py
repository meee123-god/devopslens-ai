"""Streamlit dashboard for DevOpsLens AI.

Provides an interactive user interface for uploading logs, visualizing severity distributions,
inspecting recurring error groups, running grounded AI triage, and reviewing past analyses.
"""

import json
import os
import sys
import pandas as pd
import streamlit as st

# Ensure project root and frontend directory are in sys.path regardless of launch directory
current_dir = os.path.abspath(os.path.dirname(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
for path in (project_root, current_dir):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from frontend.api_client import BackendAPIClient
except ModuleNotFoundError:
    from api_client import BackendAPIClient

# Page configuration
st.set_page_config(
    page_title="DevOpsLens AI | Log Analysis & Triage",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling for polished enterprise dashboard look
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #E2E8F0;
        text-align: center;
    }
    .priority-badge-p1 {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .priority-badge-p2 {
        background-color: #FFEDD5;
        color: #9A3412;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .priority-badge-p3 {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .priority-badge-p4 {
        background-color: #E2E8F0;
        color: #334155;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .diagnosis-box {
        background-color: #F0FDF4;
        border-left: 4px solid #16A34A;
        padding: 16px;
        border-radius: 4px;
        margin-top: 10px;
    }
    .evidence-tag {
        font-family: monospace;
        background-color: #F1F5F9;
        padding: 4px 8px;
        border-radius: 4px;
        display: block;
        margin-bottom: 4px;
        font-size: 0.88rem;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_client() -> BackendAPIClient:
    """Return cached backend client instance."""
    api_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    return BackendAPIClient(base_url=api_url)


client = get_client()

# Sidebar: System Status & Sample Logs
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=64)
    st.title("DevOpsLens AI")
    st.markdown("**Version:** `1.0.0`")

    st.markdown("---")
    st.subheader("System Health")
    health = client.check_health()

    status_icon = "🟢" if health.get("status") == "healthy" else ("🟡" if health.get("status") == "degraded" else "🔴")
    st.write(f"{status_icon} **Backend:** `{health.get('status', 'offline').upper()}`")
    st.write(f"💾 **SQLite Database:** `{'Connected' if health.get('database_connected') else 'Disconnected'}`")

    ai_mode = "External LLM" if health.get("ai_enabled") else f"Deterministic Heuristic ({health.get('ai_provider', 'offline')})"
    st.write(f"🤖 **AI Mode:** `{ai_mode}`")

    st.markdown("---")
    st.subheader("Quick Sample Logs")
    sample_choice = st.selectbox(
        "Load sample log file:",
        ["Select a sample...", "Production Web App", "Auth Microservice", "ETL Data Pipeline", "Malformed Edge Cases"]
    )

    sample_mapping = {
        "Production Web App": "sample_logs/web_app_production.log",
        "Auth Microservice": "sample_logs/microservice_auth.log",
        "ETL Data Pipeline": "sample_logs/data_pipeline.log",
        "Malformed Edge Cases": "sample_logs/malformed_sample.log",
    }

# Main Application Header
st.markdown('<div class="main-header">DevOpsLens AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Intelligent Log Analysis, Severity Grouping, Transparent Ranking & AI Triage</div>',
    unsafe_allow_html=True
)

tab_live, tab_history, tab_architecture = st.tabs(["📊 Log Analysis", "📁 Analysis History", "🏛️ System Architecture"])

# ----------------- TAB 1: LIVE ANALYSIS -----------------
with tab_live:
    # Handle sample file loading or manual file upload
    uploaded_file = st.file_uploader(
        "Upload server or application log file (.log, .txt):",
        type=["log", "txt"],
        help="Upload standard application logs. Maximum size: 5 MB."
    )

    file_bytes = None
    file_name = None

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_name = uploaded_file.name
    elif sample_choice != "Select a sample..." and sample_choice in sample_mapping:
        sample_path = sample_mapping[sample_choice]
        if os.path.exists(sample_path):
            with open(sample_path, "rb") as f:
                file_bytes = f.read()
            file_name = os.path.basename(sample_path)
            st.info(f"Loaded sample file: `{file_name}` ({len(file_bytes)} bytes)")

    if file_bytes and file_name:
        if st.button("🚀 Analyze Log File", type="primary", use_container_width=True):
            with st.spinner("Parsing logs, grouping errors, and computing transparent priority rankings..."):
                try:
                    analysis_data = client.analyze_log(filename=file_name, file_bytes=file_bytes)
                    st.session_state["current_analysis"] = analysis_data
                    st.success(f"Analysis completed in {analysis_data['summary']['execution_time_ms']} ms!")
                except Exception as e:
                    st.error(f"Analysis failed: {str(e)}")

    # Display Analysis Results
    if "current_analysis" in st.session_state:
        data = st.session_state["current_analysis"]
        summary = data["summary"]
        error_groups = data.get("error_groups", [])

        st.markdown("---")
        st.subheader(f"Analysis Report: `{summary['filename']}`")
        st.caption(f"Analysis ID: `{summary['id']}` | Uploaded at: {summary['uploaded_at']}")

        # Metric Cards
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Lines", f"{summary['total_lines']:,}")
        with col2:
            st.metric("Errors", summary["error_count"], delta_color="inverse")
        with col3:
            st.metric("Critical Events", summary["critical_count"], delta_color="inverse")
        with col4:
            st.metric("Warnings", summary["warning_count"])
        with col5:
            st.metric("Unique Issue Groups", len(error_groups))

        # Severity Distribution Chart
        st.markdown("#### Severity Breakdown")
        chart_data = pd.DataFrame([
            {"Severity": "CRITICAL", "Count": summary["critical_count"]},
            {"Severity": "ERROR", "Count": summary["error_count"]},
            {"Severity": "WARNING", "Count": summary["warning_count"]},
            {"Severity": "INFO", "Count": summary["info_count"]},
            {"Severity": "DEBUG", "Count": summary["debug_count"]},
            {"Severity": "UNSTRUCTURED", "Count": summary["unstructured_count"]},
        ])
        # Filter out 0 counts for clean chart
        chart_data = chart_data[chart_data["Count"] > 0]
        if not chart_data.empty:
            st.bar_chart(chart_data.set_index("Severity"))

        # Issue Triage & Ranking Section
        st.markdown("---")
        st.subheader("🎯 Issue Triage & Incident Ranking")
        st.caption("Issues are grouped by normalized fingerprint and ranked using transparent, rule-based scoring.")

        if not error_groups:
            st.success("🎉 No warnings, errors, or critical issues detected in this log file!")
        else:
            # Filters
            fcol1, fcol2 = st.columns([1, 1])
            with fcol1:
                selected_severity = st.selectbox(
                    "Filter by Severity:",
                    ["ALL", "CRITICAL", "ERROR", "WARNING"]
                )
            with fcol2:
                selected_priority = st.selectbox(
                    "Filter by Priority:",
                    ["ALL", "P1 - Critical", "P2 - High", "P3 - Medium", "P4 - Low"]
                )

            filtered_groups = error_groups
            if selected_severity != "ALL":
                filtered_groups = [g for g in filtered_groups if g["severity"].upper() == selected_severity]
            if selected_priority != "ALL":
                filtered_groups = [g for g in filtered_groups if g["priority"] == selected_priority]

            st.write(f"Showing **{len(filtered_groups)}** of {len(error_groups)} issue groups:")

            # Error Table / Expanders
            for idx, group in enumerate(filtered_groups, start=1):
                p_label = group["priority"]
                color_class = "priority-badge-p1" if "P1" in p_label else (
                    "priority-badge-p2" if "P2" in p_label else (
                        "priority-badge-p3" if "P3" in p_label else "priority-badge-p4"
                    )
                )

                header_text = f"#{idx} [{group['priority']}] {group['severity']} — {group['sample_message'][:90]}... ({group['count']}x)"

                with st.expander(header_text, expanded=(idx == 1)):
                    st.markdown(f"**Normalized Fingerprint:** `{group['fingerprint']}`")
                    st.markdown(f"**Sample Message:** `{group['sample_message']}`")

                    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                    with mcol1:
                        st.markdown(f"**Priority:** <span class='{color_class}'>{group['priority']}</span>", unsafe_allow_html=True)
                    with mcol2:
                        st.write(f"**Occurrences:** `{group['count']}`")
                    with mcol3:
                        st.write(f"**Score:** `{group['score']:.1f}`")
                    with mcol4:
                        st.write(f"**Lines:** `{group['first_line']}` to `{group['last_line']}`")

                    st.info(f"💡 **Scoring Calculation:** {group['scoring_explanation']}")
                    st.write(f"**Observed on source lines:** `{group['line_numbers']}`")

                    # AI Root-Cause Diagnosis Trigger
                    diag_key = f"diag_{summary['id']}_{group['id']}"
                    if st.button("🤖 Run Root-Cause Diagnosis", key=f"btn_{group['id']}"):
                        with st.spinner("Analyzing incident context and verifying evidence against log lines..."):
                            try:
                                diag_result = client.request_diagnosis(
                                    analysis_id=summary["id"],
                                    error_group_id=group["id"]
                                )
                                st.session_state[diag_key] = diag_result
                            except Exception as diag_err:
                                st.error(f"Diagnosis failed: {diag_err}")

                    # Render Diagnosis Card if available
                    if diag_key in st.session_state:
                        diag = st.session_state[diag_key]
                        st.markdown("""
                        <div class="diagnosis-box">
                            <h4 style="color: #166534; margin-top: 0;">🔬 Root-Cause Diagnosis</h4>
                        </div>
                        """, unsafe_allow_html=True)

                        st.markdown(f"**Probable Cause (Hypothesis):** {diag['probable_cause']}")

                        st.markdown("**Supporting Evidence (Cited from Log):**")
                        for ev in diag.get("supporting_evidence", []):
                            st.markdown(f"<div class='evidence-tag'>📌 {ev}</div>", unsafe_allow_html=True)

                        st.markdown("**Actionable Debugging Steps:**")
                        for step_idx, step in enumerate(diag.get("debugging_steps", []), start=1):
                            st.markdown(f"{step_idx}. {step}")

                        st.markdown(f"**Confidence Rating:** `{diag.get('confidence')}`")
                        st.warning(f"⚠️ **Limitations & Disclaimer:** {diag.get('limitations')}")
                        st.caption(f"Triage Engine: `{diag.get('model_used')}`")

        # Export Buttons
        st.markdown("---")
        st.subheader("📥 Export Analysis Report")
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            try:
                json_str = client.export_report(analysis_id=summary["id"], format_type="json")
                st.download_button(
                    label="Download JSON Report",
                    data=json_str,
                    file_name=f"{summary['id']}_report.json",
                    mime="application/json",
                    use_container_width=True
                )
            except Exception as e:
                st.caption(f"JSON export unavailable: {e}")

        with exp_col2:
            try:
                csv_str = client.export_report(analysis_id=summary["id"], format_type="csv")
                st.download_button(
                    label="Download CSV Error Summary",
                    data=csv_str,
                    file_name=f"{summary['id']}_errors.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            except Exception as e:
                st.caption(f"CSV export unavailable: {e}")

# ----------------- TAB 2: HISTORICAL ANALYSES -----------------
with tab_history:
    st.subheader("Historical Log Analyses")
    st.caption("Review past analyses stored in the SQLite database.")

    analyses = client.get_analyses(limit=25)
    if not analyses:
        st.info("No past analyses found. Upload a log in the first tab to begin!")
    else:
        history_df = pd.DataFrame([
            {
                "ID": a["id"],
                "Filename": a["filename"],
                "Uploaded At": a["uploaded_at"][:19],
                "Lines": a["total_lines"],
                "Criticals": a["critical_count"],
                "Errors": a["error_count"],
                "Warnings": a["warning_count"],
                "Duration (ms)": a["execution_time_ms"]
            }
            for a in analyses
        ])
        st.dataframe(history_df, use_container_width=True)

        selected_id = st.selectbox("Select an analysis to reload:", [a["id"] for a in analyses])
        if st.button("📂 Load Selected Analysis"):
            with st.spinner("Fetching analysis record..."):
                selected_data = client.get_analysis_details(selected_id)
                if selected_data:
                    st.session_state["current_analysis"] = selected_data
                    st.success(f"Loaded analysis `{selected_id}`! Switch to the 'Log Analysis' tab to view details.")
                else:
                    st.error("Failed to load selected analysis.")

# ----------------- TAB 3: SYSTEM ARCHITECTURE -----------------
with tab_architecture:
    st.subheader("DevOpsLens AI Architecture & Design")
    st.markdown("""
    ### 🏛️ Layered Modular Architecture
    1. **Presentation Layer (Streamlit):** Reactive dashboard for log ingestion, metric visualization, and triage exploration.
    2. **API Layer (FastAPI):** Type-safe REST endpoints (`/health`, `/analyze`, `/analyses`) with Pydantic request/response validation.
    3. **Parser Service (`LogParser`):** Regex-based timestamp extraction, standard severity mapping (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`), and unstructured line handling.
    4. **Analysis Service (`LogAnalyzer`):** Deterministic dynamic fingerprinting (`<UUID>`, `<IP>`, `<HEX>`, `<NUM>`) and transparent priority scoring.
    5. **Database Layer (SQLite + WAL):** Thread-safe transactional persistence with foreign key cascade integrity.
    6. **AI Layer (`AIDiagnosisClient`):** Dual-mode root-cause triage (offline heuristic engine vs. external LLM) with strict evidence grounding validation.

    ### 🧮 Transparent Priority Scoring Formula
    $$\\text{Total Score} = \\text{Base Severity} + \\text{Frequency Factor} + \\text{Keyword Boost}$$
    - **Base Severity:** `CRITICAL` = 100, `ERROR` = 60, `WARNING` = 30, `UNSTRUCTURED` = 10
    - **Frequency Factor:** $\\min(\\text{count} \\times 3, 40)$ points
    - **Critical Keyword Boost:** $+15$ points for database, timeout, deadlock, OOM, connection refused
    - **Tiers:**
      - $\\ge 110$: **P1 - Critical**
      - $\\ge 80$: **P2 - High**
      - $\\ge 45$: **P3 - Medium**
      - $< 45$: **P4 - Low**
    """)
