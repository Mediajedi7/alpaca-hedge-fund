"""Dashboard theme — blended palette (JARVIS dark + day-trader green/red), Google
fonts, hidden chrome, plain big-number metrics, and a centered fixed bottom pill nav."""
from __future__ import annotations

import base64
import pathlib

from core.config import cfg

T = cfg.get("dashboard.theme", {})
BG = T.get("background", "#0b0e17")
CARD1, CARD2 = (T.get("card_gradient", ["#131827", "#1a2035"]) + ["#1a2035"])[:2]
ACCENT = T.get("accent", "#6366f1")
LONG = T.get("long", "#27ae60")
SHORT = T.get("short", "#c0392b")
SANS = T.get("font_sans", "Plus Jakarta Sans")
MONO = T.get("font_mono", "JetBrains Mono")


def robot_data_uri() -> str | None:
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = pathlib.Path(__file__).parent / "assets" / f"robot.{ext}"
        if p.exists():
            mime = "jpeg" if ext in ("jpg", "jpeg") else ext
            return f"data:image/{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    return None


def css() -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap');
#MainMenu, header, footer {{visibility: hidden;}}
.stApp {{ background: {BG}; color: #e6e8ef; font-family: '{SANS}', sans-serif; }}
.block-container {{ padding-top: 2rem; padding-bottom: 6rem; max-width: 1500px; }}
h1,h2,h3,h4 {{ font-family: '{SANS}', sans-serif; font-weight: 800; color: #f3f5fb; }}
.mono {{ font-family: '{MONO}', monospace; }}

/* cover */
.jarvis {{ font-size: 96px; font-weight: 800; letter-spacing: -.04em; color: #f7f9ff; line-height: .95; }}
.subtitle {{ font-size: 12px; letter-spacing: .34em; text-transform: uppercase; color: {ACCENT};
            font-weight: 600; margin: 6px 0 26px; }}
.robot {{ height: 78vh; min-height: 560px; border-radius: 16px;
         background-size: cover; background-position: center right;
         -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 28%);
         mask-image: linear-gradient(90deg, transparent 0%, #000 28%); }}
.robot.fallback {{ background: radial-gradient(120% 90% at 78% 30%, {CARD2} 0%, {BG} 62%);
                  -webkit-mask-image:none; mask-image:none; border:1px solid #1c2438;
                  display:flex; align-items:center; justify-content:center; }}

/* inline JARVIS answer on the cover */
.ask-q {{ font-size: 12px; letter-spacing: .16em; text-transform: uppercase; color: #7e879f;
         font-weight: 600; margin: 22px 0 10px; }}
.ask-a {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border-left: 3px solid {ACCENT};
         border-radius: 12px; padding: 18px 22px; line-height: 1.65; color: #dfe3ee; font-size: 15px;
         max-height: 460px; overflow-y: auto; }}

/* plain metrics grid (no boxes) */
.mgrid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 26px 10px; margin-top: 8px; }}
.mgrid .mv {{ font-size: 34px; font-weight: 800; color: #f3f5fb; line-height: 1; }}
.mgrid .ml {{ font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: #7e879f; margin-top: 6px; }}

/* KPI cards (Research top) */
.kpi {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
       border-radius: 14px; padding: 16px 18px; min-height: 110px; margin-bottom: 14px; }}
.kpi .l {{ font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: #7e879f; }}
.kpi .v {{ font-size: 38px; font-weight: 800; margin: 6px 0 2px; font-family: '{MONO}', monospace; }}
.kpi .s {{ font-size: 12px; color: #8a93ad; }}

/* candidate cards (Research bottom) */
.cand {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
        border-radius: 14px; padding: 14px 18px; margin-bottom: 6px; }}
.cand .tkr {{ font-size: 20px; font-weight: 800; }}
.cand .sc {{ float: right; font-size: 22px; font-weight: 800; font-family: '{MONO}', monospace; }}
.cand .meta {{ font-family: '{MONO}', monospace; font-size: 13px; color: #aeb6cc; margin-top: 6px; }}
.cand .fund {{ font-size: 12px; color: #8a93ad; margin-top: 4px; }}
.amber {{ color: #e0a106; }} .grey {{ color: #9aa4bf; }}
.an-h {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: #7e879f; margin-top: 12px; }}

/* cards (other pages) */
.card {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
        border-radius: 14px; padding: 16px 18px; margin-bottom: 12px; }}
.metric {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
          border-radius: 12px; padding: 12px 14px; text-align: center; }}
.metric .v {{ font-size: 24px; font-weight: 800; font-family: '{MONO}', monospace; }}
.metric .l {{ font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: #8a93ad; }}
.long {{ color: {LONG}; }} .short {{ color: {SHORT}; }} .accent {{ color: {ACCENT}; }}
.badge {{ border:1px solid #2a3450; border-radius:999px; padding:3px 10px; font-size:11px; color:#9aa4bf; }}
.pill {{ display:inline-block; padding:4px 10px; border-radius:999px; font-size:11px; font-weight:600; }}

/* ask box + glowing button */
.stTextInput input {{ background: {CARD1}; border:1px solid #2a3450; border-radius: 12px;
                     color:#e6e8ef; padding: 14px 16px; font-size: 15px; }}
.stButton > button[kind="primary"] {{ background: linear-gradient(135deg, {ACCENT}, #4fa800);
    border: none; border-radius: 999px; color:#fff; font-weight:700; letter-spacing:.1em;
    padding: 8px 26px; box-shadow: 0 0 28px rgba(109,242,0,.5); }}
.stButton > button {{ background:{CARD2}; color:#e6e8ef; border:1px solid #2a3450; border-radius:10px; font-weight:600; }}
.stButton > button:hover {{ border-color:{ACCENT}; color:#fff; }}

/* fixed bottom pill nav */
.navbar {{ position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 1000;
          display: flex; gap: 4px; padding: 7px; border-radius: 999px;
          background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
          box-shadow: 0 8px 30px rgba(0,0,0,.5); }}
.navbar a {{ text-decoration: none; color: #8a93ad; font-size: 12px; font-weight: 600;
            letter-spacing: .08em; padding: 8px 16px; border-radius: 999px; white-space: nowrap; }}
.navbar a .rn {{ color: #5b647e; margin-right: 6px; }}
.navbar a:hover {{ color: #e6e8ef; }}
.navbar a.active {{ background: linear-gradient(135deg, {ACCENT}, #4fa800); color:#fff; }}
.navbar a.active .rn {{ color: #dffbc0; }}
/* cover "what JARVIS does" overview box */
.about {{ background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
         border-left: 3px solid {ACCENT}; border-radius: 14px; padding: 16px 18px; margin-top: 28px; }}
.about .h {{ font-size: 11px; letter-spacing: .18em; text-transform: uppercase; color: {ACCENT}; margin-bottom: 8px; }}
.about p {{ font-size: 12.5px; line-height: 1.55; color: #aeb6cc; margin: 0; }}
.about b {{ color: #e6e8ef; font-weight: 700; }}
.about ol {{ margin: 10px 0 0; padding-left: 18px; }}
.about li {{ font-size: 12px; color: #9aa3bd; margin-bottom: 4px; }}
.about li b {{ color: {ACCENT}; font-weight: 700; }}
/* live account balance + P&L strip (cover) */
.acct {{ display: flex; gap: 10px; margin: 12px 0 4px; }}
.acct > div {{ flex: 1; background: linear-gradient(135deg, {CARD1}, {CARD2}); border: 1px solid #232b40;
              border-radius: 12px; padding: 12px 14px; }}
.acct .al {{ font-size: 9.5px; letter-spacing: .14em; text-transform: uppercase; color: #7e879f; }}
.acct .av {{ font-size: 26px; font-weight: 800; color: #f3f5fb; font-family: '{MONO}', monospace;
            margin-top: 5px; line-height: 1; }}
.acct .as {{ font-size: 11px; color: #8a93ad; margin-top: 4px; }}
</style>
"""


def card(html: str) -> str:
    return f'<div class="card">{html}</div>'


def metric(label: str, value) -> str:
    return f'<div class="metric"><div class="v">{value}</div><div class="l">{label}</div></div>'


def metrics_grid(items: list[tuple[str, object]]) -> str:
    cells = "".join(f'<div><div class="mv">{v}</div><div class="ml">{l}</div></div>' for l, v in items)
    return f'<div class="mgrid">{cells}</div>'
