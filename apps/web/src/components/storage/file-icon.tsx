import {
  File,
  FileImage,
  FileArchive,
  FileAudio,
  FileCode2,
  FileSpreadsheet,
  FileType2,
  FileVideo,
  Presentation,
  FileText,
  Folder,
} from 'lucide-react';
import type { StorageNode } from '@/lib/storage-preview';

const fileIcons = [
  { type: 'pdf', Icon: FileType2, match: /application\/pdf|\.pdf$/i },
  {
    type: 'spreadsheet',
    Icon: FileSpreadsheet,
    match: /spreadsheet|excel|csv|\.(xlsx?|ods|tsv)$/i,
  },
  { type: 'presentation', Icon: Presentation, match: /presentation|powerpoint|\.(pptx?|odp)$/i },
  { type: 'image', Icon: FileImage, match: /image\/|\.(png|jpe?g|gif|webp|svg|avif|heic)$/i },
  { type: 'video', Icon: FileVideo, match: /video\/|\.(mp4|mov|mkv|webm)$/i },
  { type: 'audio', Icon: FileAudio, match: /audio\/|\.(mp3|wav|flac|ogg|m4a)$/i },
  { type: 'archive', Icon: FileArchive, match: /zip|compressed|archive|\.(7z|rar|tar|gz)$/i },
  {
    type: 'code',
    Icon: FileCode2,
    match: /json|javascript|typescript|xml|html|\.(py|go|rs|jsx?|tsx?|css|sh|ya?ml|toml)$/i,
  },
  {
    type: 'document',
    Icon: FileText,
    match: /text\/|word|opendocument.text|\.(docx?|rtf|md|txt)$/i,
  },
];
export function FileIcon({ node }: { node: Pick<StorageNode, 'kind' | 'mime' | 'name'> }) {
  const { Icon, type } =
    node.kind === 'folder'
      ? { Icon: Folder, type: 'folder' }
      : (fileIcons.find(({ match }) =>
          match.test(`${node.mime} .${node.name.split('.').at(-1)}`),
        ) ?? { Icon: File, type: 'file' });
  return (
    <Icon
      className="storage-file-icon size-5 shrink-0 text-muted-foreground data-[file-type=folder]:size-5.5 data-[file-type=folder]:fill-current data-[file-type=folder]:stroke-1"
      data-file-type={type}
      strokeWidth={1.75}
      aria-hidden="true"
    />
  );
}
