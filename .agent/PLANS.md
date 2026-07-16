# Executable plans

An ExecPlan is a living implementation document. A contributor must be able to
resume the work using only the repository and the plan.

Keep `Progress` as dated, verifiable checklist entries. Record unexpected facts
and environmental limitations in `Surprises & Discoveries`, architecture and
security choices in `Decision Log`, and milestone evidence in `Outcomes &
Retrospective`. Update these sections whenever implementation state changes.

Plans must describe observable behavior, concrete commands, acceptance criteria,
recovery/idempotence, and the important interfaces. Do not claim a check passed
unless it ran. Never silently diverge from an ExecPlan: record the reason and the
replacement decision before or alongside the code.
