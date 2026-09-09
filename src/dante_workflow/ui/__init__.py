"""Optional local UI for the durable DANTE workflow orchestrator.

Imports are lazy so the base orchestration package remains usable without the
optional Flask UI dependencies.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PublicSmokeUISettings",
    "UISettings",
    "create_app",
    "create_public_smoke_app",
]


def __getattr__(name: str) -> Any:
    if name in {"UISettings", "create_app"}:
        from .app import UISettings, create_app

        return {"UISettings": UISettings, "create_app": create_app}[name]
    if name == "PublicSmokeUISettings":
        from .smoke import PublicSmokeUISettings

        return PublicSmokeUISettings
    if name == "create_public_smoke_app":
        from .smoke_app import create_public_smoke_app

        return create_public_smoke_app
    raise AttributeError(name)
