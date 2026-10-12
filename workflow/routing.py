from langgraph.graph import END
from config import get_settings


def route_proposal(state):
    return 'ready' if state.get('proposal_status')=='READY_FOR_APPROVAL' else 'stop'


def route_approval(state):
    return 'rejected' if state.get('approval_status')=='REJECTED' else 'approved'


def check_more(state):
    return 'more' if state['current_approval_index']<len(state['approval_chain']) else 'done'


def route_operation(state):
    if state.get('last_error'):
        return 'recover' if state.get('retry_count',0)<get_settings().workflow_max_retries else 'failed'
    return 'success'


def route_recovery(state):
    return state['recovery_node']
