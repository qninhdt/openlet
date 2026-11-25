# Managed prompts

The `.j2` Jinja2 templates and static `.md` sample files are the authoring source for the `leta/common`, `leta/leta`, `leta/leti`, `leta/note_samples`, `leta/inbox_samples`, and `leta/compaction` Langfuse prompts. Runtime fetches the role prompts by the configured label and renders the raw template with Jinja2 (using `tools.*` flags and agent variables).

Publish Common first when it changes. Update the Common version in the role files, then publish the role prompts under the configured label. The Note and Inbox samples are standalone Langfuse prompts. Keep `@@@langfusePrompt:...@@@` references for Langfuse composability and Jinja2 syntax (`{{ agent_instructions }}`, `{{ box_context }}`, `{{ summary_max_tokens }}`, `{% if tools.<flag> %}`) for client-side rendering.

Use the existing role prompt configs when publishing. An agent's model selection overrides the role defaults. Compaction uses the current agent model and reasoning effort.

`openlet-env` dynamically synthesizes the WireMock Langfuse prompt fixtures directly from these files (expanding `@@@langfusePrompt:...@@@`), so no manual fixture copy is needed.
