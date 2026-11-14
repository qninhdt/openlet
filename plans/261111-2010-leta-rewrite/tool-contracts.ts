// Draft tool descriptions and inputs. Field comments explain non-obvious arguments.
// Results remain in tools.md; formats, bounds and defaults remain in tool-schemas.json.

export interface PageInput {
  cursor?: string;
}

export type HitlStatus = 'pending' | 'answered' | 'accepted' | 'denied' | 'cancelled' | 'expired';

export interface HitlListInput extends PageInput {
  status?: HitlStatus;
}

export interface Question {
  text: string;
  /** Omit for a free-text answer. */
  options?: string[];
  /** Allow several choices; requires options. */
  multiple?: boolean;
}

export interface LetiDefinition {
  name: string;
  description?: string;
  /** Specialist responsibility, deliverables and quality criteria. */
  system_prompt: string;
}

export interface CalendarValues {
  second?: number[];
  minute?: number[];
  hour?: number[];
  day_of_month?: number[];
  month?: number[];
  year?: number[];
  day_of_week?: number[];
}

export interface ScheduleTiming {
  at?: string;
  after_seconds?: number;
  every_seconds?: number;
  /** All fields must match; Sunday=0. Omitted second/minute/hour=0; other fields unrestricted. */
  calendar?: CalendarValues;
  /** Recurring start; also anchors an interval. */
  starts_at?: string;
  /** Recurring cutoff; null clears it. */
  ends_at?: string | null;
  /** IANA name; defaults to task timezone, otherwise UTC. */
  timezone?: string;
}

export interface ScheduleCreateInput extends ScheduleTiming {
  title?: string;
  content: string;
}

export interface ScheduleUpdateInput extends ScheduleTiming {
  schedule_id: string;
  title?: string;
  content?: string;
  paused?: boolean;
}

export interface LetiTools {
  /** Send a message to an allowed recipient; final activity text does not deliver. */
  inbox_send(input: {
    /** ID from workspace_get; a box routes to its representative. */
    to: string;
    content: string;
    in_reply_to?: string;
  }): unknown;

  /** Get your identity, home and allowed messaging recipients. */
  workspace_get(input: PageInput): unknown;

  /** Find current workspace members and user IDs for HITL. */
  workspace_member_list(input: PageInput): unknown;

  /** Ask any current workspace member; the answer arrives later in your inbox. */
  hitl_ask(input: { recipient_user_id: string; title?: string; questions: Question[] }): unknown;

  /** Ask a member for access to their Personal storage, shared by root and its Leti. */
  hitl_request(input: { user_id: string; role?: 'viewer' | 'editor'; reason?: string }): unknown;

  /** List your human requests; use hitl_get for details. */
  hitl_list(input: HitlListInput): unknown;

  /** Get a human request, its form, decision and grant outcome. */
  hitl_get(input: { request_id: string }): unknown;

  /** Cancel a pending human request; does not revoke granted access. */
  hitl_cancel(input: { request_id: string; reason?: string }): unknown;

  /** Schedule an inbox instruction for yourself. Choose exactly one: at, after_seconds, every_seconds, calendar. */
  schedule_create(input: ScheduleCreateInput): unknown;

  /** List your schedules. */
  schedule_list(input: PageInput): unknown;

  /** Get a schedule instruction, timing and upcoming forecasts. */
  schedule_get(input: { schedule_id: string }): unknown;

  /** Update only supplied fields. At most one timing selector; recipient stays fixed. */
  schedule_update(input: ScheduleUpdateInput): unknown;

  /** Stop future scheduled instructions; already-delivered work remains. */
  schedule_delete(input: { schedule_id: string }): unknown;

  /** Search your activity history by words; omit query for recent previews. */
  history_search(
    input: PageInput & {
      query?: string;
    },
  ): unknown;

  /** Read a history entry; follow next_start_line for more. */
  history_read(input: { entry_id: string; start_line?: number; limit?: number }): unknown;

  /** List files and directories; /mnt lists accessible storages and whether each is writable. */
  file_list(
    input: PageInput & {
      path?: string;
      /** 1: paged children; greater than 1: bounded tree. */
      depth?: number;
    },
  ): unknown;

  /** Read a text window, image preview or uploaded-document artifacts; follow returned continuations. */
  file_read(input: { path: string; start_line?: number; limit?: number }): unknown;

  /** Create text; overwrite=true replaces the entire file. Use file_edit for partial changes. */
  file_write(input: { path: string; content: string; overwrite?: boolean }): unknown;

  /** Replace literal text; exactly one match unless replace_all=true. Empty new_text deletes the match. */
  file_edit(input: {
    path: string;
    old_text: string;
    new_text: string;
    replace_all?: boolean;
  }): unknown;

  /** Run supported shell commands and pipelines over workspace files; no host programs or network. */
  exec_shell(input: { command: string; cwd?: string }): unknown;

  /** Find passages by meaning; use shell search for exact text. */
  file_semantic_search(input: {
    query: string;
    /** File/directory scopes; defaults to home. */
    paths?: string[];
  }): unknown;
}

export interface LetaTools extends LetiTools {
  /** List inbox notifications grouped by conversation. */
  inbox_list(
    input: PageInput & {
      source_id?: string;
      unread_only?: boolean;
    },
  ): unknown;

  /** Read messages and mark returned items read; unread_only=false includes previously read messages. */
  inbox_read(
    input: PageInput & {
      conversation_id: string;
      unread_only?: boolean;
    },
  ): unknown;

  /** Create a fixed team with shared home. Send tasks separately with inbox_send. */
  box_create(input: {
    name: string;
    description?: string;
    letis: LetiDefinition[];
    /** Two-way pairs of Leti names. */
    edges: [string, string][];
    /** Name of the Leti that communicates with root. */
    representative: string;
  }): unknown;

  /** List boxes and work counts. */
  box_list(input: PageInput): unknown;

  /** Get box members, links and representative; prompts are opt-in. */
  box_get(input: {
    /** Box ID or active name. */
    box: string;
    include_prompts?: boolean;
  }): unknown;

  /** Stop Leti, remove affected schedules/pending requests and trash shared home. Root storage grants remain. */
  box_delete(input: { box_id: string }): unknown;

  /** List human requests across root and boxes; box_id filters by requester box. */
  hitl_list(
    input: HitlListInput & {
      box_id?: string;
    },
  ): unknown;

  /** Schedule an inbox instruction for yourself or a box. Choose exactly one: at, after_seconds, every_seconds, calendar. */
  schedule_create(
    input: ScheduleCreateInput & {
      /** Omit to target yourself. */
      target_box_id?: string;
    },
  ): unknown;

  /** List root and box schedules; box_id filters by target box. */
  schedule_list(
    input: PageInput & {
      box_id?: string;
    },
  ): unknown;
}
