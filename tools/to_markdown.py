import io
import logging
import tempfile
import zipfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import fitz
import pymupdf4llm
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MarkdownToolParameters(BaseModel):
    files: list[File]
    paginate: bool = Field(
        default=False,
        description="Generate markdown per page with separators when true.",
    )


class ToMarkdownTool(Tool):
    """Convert PDFs to Markdown, preserving text and images."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        if tool_parameters.get("files") is None:
            yield self.create_text_message("No files provided. Please upload PDF files for processing.")
            return

        params = MarkdownToolParameters(**tool_parameters)
        files = params.files

        with tempfile.TemporaryDirectory() as temp_dir:
            for file in files:
                try:
                    logger.info("Processing file for markdown: %s", file.filename)

                    file_bytes = io.BytesIO(file.blob)
                    doc = fitz.open(stream=file_bytes, filetype="pdf")

                    safe_stem = Path(file.filename).stem or "document"
                    image_root = Path(temp_dir) / safe_stem
                    image_root.mkdir(parents=True, exist_ok=True)

                    try:
                        if params.paginate:
                            page_markdown: list[str] = []
                            for page_index in range(doc.page_count):
                                image_path = image_root / f"page-{page_index + 1}"
                                image_path.mkdir(parents=True, exist_ok=True)
                                markdown_text = pymupdf4llm.to_markdown(
                                    doc,
                                    pages=[page_index],
                                    write_images=True,
                                    image_path=str(image_path),
                                )
                                page_markdown.append(
                                    f"## Page {page_index + 1}\n\n{markdown_text}".strip()
                                )
                            markdown_output = "\n\n---PAGE BREAK---\n\n".join(page_markdown)
                        else:
                            markdown_output = pymupdf4llm.to_markdown(
                                doc,
                                write_images=True,
                                image_path=str(image_root),
                            )
                    finally:
                        doc.close()

                    image_files = sorted(image_root.rglob("*"))
                    image_relpaths = [str(path.relative_to(temp_dir)) for path in image_files if path.is_file()]

                    yield self.create_text_message(markdown_output)

                    yield self.create_json_message(
                        {
                            file.filename: {
                                "markdown": markdown_output,
                                "paginated": params.paginate,
                                "image_files": image_relpaths,
                            }
                        }
                    )

                    yield self.create_blob_message(
                        markdown_output.encode(),
                        meta={
                            "mime_type": "text/markdown",
                            "file_name": f"{safe_stem}.md",
                        },
                    )

                    if image_relpaths:
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            for image_path in image_files:
                                if image_path.is_file():
                                    archive_name = str(image_path.relative_to(temp_dir))
                                    zip_file.write(image_path, arcname=archive_name)
                        zip_buffer.seek(0)

                        yield self.create_blob_message(
                            zip_buffer.read(),
                            meta={
                                "mime_type": "application/zip",
                                "file_name": f"{safe_stem}_images.zip",
                            },
                        )

                except Exception as exc:  # pylint: disable=broad-except
                    error_msg = f"Error processing {file.filename}: {exc}"
                    logger.error(error_msg)
                    yield self.create_text_message(error_msg)
                    yield self.create_json_message({file.filename: {"error": str(exc)}})
