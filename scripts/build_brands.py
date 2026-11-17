#!/usr/bin/env python3
"""
Build the branded copies of Leverage Scout from the main index.html.

  kt/  Kingdom Traders      https://mountytechwv.github.io/leverage-scout/kt/
  le/  LE Trading Academy   https://mountytechwv.github.io/leverage-scout/le/

Each copy is the same page with:
  * <base href="../"> so it shares the data, icons and service worker at the root
  * window.BRAND_ID set, which switches on the brand's colors, logo and header
  * its own title, home-screen name, icons and link-preview tags
  * its own manifest so it installs as its own app

Only edit the main index.html. The GitHub Action runs this script whenever
index.html changes, so the branded pages always match it.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://mountytechwv.github.io/leverage-scout"

BRANDS = {
    "kt": {
        "name": "Kingdom Traders Leverage Scout",
        "short": "KT Scout",
        "description": "Kingdom Traders: every US leveraged and inverse ETF in one searchable list, with volume, liquidity and a Day Trade filter.",
        "theme": "#3A1F6E",
        "background": "#00051B",
        "icon192": "brands/kt/icon-192.png",
        "icon512": "brands/kt/icon-512.png",
    },
    "le": {
        "name": "LE Trading Academy Leverage Scout",
        "short": "LE Scout",
        "description": "LE Trading Academy: every US leveraged and inverse ETF in one searchable list, with volume, liquidity and a Day Trade filter.",
        "theme": "#673AB7",
        "background": "#F7F6FC",
        "icon192": "brands/le/icon-192.png",
        "icon512": "brands/le/icon-512.png",
    },
}


def sub(pattern, repl, text):
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise SystemExit(f"build_brands: could not find {pattern!r} in index.html")
    return new


def build(brand_id, b, src):
    h = src
    h = sub(r"<head>\n", f'<head>\n<base href="../">\n<script>window.BRAND_ID = "{brand_id}";</script>\n', h)
    h = sub(r"<title>.*?</title>", f"<title>{b['name']}</title>", h)
    h = sub(r'<meta name="theme-color" content="[^"]*">', f'<meta name="theme-color" content="{b["theme"]}">', h)
    h = sub(r'<link rel="icon" href="favicon.ico" sizes="any">', f'<link rel="icon" href="{b["icon192"]}" sizes="192x192">', h)
    h = sub(r'<link rel="icon" href="icons/icon.svg" type="image/svg\+xml">\n', "", h)
    h = sub(r'<link rel="apple-touch-icon" href="[^"]*">', f'<link rel="apple-touch-icon" href="{b["icon192"]}">', h)
    h = sub(r'<link rel="manifest" href="[^"]*">', f'<link rel="manifest" href="{brand_id}/manifest.webmanifest">', h)
    h = sub(r'<meta name="apple-mobile-web-app-title" content="[^"]*">', f'<meta name="apple-mobile-web-app-title" content="{b["short"]}">', h)
    h = sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{b["name"]}">', h)
    h = sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{b["description"]}">', h)
    h = sub(r'<meta property="og:image" content="[^"]*">', f'<meta property="og:image" content="{SITE}/{b["icon512"]}">', h)
    h = sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{SITE}/{brand_id}/">', h)
    h = h.replace("<!DOCTYPE html>", "<!DOCTYPE html>\n<!-- Generated from ../index.html by scripts/build_brands.py. Edit index.html, not this file. -->", 1)
    return h


def manifest(brand_id, b):
    return {
        "name": b["name"],
        "short_name": b["short"],
        "description": b["description"],
        "id": "./",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": b["background"],
        "theme_color": b["theme"],
        "icons": [
            {"src": f"../{b['icon192']}", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": f"../{b['icon512']}", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
    }


def main():
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    for brand_id, b in BRANDS.items():
        out = ROOT / brand_id
        out.mkdir(exist_ok=True)
        (out / "index.html").write_text(build(brand_id, b, src), encoding="utf-8")
        (out / "manifest.webmanifest").write_text(json.dumps(manifest(brand_id, b), indent=2) + "\n", encoding="utf-8")
        print(f"built {brand_id}/index.html")


if __name__ == "__main__":
    main()
