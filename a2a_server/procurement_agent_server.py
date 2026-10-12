from agents.coordinator import ProcurementCoordinatorAgent
from a2a_server.common import serve

if __name__=='__main__':
    serve('procurement',ProcurementCoordinatorAgent())
