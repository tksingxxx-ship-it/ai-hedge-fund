"""Launch the virtual office.

    python -m office

Binds to 127.0.0.1:8765 unless OFFICE_HOST / OFFICE_PORT are set.
Does not open a public listener by default and does not deploy anywhere.
"""

from __future__ import annotations

import uvicorn

from office.app import create_app
from office.config import Config


def main() -> None:
    config = Config.from_env()
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
