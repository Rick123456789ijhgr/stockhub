"""Provider registry: name -> adapter class, and per-data-kind primary/fallback order."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from stockhub.common.settings import ConfigError
from stockhub.etl.providers.base import INTERFACES, DataKind, Provider

if TYPE_CHECKING:
    from stockhub.common.settings import Settings

# Modules whose import registers built-in adapters.
BUILTIN_MODULES = ("stockhub.etl.providers.fake",)

_REGISTRY: dict[str, type[Provider]] = {}


def register_provider[P: type[Provider]](cls: P) -> P:
    """Class decorator: make an adapter available by its `name`."""
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"provider name {cls.name!r} already registered by {existing}")
    _REGISTRY[cls.name] = cls
    return cls


def registered_providers() -> dict[str, type[Provider]]:
    for module in BUILTIN_MODULES:
        importlib.import_module(module)
    return dict(_REGISTRY)


class ProviderRegistry:
    """Ordered provider instances per data kind (first = primary, rest = fallbacks)."""

    def __init__(self, order: Mapping[DataKind, Sequence[Provider]]) -> None:
        for kind, providers in order.items():
            interface = INTERFACES[kind]
            for provider in providers:
                if not isinstance(provider, interface):
                    raise ConfigError(
                        f"provider {provider.name!r} cannot serve {kind} data "
                        f"(does not implement {interface.__name__})"
                    )
        self._order = {kind: list(providers) for kind, providers in order.items()}

    def providers_for(self, kind: DataKind) -> list[Provider]:
        providers = self._order.get(kind, [])
        if not providers:
            raise ConfigError(f"no providers configured for {kind} data (PROVIDERS_{kind.upper()})")
        return providers

    @classmethod
    def from_names(
        cls,
        names: Mapping[DataKind, Sequence[str]],
        factory: Callable[[type[Provider]], Provider] | None = None,
    ) -> ProviderRegistry:
        available = registered_providers()
        build = factory or (lambda provider_cls: provider_cls())
        instances: dict[str, Provider] = {}
        order: dict[DataKind, list[Provider]] = {}
        for kind, kind_names in names.items():
            order[kind] = []
            for name in kind_names:
                if name not in available:
                    raise ConfigError(
                        f"unknown provider {name!r} for {kind} data; "
                        f"available: {', '.join(sorted(available))}"
                    )
                if name not in instances:  # one instance (and rate limiter) per source
                    instances[name] = build(available[name])
                order[kind].append(instances[name])
        return cls(order)

    @classmethod
    def from_settings(cls, settings: Settings) -> ProviderRegistry:
        return cls.from_names(
            {
                "price": settings.providers_price,
                "financial": settings.providers_financial,
                "quote": settings.providers_quote,
            }
        )
