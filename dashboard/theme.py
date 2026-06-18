"""Dashboard theme — blended palette (JARVIS dark + day-trader green/red), Google
fonts, and CSS that hides Streamlit chrome. Colors come from config.dashboard.theme."""
from __future__ import annotations

from core.config import cfg

T = cfg.get("dashboard.theme", {})
BG = T.get("background", "#0b0e17")
CARD1, CARD2 = (T.get("card_gradient", ["#131827", "#1a2035"]) + ["#1a2035"])[:2]
ACCENT = T.get("accent", "#6366f1")
LONG = T.get("long", "#27ae60")
SHORT = T.get("short", "#c0392b")
SANS = T.get("font_sans", "Plus Jakarta Sans")
MONO = T.get("font_mono", "JetBrains Mono")


def css() -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap');
#MainMenu, header, footer {{visibility: hidden;}}
.stApp {{ background: {BG}; color: #e6e8ef; font-family: '{SANS}', sans-serif; }}
.block-container {{ padding-top: 1.2rem; max-width: 1400px; }}
h1,h2,h3,h4 {{ font-family: '{SANS}', sans-serif; font-weight: 800; color: #f3f5fb; }}
.mono {{ font-family: '{MONO}', monospace; }}
.card {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
        border-radius: 14px; padding: 16px 18px; margin-bottom: 12px; }}
.metric {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
          border-radius: 12px; padding: 12px 14px; text-align: center; }}
.metric .v {{ font-size: 26px; font-weight: 800; font-family: '{MONO}', monospace; }}
.metric .l {{ font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: #8a93ad; }}
.long {{ color: {LONG}; }} .short {{ color: {SHORT}; }} .accent {{ color: {ACCENT}; }}
.pill {{ display:inline-block; padding: 4px 10px; border-radius: 999px; font-size: 11px;
        font-weight: 600; letter-spacing:.08em; }}
.badge {{ border:1px solid #2a3450; border-radius:999px; padding:3px 10px; font-size:11px; color:#9aa4bf; }}
.jarvis {{ font-size: 92px; font-weight: 800; letter-spacing: -.03em;
          background: linear-gradient(90deg, #fff, {ACCENT}); -webkit-background-clip: text;
          -webkit-text-fill-color: transparent; line-height: 1; }}
.subtitle {{ font-size: 11px; letter-spacing:.28em; text-transform: uppercase; color:#8a93ad; }}
.stButton button {{ background: {CARD2}; color:#e6e8ef; border:1px solid #2a3450; border-radius:10px;
                   font-weight:600; }}
.stButton button:hover {{ border-color: {ACCENT}; color:#fff; }}
div[data-testid="stHorizontalBlock"] .navactive button {{
    background: linear-gradient(135deg, {ACCENT}, #4f46e5); border-color: {ACCENT}; color:#fff; }}
.cover {{ background: radial-gradient(120% 120% at 80% 20%, {CARD2} 0%, {BG} 60%);
         border-radius: 18px; padding: 40px; border:1px solid #232b40; }}
</style>
"""


def card(html: str) -> str:
    return f'<div class="card">{html}</div>'


def metric(label: str, value) -> str:
    return f'<div class="metric"><div class="v">{value}</div><div class="l">{label}</div></div>'
