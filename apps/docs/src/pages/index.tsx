import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import CopyPromptButton from '@site/src/components/CopyPromptButton';
import Heading from '@theme/Heading';

import styles from './index.module.css';

const examples = [
  {
    label: 'Self Driving Labs',
    title: 'Run autonomous experiments from plan to result',
    description:
      'Connect agents to instruments, lab robots, live measurements, and approvals so each protocol can be reviewed before and after execution.',
  },
  {
    label: 'Industrial Factories',
    title: 'Coordinate physical operations with traceable control',
    description:
      'Route machine commands, sensor streams, edge clients, and operator checks through one runtime built for repeatable production workflows.',
  },
  {
    label: 'Robotic Workcells',
    title: 'Close the loop between perception and action',
    description:
      'Give agents the machine context, tool access, livestreams, and audit trails needed to inspect state and choose the next controlled step.',
  },
];

function HomepageHeader() {
  return (
    <header className={styles.heroBanner}>
      <div className="container">
        <Heading as="h1" className={styles.heroTitle}>
          PUDA Developer Docs
        </Heading>
        <p className={styles.heroSubtitle}>
          Explore guides and tutorials to start using and building on the PUDA platform
        </p>
        <div className={styles.buttons}>
          <Link
            className={clsx('button button--primary button--lg', styles.getStartedBtn)}
            to="/docs/getting-started">
            Get Started
          </Link>
          <CopyPromptButton variant="hero" />
        </div>
      </div>
    </header>
  );
}

function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container text--center">
        <Heading as="h2" className={styles.title}>
          Hardware Harness for Physical AI
        </Heading>
        <p className={styles.description}>
          PUDA connects AI agents to instruments, robots, datastreams,
          approvals, and audit trails.
        </p>
        <div className={styles.examples} aria-label="Example environments">
          {examples.map((example) => (
            <article className={styles.exampleCard} key={example.label}>
              <div className={styles.exampleLabel}>{example.label}</div>
              <h3>{example.title}</h3>
              <p>{example.description}</p>
            </article>
          ))}
        </div>
        <div className={styles.actions}>
          <Link
            className={clsx('button button--primary button--lg', styles.primaryAction)}
            to="https://www.puda.co/blog/whitepaper">
            Read our whitepaper
          </Link>
          <Link
            className={clsx('button button--secondary button--lg', styles.secondaryAction)}
            to="https://www.puda.co/">
            See the demo
          </Link>
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="PUDA Developer Docs"
      description="Explore guides and tutorials to start building on PUDA's platform">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
