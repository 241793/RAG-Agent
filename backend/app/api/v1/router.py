"""v1 路由汇总。"""
from fastapi import APIRouter

from app.api.v1 import (
    agents,
    apikey,
    audit,
    auth,
    channels,
    chat,
    document,
    email_sources,
    eval as eval_api,
    event_subscriptions,
    files,
    kb,
    mcp,
    notifications,
    notify_channels,
    provider,
    rbac,
    record_templates,
    reminders,
    retrieval,
    scheduled_tasks,
    security,
    service_api,
    service_tickets,
    settings,
    skills,
    sso,
    system,
    system_ops,
    tools,
    usage,
    webhooks,
    workflow,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(kb.router)
api_router.include_router(document.router)
api_router.include_router(email_sources.router)
api_router.include_router(eval_api.router)
api_router.include_router(event_subscriptions.router)
api_router.include_router(retrieval.router)
api_router.include_router(chat.router)
api_router.include_router(provider.router)
api_router.include_router(rbac.router)
api_router.include_router(agents.router)
api_router.include_router(skills.router)
api_router.include_router(tools.router)
api_router.include_router(mcp.router)
api_router.include_router(workflow.router)
api_router.include_router(audit.router)
api_router.include_router(apikey.router)
api_router.include_router(sso.router)
api_router.include_router(usage.router)
api_router.include_router(security.router)
api_router.include_router(settings.router)
api_router.include_router(files.router)
api_router.include_router(scheduled_tasks.router)
api_router.include_router(notifications.router)
api_router.include_router(service_tickets.router)
api_router.include_router(service_api.router)
api_router.include_router(record_templates.router)
api_router.include_router(reminders.router)
api_router.include_router(notify_channels.router)
api_router.include_router(webhooks.router)
api_router.include_router(channels.router)
api_router.include_router(system.router)
api_router.include_router(system_ops.router)
