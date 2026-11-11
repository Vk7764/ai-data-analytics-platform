// frontend/src/components/LegalPage.jsx
import { useState, useEffect } from "react";

// Only these URL schemes may become clickable links.
const SAFE_LINK_PATTERN = /^(https?:\/\/|mailto:)[^\s<>"']+$/i;
const MAX_LEGAL_LINES = 5000;
const MAX_INLINE_PARTS = 200;
const MAX_LINE_LENGTH = 10000;

function renderSafeLink(label, href, key) {
  const cleanHref = href.trim();
  if (!SAFE_LINK_PATTERN.test(cleanHref)) return label; // Unsafe or malformed target: show plain text only.
  return (
    <a key={key} href={cleanHref} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

// Renders **bold**, [label](url) links and bare http(s) URLs inside a line.
function renderInline(text) {
  const safeText = String(text ?? "").slice(0, MAX_LINE_LENGTH);
  const parts = safeText
    .split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|https?:\/\/[^\s<>)\]]+)/g)
    .slice(0, MAX_INLINE_PARTS);
  return parts.map((part, i) => {
    if (!part) return part;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const markdownLink = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (markdownLink) {
      return renderSafeLink(markdownLink[1], markdownLink[2], i);
    }
    if (/^https?:\/\//i.test(part)) {
      // Trailing sentence punctuation is not part of the address.
      const trailing = part.match(/[.,;:!?]+$/);
      const url = trailing ? part.slice(0, -trailing[0].length) : part;
      return (
        <span key={i}>
          {renderSafeLink(url, url, `link-${i}`)}
          {trailing ? trailing[0] : ""}
        </span>
      );
    }
    return part;
  });
}

// A deliberately tiny markdown renderer: supports #, ##, - lists, > quotes,
// **bold**, and plain paragraphs — all the legal documents need.
function renderMarkdown(md) {
  const elements = [];
  let listItems = [];
  let listType = null; // "ul" | "ol"

  const flushList = () => {
    if (listItems.length > 0) {
      const ListTag = listType === "ol" ? "ol" : "ul";
      elements.push(<ListTag key={`${listType}-${elements.length}`}>{listItems}</ListTag>);
    }
    listItems = [];
    listType = null;
  };

  const lines = String(md ?? "").split("\n").slice(0, MAX_LEGAL_LINES);
  lines.forEach((line, idx) => {
    if (line.startsWith("- ")) {
      if (listType !== "ul") flushList();
      listType = "ul";
      listItems.push(<li key={idx}>{renderInline(line.slice(2))}</li>);
      return;
    }
    const orderedMatch = line.match(/^\d+\.\s+([\s\S]*)$/);
    if (orderedMatch) {
      if (listType !== "ol") flushList();
      listType = "ol";
      listItems.push(<li key={idx}>{renderInline(orderedMatch[1].trim())}</li>);
      return;
    }
    flushList();

    if (!line.trim()) return;
    if (line.startsWith("# ")) elements.push(<h1 key={idx}>{renderInline(line.slice(2))}</h1>);
    else if (line.startsWith("## ")) elements.push(<h2 key={idx}>{renderInline(line.slice(3))}</h2>);
    else if (line.startsWith("> ")) elements.push(<blockquote key={idx}>{renderInline(line.slice(2))}</blockquote>);
    else elements.push(<p key={idx}>{renderInline(line)}</p>);
  });

  flushList();
  return elements;
}

function LegalPage({ title, file }) {
  const [content, setContent] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(file)
      .then((res) => res.text())
      .then((text) => {
        // If the file is missing, the dev server falls back to index.html —
        // detect that instead of showing raw HTML to the user.
        if (text.trim().toLowerCase().startsWith("<!doctype") || text.trim().startsWith("<html")) {
          setError(true);
        } else {
          setContent(text);
        }
      })
      .catch(() => setError(true));
  }, [file]);

  return (
    <div className="legal-page">
      <a href="/" className="legal-back-link">← Back to the app</a>
      {error && <p className="error-text">{title} is not available right now.</p>}
      {!content && !error && <p className="subtitle">Loading...</p>}
      {content && <div className="legal-content">{renderMarkdown(content)}</div>}
    </div>
  );
}

export default LegalPage;