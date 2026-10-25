import os
import requests
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from langchain_community.document_loaders import PyMuPDFLoader


class PyMuPDFScraper:

    def __init__(self, link, session=None):
        """
        Initialize the scraper with a link and an optional session.

        Args:
          link (str): The URL or local file path of the PDF document.
          session (requests.Session, optional): An optional session for making HTTP requests.
        """
        self.link = link
        self.session = session

    def is_url(self) -> bool:
        """
        Check if the provided `link` is a valid URL.

        Returns:
          bool: True if the link is a valid URL, False otherwise.
        """
        try:
            result = urlparse(self.link)
            return all([result.scheme, result.netloc])  # Check for valid scheme and network location
        except Exception:
            return False

    def scrape(self) -> tuple[str, list[str], str]:
        """
        The `scrape` function loads a PDF from the provided link (either URL or local file) and
        returns it as Markdown. Each page goes through the PDF page router (see pdf_router/README.md),
        or, with PDF_ROUTER_ENABLED=false, through PyMuPDFLoader as before.

        Returns:
          tuple: (content, image URLs, title); ("", [], "") on any error.
        """
        # Imported on first use: the router loads PyMuPDF and its models (~0.4 s, ~150 MB),
        # a cost that importing the scraper must not carry.
        from .. import pdf_router

        try:
            if pdf_router.settings.enabled():
                result = pdf_router.route_pdf(self._read_pdf(), self.link)
                return result.markdown, [], result.title
            return self._scrape_with_loader()

        except requests.exceptions.Timeout:
            print(f"Download timed out. Please check the link : {self.link}")
            return "", [], ""
        except Exception as e:
            print(f"Error loading PDF : {self.link} {e}")
            return "", [], ""

    def _download(self) -> requests.Response:
        http = self.session or requests
        try:
            response = http.get(self.link, timeout=(5, 30), stream=True)
            response.raise_for_status()
        except requests.exceptions.SSLError:
            import logging
            logging.getLogger(__name__).warning(
                f"SSL verification failed for {self.link}, retrying without verification"
            )
            response = http.get(self.link, timeout=(5, 30), stream=True, verify=False)
            response.raise_for_status()
        return response

    def _read_pdf(self) -> bytes:
        """The PDF's bytes, downloaded in memory or read from the local file."""
        if self.is_url():
            return b"".join(self._download().iter_content(chunk_size=8192))
        return Path(self.link).read_bytes()

    def _scrape_with_loader(self) -> tuple[str, list[str], str]:
        """Legacy path: one extractor for the whole file (PDF_ROUTER_ENABLED=false)."""
        if self.is_url():
            response = self._download()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_filename = temp_file.name  # Get the temporary file name
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)  # Write the downloaded content to the temporary file

            # Always clean up the downloaded temp file, even if loading fails
            # (PyMuPDFLoader.load() can raise on a malformed/partial PDF).
            try:
                loader = PyMuPDFLoader(temp_filename)
                doc = loader.load()
            finally:
                try:
                    os.remove(temp_filename)
                except OSError:
                    pass
        else:
            loader = PyMuPDFLoader(self.link)
            doc = loader.load()

        # Extract the content, image (if any), and title from the document.
        image = []
        # Retrieve content from ALL pages to ensure PDFs with cover pages pass validation.
        content = "\n".join(page.page_content for page in doc)
        title = doc[0].metadata.get("title", "") if doc else ""
        return content, image, title
