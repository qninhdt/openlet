import {
  Children,
  isValidElement,
  useEffect,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react';
import Markdown, { defaultUrlTransform, type ExtraProps } from 'react-markdown';
import { fileReferenceStyles } from '@/components/ui/styles';
import { fileMarkdown, fileTokenPattern } from '@/lib/file-refs';
import { FileIcon } from '@/components/storage/file-icon';
import { useAgentPreview } from './agent-preview';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { mathMarkdown } from '@/lib/markdown';
import { highlightCode } from '@/lib/highlighter';
import {
  CodeBlock,
  CodeBlockHeader,
  CodeBlockTitle,
  CodeBlockActions,
  CodeBlockCopyButton,
  CodeBlockContent,
  CodeBlockLine,
} from '@/components/ui/code-block';

export function HighlightedCode({
  code,
  language,
  title,
  variant = 'default',
}: {
  code: string;
  language: string;
  title?: string;
  variant?: 'default' | 'destructive';
}) {
  const [highlighted, setHighlighted] = useState<{
    code: string;
    language: string;
    lines: ReactNode[] | null;
  } | null>(null);
  const lines =
    highlighted?.code === code && highlighted.language === language ? highlighted.lines : null;
  useEffect(() => {
    let active = true;
    void highlightCode(code, language)
      .then((lines) => {
        if (active) setHighlighted({ code, language, lines });
      })
      .catch((error) => console.warn(`Could not highlight ${language}`, error));
    return () => {
      active = false;
    };
  }, [code, language]);
  return (
    <CodeBlock size="sm" variant={variant} className="bg-background">
      <CodeBlockHeader>
        <CodeBlockTitle>{title ?? language}</CodeBlockTitle>
        <CodeBlockActions>
          <CodeBlockCopyButton value={code} />
        </CodeBlockActions>
      </CodeBlockHeader>
      <CodeBlockContent lineNumbers aria-label={`${title ?? language} code`}>
        {lines
          ? lines.map((line, index) => (
              <CodeBlockLine
                key={index}
                className={language === 'diff' ? 'after:hidden' : undefined}
                variant={
                  language === 'diff'
                    ? code.split('\n')[index]?.startsWith('+')
                      ? 'added'
                      : code.split('\n')[index]?.startsWith('-')
                        ? 'removed'
                        : 'default'
                    : 'default'
                }
              >
                {line}
              </CodeBlockLine>
            ))
          : code}
      </CodeBlockContent>
    </CodeBlock>
  );
}

const attachmentLink = /^openlet-(file|folder):/;

function FileReference({ target, label }: { target: string; label: ReactNode }) {
  const p = useAgentPreview();
  const [storage, id] = target.replace(attachmentLink, '').split('/');
  const kind = target.startsWith('openlet-folder:') ? 'folder' : 'file';
  const node = p.fileNodes[id];
  return (
    <button
      type="button"
      className={fileReferenceStyles}
      title={node ? `${node.name} · ${storage}` : String(label)}
      onClick={() =>
        void p.openFileReference({ storage_id: storage, node_id: id, label: String(label) })
      }
    >
      <FileIcon node={node ?? { kind, mime: '', name: String(label) }} />
      <span className="truncate">{label}</span>
    </button>
  );
}
function MathSpan({ node: _node, className, ...props }: ComponentProps<'span'> & ExtraProps) {
  return (
    <span
      {...props}
      className={className}
      tabIndex={className === 'katex-display' ? 0 : undefined}
    />
  );
}

export function AgentMarkdown({ text }: { text: string }) {
  return (
    <article className="agent-markdown flex min-w-0 max-w-full flex-col gap-3 text-sm leading-relaxed wrap-anywhere">
      <Markdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { trust: false }]]}
        urlTransform={(url) => (attachmentLink.test(url) ? url : defaultUrlTransform(url))}
        components={{
          span: MathSpan,
          h1: ({ children }) => <h1 className="text-xl font-medium">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-medium">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-medium">{children}</h3>,
          ul: ({ children }) => <ul className="flex list-disc flex-col gap-1 pl-5">{children}</ul>,
          ol: ({ children }) => (
            <ol className="flex list-decimal flex-col gap-1 pl-5">{children}</ol>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l border-current/25 pl-3">{children}</blockquote>
          ),
          pre: ({ children }) => {
            const child = Children.toArray(children)[0];
            if (!isValidElement<{ children?: ReactNode; className?: string }>(child))
              return <pre>{children}</pre>;
            return (
              <HighlightedCode
                code={String(child.props.children ?? '').replace(/\n$/, '')}
                language={/language-([^\s]+)/.exec(child.props.className ?? '')?.[1] ?? 'text'}
              />
            );
          },
          code: ({ children }) => {
            const text = String(children ?? '');
            const mention = [...text.matchAll(fileTokenPattern())];
            if (mention.length === 1 && mention[0][0] === text.trim()) {
              const [, label, storage, id] = mention[0];
              return (
                <FileReference
                  target={`openlet-${text.trim().startsWith(':folder[') ? 'folder' : 'file'}:${storage}/${id}`}
                  label={label.replace(/\\(.)/g, '$1')}
                />
              );
            }
            return <code className="rounded-sm bg-muted px-1 py-0.5 text-xs">{children}</code>;
          },
          table: ({ children }) => (
            <div
              role="region"
              aria-label="Scrollable table"
              tabIndex={0}
              className="w-full min-w-0 max-w-full overflow-x-auto rounded-xl border bg-background text-foreground scrollbar-thin outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <table className="w-max min-w-full border-collapse text-left whitespace-nowrap">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-r border-b px-3 py-2 font-normal text-muted-foreground last:border-r-0">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-r border-b px-3 py-2 last:border-r-0">{children}</td>
          ),
          a: ({ href, children }) =>
            href && attachmentLink.test(href) ? (
              <FileReference target={href} label={children} />
            ) : (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-3"
              >
                {children}
              </a>
            ),
        }}
      >
        {mathMarkdown(fileMarkdown(text))}
      </Markdown>
    </article>
  );
}
