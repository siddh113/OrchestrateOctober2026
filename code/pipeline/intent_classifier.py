from __future__ import annotations
import re

# Fast path keyword patterns (case-insensitive)
_DELETION_PATTERNS = [
    r'\bdelete\b', r'\bdelete\s+my\b', r'\bdeleting\b', r'\bdeleted\b',
    r'\berase\b', r'\berase\s+my\b', r'\berasing\b',
    r'\bremove\s+my\b', r'\bremove\s+all\b', r'\bremoving\s+my\b',
    r'\bclose\s+my\s+account\b', r'\bclos(?:e|ing|ed)\s+(?:my|the)\s+account\b',
    r'\bwipe\b', r'\bwipe\s+my\b',
    r'\bright\s+to\s+(?:be\s+)?forgotten\b', r'\brtbf\b',
    r'\bgdpr\b.*\bdelet\b', r'\bccpa\b.*\bdelet\b',
    # French
    r'\bsuppression\b', r'\bsupprimer\b', r'\bsupprimez\b', r'\beffacer\b',
    r'\beffacement\b', r'\bdroit\s+.*oubli\b',
    # Spanish
    r'\beliminar\b', r'\belimina\b', r'\belimination\b', r'\bborrar\b',
    r'\bderecho\s+.*olvido\b',
    # Portuguese
    r'\beliminar\b', r'\bapagar\b', r'\bexcluir\b',
    # German
    r'\bl[oö]schen\b', r'\bl[oö]schung\b',
    # Italian
    r'\bellimina\b', r'\belliminare\b', r'\bcancella\b', r'\bcancellazione\b',
    # Dutch
    r'\bverwijder\b', r'\bverwijderen\b', r'\bwissen\b',
    # Japanese
    r'削除', r'消去', r'退会',
    # Chinese
    r'删除', r'注销', r'抹除',
    # Korean
    r'삭제', r'탈퇴',
    # Arabic/etc
    r'حذف', r'مسح',
]

_NOT_APPLICABLE_PATTERNS = [
    r'\bdata\s+access\s+request\b', r'\baccess\s+my\s+data\b', r'\bview\s+my\s+data\b',
    r'\bcopy\s+of\s+my\s+data\b', r'\bexport\s+my\s+data\b', r'\bdownload\s+my\s+data\b',
    r'\bopt.out\b', r'\bunsubscribe\b', r'\bstop\s+marketing\b', r'\bstop\s+emails\b',
    r'\bcorrect\b.*\bdata\b', r'\bupdate\s+my\s+(?:data|information|details)\b',
    r'\bcorrection\s+request\b', r'\bdata\s+portability\b',
    r'\bwhat\s+data\b', r'\bwhat\s+information\b', r'\bwhat\s+do\s+you\s+have\b',
    r'\bsupport\s+ticket\b', r'\btechnical\s+issue\b',
]

_DEL_RE = re.compile("|".join(_DELETION_PATTERNS), re.IGNORECASE)
_NAP_RE = re.compile("|".join(_NOT_APPLICABLE_PATTERNS), re.IGNORECASE)


def _fast_classify(text: str) -> str | None:
    """Returns DELETION, NOT_APPLICABLE, or None (ambiguous)."""
    has_del = bool(_DEL_RE.search(text))
    has_nap = bool(_NAP_RE.search(text))
    if has_del:
        return "DELETION"  # deletion wins if both match
    if has_nap:
        return "NOT_APPLICABLE"
    return None


def classify(request_text: str) -> str:
    """Classify request_text as 'DELETION' or 'NOT_APPLICABLE'."""
    fast = _fast_classify(request_text)
    if fast is not None:
        return fast
    # LLM fallback for ambiguous cases
    try:
        from pipeline.llm_client import classify_intent
        return classify_intent(request_text)
    except Exception:
        # Fallback: assume deletion if we can't classify
        return "DELETION"
