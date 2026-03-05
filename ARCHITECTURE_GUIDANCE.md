
# Architecture Guidance

## 1. Bloom Uses Queues And Not Workflow Management
Bloom will not implement workflow engines,
workflow steps,
or routing logic.

Bloom only manages physical materials and state.

Execution orchestration is performed through
protocol eligibility and queue consumption.

