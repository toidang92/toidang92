#!/usr/bin/env python3
"""Generate the README badge row.

Why a script: shields.io dropped several brand icons (LinkedIn among them — the
`logo=linkedin` slug now renders a badge with no glyph at all), so the icons here
are inlined as base64 data-URI SVGs instead. Hand-maintaining those URLs in
Markdown is unreadable; this file is the source of truth.

Usage:
    python3 scripts/badges.py            # print the markdown block
    python3 scripts/badges.py --write    # rewrite README.md between the markers
    python3 scripts/badges.py --check    # HTTP-check every generated URL

The markers in README.md must stay put:
    <!-- badges:start --> ... <!-- badges:end -->      the link row
    <!-- counter:start --> ... <!-- counter:end -->    the view counter
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import re
import sys
import urllib.parse
import urllib.request

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"

# Every outbound link to the site carries these, so GA4 can attribute traffic per
# CTA. Matches the convention in the blog's assets/js/extended/analytics.js:
# utm_source = originating site, utm_medium = referral.
UTM = "utm_source=github&utm_medium=referral&utm_campaign=profile-readme&utm_content="

# Lucide icon bodies (24x24, stroke-based). Kept as one visual family rather than
# mixed brand logos — half the brands we'd want aren't available anyway.
_SVG_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
)
ICONS = {
    # pen-line
    "blog": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    # briefcase
    "linkedin": (
        '<rect width="20" height="14" x="2" y="7" rx="2"/>'
        '<path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><path d="M2 13h20"/>'
    ),
    # mail
    "contact": (
        '<rect width="20" height="16" x="2" y="4" rx="2"/>'
        '<path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>'
    ),
    # eye
    "views": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
}


def logo_param(name: str) -> str:
    """base64 data-URI logo param. `+` and `=` must stay percent-encoded or
    shields reads the query string as truncated."""
    svg = f"<svg {_SVG_ATTRS}>{ICONS[name]}</svg>"
    b64 = base64.b64encode(svg.encode()).decode()
    return "logo=data:image/svg%2Bxml;base64," + urllib.parse.quote(b64, safe="")


def shields(label: str, message: str, color: str, icon: str, href: str) -> str:
    """A linked shields.io badge. Dashes in label/message would split the path,
    so they are doubled per shields' escaping rules."""
    esc = lambda s: urllib.parse.quote(s.replace("-", "--"), safe="")
    url = (
        f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}"
        f"?style=flat-square&{logo_param(icon)}&logoColor=white"
    )
    return f"[![{label}]({url})]({href})"


# hits.sh rather than komarev: it is the only counter that accepts a custom logo.
# The label carries its own caption so no prose has to sit beside the image -- a
# 20px badge in a run of text lands off the baseline, which is what made the
# earlier layout ugly. Expect a brief flicker on the count: it has to be served
# no-store to stay correct, so GitHub's Turbo paints the stale snapshot before
# swapping in the fresh one. Keeping it at the foot of the README is the mitigation.
def counter() -> str:
    label = urllib.parse.quote("Views since Aug 2026", safe="")
    return (
        f"![Views](https://hits.sh/github.com/toidang92.svg"
        f"?style=flat-square&label={label}&color=166534&{logo_param('views')}&logoColor=white)"
    )


def render() -> dict[str, str]:
    """Marker name -> block.

    Palette rule: this row stays on deep, low-chroma shades (Tailwind 700/800)
    in well-separated hues. The hero "Ask my CV" badge is the only bright,
    high-chroma colour on the page, and the only violet one — so it reads as
    the primary action. Never reuse #6E56CF here.
    """
    return {
        "badges": "\n".join(
            [
                shields("Blog", "toidang.xyz", "B45309", "blog", f"https://www.toidang.xyz/?{UTM}nav-blog"),
                shields("LinkedIn", "toidang92", "075985", "linkedin", "https://www.linkedin.com/in/toidang92"),
                shields("Contact", "form", "9F1239", "contact", f"https://www.toidang.xyz/r/cv?{UTM}nav-contact#contact-section"),
            ]
        ),
        "counter": counter(),
    }


def write(blocks: dict[str, str]) -> None:
    text = original = README.read_text(encoding="utf-8")
    for name, block in blocks.items():
        start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
        if start not in text or end not in text:
            sys.exit(f"markers {start} / {end} not found in {README}")
        text = re.sub(
            re.escape(start) + r".*?" + re.escape(end),
            lambda _, s=start, b=block, e=end: f"{s}\n{b}\n{e}",
            text,
            flags=re.S,
        )
    if text == original:
        print("README.md already up to date")
        return
    README.write_text(text, encoding="utf-8")
    print(f"wrote {README}")


def check(blocks: dict[str, str]) -> int:
    failed = 0
    urls = re.findall(r"\((https://(?:img\.shields\.io|hits\.sh)[^)]*)\)", "\n".join(blocks.values()))
    for url in urls:
        # shields.io 403s the default urllib User-Agent.
        req = urllib.request.Request(url, headers={"User-Agent": "badges.py"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", "replace")
            # A badge that asks for a logo but renders none still returns 200 --
            # that is exactly how shields' dropped linkedin icon slipped through.
            # Only badges that request one are held to it.
            has_icon = "<image" in body
            ok = resp.status == 200 and (has_icon or "logo=" not in url)
            print(f"{'ok  ' if ok else 'FAIL'} {resp.status} icon={has_icon} {url[:72]}…")
            failed += not ok
        except Exception as exc:  # noqa: BLE001 - report and keep checking the rest
            print(f"FAIL {exc} {url[:72]}…")
            failed += 1
    return failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite README.md in place")
    parser.add_argument("--check", action="store_true", help="HTTP-check the generated URLs")
    args = parser.parse_args()

    blocks = render()
    if args.write:
        write(blocks)
    if args.check:
        sys.exit(1 if check(blocks) else 0)
    if not (args.write or args.check):
        for name, block in blocks.items():
            print(f"--- {name} ---\n{block}")
