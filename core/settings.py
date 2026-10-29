"""Chi doc secrets tu moi truong; khong luu password vao Inventory."""
from dataclasses import dataclass, field
from os import getenv
import re

try:
    from dotenv import load_dotenv
except ImportError:  # Core demo khong bat buoc pip install
    def load_dotenv() -> None:
        return None


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str = field(repr=False)


def credentials_from_env(ref: str) -> Credentials:
    load_dotenv()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", ref):
        raise ValueError("credential_ref khong hop le")
    prefix = ref.upper()
    user = getenv(prefix + "_USERNAME")
    pwd = getenv(prefix + "_PASSWORD")
    if not user or not pwd:
        raise ValueError(f"Thieu {prefix}_USERNAME hoac {prefix}_PASSWORD trong .env")
    return Credentials(username=user, password=pwd)
