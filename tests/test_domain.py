from decimal import Decimal
import pytest
from app.errors import DataError
from app.modules.domain.rule import evaluate


def test_leap_anniversary(cases):
    actual, proof = evaluate(cases['leap_anniversary'])
    assert actual == Decimal('366')
    assert str(dict((label, value) for label, value, _ in proof)['原最早处置日']) == '2025-03-01'


def test_adjacent_holds(cases):
    # TRAP-23
    actual, proof = evaluate(cases['adjacent_holds'])
    assert actual == Decimal('383')
    assert str(dict((label, value) for label, value, _ in proof)['最早处置日']) == '2025-01-18'


def test_expired_hold(cases):
    actual, proof = evaluate(cases['expired_hold'])
    assert actual == Decimal('365')
    assert str(dict((label, value) for label, value, _ in proof)['查询判定']) == '可处置'


def test_half_open_policy(cases):
    actual, proof = evaluate(cases['half_open_policy'])
    assert actual == Decimal('730')
    assert str(dict((label, value) for label, value, _ in proof)['保管政策生效']) == '2025-01-01'


def test_future_hold_not_sticky(cases):
    actual, proof = evaluate(cases['future_hold_not_sticky'])
    assert actual == Decimal('365')
    assert proof


def test_valid_old(cases):
    actual, proof = evaluate(cases['valid_old'])
    assert actual == Decimal('1095')
    assert proof


def test_ambiguous_policy(cases):
    # TRAP-25
    with pytest.raises(DataError) as error:
        evaluate(cases['ambiguous_policy'])
    assert error.value.code == 'ARCHIVE_POLICY'


def test_reverse_hold(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['reverse_hold'])
    assert error.value.code == 'ARCHIVE_HOLD'


def test_asof_before(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['asof_before'])
    assert error.value.code == 'ARCHIVE_DATES'
