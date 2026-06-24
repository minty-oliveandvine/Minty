"""DOCX/PDF conversion helper."""

import os

from flask import current_app
from loguru import logger


def convert_docx_to_pdf(docx_path, pdf_path):
    """Convert DOCX file to PDF using Spire.Doc runtime."""
    try:
        temp_dir = os.path.dirname(pdf_path)
        os.makedirs(temp_dir, exist_ok=True)

        # Import inside function to keep dependency optional for command
        # contexts.
        from spire.doc import Document, FileFormat
        from spire.doc import LicenseProvider as docLicense

        docLicense.SetLicenseKey(current_app.config["SPIRE_KEY"])
        doc = Document()
        doc.LoadFromFile(docx_path)
        doc.SaveToFile(pdf_path, FileFormat.PDF)
        doc.Close()

        if os.path.exists(pdf_path):
            logger.info(f"DOCX file converted to PDF successfully: {pdf_path}")
            return True

        logger.error(f"PDF file was not created at: {pdf_path}")
        return False
    except Exception as e:
        logger.error(f"Error converting DOCX to PDF: {str(e)}")
        return False
