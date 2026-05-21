"""ERA5 dataset registry.

ERA5 and ERA5-LAND are tracked as independent subsystems. Each lives in its
own sub-package (``era5_etl.datasets.era5`` and ``era5_etl.datasets.era5_land``)
and registers a ``DatasetConfig`` via ``@DatasetRegistry.register``.

Public entry points::

    DatasetRegistry.get("era5-land")    # -> Era5LandConfig instance
    DatasetRegistry.names()             # -> ("era5", "era5-land", "inmet")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from era5_etl.datasets.base import DatasetConfig


class DatasetRegistry:
    """Registry of available ERA5-family datasets.

    Datasets register themselves via the ``@DatasetRegistry.register`` decorator
    at import time. ``ensure_loaded()`` triggers the imports lazily so callers
    don't need to remember to import sub-packages explicitly.
    """

    _registry: ClassVar[dict[str, DatasetConfig]] = {}
    _loaded: ClassVar[bool] = False

    @classmethod
    def register(cls, config_cls: type[DatasetConfig]) -> type[DatasetConfig]:
        instance = config_cls()
        if not instance.NAME:
            raise ValueError(f"{config_cls.__name__} must set a NAME")
        cls._registry[instance.NAME] = instance
        return config_cls

    @classmethod
    def ensure_loaded(cls) -> None:
        if cls._loaded:
            return
        # Importing the sub-packages triggers their @register decorators.
        from era5_etl.datasets import era5, era5_land, inmet

        cls._loaded = True

    @classmethod
    def get(cls, name: str) -> DatasetConfig:
        cls.ensure_loaded()
        try:
            return cls._registry[name]
        except KeyError as exc:
            valid = ", ".join(sorted(cls._registry)) or "<none>"
            raise KeyError(f"Unknown dataset '{name}'. Available: {valid}") from exc

    @classmethod
    def names(cls) -> tuple[str, ...]:
        cls.ensure_loaded()
        return tuple(sorted(cls._registry))

    @classmethod
    def all(cls) -> tuple[DatasetConfig, ...]:
        cls.ensure_loaded()
        return tuple(cls._registry[name] for name in cls.names())


__all__ = ["DatasetRegistry"]
