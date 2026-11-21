"""Builds web/index.html from the RastaNidhi (formerly CivicProof) prototype: live stats from the API and a real OTP sign-in.

Re-run after editing the prototype:  python tools/build_homepage.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "civicproof_homepage.html"
OUT = ROOT / "rupee_app" / "web" / "index.html"

src = SRC.read_text(encoding="utf-8")


def rep(old: str, new: str) -> None:
    global src
    assert src.count(old) == 1, f"expected exactly one match for: {old[:90]!r}"
    src = src.replace(old, new)


# --- hero: drop the "Get started free" / "See how it works" buttons (the nav already links to sign-in and How it works)
rep('''    <div class="hero-btns">
      <button class="btn-primary" onclick="document.getElementById('login').scrollIntoView({behavior:'smooth'})">Get started free</button>
      <button class="btn-outline" onclick="document.getElementById('how').scrollIntoView({behavior:'smooth'})">See how it works</button>
    </div>
''', '')

# --- hero stats: live ids, real defaults
rep('<div class="hero-stat"><div class="hero-stat-num">₹13Cr</div>', '<div class="hero-stat"><div class="hero-stat-num" id="st-spend">₹13.43 Cr</div>')
rep('<div class="hero-stat"><div class="hero-stat-num">6,501</div>', '<div class="hero-stat"><div class="hero-stat-num" id="st-complaints">6,501</div>')
rep('<div class="hero-stat"><div class="hero-stat-num">₹47L</div><div class="hero-stat-label">Flagged at risk</div>',
    '<div class="hero-stat"><div class="hero-stat-num" id="st-risk">₹3.22 Cr</div><div class="hero-stat-label">Needs review</div>')
rep('<div class="hero-stat"><div class="hero-stat-num">24</div>', '<div class="hero-stat"><div class="hero-stat-num" id="st-wards">24</div>')

# --- category counts
rep('<div class="cat-count">2,499 work orders</div>', '<div class="cat-count"><span id="st-wos">2,499</span> work orders</div>')
rep('<div class="cat-count">28 hotspots mapped</div>', '<div class="cat-count"><span id="st-hot">28</span> hotspots mapped</div>')

# --- features (match what was built)
rep("AI-generated A–F grade per contractor based on SLA, durability, cost variance and volume. Plain English, no jargon.",
    "A–E grade per contractor, adjusted for flood-prone wards and heavy rain, so nobody is punished for working in "
    "Hindmata in July. Claude writes it in plain English.")
rep("<p>Recommends where each ward should spend next based on flood risk, accident history, traffic and nearby schools and hospitals.</p>\n          </div>\n        </div>",
    "<p>Recommends where each ward should spend next based on flood risk, accident history, traffic and nearby schools and hospitals.</p>\n          </div>\n        </div>\n"
    '        <div class="feat-item">\n          <div class="feat-dot">🔧</div>\n          <div>\n            <h4>Durable repair choices</h4>\n'
    "            <p>Picks the repair method with the best track record for each issue from past jobs, and flags chronic roads "
    "that should be resurfaced instead of patched again.</p>\n          </div>\n        </div>")

# --- impact cards: real computed numbers (refreshed live from /api/public/stats)
IMPACT = """<div class="impact-grid">
    <div class="impact-card"><div class="impact-num" id="im-risk">₹3.22 Cr</div>
      <div class="impact-label">Needs review across <span id="im-risk-n">623</span> work orders: over-billing, double-billing and DLP</div></div>
    <div class="impact-card"><div class="impact-num" id="im-dlp">493</div>
      <div class="impact-label">DLP repairs: BMC paid <span id="im-dlp-amt">₹2.62 Cr</span> when the original contractor should have fixed them for free</div></div>
    <div class="impact-card"><div class="impact-num" id="im-reopen">24%</div>
      <div class="impact-label">Re-open rate: 1 in 4 repairs failed within 30 days</div></div>
    <div class="impact-card"><div class="impact-num" id="im-never">192</div>
      <div class="impact-label">Issues never fixed: still open with no work order (out of <span id="im-issues">2,086</span> issues)</div></div>
    <div class="impact-card"><div class="impact-num" id="im-cold">32%</div>
      <div class="impact-label">Cold mix failure rate: the cheapest patch fails most often</div></div>
    <div class="impact-card"><div class="impact-num" id="im-ward">L</div>
      <div class="impact-label">Ward with the most money needing review: <span id="im-ward-flags">64</span> flags, <span id="im-ward-risk">₹44.4 L</span></div></div>
  </div>
