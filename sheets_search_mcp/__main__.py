"""Allow running with python -m sheets_search_mcp."""
from .server import mcp

mcp.run(transport="stdio")
