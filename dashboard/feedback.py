"""
Feedback capture — shared by both bot channels (bot/views.py, meta_bot/views.py).

Deliberately simple: only recognises a standalone digit 1-5 (optionally
spelled out) anywhere in the message. If nothing matches, the caller should
treat the message as NOT feedback and let it flow through the normal intent
pipeline instead — never guess a rating.
"""
import re

from .models import Feedback

_DIGIT_PATTERN = re.compile(r'\b([1-5])\b')
_WORD_TO_RATING = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
_RATING_CONTEXT = re.compile(r'\b(stars?|rate|rating|out of)\b|/5', re.I)
_MAX_WORDS_FOR_BARE_NUMBER = 4  # e.g. "5", "5 stars, amazing!", "four out of five"


def extract_rating(msg: str):
    """
    Return an int 1-5 if the message looks like a rating, else None.

    Deliberately conservative: a bare number only counts as a rating in a
    short message or alongside explicit rating language ("stars", "/5",
    "out of", "rate") — otherwise a message like "2 jollof rice" would get
    misread as a rating of 2.
    """
    msg = (msg or '').strip()
    if not msg:
        return None

    lowered = msg.lower()
    digit_match = _DIGIT_PATTERN.search(msg)
    rating = int(digit_match.group(1)) if digit_match else None
    if rating is None:
        for word, value in _WORD_TO_RATING.items():
            if re.search(rf'\b{word}\b', lowered):
                rating = value
                break
    if rating is None:
        return None

    if _RATING_CONTEXT.search(lowered):
        return rating
    if len(msg.split()) <= _MAX_WORDS_FOR_BARE_NUMBER:
        return rating
    return None


def save_feedback(order, rating: int, message: str) -> Feedback:
    return Feedback.objects.create(
        customer=order.customer,
        order=order,
        rating=rating,
        message=message.strip(),
    )
