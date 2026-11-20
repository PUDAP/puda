import type {ReactNode} from 'react';
import {useState} from 'react';
import clsx from 'clsx';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {useLocation} from '@docusaurus/router';

import styles from './styles.module.css';

type CopyPromptButtonProps = {
  variant?: 'hero' | 'docs';
  tooltip?: string;
};

/** Keep in sync with the current docs line and `static/agent-setup/<version>/`. */
const LAST_DOCS_VERSION = '0.1.x';

function useAgentPromptPath(): string {
  const {pathname} = useLocation();
  const firstSegment = pathname.match(/^\/docs\/([^/]+)/)?.[1];
  if (firstSegment && /^\d/.test(firstSegment)) {
    return `agent-setup/${firstSegment}/prompt.md`;
  }
  return `agent-setup/${LAST_DOCS_VERSION}/prompt.md`;
}

export default function CopyPromptButton({
  variant = 'docs',
  tooltip = 'Paste into your AI agent to set up PUDA',
}: CopyPromptButtonProps): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const promptUrl = new URL(useAgentPromptPath(), siteConfig.url).href;
  const agentPrompt = `Fetch ${promptUrl}`;
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(agentPrompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className={clsx(styles.wrapper, styles[variant])}>
      <button
        type="button"
        className={clsx(
          'button button--lg',
          variant === 'hero' ? styles.heroBtn : 'button--secondary',
          styles.btn,
          copied && styles.copied,
        )}
        onClick={handleCopy}>
        {copied ? 'Copied!' : 'Copy Prompt'}
      </button>
      <span className={styles.tooltip}>{tooltip}</span>
    </div>
  );
}
