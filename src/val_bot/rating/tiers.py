TIERS = [
    ("Iron", 0, 499),
    ("Bronze", 500, 574),
    ("Silver", 575, 649),
    ("Gold", 650, 724),
    ("Platinum", 725, 799),
    ("Diamond", 800, 874),
    ("Ascendant", 875, 949),
    ("Immortal", 950, 1099),
    ("Radiant", 1100, None),
]

def mmr_to_tier(mmr: int) -> str:
    for name, low, high in TIERS:
        if mmr >= low and (high is None or mmr <= high):
            return name
    raise ValueError(f"no tier found for mmr={mmr}")
