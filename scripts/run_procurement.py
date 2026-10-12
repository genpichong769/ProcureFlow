"""Send natural language to a running coordinator over real A2A."""
import argparse
import asyncio
import json
from uuid import uuid4
from agents.a2a_transport import A2ATransport
from agents.common import AgentFailure


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('text')
    args=parser.parse_args()
    try:
        result=await A2ATransport().call('procurement',dict(request_id='CLI-'+uuid4().hex,text=args.text))
    except AgentFailure as exc:
        result=dict(status='ERROR',error_type=exc.code)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': asyncio.run(main())
