# Member 2 — Execution Handoff

## Mission
Own everything around the existing `engine/`: API, persistence, asynchronous execution, scenarios, fusion, authentication, audit, and deployment. Do not modify `engine/` as part of the Member 2 branch. When the engine contract needs a change, raise it with Member 1.

## Day 1 unblock
1. Start PostgreSQL + API.
2. Run `/health`.
3. Seed a planner and approver user.
4. Verify the five fixture endpoints.
5. Send Member 3 the Swagger URL and endpoint contract.

## Build order
- Fixture-serving endpoints first.
- PostgreSQL JSONB snapshots + versioning.
- Single-process-worker solver jobs + WebSocket/polling.
- Approval/reject/rollback audit trail.
- JWT roles.
- Data-fusion adapters + provenance/conflict rules.
- Scenario replay/reset + benchmark endpoint.
- Hardening and clean-machine test.

## Boundary with Member 1
The engine remains a pure decision layer. Member 2 passes full JSON state/plan/events into `engine.service`. Time is 15-minute slots. All operational values are synthetic. Public weather is optional generic environmental context, never a military operational feed.

## Boundary with Member 3
Member 3 can start from `GET /api/state`, `/api/plan`, `/api/events`, `/api/impact`, `/api/replan-options`. The live workflow then moves to authenticated scenario/job endpoints.

## Definition of done
`inject event -> instant impact -> async replan -> compare options -> approve -> new scenario version -> audit -> rollback` works after a clean clone.
