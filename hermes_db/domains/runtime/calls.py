"""Ordinary runtime call sites dispatch to the selected scoped implementation."""

from hermes_db.domains.runtime.access import runtime_for_store


def begin_runtime_epoch(db, **kwargs):
    return runtime_for_store(db).begin_epoch(**kwargs)


def admit_session_input(db, **kwargs):
    return runtime_for_store(db).admit_input(**kwargs)


def get_session_admission(db, **kwargs):
    return runtime_for_store(db).get_admission(**kwargs)


def find_session_admission(db, **kwargs):
    return runtime_for_store(db).find_admission(**kwargs)


def list_session_admissions(db, **kwargs):
    return runtime_for_store(db).list_admissions(**kwargs)


def claim_session_input(db, **kwargs):
    return runtime_for_store(db).claim_input(**kwargs)


def settle_session_input(db, **kwargs):
    return runtime_for_store(db).settle_input(**kwargs)


def cancel_session_input(db, **kwargs):
    return runtime_for_store(db).cancel_input(**kwargs)


def steer_session_input(db, **kwargs):
    return runtime_for_store(db).steer_input(**kwargs)


def revert_steer_input(db, **kwargs):
    return runtime_for_store(db).revert_steer(**kwargs)


def rehome_queued_inputs(db, **kwargs):
    return runtime_for_store(db).rehome_inputs(**kwargs)


def retarget_local_automation(db, **kwargs):
    return runtime_for_store(db).retarget_automation(**kwargs)


def recover_session_inputs(db, **kwargs):
    return runtime_for_store(db).recover_inputs(**kwargs)


def mutate_runtime_session(db, **kwargs):
    return runtime_for_store(db).mutate_session(**kwargs)


def resolve_unknown_session_input(db, **kwargs):
    return runtime_for_store(db).resolve_unknown(**kwargs)


def register_worker_execution(db, **kwargs):
    return runtime_for_store(db).register_worker(**kwargs)


def adopt_worker_execution(db, **kwargs):
    return runtime_for_store(db).adopt_worker(**kwargs)


def mutate_worker_execution(db, **kwargs):
    return runtime_for_store(db).mutate_worker(**kwargs)


def apply_worker_receipt(db, **kwargs):
    return runtime_for_store(db).apply_worker_receipt(**kwargs)
