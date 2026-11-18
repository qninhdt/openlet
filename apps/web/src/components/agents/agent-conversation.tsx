import { fileText } from '@/lib/file-refs';
import { useRef, useState } from 'react';
import { ArrowUp, Plus, X, Upload, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { useAgentPreview } from './agent-preview';
import { ComposerEditor } from './composer-editor';
import { FilePicker } from './file-picker';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { PendingRequests } from './agent-requests';
import { LiveActivity } from './agent-activity';

export function ConversationComposer() {
  const p = useAgentPreview();
  const fileInput = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState(false);
  const [empty, setEmpty] = useState(true);
  return (
    <div className="mx-auto w-full max-w-[calc(clamp(1440px,65vw,1920px)+12px)] shrink-0 px-1.5 pt-1 pb-1.5">
      <div
        data-slot="conversation-composer"
        className="relative flex flex-col rounded-3xl border border-input bg-muted focus-within:border-ring data-drop:border-ring data-drop:outline-2 data-drop:outline-ring"
      >
        <PendingRequests />
        {p.session.reply && (
          <div className="mx-3 mt-3 flex items-start gap-2 rounded-xl border bg-sidebar p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">Replying to a message</p>
              <p className="mt-1 line-clamp-2 text-caption">{fileText(p.session.reply.content)}</p>
            </div>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Cancel reply"
              onClick={() => p.updateSession({ reply: null })}
            >
              <X />
            </Button>
          </div>
        )}
        <div className="flex min-h-12 items-end gap-1 p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Attach file">
                <Plus />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top">
              <DropdownMenuItem onSelect={() => fileInput.current?.click()}>
                <Upload />
                Upload file
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setPicker(true)}>
                <HardDrive />
                Choose from storage
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            aria-label="Attach files"
            onChange={(event) => {
              for (const file of Array.from(event.target.files ?? [])) void p.queueUpload(file);
              event.target.value = '';
            }}
          />
          <ComposerEditor onEmptyChange={setEmpty} />
          <Button
            disabled={!!p.session.uploads.length || empty}
            onClick={() => p.composers.get(p.resource.id)?.submit()}
            size="icon-sm"
            aria-label="Send message"
            className="rounded-full"
          >
            <ArrowUp />
          </Button>
        </div>
      </div>
      <FilePicker
        open={picker}
        onClose={() => setPicker(false)}
        onSelect={(node) => {
          void p.attachFile(node);
          setPicker(false);
        }}
      />
      <AlertDialog open={!!p.copyRequest} onOpenChange={(open) => !open && p.setCopyRequest(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send a copy?</AlertDialogTitle>
            <AlertDialogDescription>
              {p.profile.name} cannot read this file. Copy it to your conversation storage so both
              of you can edit it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const request = p.copyRequest!;
                void p.attachFile(request.node, true, request.label, request.selection);
              }}
            >
              Send a copy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function AgentActivity() {
  return <LiveActivity />;
}
