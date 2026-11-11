import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ExternalLink } from 'lucide-react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className = '',
}) => {
  return (
    <div className={`markdown-body text-zinc-200 leading-relaxed space-y-2 select-text min-w-0 max-w-full break-words [overflow-wrap:anywhere] ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...props }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-purple-400 hover:text-purple-300 underline underline-offset-2 break-all break-words [overflow-wrap:anywhere] transition-colors font-medium inline cursor-pointer"
              {...props}
            >
              <span className="break-words">{children}</span>
              <ExternalLink className="w-3 h-3 inline-block ml-1 opacity-70 align-baseline shrink-0" />
            </a>
          ),
          h1: ({ children, ...props }) => (
            <h1
              className="text-base font-bold text-white mt-3 mb-1.5 pb-1 border-b border-purple-500/30 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2
              className="text-sm font-bold text-purple-200 mt-2.5 mb-1 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3
              className="text-xs font-semibold text-purple-300 mt-2 mb-0.5 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </h3>
          ),
          h4: ({ children, ...props }) => (
            <h4
              className="text-xs font-medium text-purple-300 mt-1 mb-0.5 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </h4>
          ),
          strong: ({ children, ...props }) => (
            <strong className="font-semibold text-white break-words [overflow-wrap:anywhere]" {...props}>
              {children}
            </strong>
          ),
          em: ({ children, ...props }) => (
            <em className="italic text-purple-200 break-words [overflow-wrap:anywhere]" {...props}>
              {children}
            </em>
          ),
          p: ({ children, ...props }) => (
            <p className="mb-2 last:mb-0 leading-relaxed break-words [overflow-wrap:anywhere]" {...props}>
              {children}
            </p>
          ),
          ul: ({ children, ...props }) => (
            <ul
              className="list-disc list-outside pl-4 space-y-1 my-1.5 text-zinc-300 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </ul>
          ),
          ol: ({ children, ...props }) => (
            <ol
              className="list-decimal list-outside pl-4 space-y-1 my-1.5 text-zinc-300 break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </ol>
          ),
          li: ({ children, ...props }) => (
            <li className="leading-relaxed break-words [overflow-wrap:anywhere]" {...props}>
              {children}
            </li>
          ),
          blockquote: ({ children, ...props }) => (
            <blockquote
              className="border-l-2 border-purple-500/70 pl-3 my-2 italic text-zinc-300 bg-purple-950/20 py-1 rounded-r break-words [overflow-wrap:anywhere]"
              {...props}
            >
              {children}
            </blockquote>
          ),
          table: ({ children, ...props }) => (
            <div className="overflow-x-auto max-w-full my-2 border border-purple-900/40 rounded-xl scrollbar-thin">
              <table className="min-w-full text-xs text-left text-zinc-300 divide-y divide-purple-900/40" {...props}>
                {children}
              </table>
            </div>
          ),
          th: ({ children, ...props }) => (
            <th className="px-3 py-1.5 bg-purple-950/60 text-purple-200 font-semibold text-[11px] whitespace-nowrap" {...props}>
              {children}
            </th>
          ),
          td: ({ children, ...props }) => (
            <td className="px-3 py-1.5 border-t border-purple-900/20 text-[11px] break-words [overflow-wrap:anywhere]" {...props}>
              {children}
            </td>
          ),
          pre: ({ children, ...props }) => (
            <pre className="p-3 my-2 rounded-xl bg-black/60 text-zinc-200 font-mono text-xs overflow-x-auto max-w-full border border-purple-500/30 whitespace-pre scrollbar-thin" {...props}>
              {children}
            </pre>
          ),
          code: ({ className: codeClassName, children, ...props }) => {
            return (
              <code
                className={
                  codeClassName
                    ? `${codeClassName} font-mono text-xs text-purple-200 break-all`
                    : 'px-1.5 py-0.5 rounded bg-black/50 text-purple-300 font-mono text-[11px] border border-purple-500/20 break-all [overflow-wrap:anywhere]'
                }
                {...props}
              >
                {children}
              </code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};
