"""Shared, readable cleaning trace for live runs and saved session results."""
from __future__ import annotations

from html import escape

import streamlit as st

TONE = {"done": "green", "reviewed": "green", "not_required": "green", "awaiting_approval": "amber",
        "needs_review": "amber", "pending": "blue", "dropped": "red", "blocked": "gray"}
STATE_TONE = {"done": "green", "waiting": "amber", "failed": "red", "none": "gray"}
STATE_TEXT = {"done": "Done", "waiting": "Open", "failed": "Failed", "none": "No findings"}
SHORT_TITLE = {"understanding": "Understand", "formatting": "Formatting", "types": "Types", "duplicates": "Duplicates",
               "missing": "Missing values", "outliers": "Outliers", "domain": "Domain rules", "validation": "Validation"}


def _html(markup: str) -> None:
    st.markdown("\n".join(line.strip() for line in markup.splitlines() if line.strip()), unsafe_allow_html=True)


def _badge(text, tone="gray"):
    return f'<span class="bf-badge {tone}">{escape(str(text))}</span>'


def _meter(value, total, color="#4f46e5"):
    share = 0 if not total else max(0, min(100, round(100 * value / total)))
    return f'<div class="bf-bar"><span style="width:{share}%;background:{color}"></span></div>'


def render_event(event: dict, evidence: dict | None = None, *, nested: bool = False) -> None:
    result = event["result"]
    evidence = evidence or event.get("evidence", {})
    outcome = ("No change" if result.get("no_op") else ("Trials passed" if result.get("tested") else "Trial failed") if event["tool"] in ("experiment_cleaning_method", "test_method", "test_builtin", "test_generated") and "tested" in result else "Awaiting approval" if result.get("approval_required") or result.get("approved") is False
               else "Rejected" if result.get("accepted") is False
               else "Failed" if result.get("success") is False
               else "Accepted" if result.get("accepted") else "Completed")
    label = f"{event['event_id']} · {event['tool']} · {outcome} · {event['source_version']} → {event['version']}"
    if result.get("error_kind") == "duplicate_method":
        label = f"{event['event_id']} · {event['tool']} · Duplicate ({result.get('candidate_status', 'unknown')}) · {event['source_version']} → {event['version']}"
    frame = (st.container(border=True) if nested
             else st.expander(label, expanded=outcome in ("Rejected", "Failed", "Awaiting approval")))
    with frame:
        if nested:
            st.markdown(f"**{escape(label)}**")
        if event.get("duration_seconds") is not None:
            st.caption(f"Tool execution: {event['duration_seconds']:.2f}s")
        if event.get("explanation"):
            if event.get("origin") == "automatic_after_trial":
                st.caption("Automatic application · original model hypothesis and measured trial results")
            st.write("Action explanation: " + event["explanation"])
        if event.get("raw_arguments"):
            st.caption("Argument layout normalized to the public tool contract; original model arguments are retained in the JSON trace.")
        if event.get("stage"):
            st.caption(f"Stage: {event.get('source_stage', event['stage'])} → {event['stage']}")
        if result.get("hypothesis"):
            st.write("Hypothesis: " + result["hypothesis"])
            st.write("Assumptions", result.get("assumptions", []))
        if event["tool"] == "apply_candidate":
            st.write("Assessment: " + event["arguments"].get("assessment", ""))
            if event["arguments"].get("next_change"):
                st.write("Proposed revision: " + event["arguments"]["next_change"])
        if result.get("revision_feedback"):
            st.warning("Returned to the LLM for reconsideration")
            st.json(result["revision_feedback"], expanded=False)
        if result.get("recovery_prompt"):
            guidance = result["recovery_prompt"]
            st.write("Guidance returned to the LLM · " + guidance["case"])
            st.write(guidance["instruction"])
            st.json(guidance["context"], expanded=False)
        if result.get("rationale"):
            st.write(result["rationale"])
        if result.get("failure_summary"):
            st.error(result["failure_summary"]["reason"])
            st.info(result["failure_summary"]["next_action"])
            if result["failure_summary"].get("lost_values"):
                st.write("All populated values that would become missing (not applied)")
                st.dataframe(result["failure_summary"]["lost_values"], hide_index=True, width="stretch")
        if result.get("no_op"):
            st.info(result["message"])
            st.json(result.get("progress", {}), expanded=False)
        st.write("Requested action")
        if event["arguments"].get("code"):
            st.code(event["arguments"]["code"], language="python")
            st.json({k: v for k, v in event["arguments"].items() if k != "code"}, expanded=False)
        else:
            st.json(event["arguments"], expanded=False)
        if result.get("candidate_id"):
            st.caption(f"Candidate: {result['candidate_id']} · Code SHA-256: {result.get('code_hash', '')}")
        if result.get("expected_effect"):
            st.write(f"Expected effect: {result['expected_effect']}")
        for trial in result.get("trials", []):
            st.write(f"{trial['partition'].title()} trial · {trial['rows']} rows · {'Passed' if trial['success'] else 'Failed'}")
            if trial.get("error"):
                st.error(trial["error"])
            if trial.get("setup"):
                st.code(trial["setup"], language="text")
            if trial.get("effect"):
                trial_effect = trial["effect"]
                st.caption(f"Changed cells: {trial_effect['changed_cells']} · Rows removed: {trial_effect['rows_removed']}")
                st.dataframe(trial_effect["rules"], hide_index=True, width="stretch")
                if trial_effect.get("column_metrics"):
                    st.write("Column distributions before and after")
                    st.json(trial_effect["column_metrics"], expanded=False)
                if trial_effect.get("changed_examples"):
                    st.dataframe(trial_effect["changed_examples"], hide_index=True, width="stretch")
                if trial_effect.get("lost_values"):
                    st.write("All populated values that would become missing in this partition")
                    st.dataframe(trial_effect["lost_values"], hide_index=True, width="stretch")
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
                    st.json(evidence[evidence_id], expanded=False)
        effect = result.get("effect") or (result["details"].get("full_data_effect") if isinstance(result.get("details"), dict) else None)
        if effect:
            before, after = effect["before"], effect["after"]
            st.dataframe([
                {"Measurement": "Rows", "Before": before["rows"], "After": after["rows"]},
                {"Measurement": "Columns", "Before": before["columns"], "After": after["columns"]},
                {"Measurement": "Missing cells", "Before": sum(before["missing"].values()), "After": sum(after["missing"].values())},
                {"Measurement": "Duplicate rows", "Before": before["duplicate_rows"], "After": after["duplicate_rows"]},
            ], hide_index=True, width="stretch")
            st.caption(f"Changed cells: {effect['changed_cells'] if effect['changed_cells'] is not None else 'Not compared after row removal'} · Rows removed: {effect['rows_removed']}")
            affected = event["arguments"].get("columns") or [event["arguments"].get("column")]
            columns = [c for c in before["dtypes"] if c in affected or before["dtypes"].get(c) != after["dtypes"].get(c) or before["missing"].get(c) != after["missing"].get(c)]
            if columns:
                st.dataframe([{"Column": c, "Type before": before["dtypes"][c],
                               "Type after": after["dtypes"].get(c, "Removed"),
                               "Missing before": before["missing"][c],
                               "Missing after": after["missing"].get(c)} for c in columns],
                             hide_index=True, width="stretch")
            st.write("Acceptance checks")
            st.dataframe(effect["rules"], hide_index=True, width="stretch")
            if effect.get("changed_examples"):
                st.write("Examples of changed values (up to 5)")
                st.dataframe(effect["changed_examples"], hide_index=True, width="stretch")
            if effect.get("lost_values") and not result.get("failure_summary"):
                st.write("All populated values converted to missing" if result.get("accepted")
                         else "All populated values converted to missing in this candidate (not yet applied)")
                st.dataframe(effect["lost_values"], hide_index=True, width="stretch")
            if not effect["accepted"]:
                st.warning("Candidate rejected. The working dataset stayed at the previous version. Measurements above describe the rejected candidate.")
        if result.get("normalized_arguments"):
            st.caption("Type alias translated to supported tool arguments")
            st.json(result["normalized_arguments"], expanded=False)
        if result.get("recovery"):
            st.write("Recovery guidance")
            st.json(result["recovery"], expanded=False)
        if result.get("error"):
            st.error(str(result["error"]))
        if not effect and result.get("rules"):
            st.dataframe(result["rules"], hide_index=True, width="stretch")
        elif not effect and not result.get("trials"):
            st.json(result, expanded=False)


