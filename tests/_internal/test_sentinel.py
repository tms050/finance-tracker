from copy import copy, deepcopy
import pickle

from src._internal.sentinel import UNSET, _UnsetType


def test_singleton():
    assert _UnsetType() is UNSET
    assert _UnsetType() is _UnsetType()


def test_copy_preserves_singleton():
    assert copy(UNSET) is UNSET
    assert deepcopy(UNSET) is UNSET


def test_pickle_preserves_singleton():
    assert pickle.loads(pickle.dumps(UNSET)) is UNSET


def test_falsy():
    assert not UNSET
    assert bool(UNSET) is False
    assert repr(UNSET) == "UNSET"


def test_works_with_is():
    """isinstance и is эквивалентны после singleton."""
    x = UNSET
    assert x is UNSET
    assert isinstance(x, _UnsetType)