"""Drop inherited provider credentials for a fixture-only preview.

The names are removed from the process environment. Values are not logged.
``~/.hedge-fund/.env`` is not read when this runs.
"""

from __future__ import annotations

import os

from office.redact import SECRET_ENV_VARS


def drop_inherited_credentials() -> list[str]:
    removed = []
    for name in SECRET_ENV_VARS:
        if os.environ.pop(name, None) is not None:
            removed.append(name)
    return removed
