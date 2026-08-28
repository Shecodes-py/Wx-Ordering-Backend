"""
WX NLU Training Dataset
=======================

Labeled examples of customer messages → expected intent + entities.

Purpose:
  1. Documents every phrase the engine should handle (living spec).
  2. Powers the test suite (run: python -m bot.nlu.dataset).
  3. Foundation for fine-tuning a small transformer if you ever want to
     go that route (export with dump_jsonl()).

Add new examples as you discover what real customers say.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Example:
    text: str
    intent: str
    items: list = field(default_factory=list)      # [{'name': str, 'qty': int}]
    notes: Optional[str] = None
    address: Optional[str] = None
    payment_method: Optional[str] = None           # 'TRANSFER' | 'PAY_ON_DELIVERY'
    is_confirmed: Optional[bool] = None
    state: str = 'ORDERING'


DATASET: list[Example] = [

    # ── VIEW_MENU ────────────────────────────────────────────────────────────
    Example("menu",                        "VIEW_MENU"),
    Example("show menu",                   "VIEW_MENU"),
    Example("what do you have",            "VIEW_MENU"),
    Example("what do you sell",            "VIEW_MENU"),
    Example("what's available",            "VIEW_MENU"),
    Example("whats available",             "VIEW_MENU"),
    Example("your menu please",            "VIEW_MENU"),
    Example("let me see your menu",        "VIEW_MENU"),
    Example("what can I order",            "VIEW_MENU"),
    Example("options",                     "VIEW_MENU"),
    Example("list of items",               "VIEW_MENU"),

    # ── GREET → VIEW_MENU ────────────────────────────────────────────────────
    Example("hi",       "VIEW_MENU"),
    Example("hello",    "VIEW_MENU"),
    Example("hey",      "VIEW_MENU"),
    Example("start",    "VIEW_MENU"),
    Example("restart",  "VIEW_MENU"),

    # ── ADD_ITEM — by name ───────────────────────────────────────────────────
    Example("jollof rice",                    "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}]),
    Example("I want jollof rice",             "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}]),
    Example("give me jollof rice",            "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}]),
    Example("add chicken",                    "ADD_ITEM", items=[{'name': 'Chicken', 'qty': 1}]),
    Example("2 jollof rice",                  "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 2}]),
    Example("two jollof rice",                "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 2}]),
    Example("gimme 3 chicken",                "ADD_ITEM", items=[{'name': 'Chicken', 'qty': 3}]),
    Example("i need 2 jollof and a chicken",  "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 2}, {'name': 'Chicken', 'qty': 1}]),
    Example("jollof rice and fried chicken",  "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}, {'name': 'Fried Chicken', 'qty': 1}]),
    Example("coke please",                    "ADD_ITEM", items=[{'name': 'Coca-Cola', 'qty': 1}]),
    Example("a bottle of water",              "ADD_ITEM", items=[{'name': 'Water', 'qty': 1}]),
    Example("5 packs of rice",                "ADD_ITEM", items=[{'name': 'Rice', 'qty': 5}]),
    Example("jollof",                         "ADD_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}]),
    Example("chicken rice",                   "ADD_ITEM", items=[{'name': 'Chicken Rice', 'qty': 1}]),

    # ── ADD_ITEM — by number ─────────────────────────────────────────────────
    Example("1",          "ADD_ITEM", items=[{'name': None, 'qty': 1, 'position': 1}]),
    Example("item 2",     "ADD_ITEM", items=[{'name': None, 'qty': 1, 'position': 2}]),
    Example("number 3",   "ADD_ITEM", items=[{'name': None, 'qty': 1, 'position': 3}]),
    Example("2 of item 1","ADD_ITEM", items=[{'name': None, 'qty': 2, 'position': 1}]),
    Example("add 1 and 3","ADD_ITEM", items=[{'name': None, 'qty': 1, 'position': 1}, {'name': None, 'qty': 1, 'position': 3}]),

    # ── REMOVE_ITEM ──────────────────────────────────────────────────────────
    Example("remove chicken",          "REMOVE_ITEM", items=[{'name': 'Chicken', 'qty': 1}]),
    Example("take out the coke",       "REMOVE_ITEM", items=[{'name': 'Coca-Cola', 'qty': 1}]),
    Example("delete jollof rice",      "REMOVE_ITEM", items=[{'name': 'Jollof Rice', 'qty': 1}]),
    Example("cancel the chicken",      "REMOVE_ITEM", items=[{'name': 'Chicken', 'qty': 1}]),
    Example("remove one chicken",      "REMOVE_ITEM", items=[{'name': 'Chicken', 'qty': 1}]),
    Example("less 2 jollof",           "REMOVE_ITEM", items=[{'name': 'Jollof Rice', 'qty': 2}]),
    Example("drop the water",          "REMOVE_ITEM", items=[{'name': 'Water', 'qty': 1}]),

    # ── VIEW_CART ────────────────────────────────────────────────────────────
    Example("what's in my cart",     "VIEW_CART"),
    Example("show my order",         "VIEW_CART"),
    Example("my cart",               "VIEW_CART"),
    Example("cart",                  "VIEW_CART"),
    Example("what did I add",        "VIEW_CART"),
    Example("current order",         "VIEW_CART"),

    # ── PROCEED_TO_CHECKOUT ──────────────────────────────────────────────────
    Example("done",          "PROCEED_TO_CHECKOUT"),
    Example("that's all",    "PROCEED_TO_CHECKOUT"),
    Example("checkout",      "PROCEED_TO_CHECKOUT"),
    Example("check out",     "PROCEED_TO_CHECKOUT"),
    Example("order now",     "PROCEED_TO_CHECKOUT"),
    Example("place order",   "PROCEED_TO_CHECKOUT"),
    Example("I'm ready",     "PROCEED_TO_CHECKOUT"),
    Example("ready",         "PROCEED_TO_CHECKOUT"),
    Example("proceed",       "PROCEED_TO_CHECKOUT"),
    Example("thats it",      "PROCEED_TO_CHECKOUT"),
    Example("finish",        "PROCEED_TO_CHECKOUT"),

    # ── PROVIDE_NOTES ────────────────────────────────────────────────────────
    Example("no onions",                            "PROVIDE_NOTES", notes="no onions",            state="CONFIRMATION"),
    Example("extra spicy please",                   "PROVIDE_NOTES", notes="extra spicy",           state="CONFIRMATION"),
    Example("well done, no pepper",                 "PROVIDE_NOTES", notes="well done, no pepper",  state="CONFIRMATION"),
    Example("none",                                 "PROVIDE_NOTES", notes="",                      state="CONFIRMATION"),
    Example("nothing",                              "PROVIDE_NOTES", notes="",                      state="CONFIRMATION"),
    Example("no special instructions",              "PROVIDE_NOTES", notes="",                      state="CONFIRMATION"),
    Example("no thanks",                            "PROVIDE_NOTES", notes="",                      state="CONFIRMATION"),
    Example("all good",                             "PROVIDE_NOTES", notes="",                      state="CONFIRMATION"),

    # ── PROVIDE_ADDRESS ──────────────────────────────────────────────────────
    Example("12 Adeola Odeku Street, Victoria Island", "PROVIDE_ADDRESS", address="12 Adeola Odeku Street, Victoria Island", state="CONFIRMATION"),
    Example("Flat 3, Block A, Lekki Phase 1",          "PROVIDE_ADDRESS", address="Flat 3, Block A, Lekki Phase 1",          state="CONFIRMATION"),
    Example("same address",                             "PROVIDE_ADDRESS", address=None,  state="CONFIRMATION"),  # uses saved
    Example("yes same place",                           "PROVIDE_ADDRESS", address=None,  state="CONFIRMATION"),
    Example("deliver to my house",                      "PROVIDE_ADDRESS", address="my house", state="CONFIRMATION"),

    # ── SELECT_PAYMENT_METHOD ────────────────────────────────────────────────
    Example("bank transfer",     "SELECT_PAYMENT_METHOD", payment_method="TRANSFER",       state="CONFIRMATION"),
    Example("transfer",          "SELECT_PAYMENT_METHOD", payment_method="TRANSFER",       state="CONFIRMATION"),
    Example("1",                 "SELECT_PAYMENT_METHOD", payment_method="TRANSFER",       state="CONFIRMATION"),
    Example("pay on delivery",   "SELECT_PAYMENT_METHOD", payment_method="PAY_ON_DELIVERY",state="CONFIRMATION"),
    Example("cash",              "SELECT_PAYMENT_METHOD", payment_method="PAY_ON_DELIVERY",state="CONFIRMATION"),
    Example("cod",               "SELECT_PAYMENT_METHOD", payment_method="PAY_ON_DELIVERY",state="CONFIRMATION"),
    Example("2",                 "SELECT_PAYMENT_METHOD", payment_method="PAY_ON_DELIVERY",state="CONFIRMATION"),
    Example("pay at door",       "SELECT_PAYMENT_METHOD", payment_method="PAY_ON_DELIVERY",state="CONFIRMATION"),

    # ── CONFIRM_ORDER — yes ──────────────────────────────────────────────────
    Example("yes",          "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("confirm",      "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("looks good",   "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("go ahead",     "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("yep",          "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("sure",         "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("perfect",      "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),
    Example("correct",      "CONFIRM_ORDER", is_confirmed=True,  state="CONFIRMATION"),

    # ── CONFIRM_ORDER — no ───────────────────────────────────────────────────
    Example("no",           "CONFIRM_ORDER", is_confirmed=False, state="CONFIRMATION"),
    Example("wait",         "CONFIRM_ORDER", is_confirmed=False, state="CONFIRMATION"),
    Example("change it",    "CONFIRM_ORDER", is_confirmed=False, state="CONFIRMATION"),
    Example("actually no",  "CONFIRM_ORDER", is_confirmed=False, state="CONFIRMATION"),

    # ── CANCEL ───────────────────────────────────────────────────────────────
    Example("cancel",       "CANCEL"),
    Example("never mind",   "CANCEL"),
    Example("nevermind",    "CANCEL"),
    Example("start over",   "CANCEL"),
    Example("reset",        "CANCEL"),
    Example("clear cart",   "CANCEL"),
    Example("abort",        "CANCEL"),

]


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def dump_jsonl(path: str = 'wx_nlu_dataset.jsonl'):
    """Write dataset as JSON Lines for ML training tools."""
    import json
    with open(path, 'w', encoding='utf-8') as f:
        for ex in DATASET:
            f.write(json.dumps({
                'text': ex.text,
                'intent': ex.intent,
                'items': ex.items,
                'notes': ex.notes,
                'address': ex.address,
                'payment_method': ex.payment_method,
                'is_confirmed': ex.is_confirmed,
                'state': ex.state,
            }, ensure_ascii=False) + '\n')
    print(f"Exported {len(DATASET)} examples → {path}")


def intent_counts() -> dict:
    from collections import Counter
    return dict(Counter(ex.intent for ex in DATASET))


# ---------------------------------------------------------------------------
# Quick smoke test (python -m bot.nlu.dataset)
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    counts = intent_counts()
    print("Dataset summary:")
    for intent, count in sorted(counts.items()):
        print(f"  {intent:<30} {count} examples")
    print(f"\nTotal: {len(DATASET)} examples")
    print("\nExporting JSONL...")
    dump_jsonl()
