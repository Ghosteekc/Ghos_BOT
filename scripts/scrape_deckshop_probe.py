from __future__ import annotations

import re
import urllib.request

html = urllib.request.urlopen(
    urllib.request.Request(
        "https://www.deckshop.pro/ru/card/detail/hog-rider",
        headers={"User-Agent": "Mozilla/5.0"},
    ),
    timeout=30,
).read().decode("utf-8", "replace")

for m in re.finditer(r'id="([^"]*(?:cnt|synergy|counter)[^"]*)"', html, re.I):
    print(m.group(1), "at", m.start())

# second column in counter grid
idx = html.find('id="atkcnt"')
chunk = html[idx : idx + 25000]
for m in re.finditer(r'<h4[^>]*id="([^"]*)"[^>]*>(.*?)</h4>', chunk, re.S):
    title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
    print("h4", m.group(1), title[:80])
