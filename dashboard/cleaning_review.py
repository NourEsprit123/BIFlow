"""Shared, readable cleaning trace for live runs and saved session results."""
from __future__ import annotations

import streamlit as st


def render_event(event: dict, evidence: dict | None = None) -> None:
    result = event["result"]
    evidence = evidence or event.get("evidence", {})
    outcome = ("No change" if result.get("no_op") else ("Trials passed" if result.get("tested") else "Trial failed") if event["tool"] in ("experiment_cleaning_method", "test_method", "test_builtin", "test_generated") and "tested" in result else "Awaiting approval" if result.get("approval_required") or result.get("approved") is False
               else "Rejected" if result.get("accepted") is False
               else "Failed" if result.get("success") is False
               else "Accepted" if result.get("accepted") else "Completed")
    label = f"{event['event_id']} Â· {event['tool']} Â· {outcome} Â· {event['source_version']} â†’ {event['version']}"
    if result.get("error_kind") == "duplicate_method":
        label = f"{event['event_id']} Â· {event['tool']} Â· Duplicate ({result.get('candidate_status', 'unknown')}) Â· {event['source_version']} â†’ {event['version']}"
    with st.expander(label, expanded=outcome in ("Rejected", "Failed", "Awaiting approval")):
        if event.get("duration_seconds") is not None:
            st.caption(f"Tool execution: {event['duration_seconds']:.2f}s")
        if event.get("explanation"):
            if event.get("origin") == "automatic_after_trial":
                st.caption("Automatic application Â· original model hypothesis and measured trial results")
            st.write("Action explanation: " + event["explanation"])
        if event.get("raw_arguments"):
            st.caption("Argument layout normalized to the public tool contract; original model arguments are retained in the JSON trace.")
        if event.get("stage"):
            st.caption(f"Stage: {event.get('source_stage', event['stage'])} â†’ {event['stage']}")
        if result.get("hypothesis"):
            st.write("Hypothesis: " + result["hypothesis"])
            st.write("Assumptions", result.get("assumptions", []))
        if event["tool"] == "apply_candidate":
            st.write("Assessment: " + event["arguments"].get("assessment", ""))
            if event["arguments"].get("next_change"):
                st.write("Proposed revision: " + event["arguments"]["next_change"])
        if result.get("revision_feedback"):
            st.warning("Returned to the LLM for reconsideration")
            st.json(result["revision_feedback"])
        if result.get("recovery_prompt"):
            guidance = result["recovery_prompt"]
            st.write("Guidance returned to the LLM Â· " + guidance["case"])
            st.write(guidance["instruction"])
            st.json(guidance["context"])
        if result.get("rationale"):
            st.write(result["rationale"])
        if result.get("failure_summary"):
            st.error(result["failure_summary"]["reason"])
            st.info(result["failure_summary"]["next_action"])
            if result["failure_summary"].get("lost_values"):
                st.write("All populated values that would become missing (not applied)")
                st.dataframe(result["failure_summary"]["lost_values"], hide_index=True, use_container_width=True)
        if result.get("no_op"):
            st.info(result["message"])
            st.json(result.get("progress", {}))
        st.write("Requested action")
        if event["arguments"].get("code"):
            st.code(event["arguments"]["code"], language="python")
            st.json({k: v for k, v in event["arguments"].items() if k != "code"})
        else:
            st.json(event["arguments"])
        if result.get("candidate_id"):
            st.caption(f"Candidate: {result['candidate_id']} Â· Code SHA-256: {result.get('code_hash', '')}")
        if result.get("expected_effect"):
            st.write(f"Expected effect: {result['expected_effect']}")
        for trial in result.get("trials", []):
            st.write(f"{trial['partition'].title()} trial Â· {trial['rows']} rows Â· {'Passed' if trial['success'] else 'Failed'}")
            if trial.get("error"):
                st.error(trial["error"])
            if trial.get("setup"):
                st.code(trial["setup"], language="text")
            if trial.get("effect"):
                trial_effect = trial["effect"]
                st.caption(f"Changed cells: {trial_effect['changed_cells']} Â· Rows removed: {trial_effect['rows_removed']}")
                st.dataframe(trial_effect["rules"], hide_index=True, use_container_width=True)
                if trial_effect.get("column_metrics"):
                    st.write("Column distributions before and after")
                    st.json(trial_effect["column_metrics"])
                if trial_effect.get("changed_examples"):
                    st.dataframe(trial_effect["changed_examples"], hide_index=True, use_container_width=True)
                if trial_effect.get("lost_values"):
                    st.write("All populated values that would become missing in this partition")
                    st.dataframe(trial_effect["lost_values"], hide_index=True, use_container_width=True)
        if result.get("trials"):
            st.info(result["message"])
            if result.get("holdout_available") is False:
                st.warning("This dataset has only one row; no independent holdout test was possible.")
        ids = result.get("evidence_ids", [])
        if ids:
            st.write("Supporting evidence")
            for evidence_id in ids:
                st.caption(evidence_id)
                if evidence and evidence_id in evidence:
                    st.json(evidence[evidence_id])
        effect = result.get("effect") or (result["details"].get("full_data_effect") if isinstance(result.get("details"), dict) else None)
        if effect:
            before, after = effect["before"], effect["after"]
            st.dataframe([
                {"Measurement": "Rows", "Before": before["rows"], "After": after["rows"]},
                {"Measurement": "Columns", "Before": before["columns"], "After": after["columns"]},
                {"Measurement": "Missing cells", "Before": sum(before["missing"].values()), "After": sum(after["missing"].values())},
                {"Measurement": "Duplicate rows", "Before": before["duplicate_rows"], "After": after["duplicate_rows"]},
            ], hide_index=True, use_container_width=True)
            st.caption(f"Changed cells: {effect['changed_cells'] if effect['changed_cells'] is not None else 'Not compared after row removal'} Â· Rows removed: {effect['rows_removed']}")
            affected = event["arguments"].get("columns") or [event["arguments"].get("column")]
            columns = [c for c in before["dtypes"] if c in affected or before["dtypes"].get(c) != after["dtypes"].get(c) or before["missing"].get(c) != after["missing"].get(c)]
            if columns:
                st.dataframe([{"Column": c, "Type before": before["dtypes"][c],
                               "Type after": after["dtypes"].get(c, "Removed"),
                               "Missing before": before["missing"][c],
                               "Missing after": after["missing"].get(c)} for c in columns],
                             hide_index=True, use_container_width=True)
            st.write("Acceptance checks")
            st.dataframe(effect["rules"], hide_index=True, use_container_width=True)
            if effect.get("changed_examples"):
                st.write("Examples of changed values (up to 5)")
                st.dataframe(effect["changed_examples"], hide_index=True, use_container_width=True)
            if effect.get("lost_values") and not result.get("failure_summary"):
                st.write("All populated values converted to missing" if result.get("accepted")
                         else "All populated values converted to missing in this candidate (not yet applied)")
                st.dataframe(effect["lost_values"], hide_index=True, use_container_width=True)
            if not effect["accepted"]:
                st.warning("Candidate rejected. The working dataset stayed at the previous version. Measurements above describe the rejected candidate.")
        if result.get("normalized_arguments"):
            st.caption("Type alias translated to supported tool arguments")
            st.json(result["normalized_arguments"])
        if result.get("recovery"):
            st.write("Recovery guidance")
            st.json(result["recovery"])
        if result.get("error"):
            st.error(str(result["error"]))
        if not effect and result.get("rules"):
            st.dataframe(result["rules"], hide_index=True, use_container_width=True)
        elif not effect and not result.get("trials"):
            st.json(result)