def render_pending_approvals(cleaning, *, key: str) -> None:
    from dataCleaningTools.approvals import pending
    from dashboard.workspace import resolve_cleaning_approvals, selected_dataset_path

    items = pending(cleaning)
    if not items:
        return
    st.subheader(f"Changes awaiting your approval ({len(items)})", anchor="approvals")
    st.caption("None of these has been applied. Approving re-tests the recorded method on the current version and "
               "commits it only if the same checks pass. Rejecting keeps the data. No model is called.")
    decisions = {}
    for item in items:
        impact = item.get("impact") or {}
        with st.container(border=True):
            st.markdown(f"**{escape(item['category'].title())} · {escape(', '.join(item['columns']))}** · "
                        + escape(item["operation"] or "generated method"))
            if impact.get("rows_changed") is not None:
                share = impact["rows_changed"] / impact["rows"] if impact["rows"] else 0
                _html(_meter(impact["rows_changed"], impact["rows"], "#f59e0b"))
                st.caption(f"Would change {impact['rows_changed']:,} of {impact['rows']:,} rows ({share:.1%})")
            elif impact.get("rows_after") is not None:
                _html(_meter(impact["rows"] - impact["rows_after"], impact["rows"], "#ef4444"))
                st.caption(f"Would keep {impact['rows_after']:,} of {impact['rows']:,} rows")
            if impact.get("dtype_changes"):
                st.caption("Type changes: " + ", ".join(f"{c}: {d}" for c, d in impact["dtype_changes"].items()))
            if item.get("hypothesis"):
                st.write("Model's reason: " + item["hypothesis"])
            if item.get("code"):
                with st.expander("Generated code"):
                    st.code(item["code"], language="python")
            elif item.get("parameters"):
                settings = {k: v for k, v in item["parameters"].items() if k not in ("column", "columns", "subset")}
                if settings:
                    st.caption("Settings: " + " · ".join(f"{k} = {v}" for k, v in settings.items()))
            decisions[item["step_id"]] = st.radio("Decision", ["Leave pending", "Approve", "Reject"],
                                                  key=f"{key}_approval_{item['step_id']}", horizontal=True)
    chosen = {step: choice.lower() for step, choice in decisions.items() if choice != "Leave pending"}
    if st.button("Apply decisions", type="primary", key=f"{key}_apply_approvals"):
        if not chosen:
            st.info("Choose Approve or Reject for at least one change first.")
            return
        path = selected_dataset_path()
        with st.spinner("Re-testing approved changes and revalidating the dataset..."):
            resolve_cleaning_approvals(path, cleaning, chosen)
        st.rerun()


