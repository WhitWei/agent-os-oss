from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/governance", tags=["Governance"])

@router.get("/audits")
async def list_audits(request: Request):
    bootstrap = request.app.state.bootstrap
    if not bootstrap.feedback_db:
        return {"audits": []}
        
    records = bootstrap.feedback_db.list_all()
    
    return {"audits": [
        {
            "id": r.id,
            "trace_id": r.trace_id,
            "reviewer": r.reviewer,
            "decision": r.decision,
            "reason": r.reason,
            "original_agent_output": r.original_agent_output,
            "timestamp": r.timestamp,
        } for r in records
    ]}
