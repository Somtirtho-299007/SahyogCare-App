import pytest

from app.rules import (
    CODE_ALPHABET,
    SYSTEM,
    Role,
    Status,
    TransitionError,
    check_transition,
    is_open,
    new_referral_code,
    triage_suggestion,
    validate_vitals,
)


def test_happy_path_through_the_state_machine():
    steps = [
        (Role.FACILITY_STAFF, Status.CREATED, Status.ACCEPTED),
        (Role.FACILITY_STAFF, Status.ACCEPTED, Status.ARRIVAL_RECORDED),
        (Role.DOCTOR, Status.ARRIVAL_RECORDED, Status.CONSULTED),
        (Role.DOCTOR, Status.CONSULTED, Status.OUTCOME_RECORDED),
        (SYSTEM, Status.OUTCOME_RECORDED, Status.FOLLOW_UP_DUE),
        (Role.WORKER, Status.FOLLOW_UP_DUE, Status.CLOSED),
    ]
    for actor, current, target in steps:
        check_transition(actor, current, target)  # must not raise


def test_skipping_steps_is_rejected():
    with pytest.raises(TransitionError) as e:
        check_transition(Role.FACILITY_STAFF, Status.CREATED, Status.CLOSED)
    assert e.value.code == "INVALID_STATE_TRANSITION"


def test_asha_cannot_accept_a_referral():
    with pytest.raises(TransitionError) as e:
        check_transition(Role.WORKER, Status.CREATED, Status.ACCEPTED)
    assert e.value.code == "FORBIDDEN"


def test_only_system_marks_overdue():
    with pytest.raises(TransitionError):
        check_transition(Role.COORDINATOR, Status.FOLLOW_UP_DUE, Status.OVERDUE)
    check_transition(SYSTEM, Status.FOLLOW_UP_DUE, Status.OVERDUE)


def test_closed_referrals_cannot_move():
    for target in Status:
        with pytest.raises(TransitionError):
            check_transition(Role.COORDINATOR, Status.CLOSED, target)


def test_open_definition():
    assert is_open(Status.CREATED)
    assert is_open(Status.OVERDUE)
    assert not is_open(Status.CLOSED)
    assert not is_open(Status.REJECTED)


def test_vitals_ranges():
    assert validate_vitals({"systolic": 120, "diastolic": 80, "spo2": 97, "pulse": None}) == {}
    problems = validate_vitals({"systolic": 1200, "spo2": 140})
    assert set(problems) == {"systolic", "spo2"}
    assert "diastolic" in validate_vitals({"systolic": 90, "diastolic": 95})
    assert "height" in validate_vitals({"height": 170})


def test_triage_suggestion_only_for_low_spo2():
    assert triage_suggestion({"spo2": 85}) is not None
    assert triage_suggestion({"spo2": 96}) is None
    assert triage_suggestion({}) is None


def test_referral_codes_are_readable_and_varied():
    codes = {new_referral_code() for _ in range(500)}
    assert len(codes) == 500
    for code in codes:
        assert code.startswith("SC-") and len(code) == 9
        assert all(ch in CODE_ALPHABET for ch in code[3:])
        assert not set("01OI") & set(code[3:])
