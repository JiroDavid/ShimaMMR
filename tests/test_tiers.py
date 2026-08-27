from val_bot.rating.tiers import mmr_to_tier

def test_boundaries():
    assert mmr_to_tier(0) == "Iron"
    assert mmr_to_tier(499) == "Iron"
    assert mmr_to_tier(500) == "Bronze"
    assert mmr_to_tier(574) == "Bronze"
    assert mmr_to_tier(575) == "Silver"
    assert mmr_to_tier(649) == "Silver"
    assert mmr_to_tier(650) == "Gold"
    assert mmr_to_tier(724) == "Gold"
    assert mmr_to_tier(725) == "Platinum"
    assert mmr_to_tier(799) == "Platinum"
    assert mmr_to_tier(800) == "Diamond"
    assert mmr_to_tier(874) == "Diamond"
    assert mmr_to_tier(875) == "Ascendant"
    assert mmr_to_tier(949) == "Ascendant"
    assert mmr_to_tier(950) == "Immortal"
    assert mmr_to_tier(1099) == "Immortal"
    assert mmr_to_tier(1100) == "Radiant"
    assert mmr_to_tier(5000) == "Radiant"

def test_starting_mmr_is_gold():
    assert mmr_to_tier(700) == "Gold"
