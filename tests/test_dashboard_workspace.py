import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import dashboard.workspace as workspace


def saved_profile(tmp_path, monkeypatch, *, legacy=False):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)
    monkeypatch.setattr(workspace.st, "session_state", {})
    source=tmp_path/'customers.csv'
    source.write_text('amount\n10\n20\n',encoding='utf-8')
    report={'schema_version':'2.1','dataset_ref':{'file_path':str(source.resolve()),
        'file_name':source.name,'rows':2,'columns':1,'size_bytes':source.stat().st_size},
        'column_profiles':{'amount':{'dtype':'int64','agent_reasoning':'Existing reasoning'}},
        'metadata':{'llm_status':'llm'}}
    if not legacy:
        report['metadata']['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    report_path=tmp_path/'data/reports/profilingReports/customers_profiling_report.json'
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report),encoding='utf-8')
    return source,report_path,report


@pytest.mark.parametrize('legacy',[False,True])
def test_saved_profiling_is_reused_without_constructing_an_agent(tmp_path,monkeypatch,legacy):
    source,report_path,report=saved_profile(tmp_path,monkeypatch,legacy=legacy)
    def unexpected():
        raise AssertionError('A matching saved report must not invoke the model')
    monkeypatch.setattr(workspace,'DataEngineeringAgent',unexpected)
    result=workspace.profile_dataset_for_workspace(source)
    assert result['reused_report'] and result['profiling_report']==report
    assert result['profile']['rows']==2 and result['report_path']==str(report_path)
    workspace.st.session_state.clear()
    assert workspace.get_workspace_result(workspace.PROFILE_STATE_KEY,source)['reused_report']
    assert 'no profiling LLM call' in workspace.profiling_execution_status(result)[1]


def test_saved_profile_hash_detects_changed_values_with_same_shape_and_size(tmp_path,monkeypatch):
    source,_,_=saved_profile(tmp_path,monkeypatch)
    source.write_text('amount\n11\n20\n',encoding='utf-8')
    assert workspace.load_saved_profile(source) is None


def test_profiling_uses_only_the_new_folder(tmp_path,monkeypatch):
    source,report_path,_=saved_profile(tmp_path,monkeypatch)
    legacy=tmp_path/'data/reports/customers_profiling_report.json'
    report_path.replace(legacy)
    assert workspace.load_saved_profile(source) is None
    legacy.replace(report_path)
    assert workspace.load_saved_profile(source)['report_path']==str(report_path)


def test_cached_report_reference_is_reloaded_from_current_folder(tmp_path,monkeypatch):
    source,report_path,report=saved_profile(tmp_path,monkeypatch)
    workspace.st.session_state[workspace.PROFILE_STATE_KEY]={
        'signature':workspace.dataset_signature(source),
        'result':{'report_path':str(tmp_path/'former_location.json'),'profiling_report':report}}
    loaded=workspace.get_workspace_result(workspace.PROFILE_STATE_KEY,source)
    assert loaded['report_path']==str(report_path) and loaded['reused_report']


@pytest.mark.parametrize('damage',['wrong_source','invalid_json','wrong_shape'])
def test_invalid_saved_reports_are_not_reused(tmp_path,monkeypatch,damage):
    source,report_path,report=saved_profile(tmp_path,monkeypatch)
    if damage=='wrong_source': report['dataset_ref']['file_path']=str(tmp_path/'other.csv')
    if damage=='wrong_shape': report['dataset_ref']['rows']=99
    report_path.write_text('broken' if damage=='invalid_json' else json.dumps(report),encoding='utf-8')
    assert workspace.load_saved_profile(source) is None


def test_explicit_refresh_bypasses_saved_profile(tmp_path,monkeypatch):
    source,_,_=saved_profile(tmp_path,monkeypatch)
    calls=[]
    expected={'profiling_report':{'agent_summary':'New reasoning'}}
    class FakeAgent:
        def run_audit(self,path):
            calls.append(path)
            return expected
    monkeypatch.setattr(workspace,'DataEngineeringAgent',FakeAgent)
    assert workspace.profile_dataset_for_workspace(source,refresh=True) is expected
    assert calls==[str(source.resolve())]