def render_pending_decisions(cleaning, *, key: str) -> None:
    """Items only a person can settle: one card per affected column."""
    from dataCleaningTools.decisions import open_decisions
    from dashboard.workspace import resolve_cleaning_decisions, selected_dataset_path

    items = open_decisions(cleaning)
    if not items:
        return
    st.subheader(f"Needs your decision ({len(items)})", anchor="decisions")
    st.caption("The agent stopped on these instead of guessing. Accepting keeps the data as it is and records your "
               "reason in the report. Filling suggests values measured on the data, led by the profiling model's "
               "choice; it uses the same checked builtin and marks the cells in <column>_imputed. No model is called.")
    choices = {}
    for item in items:
        with st.container(border=True):
            title = escape(", ".join(item["columns"]) or "Whole dataset")
            st.markdown(f"**{title}**" + (f" · {item['missing']:,} blank value(s)" if item["missing"] else ""))
            st.write(item["summary"])
            tasks = " · ".join(f"{t['category'].title()} task {t['status'].replace('_', ' ')}" for t in item["tasks"])
            st.caption(tasks + (f" · Detail: {item['detail']}" if item["detail"] else ""))
            removal = f"Remove {item.get('duplicate_rows', 0):,} exact duplicate row(s)"
            options = (["Leave for later", "Accept as is"] + (["Fill with a value"] if item["can_fill"] else [])
                       + ([removal] if item.get("can_remove_duplicates") else []))
            choice = st.radio("Decision", options, key=f"{key}_decision_{item['key']}", horizontal=True)
            if choice == removal:
                st.caption("Only rows identical to an earlier row in every column are removed; the first copy is kept.")
                choices[item["key"]] = {"action": "remove_duplicates"}
            elif choice == "Accept as is":
                note = st.text_input("Reason (optional, saved in the report)", key=f"{key}_decision_note_{item['key']}",
                                     placeholder="These blanks are acceptable for this analysis")
                choices[item["key"]] = {"action": "accept", "note": note}
            elif choice == "Fill with a value":
                suggestions = item.get("suggestions") or []
                labels = [f"{s['label']} · {s['value']}" + (" (recommended)" if s["recommended"] else "") for s in suggestions]
                picked = st.radio("Fill with", labels + ["Custom value"], key=f"{key}_decision_fill_{item['key']}")
                if picked == "Custom value":
                    value = st.text_input("Fill value", key=f"{key}_decision_value_{item['key']}", placeholder="Value to put in the blank cells")
                    choices[item["key"]] = {"action": "fill", "value": value}
                else:
                    suggestion = suggestions[labels.index(picked)]
                    if suggestion["recommended"]:
                        st.caption(("Recommended by the profiling model: " + suggestion["reason"]) if suggestion["source"] == "profiling"
                                   else "Recommended by default for this column type; the profiling report gave no strategy.")
                    choices[item["key"]] = {"action": "fill", "strategy": suggestion["strategy"]}
    if st.button("Apply decisions", type="primary", key=f"{key}_apply_decisions"):
        if not choices:
            st.info("Choose Accept or Fill for at least one item first.")
            return
        if any(c["action"] == "fill" and "strategy" not in c and not c["value"].strip() for c in choices.values()):
            st.warning("Enter a fill value for each item you chose to fill.")
            return
        with st.spinner("Applying your decisions and revalidating the dataset..."):
            resolved = resolve_cleaning_decisions(selected_dataset_path(), cleaning, choices)
        failed = [d for d in resolved.metadata.get("host_decisions", [])[-len(choices):] if not d.get("applied")]
        if failed:
            st.session_state["cleaning_decision_errors"] = [f"{d['decision']}: {d.get('error')}" for d in failed]
        st.rerun()
    for message in st.session_state.pop("cleaning_decision_errors", []):
        st.error("Not applied · " + message)


