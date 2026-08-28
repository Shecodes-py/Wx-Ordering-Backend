"""
Entity extraction — pulls structured data out of a customer message.

Depends on:  rapidfuzz  (pip install rapidfuzz)
             word2number is replaced by our own WORD_TO_NUM map (no extra dep)
"""
import re
from typing import Optional

from rapidfuzz import process as fuzz_process, fuzz

from .patterns import (
    WORD_TO_NUM, QTY_PATTERN,
    CONFIRM_YES, CONFIRM_NO, NOTES_NONE,
    TRANSFER_KEYWORDS, POD_KEYWORDS,
    _norm,
)

# Minimum fuzzy-match score to accept an item match (0-100)
ITEM_MATCH_THRESHOLD = 65


# ---------------------------------------------------------------------------
# Core extraction entry point
# ---------------------------------------------------------------------------

def extract_entities(msg: str, intent: str, menu_items: list, session=None) -> dict:
    """
    Returns a dict with keys:
        items              list of {matched_menu_id, item_name, quantity}
        notes              str or None
        address            str or None
        payment_method     'TRANSFER' | 'PAY_ON_DELIVERY' | None
        is_confirmed       True | False | None
    """
    m = _norm(msg)

    entities = {
        'items': [],
        'notes': None,
        'address': None,
        'payment_method': None,
        'is_confirmed': None,
    }

    if intent == 'ADD_ITEM':
        entities['items'] = extract_items(msg, menu_items)

    elif intent == 'REMOVE_ITEM':
        entities['items'] = extract_items(msg, menu_items)

    elif intent == 'PROVIDE_NOTES':
        entities['notes'] = extract_notes(m)

    elif intent == 'PROVIDE_ADDRESS':
        entities['address'] = extract_address(msg, session)

    elif intent == 'SELECT_PAYMENT_METHOD':
        entities['payment_method'] = extract_payment_method(m)

    elif intent == 'CONFIRM_ORDER':
        entities['is_confirmed'] = extract_confirmation(m)

    return entities


# ---------------------------------------------------------------------------
# Item extraction
# ---------------------------------------------------------------------------

def extract_items(msg: str, menu_items: list) -> list:
    """
    Parse one or more items + quantities from a free-form message.

    Handles:
      "2 jollof rice"
      "jollof rice and chicken"
      "gimme 2 jollof, 1 coke and a chicken"
      "add item 3"
      "three portions of rice"
    """
    if not menu_items:
        return []

    # Build lookup structures
    menu_names = [item.name for item in menu_items]
    menu_by_position = {i + 1: item for i, item in enumerate(menu_items)}
    menu_by_id = {item.id: item for item in menu_items}

    found = []
    seen_ids = set()

    # ---- Strategy 1: positional references ("item 3", "number 2", "3rd") ----
    pos_pattern = re.compile(
        r'(?:item|number|no\.?|#)?\s*(\d+)(?:st|nd|rd|th)?',
        re.I,
    )
    for match in pos_pattern.finditer(msg):
        pos = int(match.group(1))
        item = menu_by_position.get(pos)
        if item and item.id not in seen_ids:
            qty = _extract_qty_before(msg, match.start()) or 1
            found.append(_item_dict(item, qty))
            seen_ids.add(item.id)

    # ---- Strategy 2: named item extraction ----
    # Split on separators to get candidate phrases
    segments = re.split(r'\band\b|,|\+|&', msg, flags=re.I)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # Extract quantity from segment
        qty = _extract_qty_from_segment(seg)

        # Remove qty words to isolate the item name candidate
        candidate = _strip_qty_words(seg)
        candidate = re.sub(
            r'\b(please|pls|gimme|give me|i want|i need|add|get me|order|some|of|portion|portions|serving|servings)\b',
            '',
            candidate, flags=re.I,
        ).strip()

        if len(candidate) < 2:
            continue

        # Fuzzy match against menu names
        result = fuzz_process.extractOne(
            candidate,
            menu_names,
            scorer=fuzz.WRatio,
            score_cutoff=ITEM_MATCH_THRESHOLD,
        )
        if result:
            matched_name, score, idx = result
            item = menu_items[idx]
            if item.id not in seen_ids:
                found.append(_item_dict(item, qty))
                seen_ids.add(item.id)

    return found


def _item_dict(item, quantity: int) -> dict:
    return {
        'matched_menu_id': item.id,
        'item_name': item.name,
        'quantity': max(1, quantity),
    }


def _extract_qty_from_segment(seg: str) -> int:
    """Find the first quantity signal in a segment."""
    m = QTY_PATTERN.search(seg)
    if not m:
        return 1
    word = m.group(1).lower()
    if word.isdigit():
        return max(1, int(word))
    return WORD_TO_NUM.get(word, 1)


def _extract_qty_before(msg: str, pos: int, window: int = 20) -> Optional[int]:
    """Look for a quantity number/word in the N chars before a position."""
    snippet = msg[max(0, pos - window):pos]
    m = QTY_PATTERN.search(snippet)
    if not m:
        return None
    word = m.group(1).lower()
    if word.isdigit():
        return int(word)
    return WORD_TO_NUM.get(word, 1)


def _strip_qty_words(seg: str) -> str:
    """Remove leading quantity expressions so only the item name remains."""
    seg = QTY_PATTERN.sub('', seg, count=1).strip()
    # Remove common prefix filler
    seg = re.sub(r'^(of|x)\s+', '', seg, flags=re.I)
    return seg.strip()


# ---------------------------------------------------------------------------
# Notes extraction
# ---------------------------------------------------------------------------

def extract_notes(m: str) -> str:
    """
    Return empty string for 'none/nothing/no', otherwise return the message as notes.
    """
    if m in NOTES_NONE or any(n == m for n in NOTES_NONE):
        return ''
    # Strip meta-phrases the customer might add
    cleaned = re.sub(
        r'^(my note(s)?( is| are)?|special (instruction|request)(s)?( is| are)?|note(s)?:?)\s*',
        '',
        m, flags=re.I,
    ).strip()
    return cleaned or m


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------

def extract_address(msg: str, session=None) -> str:
    """
    If the customer confirmed their saved address, return it.
    Otherwise return the message as the address (stripped of filler).
    """
    m = _norm(msg)

    # Confirming saved address
    confirm_saved = {
        'yes', 'yeah', 'yep', 'yup', 'same', 'same address', 'same place',
        'correct', 'that one', 'there', 'use that', 'use it', 'ok', 'okay',
        'sure', 'that address', 'deliver there', 'same location',
    }
    if m in confirm_saved or any(k in m for k in confirm_saved):
        if session and session.profile.delivery_address:
            return session.profile.delivery_address
        # Can't confirm a non-existent address — fall through to treat as new address

    # Strip meta-phrases
    cleaned = re.sub(
        r'^(my address( is)?|deliver to|delivery address( is)?|send to|address:?)\s*',
        '',
        msg.strip(), flags=re.I,
    ).strip()
    return cleaned or msg.strip()


# ---------------------------------------------------------------------------
# Payment method extraction
# ---------------------------------------------------------------------------

def extract_payment_method(m: str) -> Optional[str]:
    if any(k in m for k in TRANSFER_KEYWORDS):
        return 'TRANSFER'
    if any(k in m for k in POD_KEYWORDS):
        return 'PAY_ON_DELIVERY'
    return None


# ---------------------------------------------------------------------------
# Confirmation extraction
# ---------------------------------------------------------------------------

def extract_confirmation(m: str) -> bool:
    if m in CONFIRM_YES or any(k in m for k in CONFIRM_YES):
        return True
    return False  # Default: treat as not confirmed / wants to change
