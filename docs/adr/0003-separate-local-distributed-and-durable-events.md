# Separate local, distributed, and durable events

Athena separates Local Event, Distributed Event, and Durable Work instead of treating every event as one EventBus concern. Distributed Events are non-durable notifications used to prompt state refresh across runtimes, while production-critical Durable Work uses a DB-backed work item or state machine as its source of truth and treats queues as execution signals. This keeps horizontal scaling from depending on best-effort notification delivery while preserving lightweight local fanout for non-critical in-process behavior.
