import Markdown from 'react-markdown';
import { fileText } from '@/lib/file-refs';

export function MessagePreview({ text }: { text: string | null | undefined }) {
  return (
    <Markdown
      allowedElements={['img']}
      unwrapDisallowed
      components={{ img: ({ alt }) => <>{alt}</> }}
    >
      {fileText(text ?? '')}
    </Markdown>
  );
}