def render_run_overview(summary) -> None:
    """Header, KPI tiles and the per-category progress strip."""
    status = summary["status"]
    banner = st.success if status == "passed" else st.error if status == "failed" else st.warning
    count = summary["needs_you"]
    needs = (f" · {count} decision{'s' if count != 1 else ''} need{'' if count != 1 else 's'} you: "
             + "; ".join(summary["needs_you_names"]) if count else "")
    accepted = summary.get("accepted") or []
    # A column the host accepted as it is stays visible next to the status instead of making the run partial.
    waived = (f" · {len(accepted)} column{'s' if len(accepted) != 1 else ''} accepted as is by you: "
              + ", ".join(accepted) if accepted else "")
    kept = summary.get("accepted_by_model") or []
    waived += (f" · {len(kept)} column{'s' if len(kept) != 1 else ''} kept as is by the model: " + ", ".join(kept)
               if kept else "")
    banner(f"Final validation: {status}{waived}{needs}. {summary['stop']}.")
    minutes, seconds = divmod(round(summary["seconds"]), 60)
    st.caption(f"Final version {summary['final_version']} · {summary['turns']} of {summary['max_turns']} model turns · "
               f"{minutes} min {seconds:02d} s · {summary['model'] or 'deterministic'}")
    k = summary["kpis"]
    tiles = [("Changes applied", k["applied"], "green"), ("Awaiting approval", k["awaiting"], "amber"),
             ("Dropped or blocked", k["dropped_or_blocked"], "red"), ("Values set to missing", k["set_to_missing"], "gray")]
    _html('<div class="bf-grid g4">' + "".join(
        f'<div class="bf-card bf-kpi"><div class="row"><span>{label}</span>{_badge(value, tone if value else "gray")}</div>'
        f'<div class="val">{value:,}</div></div>' for label, value, tone in tiles) + "</div>")
    cells = []
    for c in summary["categories"]:
        detail = f"{c['resolved']}/{c['total']}" if c["total"] else ""
        cells.append(f'<div style="text-align:center">{_badge(STATE_TEXT[c["state"]], STATE_TONE[c["state"]])}'
                     f'<div style="font-size:.8rem;margin-top:.35rem;color:#334155">{escape(SHORT_TITLE.get(c["key"], c["title"]))}</div>'
                     f'<div style="font-size:.75rem;color:#64748b">{detail}</div></div>')
    _html('<div class="bf-card"><div class="subt" style="margin-top:0">Progress by category</div>'
          '<div style="display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:.5rem">' + "".join(cells) + "</div></div>")


