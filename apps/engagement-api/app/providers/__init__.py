"""Provider registry wiring."""
from __future__ import annotations

from app.providers.base import ProviderRegistry
from app.providers.vietnamfb import VietnamFBProvider

provider_registry = ProviderRegistry()
provider_registry.register(VietnamFBProvider())
