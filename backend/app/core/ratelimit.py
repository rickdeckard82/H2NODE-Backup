from slowapi import Limiter
from slowapi.util import get_remote_address

# Storage em memória (por worker do gunicorn). O bloqueio de conta por tentativas
# erradas fica no banco, então isto é só uma camada extra contra força bruta.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)