def render_pending_approvals(cleaning, *, key: str) -> None:
    from dataCleaningTools.approvals import pending
    from dashboard.workspace import resolve_cleaning_approvals, selected_dataset_path

    items = pending(cleaning)
    if not items:
        return
    st.subheader(f"Changes awaiting your approval ({len(items)})")
    st.caption("None of these has been applied. Approving re-tests the recorded method on the current version and "
               "commits it only if the same checks pass. Rejecting keeps the data. No model is called.")
    decisions = {}
    for item in items:
        impact = item.get("impact") or {}
        with st.container(border=True):
            st.write(f"**{item['category'].title()} · {', '.join(item['columns'])}** · "
                     + (item["operation"] or "generated method"))
            if impact.get("rows_changed") is not None:
                share = impact["rows_changed"] / impact["rows"] if impact["rows"] else 0
                st.caption(f"Would change {impact['rows_changed']:,} of {impact['rows']:,} rows ({share:.1%})")
            elif impact.get("rows_after") is not None:
                st.caption(f"Would keep {impact['rows_after']:,} of {impact['rows']:,} rows")
            if impact.get("dtype_changes"):
                st.caption("Type changes: " + ", ".join(f"{c}: {d}" for c, d in impact["dtype_changes"].items()))
            if item.get("hypothesis"):
                st.write("Model's reason: " + item["hypothesis"])
            if item.get("code"):
                with st.expander("Generated code"):
                    st.code(item["code"], language="python")
            elif item.get("parameters"):
                st.json({k: v for k, v in item["parameters"].items() if k not in ("column", "columns", "subset")})
            decisions[item["step_id"]] = st.radio("Decision", ["Leave pending", "Approve", "Reject"],
                                                  key=f"{key}_approval_{item['step_id']}", horizontal=True)
    chosen = {step: choice.lower() for step, choice in decisions.items() if choice != "Leave pending"}
    if st.button("Apply decisions", type="primary", disabled=not chosen, key=f"{key}_apply_approvals"):
        path = selected_dataset_path()
        with st.spinner("Re-testing approved changes and revalidating the dataset..."):
            resolve_cleaning_approvals(path, cleaning, chosen)
        st.rerun()


