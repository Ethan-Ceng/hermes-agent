"""Application-owned domain selection, capability values and Profile configuration."""

from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


def acquire_domain(name, settings: DatabaseSettings, scope: DatabaseScope, *, sqlite_path=None):
    """Select one domain under the explicit owner scope; a native path never selects a Profile."""
    from hermes_cli.db_sessions import _owner_only
    from hermes_db.core.catalog import POSTGRES_DOMAINS, require_domain
    from hermes_db.domains.resource import DomainResource
    from hermes_db.errors import StorageNotReadyError
    from hermes_db.factory import acquire_backend

    _owner_only()
    require_domain(name)
    if settings.backend == "sqlite":
        return DomainResource(name, acquire_backend(settings, scope, sqlite_path=sqlite_path))
    scope.require_store_id()
    if name not in POSTGRES_DOMAINS:
        raise StorageNotReadyError(f"PostgreSQL storage domain {name} is not implemented")
    from hermes_db.schema import check_domain_schema
    from hermes_db.tables.metadata import SCHEMA

    check_domain_schema(settings.postgresql, name)
    backend = acquire_backend(settings, scope, schema_token=SCHEMA)
    return create_domain_resource(name, backend)


def acquire_profile_domain(name, *, profile_home=None, sqlite_path=None):
    from hermes_cli.db_sessions import _owner_only
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration

    settings, scope = resolve_db_configuration(profile_home)
    return acquire_domain(name, settings, scope, sqlite_path=sqlite_path)


def project_clock():
    from hermes_cli.projects_db import _now
    return _now()


def project_resource(backend):
    from hermes_cli.projects_db import Project, ProjectFolder
    from hermes_db.domains.projects.api import ProjectResource
    return ProjectResource(backend,
        project_value=Project, folder_value=ProjectFolder, now=project_clock)


def room_local_authority():
    from gateway.hosted_rooms import local_authority_gateway_id
    return local_authority_gateway_id()


def room_resource(backend):
    from hermes_db.domains.rooms.api import RoomResource
    return RoomResource(backend,
        local_authority_gateway_id=room_local_authority)


def kanban_resource(backend):
    scope = backend.scope
    from hermes_cli.kanban_db import (Task, Run, Comment, Attachment, Event, LiveClaimError,
        HallucinatedCardsError, EmptyCompletionError, ArtifactPreservationError, AttachmentTooLarge)
    from hermes_db.domains.kanban.api import KanbanResource, KanbanValues, KanbanCodec
    from hermes_cli.kanban_db_dispatch import DispatchResult
    from hermes_cli.kanban_swarm import SwarmCreated
    values = KanbanValues(Task.from_row, Run.from_row, Comment.from_row, Attachment.from_row, Event.from_row,
        LiveClaimError, HallucinatedCardsError, EmptyCompletionError, ArtifactPreservationError, AttachmentTooLarge,
        DispatchResult, SwarmCreated)
    from hermes_db.integration.kanban_application import (KanbanApplicationContext, KanbanProfilePolicy,
        KanbanProcesses, KanbanObservers, KanbanFiles)
    from hermes_db.integration.kanban_owner import board_operation_scope, board_reference
    from hermes_db.integration.kanban_wire import pack, unpack, CommandRefusal
    codec = KanbanCodec(pack, unpack, CommandRefusal, board_reference)
    context = KanbanApplicationContext(scope)
    policy = KanbanProfilePolicy(context)
    return KanbanResource(backend,
        result_values=values, mutation_guard=policy.assert_not_delegated_child_mutation,
        policy=policy, processes=KanbanProcesses(context), observers=KanbanObservers(context),
        files=KanbanFiles(context), operation_scope=board_operation_scope, codec=codec)


def create_domain_resource(name, backend):
    constructors = {"projects": project_resource, "rooms": room_resource, "kanban_tasks": kanban_resource}
    construct = constructors.get(name)
    if construct is not None:
        return construct(backend)
    if name in {"cron_executions", "cron_deliveries", "cron_notepad"}:
        return cron_resource(name, backend)
    from hermes_db.domains.resource import DomainResource
    return DomainResource(name, backend)


def cron_resource(name, backend):
    scope = backend.scope
    from hermes_db.domains.cron.api import CronResource
    from hermes_db.integration.cron_application import (
        CronExecutionRuntime, CronIncidentRuntime, CronDeliveryRuntime, CronNoteRuntime,
    )
    return CronResource(name, backend,
        executions=CronExecutionRuntime(scope), incidents=CronIncidentRuntime(scope),
        delivery=CronDeliveryRuntime(scope), notes=CronNoteRuntime(scope))