"""
a = src.index('<div class="impact-grid">')
b = src.index("</section>", a)
src = src[:a] + IMPACT + src[b:]

# --- sign-in: ward / contractor pickers + real dashboard link
rep('<select class="form-select" id="hp-role">', '<select class="form-select" id="hp-role" onchange="hpRole()">')
rep('<div id="hp-err" style="font-size:12px;color:#dc2626;margin-bottom:8px"></div>',
    '<div class="form-group step-hidden" id="hp-ward-g"><label class="form-label">Your ward</label>'
    '<select class="form-select" id="hp-ward"><option value="">Select ward</option></select></div>\n'
    '        <div class="form-group step-hidden" id="hp-con-g"><label class="form-label">Your company</label>'
    '<select class="form-select" id="hp-con"><option value="">Select contractor</option></select></div>\n'
    '        <div id="hp-err" style="font-size:12px;color:#dc2626;margin-bottom:8px"></div>')
rep("""<button class="login-submit" onclick="alert('Redirecting to dashboard...')">Go to my dashboard →</button>""",
    """<button class="login-submit" onclick="location.href='/dashboard'">Go to my dashboard →</button>""")

# --- footer: what it is actually built with
rep('<a href="#">Python FastAPI</a>\n      <a href="#">React + Tailwind</a>',
    '<a href="#">Python FastAPI + pandas</a>\n      <a href="#">HTML · CSS · JavaScript</a>\n      <a href="#">scikit-learn ML</a>')

# --- Driftbar theme: Inter, paper/ink/blue-hour palette, theme stylesheet loaded last
rep("</head>", '<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&display=swap" rel="stylesheet" />\n'
    '<link rel="stylesheet" href="/static/driftbar.css" />\n</head>')
rep("<body>", '<body class="home">')
rep('<div class="nav-logo">\n    🏛️ CivicProof\n    <span>Mumbai BMC · 2025</span>',
    '<div class="nav-logo">\n    <span class="brand__mark" style="--u:1.15px" aria-hidden="true"></span>\n    '
    '<span class="brand__word"><b>CivicProof</b><span class="brand__ticker" aria-hidden="true"><span><i>मुंबई · Mumbai</i>'
    '<i>Follow the money</i><i>Verify the work</i><i>Monsoon roads, tracked</i><i>मुंबई · Mumbai</i></span></span></span>')

# --- city photos (downloaded to web/img from Wikimedia Commons, credited as their licences require)
import json as _json
CRED = {c["file"]: c for c in _json.loads((ROOT / "rupee_app" / "web" / "img" / "credits.json").read_text(encoding="utf-8"))}


def _img(file, cls="", alt=None):
    c = CRED[file]
    return (f'<img src="/static/img/{file}" alt="{alt or c["caption"] + ", " + c["city"]}" loading="lazy" '
            f'title="Photo: {c["author"]} ({c["license"]}), Wikimedia Commons"{(" class=" + chr(34) + cls + chr(34)) if cls else ""}>')


# every remaining hot-linked Wikimedia image -> local copies (hot-links get blocked by browsers)
src = src.replace("url('https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/Mumbai_Skyline_at_Night.jpg/1280px-Mumbai_Skyline_at_Night.jpg')",
                  "url('/static/img/mumbai-skyline.jpg')")
f0 = src.index('<div class="feat-img">')
f1 = src.index("</div>", f0)
src = src[:f0] + '<div class="feat-img">\n      ' + _img("mumbai-dadar.jpg", alt="Bandra–Worli Sea Link from Dadar Beach, Mumbai") + "\n    " + src[f1:]

GALLERY = [("mumbai-sealink.jpg", "tall"), ("mumbai-skyline.jpg", ""), ("mumbai-cst.jpg", ""), ("mumbai-dadar.jpg", ""), ("mumbai-gateway.jpg", "")]
g0 = src.index('<div class="gallery-grid">')
g1 = src.index("</section>", g0)
src = src[:g0] + '<div class="gallery-grid">\n' + "\n".join(
    f'    <div class="gallery-item {cls}">{_img(f)}<div class="gallery-label">{CRED[f]["caption"]}'
    f'<small>{CRED[f]["author"]} · {CRED[f]["license"]}</small></div></div>' for f, cls in GALLERY) + "\n  </div>\n" + src[g1:]

CITIES = [("mumbai-marine-drive.jpg", "Mumbai", "24 wards · ₹13.4 Cr traced", "Live", True),
          ("delhi-india-gate.jpg", "New Delhi", "MCD road & drain repairs", "Planned", False),
          ("kolkata-howrah.jpg", "Kolkata", "KMC monsoon drainage", "Planned", False),
          ("bengaluru-skyline.jpg", "Bengaluru", "BBMP pothole spend", "Planned", False),
          ("chennai-marina.jpg", "Chennai", "GCC storm-water drains", "Planned", False)]
cards = "".join(f'<div class="city-card">{_img(f)}<div class="city-meta"><div><b>{city}</b><span>{sub}</span></div>'
                f'<span class="city-chip{" live" if live else ""}">{chip}</span></div></div>' for f, city, sub, chip, live in CITIES)
credits = " · ".join(f'<a href="{c["source"]}" target="_blank" rel="noopener">{c["caption"]}, {c["city"]}</a> by {c["author"]} ({c["license"]})'
                     for c in CRED.values())
CITY_SECTION = f"""
<!-- CITIES -->
<section class="cities" id="cities">
  <div class="section-tag">Mumbai today · India next</div>
  <div class="section-title">One city live. Every monsoon city next.</div>
  <div class="section-sub">The same money trail works anywhere a city logs complaints, work orders and a rate card. Hover to pause.</div>
  <div class="city-track">{cards}{cards}</div>
  <p class="photo-credits">Photos via Wikimedia Commons: {credits}. Licences: <a href="https://creativecommons.org/licenses/" target="_blank" rel="noopener">CC BY / CC BY-SA</a>, <a href="https://artlibre.org/licence/lal/en/" target="_blank" rel="noopener">Free Art License</a>.</p>