def render_cleaning_result(cleaning, *, key: str = "cleaning_review") -> None:
    render_pending_approvals(cleaning, key=key)
    st.subheader("Cleaning run: decisions and measured effects")
    st.caption(f"Mode: {cleaning.metadata.get('mode', 'unknown')} Â· Run: {cleaning.run_id} Â· Final version: {cleaning.final_dataset.version}")
    (st.success if cleaning.validation.all_passed else st.warning)(
        f"Final validation: {cleaning.validation.status.value}. "
        + ("All required checks passed." if cleaning.validation.all_passed else "Review the checks and unresolved items below.")
    )
    st.write(cleaning.metadata.get("finish_summary", ""))
    report_summary = cleaning.metadata.get("report_summary")
    if report_summary:
        with st.expander("Cleaning report Â· measured before and after"):
            st.json(report_summary)
            st.caption("Saved report: " + cleaning.metadata["report_path"])
        st.download_button("Download cleaning report (JSON)", cleaning.model_dump_json(indent=2),
            file_name=f"{cleaning.source_dataset.dataset_id}_cleaning_report.json", mime="application/json", key=key + "_report")
    if cleaning.metadata.get("report_export_error"):
        st.warning("Cleaning result saved, but report export failed: " + cleaning.metadata["report_export_error"])
    working_context = cleaning.metadata.get("working_context", {})
    if working_context:
        with st.expander("Working report Â· cleaning progress"):
            st.caption("Per-run progress checked against the working dataset. The original profiling report is unchanged.")
            rows = [{"Column": column, "Step": step, "Status": details["status"],
                     "Checked version": details["verified_version"],
                     "Target / remaining": str(details.get("target", details.get("remaining", "")))}
                    for column, item in working_context.get("columns", {}).items()
                    for step, details in item.get("steps", {}).items()]
            if rows:
                st.dataframe(rows, hide_index=True, use_container_width=True)
            st.json(working_context.get("completed_actions", []))
    for exception in cleaning.validation.exceptions:
        st.warning("Exception Â· " + exception)
    for switch in cleaning.metadata.get("provider_switches", []):
        st.warning(f"Switched to {switch['provider']} Â· {switch['model']} at turn {switch['turn']}: {switch['reason']}")
    if cleaning.metadata.get("stop_reason"):
        st.caption(f"Stop reason: {cleaning.metadata['stop_reason']} Â· Model: {cleaning.metadata.get('model') or 'deterministic'}")
    for error in cleaning.metadata.get("provider_errors", []):
        if error.get("recovered"):
            st.caption(f"Provider request error at turn {error['turn']} was retried successfully.")
            continue
        st.error(f"Provider failure at turn {error['turn']} ({error['type']}): {error['message']}")
    limits = cleaning.metadata.get("limits", {})
    if limits:
        st.caption(f"Model turns used: {cleaning.metadata.get('turns_used', 0)} / {limits['max_turns']} maximum Â· Elapsed: {cleaning.metadata.get('elapsed_seconds', 0):.0f}s / {limits['max_seconds']:.0f}s budget")
    inference = [step for step in cleaning.metadata.get("step_log", []) if step.get("timing")]
    if inference:
        with st.expander("Local model timing"):
            st.dataframe([{"Model turn": s["turn"], "Model": s.get("model"),
                           "Tool call format": s.get("tool_call_source", "not recorded"),
                           "Request seconds": round(s["timing"]["request_seconds"], 2),
                           "Model load seconds": s["timing"].get("load_seconds"),
                           "Prompt processing seconds": s["timing"].get("prompt_seconds"),
                           "Generation seconds": s["timing"].get("generation_seconds"),
                           "Tokens/second": s["timing"].get("tokens_per_second"),
                           "Prompt tokens": (s.get("usage") or {}).get("prompt_tokens"),
                           "Generated tokens": (s.get("usage") or {}).get("completion_tokens")}
                          for s in inference], hide_index=True, use_container_width=True)
    st.write("Final validation rules")
    if cleaning.validation.rules:
        st.dataframe([{"Check": r.rule_name, "Passed": r.passed, "Details": r.message}
                      for r in cleaning.validation.rules], hide_index=True, use_container_width=True)
    for issue in cleaning.unresolved_issues:
        st.warning(issue)
    experiments = cleaning.metadata.get("experiments", {})
    if experiments:
        st.write("Sandbox method experiments")
        st.dataframe([{"Candidate": key, "Base version": spec["base_version"],
                       "Trials passed": spec["tested"], "Columns": ", ".join(spec["columns"]),
                       "Expected effect": spec["expected_effect"], "Code hash": spec["code_hash"]}
                      for key, spec in experiments.items()], hide_index=True, use_container_width=True)
        st.caption("Passing sample/holdout trials does not apply a change. Promotion reruns the exact code on the full dataset.")
    events = cleaning.metadata.get("events", [])
    if events:
        st.write("Step-by-step execution")
        for event in events:
            render_event(event, cleaning.metadata.get("evidence", {}))
    else:
        st.info("This result predates detailed step tracking. Run cleaning again to capture a trace.")
    st.download_button("Download cleaning trace and validation", cleaning.model_dump_json(indent=2),
                       file_name=f"cleaning_{cleaning.run_id}.json", mime="application/json", key=key)