def render_task_board(summary) -> None:
    # Checks the data already met (done without a single model turn) are counted, not listed.
    shown = [t for t in summary["board"] if t["status"] != "done" or t["turns"] or t["version"]]
    already_met = len(summary["board"]) - len(shown)
    rows = []
    for task in shown:
        note = task["reason"] if task["status"] != "done" else ""
        if task["blocked_by"]:
            note = f"Blocked by {task['blocked_by']}"
        elif task["status"] == "awaiting_approval":
            note = "Waiting for your decision in “Changes awaiting your approval”"
        color = "#ef4444" if task["status"] == "dropped" else "#4f46e5"
        turns = f'{_meter(task["turns"], task["max_turns"], color)}<small>{task["turns"]} of {task["max_turns"]}</small>'
        rows.append(f'<tr><td>{escape(task["category"].title())}<small>{escape(task["id"])}</small></td>'
                    f'<td>{escape(", ".join(task["columns"]) or "dataset")}</td>'
                    f'<td>{_badge(task["status"].replace("_", " "), TONE.get(task["status"], "gray"))}</td>'
                    f'<td style="min-width:110px">{turns}</td><td>{escape(task["version"] or "–")}</td>'
                    f'<td><small>{escape(note[:160])}</small></td></tr>')
    if rows:
        met = f" · {already_met} check(s) the data already met are not listed" if already_met else ""
        _html(f'<div class="bf-card"><div class="subt" style="margin-top:0">Task board{met}</div><table class="bf-table">'
              '<thead><tr><th>Task</th><th>Columns</th><th>Status</th><th>Turns</th><th>Version</th><th>Note</th></tr></thead>'
              f'<tbody>{"".join(rows)}</tbody></table></div>')
    elif already_met:
        _html(f'<div class="bf-card"><div class="subt" style="margin:0">Task board · all {already_met} check(s) '
              'were already met by the data; nothing needed changing.</div></div>')


