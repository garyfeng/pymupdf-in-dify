import contextlib
import io
import logging
import os
import tempfile
import zipfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class ToolParameters(BaseModel):
    files: list[File]


class ToMarkdownTool(Tool):
    """Convert PDF files to Markdown while extracting and saving embedded images."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        if tool_parameters.get("files") is None:
            yield self.create_text_message("No files provided. Please upload PDF files for processing.")
            return

        try:
            params = ToolParameters(**tool_parameters)
        except ValidationError as exc:  # pragma: no cover - defensive validation
            yield self.create_text_message(f"Invalid parameters: {exc}")
            return

        if not params.files:
            yield self.create_text_message("No files provided. Please upload PDF files for processing.")
            return

        try:
            import pymupdf

            fitz_module = pymupdf
        except ImportError:
            import fitz

            fitz_module = fitz

        summary_lines: list[str] = []
        json_payload: dict[str, Any] = {}
        all_files_meta: list[dict[str, str]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            for file in params.files:
                base_name = Path(file.filename or "document.pdf").stem
                file_dir = Path(temp_dir) / base_name
                file_dir.mkdir(parents=True, exist_ok=True)

                try:
                    document = fitz_module.open(stream=io.BytesIO(file.blob), filetype="pdf")
                except Exception as exc:  # pragma: no cover - runtime safety
                    error_msg = f"Error opening {file.filename or 'file'}: {exc}"
                    logger.error(error_msg)
                    json_payload[file.filename or base_name] = {"error": str(exc)}
                    yield self.create_text_message(error_msg)
                    continue

                try:
                    page_count = document.page_count
                    markdown_lines: list[str] = []
                    page_entries: list[dict[str, Any]] = []
                    file_meta: list[dict[str, str]] = []
                    image_errors: list[str] = []

                    for page_index in range(page_count):
                        page_number = page_index + 1
                        page = document.load_page(page_index)
                        page_text = page.get_text()
                        markdown_lines.append(f"## Page {page_number}")
                        markdown_lines.append(page_text.strip() if page_text else "")

                        images_info: list[dict[str, Any]] = []
                        for image_index, image in enumerate(page.get_images(full=True)):
                            xref = image[0]
                            try:
                                image_info = document.extract_image(xref)
                                image_ext = (image_info.get("ext") or "png").lower()
                                supported_exts = {"png", "jpg", "jpeg"}

                                if image_ext not in supported_exts:
                                    pixmap = fitz_module.Pixmap(document, xref)
                                    image_bytes = pixmap.tobytes("png")
                                    image_ext = "png"
                                else:
                                    image_bytes = image_info["image"]

                                mime_type = "image/png" if image_ext == "png" else "image/jpeg"
                                relative_path = Path("images") / f"page-{page_number}-image-{image_index + 1}.{image_ext}"
                                absolute_path = file_dir / relative_path
                                absolute_path.parent.mkdir(parents=True, exist_ok=True)

                                try:
                                    absolute_path.write_bytes(image_bytes)
                                except OSError as write_error:  # pragma: no cover - filesystem failure guard
                                    error_msg = (
                                        f"Failed to write image {image_index + 1} on page {page_number} "
                                        f"for {file.filename}: {write_error}"
                                    )
                                    logger.error(error_msg)
                                    image_errors.append(error_msg)
                                    continue

                                markdown_lines.append(
                                    f"![Page {page_number} Image {image_index + 1}]({relative_path.as_posix()})"
                                )

                                image_record = {
                                    "page": page_number,
                                    "index": image_index + 1,
                                    "path": str(Path(base_name) / relative_path),
                                    "filename": absolute_path.name,
                                    "mime_type": mime_type,
                                }
                                images_info.append(image_record)
                                file_meta.append(image_record)
                            except Exception as image_error:  # pragma: no cover - runtime safety
                                error_msg = (
                                    f"Failed to save image {image_index + 1} on page {page_number} "
                                    f"for {file.filename}: {image_error}"
                                )
                                logger.error(error_msg)
                                image_errors.append(error_msg)

                        page_entries.append(
                            {
                                "page": page_number,
                                "text": page_text,
                                "images": images_info,
                            }
                        )

                    markdown_content = "\n\n".join(markdown_lines).strip()
                    markdown_filename = f"{base_name}.md"
                    markdown_path = file_dir / markdown_filename
                    markdown_rel_path = None

                    try:
                        markdown_path.write_text(markdown_content, encoding="utf-8")
                        markdown_rel_path = str(Path(base_name) / markdown_filename)
                        file_meta.append(
                            {
                                "path": markdown_rel_path,
                                "filename": markdown_filename,
                                "mime_type": "text/markdown",
                            }
                        )
                    except OSError as write_error:  # pragma: no cover - filesystem failure guard
                        error_msg = f"Failed to write markdown for {file.filename}: {write_error}"
                        logger.error(error_msg)
                        image_errors.append(error_msg)

                    summary_lines.append(f"Processed {file.filename or base_name} with {page_count} pages.")
                    json_payload[file.filename or base_name] = {
                        "markdown_path": markdown_rel_path,
                        "pages": page_entries,
                        "files": file_meta,
                        "image_errors": image_errors,
                    }
                    all_files_meta.extend(file_meta)
                except Exception as exc:  # pragma: no cover - runtime safety
                    error_msg = f"Error processing {file.filename or base_name}: {exc}"
                    logger.error(error_msg)
                    json_payload[file.filename or base_name] = {"error": str(exc)}
                    yield self.create_text_message(error_msg)
                finally:
                    with contextlib.suppress(Exception):
                        document.close()

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for root, _, filenames in os.walk(temp_dir):
                    for filename in filenames:
                        full_path = Path(root) / filename
                        rel_path = full_path.relative_to(temp_dir)
                        archive.write(full_path, arcname=rel_path.as_posix())

            zip_bytes = zip_buffer.getvalue()
            meta = {
                "mime_type": "application/zip",
                "files": all_files_meta,
            }

            if summary_lines:
                yield self.create_text_message("\n".join(summary_lines))

            if json_payload:
                yield self.create_json_message({"files": json_payload, "files_meta": all_files_meta})

            yield self.create_blob_message(zip_bytes, meta=meta)
