"""Type aliases for ERA5-ETL."""

from pathlib import Path
from typing import TypeAlias

# Path types
PathLike: TypeAlias = str | Path

# Data types
VariableName: TypeAlias = str
DatasetName: TypeAlias = str
