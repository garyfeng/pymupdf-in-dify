from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Provide a lightweight boto3 stub so imports succeed even when the dependency is
# not preinstalled. Tests monkeypatch the required functions on this stub.
if "boto3" not in sys.modules:
    sys.modules["boto3"] = types.SimpleNamespace(client=None)
from typing import Any

import fitz

from tools.to_text import ToTextTool
from tools.to_markdown import ToMarkdownTool
from dify_plugin.entities.tool import ToolRuntime, CredentialType
from dify_plugin.core.runtime import Session


def create_pdf_bytes(pages: list[str]) -> bytes:
    doc = fitz.open()
    for content in pages:
        page = doc.new_page()
        page.insert_text((72, 72), content)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def stub_tool_messages(tool: Any) -> None:
    tool.create_text_message = lambda text: ("text", text)
    tool.create_json_message = lambda obj: ("json", obj)
    tool.create_blob_message = lambda blob, meta=None: (
        "blob",
        blob,
        meta or {},
    )


def build_tool(tool_cls):
    runtime = ToolRuntime(credentials={}, credential_type=CredentialType.API_KEY, user_id=None, session_id=None)
    session = Session.empty_session()
    tool = tool_cls(runtime=runtime, session=session)
    stub_tool_messages(tool)
    return tool


def test_to_text_no_files_returns_help_message():
    tool = build_tool(ToTextTool)

    outputs = list(tool._invoke({}))

    assert outputs == [("text", "No files provided. Please upload PDF files for processing.")]


def test_to_text_generates_messages_for_pdf(tmp_path):
    from dify_plugin.file.file import File

    pdf_bytes = create_pdf_bytes(["Page 1", "Page 2"])
    file = File(
        id="1",
        filename="sample.pdf",
        mime_type="application/pdf",
        size=len(pdf_bytes),
        url="local://sample.pdf",
        type="document",
    )
    file._blob = pdf_bytes

    tool = build_tool(ToTextTool)

    outputs = list(tool._invoke({"files": [file]}))

    assert len(outputs) == 3

    text_output = outputs[0][1]
    assert "Page 1" in text_output and "Page 2" in text_output
    assert "---PAGE BREAK---" in text_output

    json_output = outputs[1][1]["sample.pdf"]
    assert json_output[0]["metadata"]["page"] == 1
    assert json_output[1]["metadata"]["page"] == 2

    blob_output = outputs[2]
    assert blob_output[0] == "blob"
    assert blob_output[1] == text_output.encode()
    assert blob_output[2]["mime_type"] == "text/plain"


def test_to_markdown_paginated_uses_s3_and_page_breaks(monkeypatch, tmp_path):
    from dify_plugin.file.file import File

    pdf_bytes = create_pdf_bytes(["Markdown page 1", "Markdown page 2"])
    file = File(
        id="2",
        filename="markdown.pdf",
        mime_type="application/pdf",
        size=len(pdf_bytes),
        url="local://markdown.pdf",
        type="document",
    )
    file._blob = pdf_bytes

    uploads: list[dict[str, Any]] = []

    class FakeS3Client:
        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            uploads.append({"filename": filename, "bucket": bucket, "key": key})

        def generate_presigned_url(self, operation: str, Params: dict[str, str], ExpiresIn: int) -> str:
            return f"https://example.com/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"

    def fake_boto3_client(service: str, region_name: str | None = None):
        assert service == "s3"
        return FakeS3Client()

    def fake_to_markdown(doc, pages=None, write_images=False, image_path: str | None = None):
        if write_images and image_path:
            Path(image_path).mkdir(parents=True, exist_ok=True)
            (Path(image_path) / "img1.png").write_text("img")
        if pages is None:
            return "all-pages-markdown"
        return f"pages-{','.join(str(p + 1) for p in pages)}-markdown"

    monkeypatch.setattr("boto3.client", fake_boto3_client)
    monkeypatch.setattr("pymupdf4llm.to_markdown", fake_to_markdown)

    tool = build_tool(ToMarkdownTool)

    outputs = list(
        tool._invoke(
            {
                "files": [file],
                "paginate": True,
                "s3_bucket": "my-bucket",
                "presigned_url_expiration": 600,
            }
        )
    )

    assert len(outputs) == 3

    markdown_text = outputs[0][1]
    assert "## Page 1" in markdown_text
    assert "## Page 2" in markdown_text
    assert "---PAGE BREAK---" in markdown_text

    json_payload = outputs[1][1]["markdown.pdf"]
    assert json_payload["paginated"] is True
    assert json_payload["markdown"] == markdown_text
    assert json_payload["images"]

    image_entry = json_payload["images"][0]
    assert image_entry["s3_bucket"] == "my-bucket"
    assert image_entry["s3_key"].startswith("pymupdf-extracts/markdown/")
    assert image_entry["url"].startswith("https://example.com/my-bucket/")
    assert uploads  # ensure upload_file was called

    blob_output = outputs[2]
    assert blob_output[0] == "blob"
    assert blob_output[1] == markdown_text.encode()
    assert blob_output[2]["mime_type"] == "text/markdown"
    assert blob_output[2]["file_name"] == "markdown.md"
