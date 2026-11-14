# Managed prompts

These Markdown files are the authoring source for `leta/common`, `leta/root`, `leta/leti`, and `leta/compaction` in Langfuse. Runtime fetches Langfuse prompts by the configured label; these files are not a runtime fallback.

Publish common first. Root and Leti reference its numeric version using `@@@langfusePrompt:name=leta/common|version=N@@@`, followed by the corresponding role file. Keep `{{agent_instructions}}`, `{{box_context}}`, and `{{summary_max_tokens}}` as Langfuse placeholders.

Preserve the existing prompt config when publishing a text change. Model and generation defaults belong to the role prompt config; an agent's database selection overrides its defaults. Compaction uses the current agent model and reasoning effort.

WireMock fixtures contain compiled common + role text because the public Langfuse API resolves composition before returning prompts. Keep them aligned when publishing a prompt revision.
