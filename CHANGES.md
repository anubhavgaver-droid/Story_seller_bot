# Story Seller Bot — v1.0.22

## पहले ये करें (Render क्रैश का फिक्स)
`config.py` में `CHANNEL_ID` अब **एक या कई ID कॉमा से** ले लेता है। पहले दो ID देने पर `int()` का ValueError आता था और बोट शुरू होते ही गिर जाता था। इस ज़िप का `config.py` उस क्रैश वाली लाइन को ठीक करता है।
- पहली ID "primary" है (पुरानी स्टोरीज़ इसी से चलती हैं)।
- `CHANNEL_ID=-100111,-100222` या अलग `DB_CHANNELS=-100222` दोनों चलते हैं।
- `requirements.txt` से दोहराव वाली `pyrogram` लाइन हटाई (Kurigram खुद वही पैकेज देता है)।

## नया क्या है

### 1. /admin: पूरा एडमिन पैनल
सारे एडमिन काम बटन से: Add / Edit Name / Set Episodes / Change Status / Add Episodes / Mark Complete / **Delete** (लिस्ट से चुनकर, पुष्टि के बाद) / Refresh / Repost (एक या सब) / Broadcast और Notify की गाइड / Add Money की गाइड / Payments / Free & Ads / Stats / Version और Help।
पुराने slash-commands पहले जैसे ही चलते हैं। पैनल उन्हीं को चलाता है।

### 2. /setup: पेमेंट और ऐड्स का सेटअप बोट के अंदर
- गेटवे: Demotry.shop, Razorpay, Cashfree। हर एक की API Key / Secret / Mode, Active बनाना, Test।
- UPI ID, Auto Pay ON / Maintenance।
- **Key स्वीकार न होने की दिक्कत ठीक:** सेटअप की स्थिति अब डेटाबेस में रहती है (Render restart या sleep पर नहीं खोती)। value साफ़ करके पढ़ी जाती है (स्पेस, `X-API-Key:` लेबल, कोट्स, डॉक्स से चिपका हुआ दोनों हेडर)। अस्वीकार होने पर कारण बताया जाता है।
- **दूसरा रास्ता:** `/setkey demotry api_key VALUE` वगैरह।

### 3. Free स्टोरी: Claim Free अब असली में अनलॉक करता है
- `/addstory` में कीमत **0** रखें तो स्टोरी फ्री है।
- स्टोरी पेज पर Buy की जगह **🎁 Claim Free** दिखता है (बोट, खोज और Mini App सब जगह)। चैनल पोस्ट पर "FREE 🎁" लिखा आता है।
- Mini App का Claim Free अब बोट खोलकर असली अनलॉक करता है (पहले सिर्फ़ स्क्रीन पर दिखता था)।

### 4. Free स्टोरी पर Ad / Shortener
- `/setup` → 🎁 Free Story Ads: ON/OFF, Shortener API URL, API Key, Minimum wait, Test।
- Claim Free दबाने पर यूज़र को शॉर्टनर का ऐड लिंक मिलता है। वह उसे पूरा करके बोट पर लौटता है और स्टोरी अनलॉक हो जाती है।
- टोकन सिर्फ़ उसी यूज़र के लिए, एक बार, और minimum wait के बाद चलता है (24 घंटे में expire)।
- Ads OFF हों तो Claim Free से सीधे अनलॉक। शॉर्टनर फेल हो जाए तो यूज़र को रोकते नहीं, सीधे अनलॉक होता है और आपको लॉग मिलता है।

### 5. /stats और /version
यूज़र, खरीदारी, गेटवे से आई कमाई (आज, 7 दिन, 30 दिन), टॉप स्टोरीज़, वॉलेट का कुल पैसा। रीस्टार्ट मैसेज में भी वर्ज़न दिखता है।

### पिछले अपग्रेड (v1.0.2x में शामिल)
रैंडम स्टोरी ID लिंक, कई DB चैनल, पेमेंट सुरक्षा (webhook की पुष्टि, atomic वॉलेट, double-click), 429 और 403 पर Manual विकल्प, Razorpay और Cashfree।

## फाइलें
- नई: `version.py`, `freeflow.py`, `gateway.py`, `fulfill.py`, `plugins/adminpanel.py`, `setup.py`, `settings.py`, `free.py`
- बदली: `config.py`, `main.py`, `app.py`, `requirements.txt`, `database/db.py`, `web/index.html`, `plugins/start.py`, `payment.py`, `search.py`, `admin.py`, `post.py`, `notification.py`

## लगाने के बाद
1. पूरा फोल्डर अपने प्रोजेक्ट पर कॉपी करें, बोट रीस्टार्ट करें। रीस्टार्ट मैसेज में `v1.0.22` दिखना चाहिए।
2. `/admin` खोलकर देखें।
3. `/setup` से गेटवे की keys डालें, Test दबाएँ, फिर Active और Auto Pay चालू करें। (अभी Auto Pay डिफ़ॉल्ट रूप से Maintenance में है।)
4. फ्री स्टोरी बनाएँ (कीमत 0) और Claim Free आज़माएँ। शॉर्टनर चाहिए तो `/setup` → Free Story Ads।
5. Razorpay या Cashfree का कोड आधिकारिक डॉक्स के हिसाब से लिखा है, पर असली अकाउंट पर टेस्ट नहीं हुआ। पहले Test, फिर ₹10 की खरीद।

## सीमाएँ (ईमानदारी से)
- शॉर्टनर का bypass पूरी तरह रोका नहीं जा सकता। हमने टोकन को एक बार, उसी यूज़र और minimum wait से बाँधा है।
- शॉर्टनर API का फ़ॉर्मेट `?api=KEY&url=LINK` वाला माना गया है (GPLinks, ShrinkMe जैसे)। किसी अलग फ़ॉर्मेट वाले शॉर्टनर के लिए छोटा बदलाव लगेगा। `/setup` में Test से पहले जाँच लें।
- Stats में "कमाई" सिर्फ़ गेटवे से आया पैसा गिनती है। वॉलेट से की गई खरीद और Manual अप्रूवल इसमें नहीं जुड़ते।
- कार्ट वाला हिस्सा कहीं से बनाया नहीं जाता, और `/api/user_purchases?user_id=` बिना लॉगिन के किसी की भी खरीदारी दिखा देता है। इन्हें मैंने नहीं छुआ।
- `config.py` में UPI ID और चैनल ID डिफ़ॉल्ट में लिखी हैं। इन्हें सिर्फ़ Render के environment variables में रखना बेहतर है।
