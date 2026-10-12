from agents.specialists import SupplierSourcingAgent
from a2a_server.common import serve

if __name__=='__main__':
    serve('supplier',SupplierSourcingAgent())
