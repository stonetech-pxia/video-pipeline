Failure-path contract test only. Do not call sessions_spawn and do not run a specialist stage.

Treat the following sanitized object as the exact result of a single rejected story-analyst startup attempt:

{
  "ok": false,
  "error": {
    "type": "provider_error",
    "code": "MODEL_ROUTE_UNAVAILABLE",
    "message": "Configured model route is unavailable.",
    "retryable": true
  }
}

Return only the final JSON object required by schemas/pipeline-result.schema.json. It must preserve the diagnostic, identify story-analyst and the story stage, use failure_kind=subagent_start_failed, return BLOCKED because the failure is retryable, and contain no invented worker artifact.
