import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent, _tool_feedback
from dataCleaningTools.experiments import assess_method
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools import workflow


@pytest.fixture
def dirty(tmp_path):
    # Genuinely unparseable tokens; number phrases such as 'one thousand' are now parsed by the builtin.
    invalid = ['see notes', 'banana', 'ERROR_404', 'TBD', 'about a lot',
               'unparsed-a', 'unparsed-b', 'unparsed-b', 'x' * 250]
    source = tmp_path / 'sales.csv'
    pd.DataFrame({'Revenue': ['$10', '20', '1.5k', '$30', '40', '2k', *invalid, None],
                  'flag': ['Yes', 'No'] * 8}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / 'versions')
    original = manager.register_original(source, dataset_id='sales')
    state = AgentSessionState(manager=manager, dataset_id='sales', source_ref=original,
        current_ref=manager.create_working_copy(original), required_targets={'Revenue': 'float'})
    return state, ToolExecutor(state), invalid


def call(executor, name, **args):
    return json.loads(executor.execute(name, args))


def revenue_trial(executor):
    # An explicit no_missing outcome can still reject a candidate. This tests
    # failure evidence, independently of the removed blanket no_new_missing rule.
    return call(executor, "test_builtin", hypothesis='Parse observed currency and numeric formats',
        columns=['Revenue'], operation='clean_numeric_string', parameters={'errors': 'coerce'},
        checks=[{'column': 'Revenue', 'kind': 'no_missing'}])


def test_every_lost_value_reaches_the_feedback_and_trace_without_truncation(dirty):
    state, executor, invalid = dirty
    original = Path(state.current_ref.path).read_bytes()
    result = revenue_trial(executor)
    assert not result['success'] and not result['tested']
    summary = result['failure_summary']
    assert summary['lost_value_count'] == len(invalid)
    assert [v['before'] for v in summary['lost_values']] == invalid
    assert [v['row_position'] for v in summary['lost_values']] == list(range(6, 15))
    assert len(result['effect']['changed_examples']) == 5
    assert all(v['column'] == 'Revenue' and v['after'] is None for v in summary['lost_values'])
    assert '9 populated cells' in result['error'] and 'expected:no_missing:Revenue' in result['error']
    assert result['recovery_prompt']['case'] == 'validation'
    assert result['recovery_prompt']['context']['lost_values'] == summary['lost_values']
    assert 'failed independent outcome checks' in result['recovery_prompt']['instruction']
    feedback = json.loads(_tool_feedback(json.dumps(result)))
    assert feedback['effect']['lost_values'] == summary['lost_values']
    assert feedback['failure_summary'] == summary
    trace = json.loads((state.manager.root / 'sales' / 'execution_trace.json').read_text())
    assert trace['events'][-1]['result']['failure_summary'] == summary
    assert state.current_ref.version == 'V1' and Path(state.current_ref.path).read_bytes() == original


def test_failed_duplicate_reuses_failure_evidence_and_never_suggests_application(dirty):
    state, executor, _ = dirty
    failed = revenue_trial(executor)
    duplicate = revenue_trial(executor)
    assert not duplicate['success'] and duplicate['candidate_status'] == 'failed'
    assert duplicate['candidate_id'] == failed['candidate_id']
    assert duplicate['failure_summary'] == failed['failure_summary']
    assert 'Do not apply or repeat it' in duplicate['error']
    assert 'Apply the passing candidate' not in duplicate['error']
    assert duplicate['recovery_prompt']['context']['candidate_status'] == 'failed'
    assert duplicate['recovery_prompt']['context']['lost_value_count'] == 9
    assert len(state.method_candidates) == 1 and state.current_ref.version == 'V1'


def test_passing_and_applied_duplicates_are_distinguished(dirty):
    state, executor, _ = dirty
    args = dict(hypothesis='Observed Yes/No flags encode binary values', columns=['flag'],
                operation='convert_data_types', parameters={'target_type': 'boolean'})
    trial = call(executor, ("test_generated" if (args).get("code") else "test_builtin"), **args)
    duplicate = call(executor, ("test_generated" if (args).get("code") else "test_builtin"), **args)
    assert duplicate['candidate_status'] == 'passed' and duplicate['tested']
    assert not duplicate['failure_summary']
    assert call(executor, 'apply_candidate', candidate_id=trial['candidate_id'], assessment='Trial preserved flag values')['success']
    # The already-boolean column now produces a passing no-op on V2.
    noop = call(executor, ("test_generated" if (args).get("code") else "test_builtin"), **args)
    assert call(executor, 'apply_candidate', candidate_id=noop['candidate_id'], assessment='Values already match')['no_op']
    duplicate = call(executor, ("test_generated" if (args).get("code") else "test_builtin"), **args)
    assert duplicate['candidate_status'] == 'already_applied'
    assert 'Do not apply or repeat it' in duplicate['error']
    assert state.current_ref.version == 'V2'


