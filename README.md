# TraceMind

**From distributed failure to verified fix.**

TraceMind ingests standard OpenTelemetry telemetry (OTLP), reconstructs incidents, investigates competing
root-cause hypotheses with multiple AI agents (LangGraph + Gemma), connects runtime evidence to source code
(Graphify), generates a patch and verifies it in an isolated sandbox. A human approves the result.

> Status: hackathon MVP under active development. Not production-ready. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Includes a demo in-app notification platform that reproduces a deterministic duplicate-notification incident
(message redelivery after a post-commit, pre-ack failure).

Quickstart will be added at Milestone 5. License: MIT.
