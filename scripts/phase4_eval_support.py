"""Deterministic evaluation-only collaborators; never used by the deployed agents."""
from agents.schemas import ExplanationPlan


class DeterministicGateway:
    """Removes paid model calls while leaving A2A, MCP, rules and MySQL real."""

    async def select_tools(self, names, request_id, agent):
        return list(names)

    async def explanation(self, candidate, request_id):
        return ExplanationPlan(factors=['PRICE', 'DELIVERY', 'ON_TIME', 'QUALITY'])

    async def extract(self, text, request_id):
        raise RuntimeError('Offline Phase4 cases use structured requirements')
