import io
import logging
from collections.abc import Generator
from typing import Any

import fitz
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolParameters(BaseModel):
    files: list[File]


class ToTextTool(Tool):
    """Extract text from PDF files using PyMuPDF."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        if tool_parameters.get("files") is None:
            yield self.create_text_message("No files provided. Please upload PDF files for processing.")
            return

        params = ToolParameters(**tool_parameters)
        files = params.files

        for file in files:
            try:
                logger.info("Processing file: %s", file.filename)

                file_bytes = io.BytesIO(file.blob)
                doc = fitz.open(stream=file_bytes, filetype="pdf")

                documents = []

                try:
                    for page_num in range(doc.page_count):
                        page = doc.load_page(page_num)
                        text = page.get_text()
                        documents.append(
                            {
                                "text": text,
                                "metadata": {
                                    "page": page_num + 1,
                                    "file_name": file.filename,
                                },
                            }
                        )
                finally:
                    doc.close()

                texts = "\n\n---PAGE BREAK---\n\n".join([doc["text"] for doc in documents])

                yield self.create_text_message(texts)

                yield self.create_json_message({file.filename: documents})

                yield self.create_blob_message(
                    texts.encode(),
                    meta={
                        "mime_type": "text/plain",
                    },
                )

            except Exception as exc:  # pylint: disable=broad-except
                error_msg = f"Error processing {file.filename}: {exc}"
                logger.error(error_msg)
                yield self.create_text_message(error_msg)
                yield self.create_json_message({file.filename: {"error": str(exc)}})
