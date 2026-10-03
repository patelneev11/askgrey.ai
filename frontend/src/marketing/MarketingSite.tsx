import { Link, Navigate, Route, Routes } from 'react-router-dom';

import { BrandMark } from '@/components/BrandMark';
import { MARKETING_HOST, productUrl } from '@/lib/hosts';
import { TermsPage } from '@/pages/TermsPage';

import { HomePage } from './HomePage';
import styles from './marketing.module.css';
import { SecurityPage } from './SecurityPage';
import { useSeo } from './useSeo';

const YEAR = new Date().getFullYear();

/**
 * A public route and the metadata a crawler or a shared link sees for it.
 *
 * The metadata lives with the route rather than inside each page, because one of these pages is
 * the product's own terms screen: left to set its own tags it would ship none, and a
 * client-side visit would keep the previous route's title and canonical.
 */
const ROUTES = [
  {
    path: '/',
    element: <HomePage />,
    title: 'AskGrey — evidence-backed biomedical research workspace',
    description:
      'AskGrey searches the literature, screens compounds, drafts protocols and IND sections, and finds grants — with every claim linked to the paper and page it came from.',
  },
  {
    path: '/security',
    element: <SecurityPage />,
    title: 'Security and data handling — AskGrey',
    description:
      'How AskGrey stores documents, what the model provider receives, what is written to the audit trail, and which security claims we do not make.',
  },
  {
    // The accepted terms are public: a visitor can read them before there is an account.
    path: '/terms',
    element: <TermsPage />,
    title: 'Terms of agreement — AskGrey',
    description:
      'What AskGrey does with your documents, what it does not claim about its scientific output, and the limits every account accepts.',
  },
];

function MarketingPage({
  title,
  description,
  path,
  children,
}: {
  title: string;
  description: string;
  path: string;
  children: React.ReactNode;
}) {
  useSeo({ title, description, path });
  return <>{children}</>;
}

function MarketingChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.site} data-theme="paper">
      <p className={styles.banner}>
        Taking design partners in preclinical discovery.{' '}
        <a className={styles.bannerLink} href={productUrl('/login')}>
          Open the workspace
        </a>
      </p>
      <nav className={styles.nav} aria-label="Site">
        <Link to="/" className={styles.brand}>
          <BrandMark size={26} />
          askgrey
        </Link>
        <div className={styles.navLinks}>
          <a className={styles.navLink} href="/#product">
            Product
          </a>
          <a className={styles.navLink} href="/#how-it-works">
            How it works
          </a>
          <a className={styles.navLink} href="/#trust">
            Trust
          </a>
          <Link className={styles.navLink} to="/security">
            Security
          </Link>
          <a
            className={[styles.cta, styles.ctaPrimary, styles.ctaSmall].join(' ')}
            href={productUrl('/login')}
          >
            Sign in
          </a>
        </div>
      </nav>
      {children}
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div>
            <Link to="/" className={styles.brand}>
              <BrandMark size={26} />
              askgrey
            </Link>
            <p className={styles.footerTagline}>
              An evidence-backed research workspace for preclinical biotech and academic labs.
            </p>
          </div>
          <div className={styles.footerColumn}>
            <span className={styles.footerHeading}>Product</span>
            <a className={styles.navLink} href="/#product">
              What is inside
            </a>
            <a className={styles.navLink} href="/#how-it-works">
              How it works
            </a>
            <a className={styles.navLink} href="/#limits">
              What it does not do
            </a>
          </div>
          <div className={styles.footerColumn}>
            <span className={styles.footerHeading}>Trust</span>
            <Link className={styles.navLink} to="/security">
              Security
            </Link>
            <Link className={styles.navLink} to="/terms">
              Terms
            </Link>
            <a className={styles.navLink} href="/sitemap.xml">
              Sitemap
            </a>
          </div>
          <div className={styles.footerColumn}>
            <span className={styles.footerHeading}>Workspace</span>
            <a className={styles.navLink} href={productUrl('/login')}>
              Sign in
            </a>
          </div>
        </div>
        <p className={styles.footerLegal}>
          © {YEAR} askgrey · {MARKETING_HOST}
        </p>
      </footer>
    </div>
  );
}

/**
 * The public site, rendered when the page load is on the marketing hostname.
 *
 * The product's routes are not mounted here at all, so no signed-in page is reachable from the
 * public host; its calls to action are absolute links to the product host instead.
 */
export function MarketingSite() {
  return (
    <MarketingChrome>
      <Routes>
        {ROUTES.map(({ path, element, title, description }) => (
          <Route
            key={path}
            path={path}
            element={
              <MarketingPage title={title} description={description} path={path}>
                {element}
              </MarketingPage>
            }
          />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </MarketingChrome>
  );
}
