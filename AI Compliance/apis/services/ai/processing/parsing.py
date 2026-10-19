from pathlib import Path
from typing import Set
import logging
import gc

from bs4 import BeautifulSoup
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem, ImageRefMode

logger = logging.getLogger(__name__)


class Parsing:
    def __init__(
        self,
        input_doc_path: Path | str,
        image_resolution_scale: float = 1.0,  # Reduced from 2.0 for memory efficiency
    ):
        self.input_doc_path = Path(input_doc_path)
        suffix = self.input_doc_path.suffix.lower()

        if suffix == ".pdf":
            # ── Tiered fallback strategy to handle memory constraints ──
            # Attempt 1: Backend-only with minimal image generation
            # Attempt 2: Backend-only without images (if memory error)
            # Attempt 3: OCR with minimal images (if insufficient text)
            # Attempt 4: OCR without images (final fallback)
            
            self._parse_pdf_with_fallback(image_resolution_scale)

        else:
            # ── DOCX / PPTX — plain converter, Docling auto-detects format ──
            converter = DocumentConverter()
            self.doc = converter.convert(self.input_doc_path).document

        self.doc_filename = self.input_doc_path.stem

    def _parse_pdf_with_fallback(self, base_resolution_scale: float):
        """Parse PDF with memory-aware fallback strategy.
        
        Uses heavily reduced image resolution for multimodal processing.
        Strategy: Try low-res images → lower res images → minimal images.
        """
        # Attempt 1: Backend with compressed images (0.3x = ~10x memory reduction)
        logger.info("DOCLING_ATTEMPT_1 parsing_path=%s strategy=backend_compressed_images", self.input_doc_path)
        try:
            gc.collect()  # Clean memory before attempt
            backend_options = PdfPipelineOptions()
            backend_options.do_ocr = False
            backend_options.force_backend_text = True
            # 0.3x resolution = ~90% smaller image files vs 2.0x, still usable for multimodal
            backend_options.images_scale = 0.3
            backend_options.generate_page_images = True  # Keep for multimodal
            backend_options.generate_picture_images = True  # Keep for multimodal

            backend_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=backend_options)
                }
            )
            backend_result = backend_converter.convert(self.input_doc_path)
            
            text_count = len(backend_result.document.texts) if hasattr(backend_result.document, 'texts') else 0
            total_text_length = sum(len(getattr(t, 'text', '')) for t in backend_result.document.texts) if hasattr(backend_result.document, 'texts') else 0
            logger.info("DOCLING_ATTEMPT_1_SUCCESS text_items=%s total_text_length=%s has_sufficient_text=%s", 
                       text_count, total_text_length, self._has_sufficient_text(backend_result.document))

            if self._has_sufficient_text(backend_result.document):
                self.doc = backend_result.document
                logger.info("DOCLING_SUCCESS strategy=backend_compressed_images")
                return
            else:
                logger.info("DOCLING_ATTEMPT_1_INSUFFICIENT_TEXT switching_to_ocr")
                del backend_result, backend_converter
                
        except (MemoryError, RuntimeError) as e:
            logger.warning("DOCLING_ATTEMPT_1_MEMORY_ERROR error=%s attempting_ultra_low_res", str(e))
            del backend_converter
            
        # Attempt 2: OCR with ultra-low-res images (0.15x resolution)
        logger.info("DOCLING_ATTEMPT_2 parsing_path=%s strategy=ocr_ultra_low_res", self.input_doc_path)
        try:
            gc.collect()
            ocr_options = PdfPipelineOptions()
            ocr_options.do_ocr = True
            ocr_options.force_backend_text = False
            # 0.15x = ~95% memory reduction vs 2.0x, still enough for text structure visibility
            ocr_options.images_scale = 0.15
            ocr_options.generate_page_images = True  # Keep for multimodal
            ocr_options.generate_picture_images = True  # Keep for multimodal

            ocr_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=ocr_options)
                }
            )
            ocr_result = ocr_converter.convert(self.input_doc_path)
            self.doc = ocr_result.document
            
            ocr_text_count = len(ocr_result.document.texts) if hasattr(ocr_result.document, 'texts') else 0
            ocr_total_length = sum(len(getattr(t, 'text', '')) for t in ocr_result.document.texts) if hasattr(ocr_result.document, 'texts') else 0
            logger.info("DOCLING_ATTEMPT_2_SUCCESS strategy=ocr_ultra_low_res text_items=%s total_text_length=%s", 
                       ocr_text_count, ocr_total_length)
            return
            
        except (MemoryError, RuntimeError) as e:
            logger.error("DOCLING_ATTEMPT_2_MEMORY_ERROR error=%s attempting_minimal_images", str(e))
            
        # Attempt 3: Last resort - minimal images
        logger.info("DOCLING_ATTEMPT_3 parsing_path=%s strategy=minimal_images", self.input_doc_path)
        try:
            gc.collect()
            minimal_options = PdfPipelineOptions()
            minimal_options.do_ocr = True
            minimal_options.force_backend_text = False
            # 0.1x = maximum compression, bare minimum for structure
            minimal_options.images_scale = 0.1
            minimal_options.generate_page_images = True
            minimal_options.generate_picture_images = False  # Only skip embedded pics

            minimal_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=minimal_options)
                }
            )
            minimal_result = minimal_converter.convert(self.input_doc_path)
            self.doc = minimal_result.document
            
            logger.info("DOCLING_ATTEMPT_3_SUCCESS strategy=minimal_images")
            return
            
        except (MemoryError, RuntimeError) as e:
            logger.error("DOCLING_ALL_ATTEMPTS_FAILED error=%s", str(e))
            raise RuntimeError(
                f"PDF parsing exhausted memory after 3 attempts. "
                f"PDF may exceed container memory limits ({e}). "
                f"Consider increasing container memory or splitting PDF."
            )

    @staticmethod
    def _has_sufficient_text(doc) -> bool:
        """Return True if the document has any meaningful extracted text (>5 chars).
        Used to decide whether OCR fallback is needed for scanned PDFs."""
        for text_item in doc.texts:
            text = getattr(text_item, "text", "").strip()
            if len(text) > 5:
                return True
        return False

    def find_phrase_locations(self, phrase: str) -> list[dict]:
        """Find all occurrences of a phrase in the parsed document.

        Returns a list of dicts with keys: text, page_no, bbox (l/t/r/b).
        Useful for driving the highlighter after a compliance scan.
        """
        phrase_lower = phrase.lower().strip()
        matches: list[dict] = []

        for text_item in self.doc.texts:
            text = getattr(text_item, "text", "").strip()
            if not text or phrase_lower not in text.lower():
                continue
            prov = getattr(text_item, "prov", [])
            if not prov:
                continue
            bbox = prov[0].bbox
            matches.append({
                "text": text,
                "page_no": prov[0].page_no,
                "bbox": {"l": bbox.l, "t": bbox.t, "r": bbox.r, "b": bbox.b},
            })
        return matches

    def save_doc_html(
        self,
        output_dir: Path | str,
        file_name: str,
        page_no: int = 1,
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / file_name
        self.doc.save_as_html(
            html_path,
            image_mode=ImageRefMode.REFERENCED,
        )
        return html_path

    @staticmethod
    def load_html(html_path: Path | str) -> BeautifulSoup:
        html_path = Path(html_path)
        with open(html_path, "r", encoding="utf-8") as f:
            return BeautifulSoup(f.read(), "html.parser")

    @staticmethod
    def write_html(html_path: Path | str, soup: BeautifulSoup) -> None:
        html_path = Path(html_path)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

    def collect_page_heights(self) -> dict:
        return {p_no: p.size.height for p_no, p in self.doc.pages.items()}

    @staticmethod
    def is_important_image(
        item: PictureItem,
        page_heights: dict,
        doc,
    ) -> bool:
        if not item.prov:
            return False

        prov = item.prov[0]
        bbox = prov.bbox
        page_height = page_heights.get(prov.page_no)

        if not page_height:
            return False

        image = item.get_image(doc)
        width, height = image.size

        is_small = width < 100 or height < 100
        is_header_footer = (
            bbox.t < page_height * 0.1 or bbox.b > page_height * 0.9
        )

        return not is_small and not is_header_footer

    def find_important_images(self) -> Set[str]:
        page_heights = self.collect_page_heights()
        important_coords: Set[str] = set()

        for element, _ in self.doc.iterate_items():
            if isinstance(element, PictureItem) and self.is_important_image(
                element, page_heights, self.doc
            ):
                bbox = element.prov[0].bbox
                important_coords.add(f"{bbox.l:.1f}-{bbox.t:.1f}")

        return important_coords

    def annotate_images(
        self,
        soup: BeautifulSoup,
        important_coords: Set[str],
    ) -> None:
        img_tags = soup.find_all("img")
        picture_items = [
            el
            for el, _ in self.doc.iterate_items()
            if isinstance(el, PictureItem)
        ]

        for img_tag, item in zip(img_tags, picture_items):
            if not getattr(item, "prov", None):
                img_tag["important"] = "false"
                img_tag["style"] = "display: none;"
                continue

            bbox = item.prov[0].bbox
            coord_key = f"{bbox.l:.1f}-{bbox.t:.1f}"

            if coord_key in important_coords:
                img_tag["important"] = "true"
                existing_class = img_tag.get("class", [])
                if not isinstance(existing_class, list):
                    existing_class = [existing_class]
                img_tag["class"] = existing_class + ["important-image"]
            else:
                img_tag["important"] = "false"
                img_tag["style"] = "display: none;"

    def build_text_lookup(self) -> dict:
        lookup = {}

        for text_item in self.doc.texts:
            prov = getattr(text_item, "prov", [])
            if not prov:
                continue

            bbox = prov[0].bbox
            text = getattr(text_item, "text", "").strip()
            if len(text) <= 2:
                continue

            style = getattr(text_item, "style", {})
            font_size = style.get("font_size", 12.0)

            lookup[text] = {
                "font_size": font_size,
                "pos": {
                    "l": bbox.l,
                    "t": bbox.t,
                    "r": bbox.r,
                    "b": bbox.b,
                    "w": bbox.r - bbox.l,
                    "h": bbox.b - bbox.t,
                },
            }

        return lookup

    @staticmethod
    def inject_text_metadata(soup: BeautifulSoup, item_lookup: dict) -> None:
        for node in soup.find_all(string=True):
            if node.parent.name not in {
                "p",
                "div",
                "li",
                "td",
                "th",
                "h1",
                "h2",
                "h3",
            }:
                continue

            text = node.strip()
            if text not in item_lookup:
                continue

            data = item_lookup[text]
            pos = data["pos"]

            span = soup.new_tag(
                "span",
                attrs={
                    "font-size": f"{data['font_size']:.1f}",
                    **{f"pos-{k}": f"{v:.1f}" for k, v in pos.items()},
                },
            )
            span.string = text
            node.replace_with(span)

    def add_metadata_to_file(
        self,
        output_dir: Path | str,
        file_name: str,
        page_no: int = 1,
    ) -> Path:
        output_dir = Path(output_dir)
        html_path = self.save_doc_html(output_dir, file_name, page_no)
        soup = self.load_html(html_path)

        important_coords = self.find_important_images()
        self.annotate_images(soup, important_coords)

        text_lookup = self.build_text_lookup()
        self.inject_text_metadata(soup, text_lookup)

        self.write_html(html_path, soup)
        return html_path
