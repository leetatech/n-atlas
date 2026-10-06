import math
import re
from typing import Dict, Any

def extract_gas_order_intent(text: str, language: str = "en") -> Dict[str, Any]:
    """
    Extracts gas purchase intent and cylinder size from transcribed text.
    Handles English, Yoruba, Hausa, and Igbo keywords and accepts any cylinder size.
    """
    text_lower = text.lower()

    # Multilingual keywords for ordering/buying cooking gas
    gas_keywords = [
        # English
        "gas", "refill", "cylinder",
        # Yoruba
        "gáàsì", "gaasi", "ra", "fẹ́", "fe", "epo",
        # Hausa
        "iṣka", "iska", "siya", "sai", "oda", "kama",
        # Igbo
        "gasi", "azụ", "azu", "zụọ", "zuo", "mmanụ", "mmanu"
    ]
    
    mentions_gas = any(
        re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text_lower)
        for kw in gas_keywords
    )
    browsing = bool(re.search(
        r"\b(vendors?|nearby|near me|closest|where|find|looking for)\b", text_lower
    ))
    transactional = bool(re.search(
        r"\b(order|buy|purchase|refill|ra|fẹ́|fe|siya|sai|oda|azụ|azu|zụọ|zuo)\b", text_lower
    ))
    purchasing = transactional or bool(re.search(r"\b(need|want)\b", text_lower))
    negated = bool(re.search(
        r"\b(?:do not|don't|not|no)\s+(?:want\s+to\s+|want\s+|need\s+to\s+)?"
        r"(?:order|buy|purchase|refill|gas)\b", text_lower
    ))
    # Extract any numeric cylinder size (e.g., 3, 6, 12.5, 12, 15, 50, etc.)
    size_match = re.search(
        r'(?<![\w.+-])(\d+(?:\.\d+)?)\s*(?:kg|kilos?|kilograms?)\b', text_lower
    )
    
    cylinder_size = None
    if size_match:
        val = float(size_match.group(1))
        if val == 12:  # Common shorthand for 12.5kg
            cylinder_size = 12.5
        else:
            cylinder_size = val

    cylinder_size = (
        cylinder_size if cylinder_size and math.isfinite(cylinder_size) and cylinder_size > 0
        else None
    )
    has_gas_intent = mentions_gas and not negated and (
        transactional or (not browsing and (purchasing or cylinder_size is not None))
    )
    return {
        "is_gas_order": has_gas_intent,
        "is_order_declined": mentions_gas and negated,
        "size_kg": cylinder_size,
        "raw_text": text,
        "language": language
    }
