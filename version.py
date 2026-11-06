"""Bot version. Har upgrade par VERSION badlein aur CHANGELOG me upar nayi entry jodein."""

VERSION = "1.0.26"

CHANGELOG = [
    ("1.0.26", [
        "New gateway: FamPay (Gmail). Reads the payment-received emails over IMAP and matches each payment by its exact amount and UTR",
        "Every order gets a unique amount (price plus a few paise); the order is delivered automatically when the matching email arrives",
        "Spoof protection: only the configured sender, and only when Gmail's DKIM/SPF check passed; a UTR can be used once",
    ]),
    ("1.0.25", [
        "Whole bot: every text screen now uses Telegram Rich Messages (big heading, bordered tables, buttons inside the message)",
        "One global hook on Client.send_message / edit_message_text, with automatic fallback per message; /richui all | admin | off",
        "Admin panels and every button press edit the same message instead of sending a new page",
    ]),
    ("1.0.24", [
        "Panels (/admin, /setup) now EDIT the same message on every button (Next, Back, Delete list ...)",
        "Big, dark real headings using Telegram Rich Messages (with automatic fallback and a /richui switch)",
    ]),
    ("1.0.23", [
        "Fixed: setup values (API keys, shortener URL, UPI ID) were not being saved or answered",
        "Auto UPI now shows a 'Please wait, your invoice is being generated' message instead of a popup",
        "All new screens are in proper English with small-caps headings",
        "New: 'I paid but got nothing' support button with one-tap admin check",
        "New: wallet top-up bonus (set in /setup)",
        "New: UTR duplicate guard for manual payments",
        "Security: the purchases API now needs Telegram's signed initData",
    ]),
    ("1.0.22", [
        "Admin Panel (/admin): saari admin commands buttons se",
        "/setup: payment gateway (Demotry / Razorpay / Cashfree) bot ke andar se set",
        "Free story: Claim Free asli me unlock karta hai",
        "Free story par optional Ad / Shortener gate",
        "Random story ID links, kai DB channels, /stats, /version",
        "Payment security fixes (webhook, atomic wallet, double-click)",
    ]),
]
