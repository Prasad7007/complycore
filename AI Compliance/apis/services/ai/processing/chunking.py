import logging
import os

from bs4 import BeautifulSoup
import tiktoken

from apis.services.ai.core.config import CHUNK_MIN_TOKENS, CHUNK_MAX_TOKENS, CHUNK_TARGET_TOKENS

logger = logging.getLogger(__name__)

# gpt-4o uses o200k_base (~large vocab); loading it can MemoryError on low-RAM Windows.
# Chunk sizing only needs a consistent tokenizer — cl100k_base matches GPT-4/GPT-3.5-style counts.
_DEFAULT_ENCODING = "cl100k_base"


class Chunker:
    def __init__(
        self,
        target_tokens: int = CHUNK_TARGET_TOKENS,
        min_tokens: int = CHUNK_MIN_TOKENS,
        max_tokens: int = CHUNK_MAX_TOKENS,
        model_name: str = "gpt-4o",
    ):
        self.target_tokens = target_tokens
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.model_name = model_name
        enc_name = (os.getenv("TIKTOKEN_ENCODING") or "").strip() or _DEFAULT_ENCODING
        try:
            self.enc = tiktoken.get_encoding(enc_name)
        except Exception as e:
            logger.warning(
                "tiktoken get_encoding(%r) failed (%s); using %s",
                enc_name,
                e,
                _DEFAULT_ENCODING,
            )
            self.enc = tiktoken.get_encoding(_DEFAULT_ENCODING)

    def token_count(self,text:str)-> int : 
        return len(self.enc.encode(text))
    
    def _extract_text_and_metadata(self, element) -> tuple[str, list[dict]]:
        """
        Recursively extract text and metadata from an element.
        Returns: (text, list of metadata dicts)
        Metadata dict: {
            "text": str,
            "font_size": float | None,
            "bbox": list[float] | None  # [left, top, right, bottom]
        }
        """
        text_parts = []
        metadata_list = []
        
        # If it's a NavigableString (just text), return it
        if isinstance(element, str):
            clean_text = element.strip()
            if clean_text:
                text_parts.append(clean_text)
                # No metadata for raw text nodes usually, unless parent passed it down
            return "".join(text_parts), metadata_list

        # If it's an element (tag)
        if hasattr(element, "children"):
            for child in element.children:
                if child.name == "span":
                    # Extract metadata from span attributes
                    font_size = None
                    bbox = None
                    
                    fs_str = child.get("font-size")
                    if fs_str:
                        try:
                            font_size = float(fs_str)
                        except ValueError:
                            pass
                            
                    # Coordinates: bbox="[L, T, R, B]" or separate attrs
                    # Parsing.py produces separate attrs: pos-l, pos-t, pos-r, pos-b
                    try:
                        l = float(child.get("pos-l", 0))
                        t = float(child.get("pos-t", 0))
                        r = float(child.get("pos-r", 0))
                        b = float(child.get("pos-b", 0))
                        if l or t or r or b:
                            bbox = [l, t, r, b]
                    except ValueError:
                        pass
                    
                    span_text = child.get_text(strip=True)
                    if span_text:
                        text_parts.append(span_text)
                        metadata_list.append({
                            "text": span_text,
                            "font_size": font_size,
                            "bbox": bbox
                        })
                elif isinstance(child, str):
                    clean = child.strip()
                    if clean:
                        text_parts.append(clean)
                else:
                    # Recurse for other tags (bold, italic, etc)
                    t, m = self._extract_text_and_metadata(child)
                    text_parts.append(t)
                    metadata_list.extend(m)
                    
        return " ".join(text_parts), metadata_list

    def parse_html_with_media(self, html: str):
        soup = BeautifulSoup(html, "html.parser")
        blocks = []
        current_h1 = None
        current_h2 = None

        for tag in soup.find_all(["h1", "h2", "p", "li", "table", "figure"]):
            if tag.name == "h1":
                current_h1 = tag.get_text(strip=True)
                current_h2 = None
                continue

            if tag.name == "h2":
                current_h2 = tag.get_text(strip=True)
                continue

            if tag.name == "figure":
                img = tag.find("img")
                if (
                    img
                    and img.get("src")
                    and img.get("important") == "true"
                ):
                    blocks.append({
                        "type": "image",
                        "h1": current_h1,
                        "h2": current_h2,
                        "src": img["src"]
                    })
                continue

            if tag.name == "table":
                blocks.append({
                    "type": "table",
                    "h1": current_h1,
                    "h2": current_h2,
                    "html": str(tag)
                })
                continue

            # Text block - extract metadata
            content_text, metadata = self._extract_text_and_metadata(tag)
            if content_text:
                blocks.append({
                    "type": "text",
                    "h1": current_h1,
                    "h2": current_h2,
                    "content": content_text,
                    "metadata": metadata 
                })

        return blocks

    def build_chunks(self, blocks):
        chunks = []
        current_text = ""
        current_media = []
        current_metadata = [] # Accumulate metadata for the chunk
        current_tokens = 0

        def flush(force=False):
            nonlocal current_text, current_media, current_metadata, current_tokens
            if current_text.strip() or current_media:
                chunks.append({
                    "text": current_text.strip(),
                    "media": current_media,
                    "metadata": current_metadata # Include accumulated metadata
                })
            current_text = ""
            current_media = []
            current_metadata = []
            current_tokens = 0

        for block in blocks:
            header = ""
            if block.get("h1"):
                header += f"\n# {block['h1']}\n"
            if block.get("h2"):
                header += f"\n## {block['h2']}\n"

            # ---------- MEDIA ----------
            if block["type"] in ["image", "table"]:
                media_tokens = self.token_count(header)

                # Case 1: media fits in current chunk
                if current_tokens + media_tokens <= self.max_tokens:
                    current_text += header
                    current_tokens += media_tokens
                    current_media.append(block)
                else:
                    # Case 2: chunk is already "good enough"
                    if current_tokens >= self.min_tokens:
                        flush()
                    # Case 3: still too small → allow overflow (intentional)
                    current_text += header
                    current_tokens += media_tokens
                    current_media.append(block)
                continue

            # ---------- TEXT ----------
            text = header + block["content"] + "\n"
            tokens = self.token_count(text)
            
            # Metadata for this block
            block_meta = block.get("metadata", [])

            # If adding this crosses hard max
            if current_tokens + tokens > self.max_tokens:
                if current_tokens >= self.min_tokens:
                    flush()
                # else: intentionally overflow to reach density

            current_text += text
            current_tokens += tokens
            current_metadata.extend(block_meta) # Add block metadata to chunk

            # Optional early close near target
            if current_tokens >= self.target_tokens:
                flush()

        flush()
        return chunks

    def chunk_html_with_media(self, html: str):
        blocks = self.parse_html_with_media(html)
        return self.build_chunks(blocks)