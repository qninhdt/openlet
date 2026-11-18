export function mapMarkdownText(content: string, transform: (text: string) => string) {
  // Leave Markdown code spans and fenced blocks byte-for-byte intact.
  const markers = /^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)|`+/gm;
  let result = '',
    start = 0;
  for (let marker = markers.exec(content); marker; marker = markers.exec(content)) {
    const at = marker.index;
    if (at < start) continue;
    let end = -1;
    if (marker[1]) {
      const fence = marker[1];
      const closing = new RegExp(`^ {0,3}${fence[0]}{${fence.length},}[ \\t]*(?:\\n|$)`, 'gm');
      closing.lastIndex = markers.lastIndex;
      const match = closing.exec(content);
      end = match ? closing.lastIndex : content.length;
    } else {
      const slashes = /\\*$/.exec(content.slice(0, at))![0].length;
      if (slashes % 2) continue;
      const closing = /`+/g;
      closing.lastIndex = markers.lastIndex;
      for (let match = closing.exec(content); match; match = closing.exec(content)) {
        if (match[0].length === marker[0].length) {
          end = closing.lastIndex;
          break;
        }
      }
    }
    if (end < 0) continue;
    result += transform(content.slice(start, at)) + content.slice(at, end);
    start = end;
    markers.lastIndex = end;
  }
  return result + transform(content.slice(start));
}

export function mathMarkdown(content: string) {
  // Normalize TeX delimiters before Markdown consumes the escaped parentheses/brackets.
  return mapMarkdownText(content, (text) =>
    text.replace(
      /(\\*)\\\(([\s\S]*?)\\\)|(\\*)\\\[([\s\S]*?)\\\]/g,
      (
        match,
        inlineSlashes: string | undefined,
        inline: string | undefined,
        blockSlashes: string | undefined,
        block: string | undefined,
      ) => {
        const slashes = inlineSlashes ?? blockSlashes ?? '';
        const math = (inline ?? block ?? '').trim();
        if (slashes.length % 2 || !math) return match;
        return slashes + (block === undefined ? `$${math}$` : `\n$$\n${math}\n$$\n`);
      },
    ),
  );
}
