from agents.specialists import BudgetAgent
from a2a_server.common import serve

if __name__=='__main__':
    serve('budget',BudgetAgent())
