from datetime import date, datetime
from decimal import Decimal
from functools import partial
import anyio
from mysql.connector import Error as DatabaseError
from pydantic import ValidationError
from mcp.server.fastmcp import FastMCP
from services.errors import BusinessError
from create_logger import get_logger


def server(name, port):
    return FastMCP(name, host='127.0.0.1',port=port,log_level='WARNING',json_response=True)


def serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value,(date,datetime)):
        return value.isoformat()
    if isinstance(value,dict):
        return {k:serialize(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [serialize(v) for v in value]
    return value


async def invoke(fn, *args, **kwargs):
    try:
        result = await anyio.to_thread.run_sync(partial(fn,*args,**kwargs))
        return {'ok':True,'data':serialize(result)}
    except BusinessError as exc:
        return {'ok':False,'error':{'code':'BUSINESS_RULE','message':str(exc)}}
    except ValidationError:
        return {'ok':False,'error':{'code':'VALIDATION','message':'输入字段、类型或金额无效'}}
    except DatabaseError:
        get_logger().error('database operation failed; details intentionally omitted')
        return {'ok':False,'error':{'code':'DATABASE','message':'数据库操作失败；事务已回滚，请检查本地数据库状态'}}