</section>
"""
c0 = src.index("</section>", src.index('<section class="gallery"')) + len("</section>")
src = src[:c0] + CITY_SECTION + src[c0:]
rep('<a href="#features">Features</a>', '<a href="#features">Features</a>\n    <a href="#cities">Cities</a>')

# --- OTP step: compact, realistic code entry (masked email, resend timer, auto-submit)
o0 = src.index('<div id="login-step-2" class="step-hidden">')
o1 = src.index('<div id="login-step-3"', o0)
src = src[:o0] + """<div id="login-step-2" class="step-hidden otp-step">
        <button type="button" class="otp-back" onclick="hpBack()">← Change email</button>
        <div class="otp-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m4 7 8 6 8-6"/></svg></div>
        <h3>Check your email</h3>
        <p class="otp-sub">Enter the 4-digit code we sent to<br><b id="hp-otp-to"></b></p>
        <div class="otp-row" role="group" aria-label="4-digit sign-in code">
          <input class="otp-box" id="b1" maxlength="1" inputmode="numeric" autocomplete="one-time-code" aria-label="Digit 1" oninput="bn(this,'b2')">
          <input class="otp-box" id="b2" maxlength="1" inputmode="numeric" aria-label="Digit 2" oninput="bn(this,'b3')">
          <input class="otp-box" id="b3" maxlength="1" inputmode="numeric" aria-label="Digit 3" oninput="bn(this,'b4')">
          <input class="otp-box" id="b4" maxlength="1" inputmode="numeric" aria-label="Digit 4" oninput="bn(this,null)">
        </div>
        <div id="hp-otp-err" class="otp-err" role="alert"></div>
        <button class="login-submit" id="hp-verify" onclick="hpVerify()" disabled>Verify &amp; sign in</button>
        <div class="otp-foot"><span>Didn't get it?</span><button type="button" class="otp-link" id="hp-resend" onclick="hpResend()" disabled>Resend in 0:30</button></div>
        <div class="otp-demo">Demo build · use code <b>1234</b></div>
      </div>
      """ + src[o1:]

# --- brand tagline in the hero (RastaNidhi = रस्ता road + निधी fund)
rep('<div class="hero-badge">', '<div class="hero-tagline"><b>RastaNidhi</b><span>रस्ता निधी</span><em>Every rupee. Every road. On the record.</em>'
    '<span class="hero-tagline__mr">हर रुपया · हर रस्ता</span></div>\n    <div class="hero-badge">')

# --- footer: Driftbar meadow footer with CivicProof content
f0 = src.index("<!-- FOOTER / CONTACT -->")
f1 = src.index("</footer>", f0) + len("</footer>")
src = src[:f0] + (Path(__file__).parent / "homepage_footer.html").read_text(encoding="utf-8") + src[f1:]

# --- script: real login against /api/login + live numbers
SCRIPT = (Path(__file__).parent / "homepage_script.js").read_text(encoding="utf-8")
s0 = src.index("<script>")
s1 = src.index("</script>") + len("</script>")
src = src[:s0] + "<script>\n" + SCRIPT + "</script>" + src[s1:]

# --- AI-features section removed at the user's request (section + its nav/footer links)
import re as _re
src, _n = _re.subn(r'<!-- FEATURES -->\s*<section class="features" id="features">.*?</section>\s*', '', src, count=1, flags=_re.S)
assert _n == 1, "features section not found"
src = _re.sub(r'\s*<a href="#features">Features</a>', '', src)
src = _re.sub(r'\s*<li><a href="#features">AI features</a></li>', '', src)

# --- app name: the prototype says CivicProof; the app is now RastaNidhi (done last so every injected piece is covered)
src = src.replace("<title>CivicProof — Follow the money. Verify the work.</title>",
                  "<title>RastaNidhi — Every rupee. Every road. On the record.</title>")
src = src.replace("CivicProof", "RastaNidhi")

OUT.write_text(src, encoding="utf-8")
print(f"wrote {OUT} ({len(src):,} chars)")