def test_generated_trial_loss_evidence_survives_feedback_compaction(dirty):
    state, _, _ = dirty
    before = state.manager.load(state.current_ref)
    after = before.copy(); after['Revenue'] = pd.to_numeric(after.Revenue, errors='coerce')
    effect = assess_method(before, after, ['Revenue'], [{'column': 'Revenue', 'kind': 'numeric'}])
    result = {'success': False, 'trials': [{'partition': 'holdout', 'rows': len(before),
               'success': False, 'effect': effect}]}
    compact = json.loads(_tool_feedback(json.dumps(result)))
    assert compact['trials'][0]['effect']['lost_values'] == effect['lost_values']
    result = {'success': False, 'details': {'full_data_effect': effect}}
    compact = json.loads(_tool_feedback(json.dumps(result)))
    assert compact['details']['lost_values'] == effect['lost_values']


def test_application_rejection_also_reports_all_loss_evidence(dirty, monkeypatch):
    state, executor, _ = dirty
    trial = call(executor, "test_builtin", hypothesis='Convert observed binary flags', columns=['flag'],
                 operation='convert_data_types', parameters={'target_type': 'boolean'})
    original = workflow.run_builtin
    def changed(frame, operation, parameters):
        output = original(frame, operation, parameters)
        output.df['flag'] = None
        return output
    monkeypatch.setattr(workflow, 'run_builtin', changed)
    result = call(executor, 'apply_candidate', candidate_id=trial['candidate_id'], assessment='Trial passed')
    assert not result['success'] and result['failure_summary']['lost_value_count'] == 16
    assert result['recovery_prompt']['case'] == 'conversion'
    assert state.current_ref.version == 'V1'


def test_dirty_sales_case_loses_only_the_truly_unparseable_values(tmp_path):
    source = Path('data/raw/dirty_sales_test.csv').resolve()
    manager = DatasetVersionManager(tmp_path / 'versions')
    original = manager.register_original(source, dataset_id='sales')
    state = AgentSessionState(manager=manager, dataset_id='sales', source_ref=original,
        current_ref=manager.create_working_copy(original))
    failed = revenue_trial(ToolExecutor(state))
    # 'one thousand', 'five hundred' and 'quarter million' are now parsed to their numeric values.
    assert [v['before'] for v in failed['failure_summary']['lost_values']] == ['banana', 'ERROR_404']


def test_model_receives_full_loss_summary_and_specific_next_decision(tmp_path, monkeypatch, dirty):
    state, _, invalid = dirty
    source = tmp_path/'sales.csv'
    report = {'dataset_ref': {'file_path': str(source), 'file_name': source.name, 'rows': 16, 'columns': 2},
              'column_profiles': {'Revenue': {'dtype': 'str', 'etl_cast_to': 'float'}}}
    turns = []
    def respond(messages, tools, **kwargs):
        turns.append(messages)
        if len(turns) == 1:
            name, args = "test_builtin", dict(hypothesis='Parse observed numeric formats', columns=['Revenue'],
                operation='clean_numeric_string', parameters={'errors': 'coerce'},
                checks=[{'column': 'Revenue', 'kind': 'no_missing'}])
        elif len(turns) == 2:
            feedback = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
            assert [v['before'] for v in feedback['failure_summary']['lost_values']] == invalid
            guidance = [json.loads(m['content']) for m in messages if m['role'] == 'user' and m['content'].startswith('{"case":')][-1]
            assert guidance['case'] == 'validation'
            name, args = 'flag_for_review', {'columns': ['Revenue'], 'reason': 'Unknown numeric meaning requires a business decision'}
        else:
            name, args = 'finish', {'summary': 'Revenue requires review; no destructive conversion applied'}
        return {'tool_calls': [{'id': str(len(turns)), 'name': name, 'arguments': args}]}
    monkeypatch.setattr('agents.dataCleaning_agent.chat_with_tools', respond)
    monkeypatch.setattr('agents.dataCleaning_agent.sandbox_status', lambda: {})
    result = DataCleaningAgent(data_root=tmp_path/'agent_runs', use_llm=True).run(report)
    assert result.final_dataset.version == 'V1' and not result.change_log.successful_ops()
    assert result.validation.status.value == 'partial' and len(turns) == 3
