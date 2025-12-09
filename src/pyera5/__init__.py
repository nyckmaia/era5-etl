"""PyERA5 - Pipeline profissional para dados ERA5/ERA5-Land.

PyERA5 é um pacote Python para download, processamento e análise
de dados ERA5/ERA5-Land do Copernicus Climate Data Store.
"""

from pyera5.__version__ import __version__
from pyera5.config import PipelineConfig
from pyera5.pipeline.era5_pipeline import ERA5Pipeline

__all__ = [
    "__version__",
    "PipelineConfig",
    "ERA5Pipeline",
]
