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

def test_successful_trial_applies_before_the_next_model_turn(tmp_path,monkeypatch):
    calls=[]
    def respond(messages,tools,**kwargs):
        calls.append(messages)
        assert {t['function']['name'] for t in tools}=={'inspect_data',"test_builtin",'test_generated','apply_candidate','flag_for_review','complete_task','finish'}
        guide=json.loads(messages[-1]['content'])['request_guide']
        assert '<column>' not in guide
        if len(calls)==1:
            assert 'always include reason AND view' in guide and 'supply operation explicitly' in guide
            assert '"flag"' in guide
            return action("test_builtin",hypothesis='Yes/No flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
        assert 'Call finish' in guide
        context=json.loads(messages[-1]['content'])
        assert context['cleaning_focus']['category']=='validation'
        assert context['working_context']['version']=='V2'
        assert context['working_context']['completed_actions'][0]['columns']==['flag']
        assert not context['outstanding']['pending_types']
        assert pd.read_csv(tmp_path/'input.csv')['flag'].tolist()==['Yes','No']
        return action('finish',summary='Flag prepared')
    result=run(tmp_path,monkeypatch,respond)
    assert result.validation.all_passed and len(calls)==2 and result.metadata['stop_reason']=='completed'
    assert [event['tool'] for event in result.metadata['events']]==["test_builtin",'apply_candidate','finish']
    events=result.metadata['events']
    assert events[0]['origin']=='model' and events[0]['explanation']=='Yes/No flags'
    assert events[1]['origin']=='automatic_after_trial'
    assert events[0]['explanation'] in events[1]['explanation']


def test_failed_trial_never_auto_applies(tmp_path,monkeypatch):
    calls=[]
    def respond(messages,tools,**kwargs):
        calls.append(messages)
        if len(calls)==1:
            return action("test_builtin",hypothesis='Invalid numeric conversion',columns=['flag'],operation='convert_data_types',parameters={'target_type':'float','errors':'coerce'})
        return action('flag_for_review',columns=['flag'],reason='Needs review') if len(calls)==2 else action('finish',summary='Review needed')
    result=run(tmp_path,monkeypatch,respond)
    assert result.final_dataset.version=='V1'
    assert not result.change_log.successful_ops()
    assert 'apply_candidate' not in [event['tool'] for event in result.metadata['events']]


def test_auto_application_rechecks_full_data_before_commit(tmp_path,monkeypatch):
    from dataCleaningTools import workflow
    original=workflow.run_builtin
    executions=[]
    def changed(frame,operation,parameters):
        executions.append(1)
        output=original(frame,operation,parameters)
        if len(executions)==2:
            output.df['flag']=None
        return output
    monkeypatch.setattr(workflow,'run_builtin',changed)
    calls=[]
    def respond(messages,tools,**kwargs):
        calls.append(messages)
        if len(calls)==1:
            return action("test_builtin",hypothesis='Yes/No flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
        feedback=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        assert feedback['tested'] and not feedback['applied'] and not feedback['success']
        assert json.loads(messages[-1]['content'])['working_context']['columns']['flag']['steps']['type_conversion']['status']=='pending'
        return action('flag_for_review',columns=['flag'],reason='Full-data execution failed')
    result=run(tmp_path,monkeypatch,respond,max_turns=2)
    assert len(executions)==2 and result.final_dataset.version=='V1'
    assert not result.change_log.successful_ops()
    assert result.metadata['working_context']['columns']['flag']['steps']['type_conversion']['status']=='needs_review'
    assert not result.metadata['working_context']['completed_actions']

def test_three_empty_responses_drop_the_task_then_stop_without_one(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:{'content':'I will clean','tool_calls':[]})
    # Three on the task drop it; three more with no task left stop the run.
    assert [d['reason'] for d in result.metadata['task_drops']]==['no_tool_calls']
    assert result.metadata['stop_reason']=='no_tool_calls' and result.metadata['turns_used']==6
    assert not result.validation.all_passed

def test_repeated_inspection_is_bounded(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:action('inspect_data',view='schema',reason='Inspect current types'))
    assert result.metadata['stop_reason']=='inspection_stalled' and result.metadata['turns_used']<=7
    assert any(e['result'].get('task_deferred') for e in result.metadata['events'])

def test_finish_rechecks_once_and_then_stops(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,lambda *a,**k:action('finish',summary='Unable to resolve flag'))
    assert result.metadata['turns_used']==2 and result.metadata['stop_reason']=='incomplete'
    assert not result.validation.all_passed


@pytest.mark.parametrize('last_assessment',[{'unresolved':[]},{}])
def test_finish_replaces_resolved_assessment_and_preserves_audit_history(tmp_path,monkeypatch,last_assessment):
    responses=iter([
        action('finish',summary='Flag still needs conversion',unresolved=['flag']),
        action("test_builtin",hypothesis='Observed Yes/No flags encode binary values',columns=['flag'],
               operation='convert_data_types',parameters={'target_type':'boolean'}),
        action('finish',summary='Flag conversion verified',**last_assessment),
    ])
    result=run(tmp_path,monkeypatch,lambda *a,**k:next(responses))
    assert result.validation.all_passed and not result.unresolved_issues
    assert result.metadata['stop_reason']=='completed' and result.final_dataset.status.value=='validated'
    trace=json.loads(Path(result.metadata['result_path']).with_name('execution_trace.json').read_text())
    finishes=[event for event in trace['events'] if event['tool']=='finish']
    assert finishes[0]['arguments']['unresolved']==['flag']
    assert finishes[0]['result']['unresolved']==['flag']
    assert finishes[0]['result']['validation']['status']=='failed'
    assert finishes[1]['result']['previous_unresolved']==['flag']
    assert finishes[1]['result']['unresolved']==[]
    assert finishes[1]['result']['validation']['status']=='passed'
    assert trace['model_unresolved']==[] and result.metadata['model_unresolved']==[]

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
    def respond(*a,**k): now[0]=106;return action("test_builtin",hypothesis='Flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
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
