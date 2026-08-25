"""TEMM V1 token contrast gate — freeze §5.3.

Validates the canonical token pairs in src/styles/tokens.css against the
binding contrast requirements, on BOTH canvases (Graphite dark, Chalk light).

  body/small text      >= 4.5:1   (WCAG 2.1 AA 1.4.3, no large-text exemption)
  state ink vs canvas  >= 3.0:1   (WCAG 2.1 AA 1.4.11 non-text)
  focus ring           >= 3.0:1   vs component AND surface
  earned green         >= 4.5:1   even as a graphical fill (it is the payoff)

usage:  python tools_web/check_token_contrast.py
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "apps/web/src/styles/tokens.css"


def parse_tokens(text: str, block: str) -> dict:
    """Extract custom properties from a :root-like block."""
    m = re.search(re.escape(block) + r"\s*\{(.*?)\n\}", text, re.S)
    out = {}
    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)):
        out[name] = value.strip()
    return out


def resolve(name, scopes):
    for s in scopes:
        if name in s and not s[name].startswith("var("):
            return s[name]
        if name in s:
            return resolve(s[name].strip()[4:-1].strip(), scopes)
    raise KeyError(name)


def lum(hex_color: str) -> float:
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) == 8:  # alpha hatch — composite over nothing, use rgb only
        hex_color = hex_color[:6]
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(fg: str, bg: str) -> float:
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    text = CSS.read_text(encoding="utf-8")
    chalk = parse_tokens(text, ":root")
    graphite = parse_tokens(text, ":root[data-theme='dark']")

    # text pairs: token -> minimum ratio
    text_pairs = {
        "--c-ink-1": 4.5,
        "--c-ink-2": 4.5,
        "--c-ink-3": 4.5,
    }
    # non-text pairs vs canvas: token -> minimum ratio
    nontext_pairs = {
        "--c-line-planned": 3.0,
        "--c-clay": 3.0,
        "--c-live": 3.0,
        "--c-verify": 3.0,
    }

    failures = []
    for label, scope in (("CHALK", [chalk]), ("GRAPHITE", [graphite, chalk])):
        canvas = resolve("--c-canvas", scope)
        print(f"\n== {label}  canvas {canvas} ==")
        for tok, minimum in text_pairs.items():
            r = ratio(resolve(tok, scope), canvas)
            ok = r >= minimum
            print(f"  {'PASS' if ok else 'FAIL'}  {tok:18s} {r:5.2f}:1  (>= {minimum})")
            if not ok:
                failures.append((label, tok, r))
        for tok, minimum in nontext_pairs.items():
            r = ratio(resolve(tok, scope), canvas)
            ok = r >= minimum
            print(f"  {'PASS' if ok else 'FAIL'}  {tok:18s} {r:5.2f}:1  (>= {minimum})")
            if not ok:
                failures.append((label, tok, r))
        # earned green: binding at 4.5 even as a graphical fill
        g = resolve("--c-green", scope)
        r = ratio(g, canvas)
        print(f"  {'PASS' if r >= 4.5 else 'FAIL'}  {'--c-green':18s} {r:5.2f}:1  (>= 4.5, earned payoff)")
        if r < 4.5:
            failures.append((label, "--c-green", r))
        # focus ring vs canvas and vs object (the two surfaces it crosses)
        f = resolve("--c-focus", scope)
        r1, r2 = ratio(f, canvas), ratio(f, resolve("--c-object", scope))
        ok = r1 >= 3 and r2 >= 3
        print(f"  {'PASS' if ok else 'FAIL'}  {'--c-focus':18s} {r1:5.2f}:1 canvas / {r2:5.2f}:1 object  (>= 3)")
        if not ok:
            failures.append((label, "--c-focus", min(r1, r2)))
        # disabled ink must still be perceivable against object
        d = resolve("--c-disabled-ink", scope)
        # color-mix with transparent — approximate by mixing over object
        m = re.match(r"color-mix\(in srgb, (--[\w-]+) (\d+)%, transparent\)", d)
        if m:
            base = resolve(m.group(1), scope)
            pct = int(m.group(2)) / 100
            br, bg_, bb = (int(base.strip().lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            orr, og, ob = (int(resolve("--c-object", scope).strip().lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            mixed = "#{:02x}{:02x}{:02x}".format(
                round(br * pct + orr * (1 - pct)),
                round(bg_ * pct + og * (1 - pct)),
                round(bb * pct + ob * (1 - pct)),
            )
            r = ratio(mixed, resolve("--c-object", scope))
            ok = r >= 2.2  # disabled is exempt from AA text but must stay perceivable
            print(f"  {'PASS' if ok else 'FAIL'}  {'--c-disabled-ink':18s} {r:5.2f}:1 vs object  (>= 2.2 perceivable)")
            if not ok:
                failures.append((label, "--c-disabled-ink", r))
        # State inks vs canvas: every state token must clear non-text contrast
        # (§5.3 1.4.11) on its own surface.
        #
        # NOTE — deliberately NO pairwise hue-separation requirement between
        # states. The frozen state table (§5.1) intentionally REUSES hues:
        # attention/blocked/rejected are all clay, accepted/complete are both
        # green, ready/neutral are ink. States are distinguished by geometry,
        # line, fill and position (§5.2 documents each pair); hue is the fifth
        # channel and never counts. A pairwise hue gate would contradict the
        # frozen design. The greyscale legibility of the full eleven-state set
        # is a screenshot gate that lands with the V2 state primitives.
        state_tokens = ["--state-neutral", "--state-planned", "--state-ready",
                        "--state-running", "--state-attention", "--state-blocked",
                        "--state-retrying", "--state-verifying", "--state-rejected",
                        "--state-accepted", "--state-complete"]
        seen = set()
        for tok in state_tokens:
            val = resolve(tok, scope)
            if val in seen:
                continue  # shared-hue group — separated by geometry per §5.2
            seen.add(val)
            r = ratio(val, canvas)
            ok = r >= 3.0
            print(f"  {'PASS' if ok else 'FAIL'}  {tok:18s} {r:5.2f}:1 vs canvas  (>= 3)")
            if not ok:
                failures.append((label, tok, r))

    print()
    if failures:
        print(f"CONTRAST GATE FAILED: {len(failures)} pair(s)")
        for label, tok, r in failures:
            print(f"  {label}  {tok}  {r:.2f}:1")
        return 1
    print("CONTRAST GATE PASSED: all binding pairs on both canvases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
