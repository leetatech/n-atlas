import re

VALID_CYLINDER_SIZES = [3, 6, 12.5, 25, 50]

def extract_gas_order_intent(transcription: str) -> dict:
    """Extracts gas purchase intent and cylinder size from transcribed text."""
    text_lower = transcription.lower()

    # Yoruba & English keywords for ordering gas
    gas_keywords = ["gáàsì", "gaasi", "gas", "refill", "ra", "fẹ́", "fe", "order", "buy"]
    has_gas_intent = any(kw in text_lower for kw in gas_keywords)

    # Extract cylinder sizes (e.g., 12.5kg, 12.5, 6kg, 50kg)
    size_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|kilo)?', text_lower)
    
    cylinder_size = None
    if size_match:
        val = float(size_match.group(1))
        if val in VALID_CYLINDER_SIZES:
            cylinder_size = val
        elif val == 12: # Common shorthand for 12.5kg
            cylinder_size = 12.5

    return {
        "is_order_intent": has_gas_intent,
        "cylinder_size_kg": cylinder_size,
        "raw_text": transcription
    }
