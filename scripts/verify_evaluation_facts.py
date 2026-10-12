"""Audit every recorded quote fact against frozen SQL data, independently of the online run."""
import json
from config import ROOT,get_settings
from scripts.evaluate_phase2 import Oracle,parse_matches


def verify():
    report=json.loads((ROOT/'reports/phase2/evaluation.json').read_text(encoding='utf-8'))
    scenarios={s['id']:s for s in json.loads((get_settings().generated_dir/'phase2/scenarios.json').read_text(encoding='utf-8'))}
    oracle=Oracle();checked=0;failures=[]
    for row in report['records']:
        expected=scenarios[row['scenario_id']]['requirement'];proposal=row['proposal']
        for candidate in proposal.get('all_candidates',[])+proposal.get('qualified_candidates',[])+([proposal['recommended_supplier']] if proposal.get('recommended_supplier') else []):
            checked+=1
            if not oracle.facts_match(candidate,expected):failures.append(dict(scenario=row['scenario_id'],quote_id=candidate.get('quote_id')))
        if not parse_matches(proposal.get('requirement') or {},expected):failures.append(dict(scenario=row['scenario_id'],kind='parse'))
    result=dict(result='PASS' if not failures else 'FAIL',run_id=report['run_id'],candidate_records_checked=checked,
        fields_per_record=16,parse_requests_checked=len(report['records']),failures=failures)
    (ROOT/'reports/phase2/facts-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':raise SystemExit(0 if verify()['result']=='PASS' else 1)