def render_versions_and_health(summary) -> None:
    chips = []
    for step in summary["trail"]:
        tone = "gray" if step["label"] in ("original", "working copy") else "purple" if step.get("approved") else "green"
        note = " · approved by you" if step.get("approved") else ""
        chips.append(f'<div style="display:flex;gap:.6rem;align-items:center;padding:.3rem 0;'
                     f'border-bottom:1px solid #f1f5f9">{_badge(step["version"], tone)}'
                     f'<span style="font-size:.85rem;color:#334155">{escape(step["label"])}{note}</span></div>')
    trail_html = "".join(chips)
    rows = []
    for h in summary["health"]:
        total = h["rows_before"] or 1
        before, after = h["missing_before"] or 0, h["missing_after"] or 0
        missing = (f'{_meter(before, total, "#93c5fd")}{_meter(after, total, "#4f46e5")}'
                   f'<small>{before:,} → {after:,}</small>')
        dtype = (escape(str(h["dtype_after"])) if h["dtype_before"] == h["dtype_after"]
                 else f'{escape(str(h["dtype_before"]))} → <b>{escape(str(h["dtype_after"]))}</b>')
        rows.append(f'<tr><td>{escape(h["column"])}</td><td style="min-width:120px">{missing}</td>'
                    f'<td>{dtype}</td><td>{h["values_changed"]:,}</td></tr>')
    if rows:
        health_html = ('<table class="bf-table"><thead><tr><th>Column</th><th>Missing before → after</th>'
                       f'<th>Type</th><th>Cells rewritten</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
    else:
        health_html = '<small style="color:#64748b">No column changed its missing values, type or contents.</small>'
    _html(f'<div class="bf-grid g12"><div class="bf-card"><div class="subt" style="margin-top:0">Version trail</div>'
          f'<div>{trail_html}</div></div>'
          f'<div class="bf-card"><div class="subt" style="margin-top:0">Column health</div>{health_html}</div></div>')


def render_trace(cleaning) -> None:
    """Events grouped by task; runs without a task queue keep one expander per event."""
    events, evidence = cleaning.metadata.get("events", []), cleaning.metadata.get("evidence", {})
    if not events:
        st.info("This result predates detailed step tracking. Run cleaning again to capture a trace.")
        return
    st.markdown("**Step-by-step trace**")
    if not any(e.get("task_id") for e in events):
        for event in events:
            render_event(event, evidence)
        return
    tasks = {t["id"]: t for t in cleaning.metadata.get("cleaning_tasks", [])}
    groups = {}
    for event in events:
        groups.setdefault(event.get("task_id") or "run", []).append(event)
    for task_id, group in groups.items():
        task = tasks.get(task_id)
        if task:
            title = (f"{task['category'].title()} · {', '.join(task['columns']) or 'dataset'} · "
                     f"{len(group)} action(s) · {task['status'].replace('_', ' ')}")
        else:
            title = f"Run · {len(group)} action(s)"
        with st.expander(title, expanded=bool(task) and task["status"] in ("dropped", "awaiting_approval")):
            for event in group:
                render_event(event, evidence, nested=True)


def render_cleaning_result(cleaning, *, key: str = "cleaning_review", approvals: bool = True) -> None:
    from dataCleaningTools.run_summary import summarize

    summary = summarize(cleaning)
    st.subheader("Cleaning run")
    render_run_overview(summary)
    if approvals:
        render_pending_approvals(cleaning, key=key)
        render_pending_decisions(cleaning, key=key)
    render_task_board(summary)
    render_versions_and_health(summary)
    downloads = st.columns(2)
    with downloads[0]:
        st.download_button("Download cleaning report (JSON)", cleaning.model_dump_json(indent=2),
                           file_name=f"{cleaning.source_dataset.dataset_id}_cleaning_report.json",
                           mime="application/json", key=key + "_report", width="stretch")
    with downloads[1]:
        st.download_button("Download cleaning trace and validation", cleaning.model_dump_json(indent=2),
                           file_name=f"cleaning_{cleaning.run_id}.json", mime="application/json", key=key, width="stretch")
    if cleaning.metadata.get("report_export_error"):
        st.warning("Cleaning result saved, but report export failed: " + cleaning.metadata["report_export_error"])
    for error in cleaning.metadata.get("provider_errors", []):
        if not error.get("recovered"):
            st.error(f"Provider failure at turn {error['turn']} ({error['type']}): {error['message']}")
    with st.expander("Validation rules and exceptions"):
        if cleaning.validation.rules:
            st.dataframe([{"Check": r.rule_name, "Passed": r.passed, "Details": r.message}
                          for r in cleaning.validation.rules], hide_index=True, width="stretch")
        for exception in cleaning.validation.exceptions:
            st.warning("Exception · " + exception)
        for issue in cleaning.unresolved_issues:
            st.caption(issue)
    inference = [step for step in cleaning.metadata.get("step_log", []) if step.get("timing")]
    if inference:
        with st.expander("Local model timing"):
            st.dataframe([{"Model turn": s["turn"], "Source": s.get("source", "main"),
                           "Request seconds": round(s["timing"]["request_seconds"], 2),
                           "Generation seconds": s["timing"].get("generation_seconds"),
                           "Tokens/second": s["timing"].get("tokens_per_second"),
                           "Prompt tokens": (s.get("usage") or {}).get("prompt_tokens"),
                           "Generated tokens": (s.get("usage") or {}).get("completion_tokens")}
                          for s in inference], hide_index=True, width="stretch")
    experiments = cleaning.metadata.get("experiments", {})
    if experiments:
        with st.expander("Sandbox method experiments"):
            st.dataframe([{"Candidate": name, "Base version": spec["base_version"],
                           "Trials passed": spec["tested"], "Columns": ", ".join(spec["columns"]),
                           "Code hash": spec["code_hash"]}
                          for name, spec in experiments.items()], hide_index=True, width="stretch")
            st.caption("Passing sample/holdout trials does not apply a change. "
                       "Promotion reruns the exact code on the full dataset.")
    render_trace(cleaning)


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
                label = (f"{event['phase']} · elapsed {elapsed:.0f}s" if event.get("stage") == "profiling"
                         else f"{event['phase']} · model turn {turn}/{maximum} max · elapsed {elapsed:.0f}s")
                status.update(label=label)
            else:
                render_event(event)
        result = clean_profiled_dataset(path, on_event=on_event)
        st.write(result.metadata.get("finish_summary", ""))
        for switch in result.metadata.get("provider_switches", []):
            st.warning(f"Switched to {switch['provider']} · {switch['model']} at turn {switch['turn']}: {switch['reason']}")
        for error in result.metadata.get("provider_errors", []):
            if error.get("recovered"):
                st.caption(f"Provider request error at turn {error['turn']} was retried successfully.")
                continue
            st.error(f"Provider failure at turn {error['turn']} ({error['type']}): {error['message']}")
        from dataCleaningTools.approvals import pending
        waiting = pending(result)
        if waiting:
            st.info(f"{len(waiting)} change(s) are waiting for your approval. Nothing was applied for them; "
                    "decide in “Changes awaiting your approval”.")
        failed = [r for r in result.validation.rules if not r.passed]
        if failed:
            st.write("Remaining validation failures")
            st.dataframe([{"Check": r.rule_name, "Details": r.message} for r in failed], hide_index=True, width="stretch")
        status.update(label=f"Cleaning finished · validation {result.validation.status.value}",
                      state="complete" if result.validation.all_passed else "error", expanded=False)
    return result


def render_experiment_runtime():
    from dataCleaningTools.experiments import runtime_status, BUILD_COMMAND
    with st.expander("Generated cleaning methods · sandbox setup"):
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


DECISION_MODES = {"in_the_loop": "Stay in the loop", "autonomous": "Let the model decide"}
DECISION_HELP = {
    "in_the_loop": "Changes that need approval, such as capping outliers, wait for you, and anything the agent "
                   "cannot settle comes to you as a decision on the Data Cleaning page.",
    "autonomous": "The model applies changes that normally need your approval once their trial passes, then settles "
                  "what is left: blanks get the recommended fill, anything else is kept as it is with its reason. "
                  "Every decision is listed in the report as the model's.",
}


def render_decision_mode(key: str) -> str:
    """Who takes the cleaning decisions; one choice shared by the Workflows and Data Cleaning pages."""
    current = st.session_state.get("cleaning_decision_mode", "in_the_loop")

    def remember():
        st.session_state["cleaning_decision_mode"] = st.session_state[key]

    with st.container(border=True):
        choice = st.radio("Cleaning decisions", list(DECISION_MODES), index=list(DECISION_MODES).index(current),
                          format_func=DECISION_MODES.get, key=key, horizontal=True, on_change=remember)
        st.caption(DECISION_HELP[choice])
    st.session_state["cleaning_decision_mode"] = choice
    return choice


def render_cleaning_limits():
    from dataCleaningTools.llm_client import default_model, positive_setting
    settings = st.session_state.get("cleaning_run_settings", {})
    with st.expander("Local model speed and run limits"):
        turns = st.number_input("Minimum model turns", min_value=1, max_value=100,
                               value=int(settings.get("max_turns", positive_setting("BIFLOW_CLEANING_MAX_TURNS", 12, True))), key="cleaning_turn_limit")
        minutes = st.number_input("Minimum run time (minutes)", min_value=0.1, max_value=120.0, step=0.5,
                                 value=float(settings.get("max_seconds", positive_setting("BIFLOW_CLEANING_MAX_SECONDS", 300))) / 60, key="cleaning_minutes")
        st.session_state["cleaning_run_settings"] = {"max_turns": int(turns), "max_seconds": int(minutes * 60)}
        st.caption(f"Both grow with the number of cleaning tasks: {positive_setting('BIFLOW_CLEANING_TURNS_PER_TASK', 3, True)} turns "
                   f"and {positive_setting('BIFLOW_CLEANING_SECONDS_PER_TASK', 30):.0f} s per task.")
        st.caption(f"Ollama only · {default_model()} · Request timeout: {positive_setting('BIFLOW_OLLAMA_TIMEOUT', 90):.0f}s · Context: {positive_setting('BIFLOW_OLLAMA_NUM_CTX', 8192, True):,} tokens · Maximum output: {positive_setting('BIFLOW_OLLAMA_NUM_PREDICT', 1024, True):,} tokens")
        st.write("A smaller turn limit bounds exploration; it does not make one model request faster. Leave sandbox experimentation unchecked for the quicker builtin-first behaviour.")
        st.code("ollama ps", language="powershell")
        st.caption("While a request is running, check PROCESSOR for GPU versus CPU offloading. The run trace records model-load, prompt-processing and generation times.")
        st.caption("The run budget is checked before model calls and tools, and before accepting a change. An already-running sandbox operation can take up to its own 60-second limit to return.")