def run_cleaning_with_progress(path):
    from dashboard.workspace import clean_profiled_dataset

    import time
    started = time.monotonic()
    with st.status("Data Cleaning Agent: inspecting and cleaning...", expanded=True) as status:
        st.write("Each transformation is checked before it can become the working version.")
        st.caption("A model turn chooses one or more tools. The displayed count is a maximum, not a target. Runs can finish earlier.")
        st.caption("Model inference runs locally in Ollama. Sandbox testing is separate. If a profiling report is missing, profiling runs first, outside the cleaning time budget.")
        def on_event(event):
            if "phase" in event:
                elapsed = time.monotonic() - started
                turn = event.get("turn", 0)
                maximum = event.get("max_turns", "?")
                label = (f"{event['phase']} Â· elapsed {elapsed:.0f}s" if event.get("stage") == "profiling"
                         else f"{event['phase']} Â· model turn {turn}/{maximum} max Â· elapsed {elapsed:.0f}s")
                status.update(label=label)
            else:
                render_event(event)
        result = clean_profiled_dataset(path, on_event=on_event)
        st.write(result.metadata.get("finish_summary", ""))
        for switch in result.metadata.get("provider_switches", []):
            st.warning(f"Switched to {switch['provider']} Â· {switch['model']} at turn {switch['turn']}: {switch['reason']}")
        for error in result.metadata.get("provider_errors", []):
            if error.get("recovered"):
                st.caption(f"Provider request error at turn {error['turn']} was retried successfully.")
                continue
            st.error(f"Provider failure at turn {error['turn']} ({error['type']}): {error['message']}")
        failed = [r for r in result.validation.rules if not r.passed]
        if failed:
            st.write("Remaining validation failures")
            st.dataframe([{"Check": r.rule_name, "Details": r.message} for r in failed], hide_index=True, use_container_width=True)
        status.update(label=f"Cleaning finished Â· validation {result.validation.status.value}",
                      state="complete" if result.validation.all_passed else "error", expanded=True)
    return result


