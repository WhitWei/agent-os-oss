from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])

@router.get("/overview")
async def get_overview(request: Request):
    bootstrap = request.app.state.bootstrap
    
    spend = 0.0
    if bootstrap.kernel and hasattr(bootstrap.kernel, "_billing_fuse"):
        spend = bootstrap.kernel._billing_fuse.cumulative_spend
        
    intercepts = 0
    if bootstrap.feedback_db:
        intercepts = bootstrap.feedback_db.count_by_decision("REJECTED")
        
    successful_runs = 0
    if bootstrap.state_store:
        successful_runs = bootstrap.state_store.count_by_state("COMPLETED")
        
    return {
        "total_spend_usd": round(spend, 4),
        "total_intercepts": intercepts,
        "successful_workflows": successful_runs
    }
