"""Shared writing-style directive appended to every Claude system prompt so all
user-facing prose (Research analyses, the investors' letter, the daily/weekly
emails, and JARVIS chat) lands in plain, layman's-terms English.

The reader is a smart non-specialist (a network engineer), not a finance pro.
Tweak the wording here and it changes everywhere at once. Keep it short — system
prompts stay well under the prompt-cache minimum, so this is essentially free."""

PLAIN_LANGUAGE = (
    "AUDIENCE & STYLE: the reader is a smart non-specialist — a network engineer, "
    "not a stock analyst. Write all prose and free-text fields in plain, everyday "
    "English a layperson can follow. Avoid finance jargon; when a technical term is "
    "unavoidable (e.g. beta, accruals, gross exposure, free cash flow, basis points), "
    "add a 3-6 word plain-English gloss in parentheses the first time you use it. "
    "Prefer short sentences and concrete cause-and-effect ('the stock went up, so our "
    "short bet lost money') over analyst shorthand. Simplify the LANGUAGE, never the "
    "facts or the numbers — keep everything accurate. Do not change any numeric scores, "
    "enum values, or the required output structure (e.g. JSON shape); this governs "
    "wording only."
)
