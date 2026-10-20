"""Behavioral parity with the byte-identical 2.1 acquisition snapshot."""
from itertools import combinations
import json
from pathlib import Path
import numpy as np
import pytest
from intentcart.learning import PARTICLES, choose_pair
from scripts.benchmarks.learning_v2_1 import choose_pair as reference_pair


@pytest.mark.parametrize('policy', ['decision', 'uncertainty'])
@pytest.mark.parametrize('kind', ['diffuse', 'concentrated', 'equal_utilities'])
def test_batched_acquisition_preserves_reference_selection_and_gain(policy, kind):
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'intentcart/data/catalog.json').read_text())
    utilities = PARTICLES @ np.array([p['features'] for p in catalog]).T
    rng = np.random.default_rng(741)
    weights = rng.dirichlet(np.ones(len(PARTICLES)) * (.08 if kind == 'concentrated' else 1.4))
    if kind == 'equal_utilities':
        utilities = np.full_like(utilities, .42)
    for count in [2, 7, 16, 24]:
        available = list(rng.choice(24, count, replace=False))
        used = {tuple(sorted(pair)) for pair in list(combinations(available, 2))[:count // 3]}
        actual = choose_pair(utilities, weights, available, used, policy)
        expected = reference_pair(utilities, weights, available, used, policy)
        assert actual[:2] == expected[:2]
        assert actual[2] == pytest.approx(expected[2], abs=5e-13)


def test_acquisition_exhaustion_and_seeded_random_are_unchanged():
    rng = np.random.default_rng(7)
    utilities = rng.random((128, 5))
    weights = np.ones(128) / 128
    for available in [[], [0], [2, 4]]:
        used = {tuple(sorted(pair)) for pair in combinations(available, 2)}
        assert choose_pair(utilities, weights, available, used) is None
    actual = choose_pair(utilities, weights, [4, 2, 0, 1], {(0, 4)}, 'random', np.random.default_rng(12))
    expected = reference_pair(utilities, weights, [4, 2, 0, 1], {(0, 4)}, 'random', np.random.default_rng(12))
    assert actual == expected
