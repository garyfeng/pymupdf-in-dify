# PyMuPDF Plugin for Dify

A powerful PDF text and Markdown extraction plugin for Dify powered by PyMuPDF (aka fitz) and PyMuPDF4LLM.

![Demo Screenshot](./_assets/image.png)

## Overview

PyMuPDF Plugin is a high-performance tool that allows you to extract, analyze, and manipulate content from PDF documents directly within Dify applications. Built on the robust PyMuPDF library (and its PyMuPDF4LLM extension), this plugin provides accurate and efficient PDF text or Markdown extraction capabilities.

## Features

- Extract complete text content from PDF files (``to_text``)
- Convert PDFs to Markdown with S3-hosted image references delivered via pre-signed URLs (``to_markdown``), isolating each PDF's images in unique per-file folders to avoid collisions
- Process single or multiple PDF documents simultaneously
- Maintain page structure with clear page separations
- Return both human-readable text/markdown and structured JSON data
- Detailed metadata including page numbers and file information

## Installation

To install the PyMuPDF Plugin:

1. Navigate to the Plugin section in your Dify application
2. Click "Add Plugin"
3. Search for "PyMuPDF" or upload this plugin package
4. Follow the on-screen instructions to complete installation

## Requirements

- PyMuPDF library (installed automatically with the plugin)
- Compatible with Dify plugin system

## Usage

Once installed, the plugin can be accessed through the Dify interface:

1. Upload one or more PDF files using the file selector.
2. Choose the action:
   - **to_text**: extract plain text with page breaks and per-page metadata.
   - **to_markdown**: convert the PDF to Markdown (optionally per-page) with linked images uploaded to S3 and shared as pre-signed URLs. Each PDF's images live in a unique folder under your configured prefix so parallel runs and repeated filenames do not overwrite each other.
3. The plugin will return human-readable output plus structured JSON and a Markdown blob for downstream processing.

## Example Response

The plugin returns data in multiple formats:

1. **Text Message**: Human-readable text with page breaks indicated
2. **JSON Message**: Structured data containing:
   ```json
   {
     "example.pdf": [
       {
         "text": "Content from page 1...",
         "metadata": {
           "page": 1,
           "file_name": "example.pdf"
         }
       },
       {
         "text": "Content from page 2...",
         "metadata": {
           "page": 2,
           "file_name": "example.pdf"
         }
       }
     ]
   }
   ```
3. **Blob Message**: Raw text content with MIME type specification
4. **Images in S3**: Extracted images are uploaded to your configured S3 bucket. JSON includes their keys and pre-signed URLs so downstream workflow nodes can fetch them during the URL lifetime. Objects persist in S3 until you clean them up.

## Actions

- **Convert PDF to Markdown** (`to_markdown`): Converts uploaded PDFs to Markdown, extracting both text and embedded images. Images are uploaded to S3 under the provided bucket/prefix in unique per-file folders, and pre-signed URLs are returned alongside the Markdown so later workflow steps can reuse them without collision.

## Privacy Policy

The plugin processes PDFs within the execution environment and uploads extracted images to the S3 bucket you configure. Objects remain in your bucket until you remove them; pre-signed URLs expire based on the configured lifetime.

- No user information is collected beyond the content you upload
- Extracted images are stored in your S3 bucket under the configured prefix
- Markdown remains in-memory except for the optional blob response
- Pre-signed URLs expire automatically, but the underlying S3 objects persist until you delete them

## License

This plugin is licensed under the [AGPL-3.0 License](https://www.gnu.org/licenses/agpl-3.0.en.html).

## Contact

For questions, support, or feedback, please:

- Open an issue in this repository with details about your request or problem.
- Email the plugin maintainer at yevanchen.dev@gmail.com for direct assistance.

## Credits

- Code generated with assistance from Cursor
- Powered by PyMuPDF library

## Disclaimer

This plugin is provided "as is" without warranty of any kind, express or implied. Users should ensure they have appropriate rights to process any PDF documents uploaded for extraction.



