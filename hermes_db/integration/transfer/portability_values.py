"""Pure validation of the current public transcript export payload."""

from hermes_state_portability import SessionPortabilityMixin as Existing


class ImportValues:
    _IMPORT_MAX_SESSIONS, _IMPORT_MAX_MESSAGES_PER_SESSION, _IMPORT_MAX_TOTAL_MESSAGES = 500, 10000, 50000
    _IMPORT_MAX_SESSION_BYTES, _IMPORT_MAX_TOTAL_BYTES = 5 * 1024 * 1024, 25 * 1024 * 1024
    _SQLITE_INT_MIN, _SQLITE_INT_MAX = -(1 << 63), (1 << 63) - 1
    _import_text_or_none = staticmethod(Existing._import_text_or_none)
    _import_int_or_none = staticmethod(Existing._import_int_or_none)
    _import_non_finite_path = staticmethod(Existing._import_non_finite_path)
    _import_load_json = classmethod(Existing._import_load_json.__func__)
    _import_json_object_or_none = classmethod(Existing._import_json_object_or_none.__func__)
    _coerce_or = staticmethod(Existing._coerce_or)
    _import_int_or_bounded = classmethod(Existing._import_int_or_bounded.__func__)
    _normalize_import_message = Existing._normalize_import_message
    _validate_import_message_content = classmethod(Existing._validate_import_message_content.__func__)
    _import_float_or_finite = classmethod(Existing._import_float_or_finite.__func__)
    _normalize_import_session = Existing._normalize_import_session
    _validate_import_payload = Existing._validate_import_payload
    _validate_import_session = Existing._validate_import_session


values = ImportValues()
