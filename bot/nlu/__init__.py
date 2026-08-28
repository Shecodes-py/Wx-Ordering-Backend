"""
WX NLU — custom intent/entity engine for the WhatsApp ordering bot.

No external API. No generative model. Pipeline:

  message
    → patterns.detect_intent()      (regex + state-aware rules)
    → extractor.extract_entities()  (fuzzy menu match, qty, address, payment)
    → responder.build_reply()       (template-based, warm)
    → structured dict               (same schema the views.py dispatcher expects)
"""
from .engine import process_message  # noqa: F401
