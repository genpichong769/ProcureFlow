"""Evaluation-only A2A specialist process with deterministic tool planning."""
import argparse
from a2a_server.common import serve
from agents.specialists import BudgetAgent, SupplierSourcingAgent, ComplianceApprovalAgent
from scripts.phase4_eval_support import DeterministicGateway


AGENTS = {
    'budget': BudgetAgent,
    'supplier': SupplierSourcingAgent,
    'compliance': ComplianceApprovalAgent,
}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=sorted(AGENTS))
    args = parser.parse_args()
    serve(args.role, AGENTS[args.role](llm=DeterministicGateway()))
