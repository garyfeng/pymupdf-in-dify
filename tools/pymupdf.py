import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any
import io

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolParameters(BaseModel):
    files: list[File]
    save_images: bool = True


class PymupdfTool(Tool):
    """
    A tool for extracting text from PDF files using PyMuPDF
    """

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        if tool_parameters.get("files") is None:
            yield self.create_text_message("No files provided. Please upload PDF files for processing.")
            return
            
        params = ToolParameters(**tool_parameters)

        if not isinstance(params.save_images, bool):
            yield self.create_text_message("Invalid parameter: 'save_images' must be a boolean.")
            return

        files = params.files
        save_images = params.save_images

        try:
            # Try both import methods to ensure compatibility
            try:
                import pymupdf
                fitz_module = pymupdf
            except ImportError:
                import fitz
                fitz_module = fitz
                
            for file in files:
                try:
                    logger.info(f"Processing file: {file.filename}")

                    # Process PDF file
                    file_bytes = io.BytesIO(file.blob)
                    doc = fitz_module.open(stream=file_bytes, filetype="pdf")

                    page_count = doc.page_count
                    documents = []
                    markdown_parts: list[str] = [f"# {file.filename}", f"Total pages: {page_count}"]
                    image_output_dir = Path("/tmp/pymupdf-images")
                    if save_images:
                        image_output_dir.mkdir(parents=True, exist_ok=True)

                    for page_num in range(page_count):
                        page = doc.load_page(page_num)
                        text = page.get_text()
                        page_record: dict[str, Any] = {
                            "text": text,
                            "metadata": {
                                "page": page_num + 1,
                                "file_name": file.filename
                            }
                        }

                        markdown_parts.append(f"\n## Page {page_num + 1}")
                        markdown_parts.append(text or "_No text content extracted._")

                        if save_images:
                            images = page.get_images(full=True)
                            extracted_images = []
                            for image_index, image in enumerate(images, start=1):
                                xref = image[0]
                                base_image = doc.extract_image(xref)
                                image_bytes = base_image.get("image")
                                if image_bytes is None:
                                    continue

                                image_ext = base_image.get("ext", "png")
                                safe_stem = Path(file.filename).stem.replace(" ", "_")
                                image_filename = f"{safe_stem}_page{page_num + 1}_image{image_index}.{image_ext}"
                                image_path = image_output_dir / image_filename

                                with open(image_path, "wb") as image_file:
                                    image_file.write(image_bytes)

                                extracted_images.append({
                                    "page": page_num + 1,
                                    "image_index": image_index,
                                    "path": str(image_path)
                                })
                                markdown_parts.append(
                                    f"![Page {page_num + 1} Image {image_index}]({image_path})"
                                )

                            if extracted_images:
                                page_record["images"] = extracted_images
                        else:
                            if page.get_images(full=True):
                                markdown_parts.append("_Images detected on this page were skipped (save_images=false)._")

                        documents.append(page_record)

                    # Close the document to free resources
                    doc.close()

                    # Join all extracted text with page separators
                    texts = "\n\n---PAGE BREAK---\n\n".join([doc["text"] for doc in documents])

                    # Yield text message for human readability
                    yield self.create_text_message("\n\n".join(markdown_parts))

                    # Yield structured JSON data
                    yield self.create_json_message({file.filename: documents})
                    
                    # Yield raw text as blob with mime type
                    yield self.create_blob_message(
                        texts.encode(),
                        meta={
                            "mime_type": "text/plain",
                        },
                    )
                    
                except Exception as e:
                    error_msg = f"Error processing {file.filename}: {str(e)}"
                    logger.error(error_msg)
                    yield self.create_text_message(error_msg)
                    yield self.create_json_message({
                        file.filename: {"error": str(e)}
                    })
                    
        except ImportError as e:
            error_msg = f"Error: PyMuPDF library not installed. {str(e)}"
            logger.error(error_msg)
            yield self.create_text_message(error_msg)
