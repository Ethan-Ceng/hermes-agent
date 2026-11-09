"""Bind concrete domain values at the application/storage composition boundary."""


def project_clock():
    from hermes_cli.projects_db import _now
    return _now()


def project_resource(settings, scope, transactions):
    from hermes_cli.projects_db import Project, ProjectFolder
    from hermes_db.domains.projects.api import ProjectResource
    return ProjectResource(settings, scope, transactions=transactions,
        project_value=Project, folder_value=ProjectFolder, now=project_clock)


def room_local_authority():
    from gateway.hosted_rooms import local_authority_gateway_id
    return local_authority_gateway_id()


def room_resource(settings, scope, transactions):
    from hermes_db.domains.rooms.api import RoomResource
    return RoomResource(settings, scope, transactions=transactions,
        local_authority_gateway_id=room_local_authority)


def kanban_resource(settings, scope, transactions):
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
    return KanbanResource(settings, scope, transactions=transactions,
        result_values=values, mutation_guard=policy.assert_not_delegated_child_mutation,
        policy=policy, processes=KanbanProcesses(context), observers=KanbanObservers(context),
        files=KanbanFiles(context), operation_scope=board_operation_scope, codec=codec)


def create_domain_resource(name, settings, scope, *, transactions):
    constructors = {"projects": project_resource, "rooms": room_resource, "kanban_tasks": kanban_resource}
    construct = constructors.get(name)
    if construct is not None:
        return construct(settings, scope, transactions)
    if name in {"cron_executions", "cron_deliveries", "cron_notepad"}:
        return cron_resource(name, settings, scope, transactions=transactions)
    from hermes_db.core.resource import DomainResource
    return DomainResource(name, settings, scope, transactions=transactions)


def cron_resource(name, settings, scope, *, transactions):
    from hermes_db.domains.cron.api import CronResource
    from hermes_db.integration.cron_application import (
        CronExecutionRuntime, CronIncidentRuntime, CronDeliveryRuntime, CronNoteRuntime,
    )
    return CronResource(name, settings, scope, transactions=transactions,
        executions=CronExecutionRuntime(scope), incidents=CronIncidentRuntime(scope),
        delivery=CronDeliveryRuntime(scope), notes=CronNoteRuntime(scope))
