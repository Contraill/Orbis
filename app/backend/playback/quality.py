"""Consumer quality classes from encoded dimensions; raw dimensions remain available."""

TIERS = ((4320, 7680), (2160, 3840), (1440, 2560), (1080, 1920),
         (720, 1280), (480, 854), (360, 640), (240, 426))


def quality_class(width: int | None, height: int | None) -> int | None:
    if not width or not height or width <= 0 or height <= 0:
        return None
    short, long = sorted((width, height))
    for tier, edge in TIERS:
        if long >= edge * .94 and short >= tier * .72:
            return tier
    return height


def quality_label(width: int | None, height: int | None) -> str | None:
    tier = quality_class(width, height)
    return f"{tier}p" if tier else None
