from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])

@router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    bootstrap = request.app.state.bootstrap
    if not bootstrap.state_store:
        return {"runs": [], "limit": limit, "offset": offset}
        
    runs = bootstrap.state_store.list_runs(limit=limit, offset=offset)
    return {"runs": runs, "limit": limit, "offset": offset}
