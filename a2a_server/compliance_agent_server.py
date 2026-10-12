from agents.specialists import ComplianceApprovalAgent
from a2a_server.common import serve

if __name__=='__main__':
    serve('compliance',ComplianceApprovalAgent())