def render_experiment_runtime():
    from dataCleaningTools.experiments import runtime_status, BUILD_COMMAND
    with st.expander("Generated cleaning methods Â· sandbox setup"):
        st.write("The agent can invent a transform(df) function, test it on sample and holdout copies, and promote it only after full-data checks. Generated code runs in Docker with no host mounts or network.")
        st.code(BUILD_COMMAND, language="powershell")
        if st.button("Check experiment runtime", key="check_experiment_runtime"):
            result = runtime_status()
            if result["available"]:
                st.success("Isolated experiment runtime is ready.")
                st.caption(f"Image: {result['image_id']}")
            else:
                st.warning(result["setup"])
                st.caption(result["error"])


def render_cleaning_limits():
    from dataCleaningTools.llm_client import default_model, positive_setting
    settings = st.session_state.get("cleaning_run_settings", {})
    with st.expander("Local model speed and run limits"):
        turns = st.number_input("Maximum model turns", min_value=1, max_value=100,
                               value=int(settings.get("max_turns", positive_setting("BIFLOW_CLEANING_MAX_TURNS", 12, True))), key="cleaning_turn_limit")
        minutes = st.number_input("Run time budget (minutes)", min_value=0.1, max_value=120.0, step=0.5,
                                 value=float(settings.get("max_seconds", positive_setting("BIFLOW_CLEANING_MAX_SECONDS", 300))) / 60, key="cleaning_minutes")
        st.session_state["cleaning_run_settings"] = {"max_turns": int(turns), "max_seconds": int(minutes * 60)}
        st.caption(f"Ollama only Â· {default_model()} Â· Request timeout: {positive_setting('BIFLOW_OLLAMA_TIMEOUT', 90):.0f}s Â· Context: {positive_setting('BIFLOW_OLLAMA_NUM_CTX', 8192, True):,} tokens Â· Maximum output: {positive_setting('BIFLOW_OLLAMA_NUM_PREDICT', 1024, True):,} tokens")
        st.write("A smaller turn limit bounds exploration; it does not make one model request faster. Leave sandbox experimentation unchecked for the quicker builtin-first behaviour.")
        st.code("ollama ps", language="powershell")
        st.caption("While a request is running, check PROCESSOR for GPU versus CPU offloading. The run trace records model-load, prompt-processing and generation times.")
        st.caption("The run budget is checked before model calls and tools, and before accepting a change. An already-running sandbox operation can take up to its own 60-second limit to return.")
