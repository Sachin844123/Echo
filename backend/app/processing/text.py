"""Conservative text normalization; offsets always refer to this cleaned text."""

import re
import unicodedata


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n"))
    value = "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and not 0x7F <= ord(c) <= 0x9F))
    value = re.sub(r"[^\S\n]+", " ", value)
    value = "\n".join(line.strip() for line in value.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", value).strip()
