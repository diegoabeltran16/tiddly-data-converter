import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'/'python_scripts'))
from audit_artifact_family_coverage import audit, render_human

def test_lifecycle_not_applicable_outside_repo_artifact(tmp_path):
    p=tmp_path/'tiddlers_1.jsonl'
    rows=[{"id":"a","source_fields":{"artifact_family":"session"}}, {"id":"b","source_fields":{"artifact_family":"repo_artifact","authority_level":"current_verified","repo_lifecycle_state":"current_repo_artifact"}}]
    p.write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf8')
    report=audit(tmp_path); by={x['artifact_family']:x for x in report['families']}
    assert by['session']['repo_lifecycle_state']['state']=='not_applicable'
    assert by['repo_artifact']['repo_lifecycle_state']['state']=='ok'
    assert 'familia | registros' in render_human(report)
