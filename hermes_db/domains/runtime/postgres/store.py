"""Public runtime facade with explicit owner-scoped component delegation."""

class PostgresRuntimeStore:

    def __init__(self, context, admissions, local, policy, workers, media, delegations):
        self._context = context
        self._admissions = admissions
        self._local = local
        self._policy = policy
        self._workers = workers
        self._media = media
        self._delegations = delegations

    @property
    def scope(self):
        return self._context.scope

    @property
    def delegations(self):
        self._context.session.assert_open()
        return self._delegations

    def _write(self):
        return self._context.write()

    def create_api_session(self, *, session_id, source, title, **values):
        return self._admissions.create_api_session(session_id=session_id, source=source, title=title, **values)

    def queued_api_sessions(self):
        return self._admissions.queued_api_sessions()

    def bind_api_session(self, **kwargs):
        return self._admissions.bind_api_session(**kwargs)

    def find_api_run(self, run_id, *, admission_id=None):
        return self._admissions.find_api_run(run_id, admission_id=admission_id)

    def completion_replay(self, *, epoch, row):
        return self._admissions.completion_replay(epoch=epoch, row=row)

    def current_result(self, admission_id):
        return self._admissions.current_result(admission_id)

    def retry_terminal_admission(self, *, epoch, principal_id, session_id, request_id, payload, intent='queue'):
        return self._admissions.retry_terminal_admission(epoch=epoch, principal_id=principal_id, session_id=session_id, request_id=request_id, payload=payload, intent=intent)

    def terminal_worker_receipt(self, **kwargs):
        return self._admissions.terminal_worker_receipt(**kwargs)

    def terminal_api_admissions(self, request_id):
        return self._admissions.terminal_api_admissions(request_id)

    def terminal_admission(self, admission_id):
        return self._admissions.terminal_admission(admission_id)

    def admission_result(self, admission_id):
        return self._admissions.admission_result(admission_id)

    def pending_target_ids(self, statuses):
        return self._admissions.pending_target_ids(statuses)

    def runtime_busy_reason(self):
        return self._admissions.runtime_busy_reason()

    def committed_delivery(self, principal, request_id):
        return self._admissions.committed_delivery(principal, request_id)

    def webhook_payloads(self, chat_id):
        return self._admissions.webhook_payloads(chat_id)

    def webhook_finalizations(self):
        return self._admissions.webhook_finalizations()

    def _webhook_rows(self, *, chat_id=None, finalizing=False):
        return self._admissions._webhook_rows(chat_id=chat_id, finalizing=finalizing)

    def finalize_webhook(self, *, epoch, session_id, generation, admission_id, owner_epoch):
        return self._admissions.finalize_webhook(epoch=epoch, session_id=session_id, generation=generation, admission_id=admission_id, owner_epoch=owner_epoch)

    def promote_current_history(self, *, epoch, actor, receipt, native_transport):
        return self._local.promote_current_history(epoch=epoch, actor=actor, receipt=receipt, native_transport=native_transport)

    def persist_hosted_binding(self, *, epoch, key, value):
        return self._local.persist_hosted_binding(epoch=epoch, key=key, value=value)

    def label_hosted_session(self, *, epoch, session_id, title):
        return self._local.label_hosted_session(epoch=epoch, session_id=session_id, title=title)

    def session_launch_source(self, session_id):
        return self._local.session_launch_source(session_id)

    def local_owner(self, session_id):
        return self._local.local_owner(session_id)

    def validate_local_lineage(self, receipt):
        return self._local.validate_local_lineage(receipt)

    def local_receipt_ids(self):
        return self._local.local_receipt_ids()

    def unknown_inputs(self):
        return self._local.unknown_inputs()

    def commit_local_session(self, *, epoch, receipt):
        return self._local.commit_local_session(epoch=epoch, receipt=receipt)

    def local_receipt(self, session_id):
        return self._local.local_receipt(session_id)

    def handoff_head(self, session_id):
        return self._local.handoff_head(session_id)

    def end_idle_local_session(self, **kwargs):
        return self._local.end_idle_local_session(**kwargs)

    def authorize_history(self, actor, session_id, *, native_transport):
        return self._local.authorize_history(actor, session_id, native_transport=native_transport)

    def require_history_leaf(self, session_id):
        return self._local.require_history_leaf(session_id)

    def defer_pick(self, **kwargs):
        return self._policy.defer_pick(**kwargs)

    def compare_deferred_pick(self, **kwargs):
        return self._policy.compare_deferred_pick(**kwargs)

    def request_admission_id(self, session_id, request_id):
        return self._policy.request_admission_id(session_id, request_id)

    def has_request(self, request_id, *, session_id=None):
        return self._policy.has_request(request_id, session_id=session_id)

    def holds_admissions(self, session_ids):
        return self._policy.holds_admissions(session_ids)

    def bot_sessions(self, subject, operator):
        return self._policy.bot_sessions(subject, operator)

    def viewer_busy(self, session_id, target):
        return self._policy.viewer_busy(session_id, target)

    def store_viewer_close(self, *, epoch, session_id, record):
        return self._policy.store_viewer_close(epoch=epoch, session_id=session_id, record=record)

    def forget_viewer_close(self, *, epoch, session_id, record):
        return self._policy.forget_viewer_close(epoch=epoch, session_id=session_id, record=record)

    def session_last_active(self, session_id):
        return self._policy.session_last_active(session_id)

    def live_store_facts(self, session_ids):
        return self._policy.live_store_facts(session_ids)

    def read_domain(self, session_id, name, arguments):
        return self._workers.read_domain(session_id, name, arguments)

    def worker_session(self, execution_id):
        return self._workers.worker_session(execution_id)

    def reserve_admission_worker(self, **kwargs):
        return self._workers.reserve_admission_worker(**kwargs)

    def lose_admission_worker(self, **kwargs):
        return self._workers.lose_admission_worker(**kwargs)

    def delegation_event(self, session_id, execution_id, delegation_id):
        return self._workers.delegation_event(session_id, execution_id, delegation_id)

    def register_worker(self, **kwargs):
        return self._workers.register_worker(**kwargs)

    def adopt_worker(self, **kwargs):
        return self._workers.adopt_worker(**kwargs)

    def apply_worker_receipt(self, **kwargs):
        return self._workers.apply_worker_receipt(**kwargs)

    def mutate_worker(self, **kwargs):
        return self._workers.mutate_worker(**kwargs)

    def worker_claim_origin(self, params):
        return self._workers.worker_claim_origin(params)

    def worker_retry_target(self, params):
        return self._workers.worker_retry_target(params)

    def verify_worker_claim(self, params, claim, *, active_epoch=None):
        return self._workers.verify_worker_claim(params, claim, active_epoch=active_epoch)

    def persist_delegation(self, *, owner, **kwargs):
        return self._workers.persist_delegation(owner=owner, **kwargs)

    def settled_native_media(self):
        return self._media.settled_native_media()

    def release_media(self, references, *, retain_history=True):
        return self._media.release_media(references, retain_history=retain_history)

    def retire_refused_media(self, references):
        return self._media.retire_refused_media(references)

    def compact_api_payloads(self, admission_id=None):
        return self._media.compact_api_payloads(admission_id)

    def begin_epoch(self, *, instance_id):
        return self._admissions.begin_epoch(instance_id=instance_id)

    def check_epoch(self, epoch):
        return self._admissions.check_epoch(epoch)

    def current_epoch(self):
        return self._admissions.current_epoch()

    def mutate_session(self, **kwargs):
        return self._policy.mutate_session(**kwargs)

    def policy_picks(self, session_id):
        return self._policy.policy_picks(session_id)

    def commit_refreshed_policy(self, **kwargs):
        return self._policy.commit_refreshed_policy(**kwargs)

    def prepare_chat_pick(self, **kwargs):
        return self._policy.prepare_chat_pick(**kwargs)

    def commit_chat_pick(self, **kwargs):
        return self._policy.commit_chat_pick(**kwargs)

    def admit_input(self, **kwargs):
        return self._admissions.admit_input(**kwargs)

    def claim_input(self, **kwargs):
        return self._admissions.claim_input(**kwargs)

    def settle_input(self, **kwargs):
        return self._admissions.settle_input(**kwargs)

    def cancel_input(self, **kwargs):
        return self._admissions.cancel_input(**kwargs)

    def steer_input(self, **kwargs):
        return self._admissions.steer_input(**kwargs)

    def revert_steer(self, **kwargs):
        return self._admissions.revert_steer(**kwargs)

    def recover_inputs(self, **kwargs):
        return self._admissions.recover_inputs(**kwargs)

    def resolve_unknown(self, **kwargs):
        return self._admissions.resolve_unknown(**kwargs)

    def mark_unknown(self, **kwargs):
        return self._admissions.mark_unknown(**kwargs)

    def rehome_inputs(self, **kwargs):
        return self._admissions.rehome_inputs(**kwargs)

    def retarget_automation(self, **kwargs):
        return self._admissions.retarget_automation(**kwargs)

    def get_admission(self, *, admission_id):
        return self._admissions.get_admission(admission_id=admission_id)

    def find_admission(self, *, principal_id, session_id, request_id):
        return self._admissions.find_admission(principal_id=principal_id, session_id=session_id, request_id=request_id)

    def list_admissions(self, *, session_id, pending_only=True):
        return self._admissions.list_admissions(session_id=session_id, pending_only=pending_only)
