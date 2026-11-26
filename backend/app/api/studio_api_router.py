# Register the routers used by the assistant and workflow studio.
from fastapi import APIRouter

from . import order_automation_routes, studio_file_routes, workflow_chat_routes, workflow_definition_routes, workflow_execution_routes, workflow_generator_routes

router = APIRouter()
router.include_router(workflow_definition_routes.router)
router.include_router(workflow_chat_routes.router)
router.include_router(workflow_execution_routes.router)
router.include_router(studio_file_routes.router)
router.include_router(workflow_generator_routes.router)
router.include_router(order_automation_routes.router)
