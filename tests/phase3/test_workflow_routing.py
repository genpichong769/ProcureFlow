from workflow.routing import route_proposal,route_approval,check_more


def test_fixed_routes():
    assert route_proposal({'proposal_status':'READY_FOR_APPROVAL'})=='ready'
    assert route_proposal({'proposal_status':'NO_BUDGET'})=='stop'
    assert route_approval({'approval_status':'REJECTED'})=='rejected'
    assert check_more({'current_approval_index':1,'approval_chain':['a','b']})=='more'
    assert check_more({'current_approval_index':2,'approval_chain':['a','b']})=='done'
