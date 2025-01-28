import os

DEFAULT_HOST: str = os.getenv("SUBPROCESS_DEFAULT_MONITOR_HOST", "localhost")
DEFAULT_PORT: int = int(os.getenv("SUBPROCESS_DEFAULT_MONITOR_PORT", "5057"))
