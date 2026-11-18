const textExtensions =
  /\.(md|mdx|markdown|txt|text|py|pyi|js|mjs|cjs|jsx|ts|tsx|go|rs|c|h|cpp|cc|cxx|hpp|cs|java|kt|kts|swift|rb|php|vue|svelte|css|scss|sass|less|yaml|yml|toml|log|json|jsonc|jsonl|ndjson|csv|tsv|html|htm|xml|svg|sh|bash|zsh|fish|sql|ini|conf|config|env|properties|graphql|gql|proto|diff|patch|r|lua|ex|exs|erl|hrl|lock)$/i;
export function isTextFile(name: string, mime = '') {
  return (
    /^text\//i.test(mime) ||
    /^application\/(json|xml|javascript|x-javascript|yaml|x-yaml|toml|graphql)(;|$)|\+(json|xml)(;|$)/i.test(
      mime,
    ) ||
    textExtensions.test(name) ||
    /^(Dockerfile|Containerfile|Makefile|Gemfile|Procfile|\.gitignore|\.dockerignore|\.editorconfig|\.env(?:\..*)?)$/i.test(
      name,
    )
  );
}
export function fileMediaType(name: string, mime = '') {
  if (mime && mime !== 'application/octet-stream') return mime;
  if (/\.json$/i.test(name)) return 'application/json';
  if (/\.(md|markdown)$/i.test(name)) return 'text/markdown';
  if (/\.csv$/i.test(name)) return 'text/csv';
  if (isTextFile(name)) return 'text/plain';
  return mime || 'application/octet-stream';
}
