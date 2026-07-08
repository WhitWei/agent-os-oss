import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from agentos.database.state_store import WorkflowStateStore
from agentos.workflow.sop_schema import SOPRunContext, SOPRunState

store = WorkflowStateStore("agentos_state.db")
ctx = SOPRunContext(
    run_id="test-run-123",
    sop_id="it-onboarding-v1",
    state=SOPRunState.SUSPENDED,
    current_step_index=2,
    inputs={"employee_id": "emp_001"},
    step_results=[{"step_id": "review", "result": {"action": "execute_governed_write", "domain": "it-asset-mgmt", "data": "<some_rdf>"}}]
)
store.save_state(ctx)
print("Run inserted")
