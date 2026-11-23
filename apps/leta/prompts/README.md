# Managed prompts

The Markdown files are the authoring source for the `leta/common`, `leta/leta`, `leta/leti`, `leta/note_samples`, `leta/inbox_samples`, and `leta/compaction` Langfuse prompts. Runtime fetches the role prompts by the configured label.

Publish Common first when it changes. Update the Common version in the role files, then publish the role prompts under the configured label. The Note and Inbox samples are standalone Langfuse prompts. Keep the agent metadata, `{{agent_instructions}}`, `{{box_context}}`, and `{{summary_max_tokens}}` as Langfuse placeholders.

Use the existing role prompt configs when publishing. An agent's model selection overrides the role defaults. Compaction uses the current agent model and reasoning effort.

WireMock fixtures contain the role prompts with the referenced sections expanded. Keep them aligned with the authoring files.
