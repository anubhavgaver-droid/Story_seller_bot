"""Bot version. Har upgrade par VERSION badlein aur CHANGELOG me upar nayi entry jodein."""

VERSION = "1.0.24"

CHANGELOG = [
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
