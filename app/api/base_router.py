from fastapi import APIRouter


base_router = APIRouter()

routers = [
    # user_router,
    #auth_router
]

for router in routers:
    base_router.include_router(router)
