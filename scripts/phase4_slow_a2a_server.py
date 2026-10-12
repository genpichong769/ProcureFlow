"""Evaluation fixture that accepts a real A2A request and responds too slowly."""
import json
import time
from python_a2a import A2AServer, AgentCard, AgentSkill, TaskStatus, TaskState, run_server
from agents.a2a_transport import NAMES


PORT = 5095


class SlowBudgetServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=AgentCard(
            name=NAMES['budget'], description='Phase4 bounded-timeout fixture',
            url=f'http://127.0.0.1:{PORT}', version='4.0.0', capabilities={'streaming': False},
            skills=[AgentSkill(name='budget_analysis', description='Phase4 timeout fixture')]))

    def handle_task(self, task):
        time.sleep(2)
        task.status = TaskStatus(state=TaskState.COMPLETED)
        task.artifacts = [{'parts': [{'type': 'text', 'text': json.dumps({'ok': True, 'data': {}})}]}]
        return task


if __name__ == '__main__':
    run_server(SlowBudgetServer(), host='127.0.0.1', port=PORT)
