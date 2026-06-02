"""
Response masking for sensitive gateway responses.

Rules:
- hCaptcha / Checkpoint / Captcha responses: NEVER show the real captcha message.
  50% → "Generic Declined - 3DS Bypassed"
  50% → "Declined" (no mention of captcha)

- 3DS / requires_action responses:
  50% → "Generic Declined - 3DS Bypassed"
  50% → exact response (3DS messages are acceptable)
"""

import random

_CAPTCHA_KEYWORDS = [
    "captcha", "hcaptcha", "h-captcha",
    "checkpoint denied", "checkpoint",
    "captcha solving failed", "captcha detected",
    "captcha blocked",
]

_THREED_KEYWORDS = [
    "3ds", "3d secure", "3d_secure", "requires_action",
    "3ds required", "3d_auth", "3ds_authentication",
    "3d_authentication", "three_d_secure",
    "authentication_required", "3ds bypassed",
]

MASKED_RESPONSE = "Generic Declined - 3DS Bypassed"


def _is_captcha(response: str) -> bool:
    rl = response.lower()
    return any(k in rl for k in _CAPTCHA_KEYWORDS)


def _is_3ds(response: str) -> bool:
    rl = response.lower()
    return any(k in rl for k in _THREED_KEYWORDS)


def mask_response(response: str) -> str:
    """
    Apply 50/50 masking to captcha and 3DS responses.
    Never returns the raw captcha message.
    """
    if not response:
        return response

    if _is_captcha(response):
        if random.random() < 0.5:
            return MASKED_RESPONSE
        else:
            return "Declined"

    if _is_3ds(response):
        if random.random() < 0.5:
            return MASKED_RESPONSE
        else:
            return response

    return response


def mask_status(response: str, original_status: str) -> str:
    """
    Return the appropriate status after masking.
    Captcha/3DS masked to 'DECLINED' (not APPROVED).
    """
    masked = mask_response(response)
    if masked in (MASKED_RESPONSE, "Declined"):
        return "DECLINED"
    return original_status
