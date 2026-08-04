# .env loading. Inline comments strip on whitespace+# — a template comment once
# resolved a demo config to MAINNET (v2, pinned then, pinned again here).
import os
from pathlib import Path


def load_env(path=None):
    """Populate os.environ from .env; the process environment wins."""
    p = Path(path) if path else Path(__file__).resolve().parents[2] / '.env'
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        for marker in (' #', '\t#'):
            if marker in value:
                value = value.split(marker, 1)[0]
        os.environ.setdefault(key.strip(), value.strip())
