class BusinessError(ValueError):
    """Safe public business error; never includes SQL or credentials."""


def require(condition, message):
    if not condition:
        raise BusinessError(message)
