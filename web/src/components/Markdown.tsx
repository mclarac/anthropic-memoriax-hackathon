import ReactMarkdown from "react-markdown";
import styles from "./Markdown.module.css";

/** react-markdown does not render raw HTML, so model output cannot inject markup. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className={styles.prose}>
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
