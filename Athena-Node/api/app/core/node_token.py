MIN_NODE_TOKEN_LENGTH = 32
MAX_NODE_TOKEN_LENGTH = 256
NODE_TOKEN_LENGTH_MESSAGE = "Token 长度必须为 32 至 256 个字符"


def validate_node_token(value: str) -> str:
    if value and not MIN_NODE_TOKEN_LENGTH <= len(value) <= MAX_NODE_TOKEN_LENGTH:
        raise ValueError(NODE_TOKEN_LENGTH_MESSAGE)
    return value
