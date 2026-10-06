from engine.constraints.feasibility import outage_blocks


def test_outage_starting_mid_sortie_is_deferred_until_landing():
    assert outage_blocks([(15, 100)], [(10, 8)]) == [(18, 82)]


def test_non_overlapping_outage_untouched():
    assert outage_blocks([(40, 60)], [(10, 8)]) == [(40, 20)]


def test_outage_fully_inside_sortie_vanishes():
    assert outage_blocks([(12, 16)], [(10, 8)]) == []


def test_chained_locked_sorties():
    assert outage_blocks([(12, 60)], [(10, 5), (15, 6)]) == [(21, 39)]


def test_overlapping_outages_are_merged():
    assert outage_blocks([(10, 30), (20, 100)], []) == [(10, 90)]       # failure during maintenance


def test_merge_windows():
    from engine.constraints.feasibility import merge_windows
    assert merge_windows([(5, 9), (1, 3), (3, 4), (8, 12)]) == [(1, 4), (5, 12)]
