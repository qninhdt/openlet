import { useEffect, useState, type ReactNode } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
      .catch(() => {});
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
      <CodeBlockContent lineNumbers={!lines} aria-label={`${title ?? language} code`}>
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

export function AgentMarkdown({ text }: { text: string }) {
  return (
    <article className="flex min-w-0 max-w-full flex-col gap-3 text-sm leading-relaxed wrap-anywhere">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-medium">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-medium">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-medium">{children}</h3>,
          ul: ({ children }) => <ul className="flex list-disc flex-col gap-1 pl-5">{children}</ul>,
          ol: ({ children }) => (
            <ol className="flex list-decimal flex-col gap-1 pl-5">{children}</ol>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l pl-3 text-muted-foreground">{children}</blockquote>
          ),
          pre: ({ children }) => <>{children}</>,
          code: ({ children, className }) => {
            const code = String(children).replace(/\n$/, '');
            const language = /language-(\w+)/.exec(className ?? '')?.[1];
            return language || code.includes('\n') ? (
              <HighlightedCode code={code} language={language ?? 'text'} />
            ) : (
              <code className="rounded-sm bg-muted px-1 py-0.5 text-xs">{children}</code>
            );
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
          a: ({ href, children }) => (
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
        {text}
      </Markdown>
    </article>
  );
}
