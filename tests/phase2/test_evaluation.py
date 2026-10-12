from scripts.evaluate_phase2 import parse_matches


def test_money_representation_is_not_a_parse_error():
    assert parse_matches({'max_total_amount':'2266.8'},{'max_total_amount':'2266.80'})
    assert not parse_matches({'max_total_amount':'2266.81'},{'max_total_amount':'2266.80'})
    assert not parse_matches({'quantity':10},{'quantity':None})
