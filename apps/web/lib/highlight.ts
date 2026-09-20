/**
 * A very small tokenizer for the code viewer.
 *
 * The sandbox only ever hands back Python source plus captured stdout/stderr,
 * so a full highlighter library would be several hundred kilobytes to colour
 * two grammars. This scans once with a single alternation regex and returns
 * tokens already split per line, which is the shape the viewer renders.
 */

export type TokenKind =
  | "comment"
  | "string"
  | "docstring"
  | "number"
  | "keyword"
  | "builtin"
  | "decorator"
  | "def"
  | "call"
  | "operator"
  | "key"
  | "error"
  | "plain";

export interface Token {
  kind: TokenKind;
  value: string;
}

export type Language = "python" | "log" | "text";

const KEYWORDS = new Set([
  "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
  "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
  "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
  "return", "try", "while", "with", "yield", "match", "case",
]);

const BUILTINS = new Set([
  "abs", "all", "any", "bool", "dict", "enumerate", "float", "format", "int",
  "isinstance", "len", "list", "map", "max", "min", "open", "print", "range",
  "round", "set", "sorted", "str", "sum", "tuple", "type", "zip",
  "True", "False", "None", "self", "cls", "__name__", "__main__",
]);

/** `word` is resolved later — a bare identifier could be five different things. */
type Rule = [kind: TokenKind | "word", pattern: RegExp];

/**
 * Order matters: comments and strings must win over words and operators.
 *
 * The patterns are regex *literals* joined by `.source`. Written as strings
 * every backslash would have to survive two levels of escaping, which is
 * exactly the kind of quiet corruption that turns a character class into an
 * out-of-order range. Each pattern must use only non-capturing groups, since
 * the scanner identifies a match by which top-level group is defined.
 */
const PYTHON_RULES: Rule[] = [
  ["comment", /#[^\n]*/],
  ["docstring", /[rbuf]{0,2}(?:"""[\s\S]*?"""|'''[\s\S]*?''')/],
  ["string", /[rbuf]{0,2}(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/],
  ["decorator", /@[A-Za-z_][\w.]*/],
  ["number", /\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b/],
  ["word", /[A-Za-z_]\w*/],
  ["operator", /[-+*/%=<>!&|^~]+/],
];

const LOG_RULES: Rule[] = [
  ["error", /\b(?:Traceback|Error|error|ERROR|Exception|Warning|WARNING|FAILED|failed)\b[^\n]*/],
  ["key", /^[ \t]*[A-Za-z_][\w .-]*(?=:)/],
  ["string", /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/],
  ["number", /[-+]?\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?%?\b/],
];

function scannerFor(rules: Rule[], flags: string): RegExp {
  return new RegExp(rules.map(([, pattern]) => `(${pattern.source})`).join("|"), flags);
}

const PYTHON_SCANNER = scannerFor(PYTHON_RULES, "g");
const LOG_SCANNER = scannerFor(LOG_RULES, "gm");

function pythonWordKind(word: string, previous: string | null, after: string): TokenKind {
  if (previous === "def" || previous === "class") return "def";
  if (KEYWORDS.has(word)) return "keyword";
  if (BUILTINS.has(word)) return "builtin";
  if (after.startsWith("(")) return "call";
  return "plain";
}

function tokenize(source: string, language: Language): Token[] {
  if (language === "text") return [{ kind: "plain", value: source }];

  const python = language === "python";
  const scanner = python ? PYTHON_SCANNER : LOG_SCANNER;
  const rules = python ? PYTHON_RULES : LOG_RULES;

  const tokens: Token[] = [];
  let cursor = 0;
  /* The last significant word, so `def foo` can colour `foo` as a definition. */
  let previousWord: string | null = null;

  scanner.lastIndex = 0;
  for (let match = scanner.exec(source); match !== null; match = scanner.exec(source)) {
    if (match.index > cursor) {
      tokens.push({ kind: "plain", value: source.slice(cursor, match.index) });
    }

    const value = match[0];
    /* Group n+1 belongs to rule n; exactly one of them is defined. */
    const group = match.findIndex((captured, index) => index > 0 && captured !== undefined);
    const rule = rules[group - 1];

    if (rule && rule[0] === "word") {
      const after = source.slice(match.index + value.length).trimStart();
      tokens.push({ kind: pythonWordKind(value, previousWord, after), value });
      previousWord = value;
    } else {
      const kind = (rule?.[0] ?? "plain") as TokenKind;
      tokens.push({ kind, value });
      if (kind !== "operator") previousWord = null;
    }

    cursor = match.index + value.length;
    /* A zero-length match would spin forever; nudge past it. */
    if (value.length === 0) scanner.lastIndex += 1;
  }

  if (cursor < source.length) tokens.push({ kind: "plain", value: source.slice(cursor) });
  return tokens;
}

/** Tokens grouped per source line — one array entry per rendered row. */
export function highlightLines(source: string, language: Language): Token[][] {
  const lines: Token[][] = [[]];
  for (const token of tokenize(source, language)) {
    const segments = token.value.split("\n");
    segments.forEach((segment, index) => {
      if (index > 0) lines.push([]);
      if (segment.length > 0) lines[lines.length - 1].push({ kind: token.kind, value: segment });
    });
  }
  /* A trailing newline should not render as a phantom final row. */
  if (lines.length > 1 && lines[lines.length - 1].length === 0) lines.pop();
  return lines;
}

export const TOKEN_COLOR: Record<TokenKind, string> = {
  comment: "var(--code-comment)",
  string: "var(--code-string)",
  docstring: "var(--code-comment)",
  number: "var(--code-number)",
  keyword: "var(--code-keyword)",
  builtin: "var(--code-builtin)",
  decorator: "var(--code-decorator)",
  def: "var(--code-def)",
  call: "var(--code-call)",
  operator: "var(--code-operator)",
  key: "var(--code-builtin)",
  error: "var(--code-error)",
  plain: "var(--code-plain)",
};
