"""TeXada — Math Formula Agent powered by MiniCPM."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("texada")
except PackageNotFoundError:
    __version__ = "0.2.0"
