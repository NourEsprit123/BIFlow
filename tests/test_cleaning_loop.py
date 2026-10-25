import json
from pathlib import Path
import pandas as pd
import pytest
from agents.dataCleaning_agent import DataCleaningAgent

@pytest.fixture(autouse=True)
def offline(monkeypatch): monkeypatch.setattr('agents.dataCleaning_agent.sandbox_status',lambda:{})

def report(tmp_path):
    source=tmp_path/'input.csv';pd.DataFrame({'flag':['Yes','No']}).to_csv(source,index=False)
    return {'dataset_ref':{'file_path':str(source),'file_name':source.name,'rows':2,'columns':1},
        'column_profiles':{'flag':{'dtype':'str','etl_cast_to':'boolean'}}}
def action(name,**args): return {'content':None,'tool_calls':[{'id':name,'name':name,'arguments':args}]}
def run(tmp_path,monkeypatch,respond,**settings):
    monkeypatch.setattr('agents.dataCleaning_agent.chat_with_tools',respond)
    return DataCleaningAgent(data_root=tmp_path/'versions',use_llm=True,**settings).run(report(tmp_path))

def test_flat_tools_stay_constant_and_apply_needs_no_review_turn(tmp_path,monkeypatch):
    calls=[]
    def respond(messages,tools,**kwargs):
        calls.append(messages)
        assert {t['function']['name'] for t in tools}=={'inspect_data','test_method','apply_candidate','flag_for_review','finish'}
        if len(calls)==1: return action('test_method',hypothesis='Yes/No flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
        result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        if len(calls)==2: return action('apply_candidate',candidate_id=result['candidate_id'],assessment='Both values parsed in the full copy')
        return action('finish',summary='Flag prepared')
    result=run(tmp_path,monkeypatch,respond)
    assert result.validation.all_passed and len(calls)==3 and result.metadata['stop_reason']=='completed'

def test_three_empty_responses_are_bounded(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:{'content':'I will clean','tool_calls':[]})
    assert result.metadata['stop_reason']=='no_tool_calls' and result.metadata['turns_used']==3
    assert not result.validation.all_passed

def test_repeated_inspection_is_bounded(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:action('inspect_data',view='schema'))
    assert result.metadata['stop_reason']=='stalled' and result.metadata['turns_used']==3

def test_finish_rechecks_once_and_then_stops(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:action('finish',summary='Unable to resolve flag'))
    assert result.metadata['turns_used']==2 and result.metadata['stop_reason']=='incomplete'
    assert not result.validation.all_passed

def test_flagging_finishes_with_visible_exceptions_not_full_success(tmp_path,monkeypatch):
    calls=iter([action('flag_for_review',columns=['flag'],reason='Meaning undocumented'),action('finish',summary='Needs human review')])
    result=run(tmp_path,monkeypatch,lambda *a,**k:next(calls))
    assert result.metadata['stop_reason']=='completed_with_exceptions'
    assert result.validation.exceptions and not result.validation.all_passed
    assert result.validation.status.value=='partial' and result.final_dataset.status.value=='working'

def test_provider_error_is_persisted(tmp_path,monkeypatch):
    def respond(*a,**k): raise RuntimeError('synthetic provider failure')
    result=run(tmp_path,monkeypatch,respond)
    assert result.metadata['stop_reason']=='provider_error'
    trace=json.loads(Path(result.metadata['result_path']).with_name('execution_trace.json').read_text())
    assert trace['provider_errors'][0]['message']=='synthetic provider failure'

@pytest.mark.parametrize('code,count',[('tool_use_failed',2),('other',1)])
def test_format_retry_is_bounded(tmp_path,monkeypatch,code,count):
    class BadResponse(ValueError):
        status_code=400
        body={'code':code}
    calls=[]
    def respond(*a,**k): calls.append(1);raise BadResponse('invalid response')
    result=run(tmp_path,monkeypatch,respond)
    assert len(calls)==count and result.metadata['stop_reason']=='provider_error'

def test_time_budget_prevents_a_late_tool_call(tmp_path,monkeypatch):
    now=[100.0]
    monkeypatch.setattr('agents.dataCleaning_agent.time.monotonic',lambda:now[0])
    def respond(*a,**k): now[0]=106;return action('test_method',hypothesis='Flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
    result=run(tmp_path,monkeypatch,respond,max_seconds=5)
    assert result.metadata['stop_reason']=='time_budget' and not result.change_log.entries

def test_saved_run_recovers_after_session_loss_but_not_after_data_or_profile_changes(tmp_path, monkeypatch):
    import dashboard.workspace as workspace
    source = tmp_path / "sample.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}
    original = DataCleaningAgent(data_root=tmp_path / "data/versions/dashboard", use_llm=False).run(report)
    monkeypatch.setattr(workspace, "ROOT", tmp_path)
    monkeypatch.setattr(workspace.st, "session_state", {})
    recovered = workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source)
    assert recovered.run_id == original.run_id
    workspace.st.session_state.clear()
    workspace.st.session_state[workspace.PROFILE_STATE_KEY] = {
        "signature": workspace.dataset_signature(source),
        "result": {"profiling_report": {**report, "agent_summary": "New interpretation"}},
    }
    assert workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source) is None
    workspace.st.session_state.clear()
    source.write_text("value\n100\n200\n", encoding="utf-8")
    assert workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source) is None
