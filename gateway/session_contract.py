"""Public session authority contract; live execution state never crosses this boundary."""

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Protocol

JsonObject = Mapping[str, object]

# Authenticated local WebSocket family, separate from the legacy Desktop API contract.
CANONICAL_GATEWAY_PROTOCOL = 'hermes-gateway-v1'


@dataclass(frozen=True)
class SessionActor:
    subject: str
    profile_id: str
    capabilities: frozenset[str]
    transport_id: str


@dataclass(frozen=True)
class SessionRef:
    profile_id: str
    session_id: str


@dataclass(frozen=True)
class SessionHandle:
    ref: SessionRef
    instance_id: str
    authority_epoch: int
    revision: int
    execution_generation: int
    execution_state: Literal["idle", "running", "waiting", "unknown", "terminal"]


@dataclass(frozen=True)
class SessionCreate:
    request_id: str
    cwd: str
    source: str
    policy: JsonObject


@dataclass(frozen=True)
class Submission:
    request_id: str
    ref: SessionRef
    payload: JsonObject
    intent: Literal["queue", "steer", "redirect"]


@dataclass(frozen=True)
class AdmissionReceipt:
    admission_id: str
    ref: SessionRef
    sequence: int
    status: Literal["queued", "started", "unknown", "terminal"]
    outcome: str | None
    authority_epoch: int
    execution_generation: int | None


@dataclass(frozen=True)
class PendingAdmission(AdmissionReceipt):
    input_id: str
    text: str
    # The queued-row verbs this owner serves for the row (``steer`` / ``replace``); empty otherwise.
    controls: list[str] = field(default_factory=list)
    # A queued admission in transfer to the running turn (``prompt.steer_queued``): it reads ``started``
    # but goes back to its queue place if its text never reached that turn.
    steering: bool = False


@dataclass(frozen=True)
class SubscriptionSnapshot:
    subscription_id: str
    handle: SessionHandle
    replay_epoch: str
    last_sequence: int
    history: tuple[JsonObject, ...]
    pending: tuple[PendingAdmission, ...]
    prompts: tuple[JsonObject, ...]
    # The physical transcript a history-less attach resolved under the stream lock (``history=False``).
    transcript_target: str | None = None


class SessionAuthority(Protocol):
    async def create(self, actor: SessionActor, request: SessionCreate) -> SessionHandle: ...
    async def resolve(self, actor: SessionActor, ref: SessionRef) -> SessionHandle: ...
    async def attach(self, actor: SessionActor, ref: SessionRef, *, history: bool = True,
                     replay_from: tuple[str, int] | None = None) -> SubscriptionSnapshot: ...
    async def detach(self, actor: SessionActor, subscription_id: str, *, end_reason: str | None = None) -> None: ...
    async def submit(self, actor: SessionActor, request: Submission) -> AdmissionReceipt: ...
    async def receipt(self, actor: SessionActor, ref: SessionRef, admission_id: str) -> AdmissionReceipt: ...
    async def cancel_queued(self, actor: SessionActor, ref: SessionRef, admission_id: str) -> AdmissionReceipt: ...
    async def interrupt(self, actor: SessionActor, ref: SessionRef, generation: int) -> SessionHandle: ...
    async def respond(self, actor: SessionActor, ref: SessionRef, generation: int,
                      prompt_id: str, response: JsonObject) -> JsonObject: ...
    async def mutate(self, actor: SessionActor, ref: SessionRef, revision: int,
                     request_id: str, action: str, arguments: JsonObject) -> SessionHandle: ...

SURFACES = {'cli': 'cli', 'tui': 'tui', 'gui': 'desktop', 'acp': 'acp', 'tool': 'cli', 'oneshot': 'cli'}

DAYBREAK_LABELS = frozenset({'cli', 'tui', 'gui', 'oneshot'})

_KEEP_STORED_LABEL = frozenset({'tool', 'oneshot'})

STORED_AS_LOCAL = frozenset(SURFACES) - _KEEP_STORED_LABEL

_NOT_A_SURFACE = frozenset({None, '', 'local', 'unknown'})

def created_surface(label):
    """``created_source`` for a policy or live label.

    ``local`` and ``unknown`` are not surfaces. A label stored as ``local`` maps
    through ``SURFACES`` (``gui`` is ``desktop``). Any other label, including
    ``tool`` and ``oneshot``, is kept as itself: created_source is provenance.
    """
    if label in _NOT_A_SURFACE:
        return None
    return SURFACES[label] if label in STORED_AS_LOCAL else label

SURFACE_GROUPS = {name: group for group in (frozenset({label, SURFACES[label]}) for label in STORED_AS_LOCAL)
                  for name in group}

def admission_media_references(payload):
    """Native references eligible as deletion candidates after terminal settlement."""
    return list(payload.get('attachments_v1', {}).get('media', ())) + list(
        payload.get('native_text_v1', {}).get('media', ()))

def _session_key_namespace(profile: Optional[str]) -> str:
    """``agent:<ns>`` prefix for a session key: default/None profile → ``agent:main``
    (BYTE-IDENTICAL to every historical key); named profile → ``agent:<name>`` so two
    profiles serving the same chat never collide. A profile literally named ``main`` would
    otherwise produce the default's namespace and share every session (routing index, agent
    cache, store) with it, so it is marked ``main~``: ``~`` is outside the profile-id alphabet,
    so the marked form can never be another profile's id."""
    if not profile or profile == "default":
        return "agent:main"
    return "agent:main~" if profile == "main" else f"agent:{profile}"
