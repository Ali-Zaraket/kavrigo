"""Run the control plane: ``python -m kavrigo_api``."""

from __future__ import annotations

import uvicorn

from kavrigo_api.app import create_app
from kavrigo_api.settings import get_settings
from kavrigo_observability import telemetry_from_env


def main() -> None:
    settings = get_settings()
    with telemetry_from_env("kavrigo-api"):
        uvicorn.run(
            create_app(settings),
            host=settings.api_host,
            port=settings.api_port,
            log_config=None,  # structlog owns logging
            access_log=False,  # middleware logs route templates without query/path values
        )


if __name__ == "__main__":
    main()
