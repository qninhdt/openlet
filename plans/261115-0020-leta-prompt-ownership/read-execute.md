# File-read and execution: source comparison and approved design

Date: 2026-11-15. Status: **Design approved after source review; implemented; see the execution record in plan.md section 11.** The user confirmed the plain file-read contract and the `execute` name/output behavior. That source-review phase changed no product code, cloud prompts or running agents.

## 1. Sources inspected

Read implementations that produce model-facing content, not only UI renderers or prompt descriptions. Reused the existing local clones, confirmed their pinned revisions, and did not claim these are the latest upstream versions.

| Harness | Read arguments and rendered content | Execution result sent to the model |
| --- | --- | --- |
| Pi 8636e211e7834e4ca46a22aec1d65dfd2eac8677 | `path`, optional 1-based `offset`, optional line `limit`. Text is the selected source text, without a number on each line. Add a continuation only when capped or a requested limit leaves more content. | Success is plain captured output, or `(no output)`. Nonzero exit appends `Command exited with code N` and marks the result as an error. Full structured exit/timing data exist separately for programmatic callers. |
| OpenCode d759c548aab33a7a6f5171cbeab40a59e91d90aa | `path`, optional 1-based `offset`, optional `limit` defaulting/capped at 2000. Model-facing read output has a file/range header and prefixes each text line with its number. | `resultMessages` uses output plus a notice. A normal success adds no exit-code notice; nonzero/signal/timeout does. Structured output/metadata still retain exitCode and timing. |
| OpenHands SDK 3c66af1d14d0a7fbe74b8dc4218412ec7a877b79 | File editor `command="view"`, `path`, optional inclusive `view_range=[start,end]`, with -1 for EOF. Ordinary text uses `cat -n` style line numbers. Converted Markdown has a separate unnumbered path. | `TerminalObservation.to_llm_content` includes working-directory/interpreter metadata when present and an exit-code footer when known, including zero. It is not merely a UI status. |
| Codex b1573f102413e96a6481087922bf425231222dee | The unified-exec path inspected returns command output; it does not insert line numbers into every source line. A shell read may use cat/sed/rg, so numbering depends on the command. This is not a claim about every optional MCP/extension read tool. | Native exec response_text includes chunk/time/process information and `Process exited with code N`, including zero. Code-mode returns structured output instead. |

There is no universal convention that all coding agents omit line numbers or exit-code text. Pi supplies a concrete smaller format suitable for Openlet; OpenCode supplies the same success-versus-failure exit behavior. OpenHands has insertion-by-line operations, making numbered reads more directly useful there. Openlet's file_edit uses literal text replacement.

Primary links:

- [Pi read schema](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/read.ts#L14), [plain text and continuation](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/read.ts#L319).
- [Pi bash success/failure output](https://github.com/badlogic/pi-mono/blob/8636e211e7834e4ca46a22aec1d65dfd2eac8677/packages/coding-agent/src/core/tools/bash.ts#L415).
- [OpenCode numbered model content](https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/tool/plugin/read.ts), [shell notices](https://github.com/anomalyco/opencode/blob/d759c548aab33a7a6f5171cbeab40a59e91d90aa/packages/core/src/shell/result.ts#L50).
- [OpenHands editor rendering](https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/file_editor/editor.py#L838), [terminal LLM content](https://github.com/OpenHands/software-agent-sdk/blob/3c66af1d14d0a7fbe74b8dc4218412ec7a877b79/openhands-tools/openhands/tools/terminal/definition.py#L173).
- [Codex native exec model response](https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/tools/context.rs#L459), [exit header](https://github.com/openai/codex/blob/b1573f102413e96a6481087922bf425231222dee/codex-rs/core/src/tools/context.rs#L548).

## 2. Approved file_read contract

Keep the existing tool name and its clear line-selection vocabulary. Do not add formatting modes, line_numbers switches or a new read-file wrapper.

```text
file_read(path, start_line=1, limit=None)
```

- `path` is required. `start_line` and `limit` are optional and measured in lines, not tokens. Keep normal input validation.
- With limit omitted, return source text from start_line until EOF or the existing output-byte cap, rather than stopping automatically at 200 lines. An explicit limit still selects a smaller window. No need to rename start_line to offset merely to copy another API.
- Return plain text without JSON content fields, per-line prefixes, an always-present path/range header or a line total. The tool call already identifies the source. Preserve source text and blank lines in the selected window.
- If more content remains, append only an actionable note, e.g. `[More content. Continue with start_line=241.]`. The next line must follow the actual last complete line returned, not the requested limit.
- Do not cut a line and then skip its remainder by advancing to the next line. If a single line cannot fit, keep the existing explicit long-line notice and suggest execute with jq/Python to select fields or a substring. Do not loop forever by calling a blank result EOF.
- Empty file: a short `(empty file)` indication is sufficient. No metadata object.
- Keep native image blocks and document-artifact discovery. Do not mix a large document tree response into a text-read envelope.
- Reading a smaller window does not imply the whole file was read. An explicit limit or cap leaves a continuation whenever more content remains.

Approved short description:

```text
Read file text, an image, or an uploaded document's extracted files. For text, start_line and limit select lines; omitted limit reads up to the output cap. Follow the continuation when more content is needed.
```

The 16,384-byte approximate preview cap remains; it is not an exact token count. This change removes formatting and the automatic 200-line window, not bounded output. Do not import Pi's larger 50KB/2000-line defaults without a separate need.

## 3. Approved execute contract

```text
execute(command, cwd="~")
```

It retains the same supported shell/Python-through-shell execution capability, system-managed timeout, Mirage session lifetime and access restrictions. Renaming does not add host execution, external network or arbitrary runtimes.

Success with output:

```text
NorthPack: 15044400
SouthPack: 13556160
GreenCarton: 14886720
```

Success without output:

```text
(no output)
```

Failure:

```text
cat: missing.csv: No such file or directory

Command exited with code 1.
```

- Return terminal text; no `Exit: 0`, JSON stdout/stderr envelope, repeated command, timing, process IDs or default success banner.
- Capture stdout/stderr text in the order of events delivered by the runtime. Keep internal exit/error metadata for native tool status and observability; omit successful exit metadata only from model prose.
- Always disclose a nonzero exit, timeout/cancellation or unknown completion. Native ToolMessage.status is useful metadata but is not a reliable substitute for explaining failure in model-visible content across providers.
- Preserve bounded output, truncation indication and the saved output path when needed; say when the saved capture is incomplete. Do not add a second truncation system or background/polling tool.

Approved short description:

```text
Run supported shell commands and Python over workspace files. Use cwd for the working directory. Output is capped; read the saved output when needed. No host programs or network access.
```

## 4. Implementation reach and limits

The execution-tool rename reaches the catalog/decorator, descriptions, prompt Markdown, compiled Langfuse fixtures, runtime history/error handling that branches on tool names, relevant tests and owning docs. Search current consumers before editing. Do not retain exec_shell as a compatibility alias; do not rewrite historical records of prior calls.

Plain read formatting may share its small selection/continuation helper with history reads, but keep the agreed history audit header. No generic renderer framework or dependency. Tests should cover a normal full file, selected window/capped continuation, long-line non-progress notice, image preservation and successful/failed/truncated execution. Run relevant typing/format checks when code is changed.

The source-review phase copied no implementations and installed no dependency. The approved implementation, fresh smoke journey and limits of the performance evidence are recorded in plan.md section 11.