def test_upload_dataset_uses_local_storage_and_avoids_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "RAW_DATA", tmp_path)
    first_upload = SimpleNamespace(name="sales.csv", getvalue=lambda: b"amount\n1\n")
    second_upload = SimpleNamespace(name="sales.csv", getvalue=lambda: b"amount\n2\n")

    first = workspace.save_uploaded_dataset(first_upload)
    second = workspace.save_uploaded_dataset(second_upload)

    assert first == tmp_path / "sales.csv"
    assert second == tmp_path / "sales_1.csv"
    assert first.read_bytes() == b"amount\n1\n"
    assert second.read_bytes() == b"amount\n2\n"


def test_analysis_metrics_are_calculated_from_dataframe(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.st, "session_state", {})
    path = tmp_path / "customers.csv"
    path.write_text("Churn,amount\nYes,10\nNo,20\nYes,30\n,40\n", encoding="utf-8")
    frame = pd.DataFrame(
        {
            "Churn": ["Yes", "No", "Yes", None],
            "amount": [10.0, 20.0, 30.0, 40.0],
        }
    )

    result = workspace.analyze_dataframe(frame, path)

    assert result["rows"] == 4
    assert result["columns"] == 2
    assert result["numeric_columns"] == 1
    assert result["churn_count"] == 2
    assert round(result["churn_rate"], 2) == 66.67


def test_workspace_profiling_uses_the_configured_agent_client(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.st, "session_state", {})
    path = tmp_path / "customers.csv"
    path.write_text("amount\n10\n", encoding="utf-8")
    observed = {}
    expected = {"profile": {"rows": 1}, "profiling_report": {"agent_summary": "LLM"}}

    class FakeProfilingAgent:
        def __init__(self, **kwargs):
            observed["constructor"] = kwargs

        def run_audit(self, file_path):
            observed["path"] = file_path
            return expected

    monkeypatch.setattr(workspace, "DataEngineeringAgent", FakeProfilingAgent)

    result = workspace.profile_dataset_for_workspace(path)

    assert result is expected
    assert observed == {"constructor": {}, "path": str(path.resolve())}
    assert workspace.get_workspace_result(workspace.PROFILE_STATE_KEY, path) is expected


def test_cleaning_workspace_uses_fresh_validated_profiling_report(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(workspace.st, "session_state", {})
    path = tmp_path / "customers.csv"
    path.write_text("amount\n10\n", encoding="utf-8")
    expected_report = {"schema_version": "2.1"}
    calls = {}
    workspace.st.session_state[workspace.PROFILE_STATE_KEY] = {
        "signature": (str(path.resolve()), 0, 1),
        "result": {"profiling_report": {"schema_version": "stale"}},
    }

    class FakeProfilingAgent:
        def __init__(self, **kwargs):
            pass

        def run_audit(self, file_path):
            calls["profiled_path"] = file_path
            return {"profiling_report": expected_report}

    class FakeCleaningAgent:
        def __init__(self, **kwargs):
            calls["cleaner_options"] = kwargs

        def run(self, report, **kwargs):
            calls["report"] = report
            calls["run_options"] = kwargs
            return "cleaning-result"

    monkeypatch.setattr(workspace, "DataEngineeringAgent", FakeProfilingAgent)
    monkeypatch.setattr(workspace, "DataCleaningAgent", FakeCleaningAgent)

    result = workspace.clean_profiled_dataset(path)

    assert result == "cleaning-result"
    assert calls["profiled_path"] == str(path.resolve())
    assert calls["report"] is expected_report
    assert calls["cleaner_options"]["use_llm"] is None
    assert calls["run_options"]["user_request"]


def test_profile_report_verification_checks_saved_content_and_source(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    report = {
        "dataset_ref": {
            "file_path": str(source.resolve()),
            "rows": 1,
            "columns": 1,
        }
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    result = {
        "profiling_report": report,
        "report_path": str(report_path),
        "profile": {"rows": 1, "columns": 1},
    }

    verification = workspace.verify_profiling_report(source, result)

    assert verification["verified"] is True
    assert len(verification["sha256"]) == 64

    report_path.write_text('{"tampered": true}', encoding="utf-8")
    verification = workspace.verify_profiling_report(source, result)

    assert verification["verified"] is False
    assert "content" in verification["reason"]
