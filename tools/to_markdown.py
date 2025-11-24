import io
import logging
import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
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
    s3_bucket: str = Field(
        description="S3 bucket name where extracted images will be uploaded.",
    )
    s3_prefix: str = Field(
        default="pymupdf-extracts",
        description="Prefix to use for uploaded images in the S3 bucket.",
    )
    presigned_url_expiration: int = Field(
        default=3600,
        description=(
            "Expiration time in seconds for the generated pre-signed URLs. "
            "Objects remain in S3 until manually removed."
        ),
    )
    aws_region: str | None = Field(
        default=None,
        description="AWS region for the S3 bucket. Leave empty to use the default client region.",
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
        s3_client = boto3.client("s3", region_name=params.aws_region)

        with tempfile.TemporaryDirectory() as temp_dir:
            for file in files:
                try:
                    logger.info("Processing file for markdown: %s", file.filename)

                    file_bytes = io.BytesIO(file.blob)
                    doc = fitz.open(stream=file_bytes, filetype="pdf")

                    safe_stem = Path(file.filename).stem or "document"
                    file_namespace = uuid4().hex
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

                    images_metadata: list[dict[str, str]] = []
                    for image_path in image_files:
                        if not image_path.is_file():
                            continue

                        relative_key = str(image_path.relative_to(image_root)).replace("\\", "/")
                        prefix = params.s3_prefix.strip("/")
                        s3_key = "/".join(
                            part
                            for part in [
                                prefix,
                                safe_stem,
                                file_namespace,
                                relative_key,
                            ]
                            if part
                        )

                        s3_client.upload_file(str(image_path), params.s3_bucket, s3_key)

                        expires_at = datetime.now(timezone.utc) + timedelta(
                            seconds=params.presigned_url_expiration
                        )
                        presigned_url = s3_client.generate_presigned_url(
                            "get_object",
                            Params={"Bucket": params.s3_bucket, "Key": s3_key},
                            ExpiresIn=params.presigned_url_expiration,
                        )

                        images_metadata.append(
                            {
                                "s3_bucket": params.s3_bucket,
                                "s3_key": s3_key,
                                "url": presigned_url,
                                "expires_at": expires_at.isoformat(),
                            }
                        )

                    yield self.create_text_message(markdown_output)

                    yield self.create_json_message(
                        {
                            file.filename: {
                                "markdown": markdown_output,
                                "paginated": params.paginate,
                                "images": images_metadata,
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

                except Exception as exc:  # pylint: disable=broad-except
                    error_msg = f"Error processing {file.filename}: {exc}"
                    logger.error(error_msg)
                    yield self.create_text_message(error_msg)
                    yield self.create_json_message({file.filename: {"error": str(exc)}})
