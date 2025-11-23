from typing import Any

from dify_plugin import ToolProvider


class PymupdfProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """PyMuPDF tools do not require credential validation."""
