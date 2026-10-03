import { Link, Navigate, Route, Routes } from 'react-router-dom';

import { BrandMark } from '@/components/BrandMark';
import { MARKETING_HOST, productUrl } from '@/lib/hosts';
import { TermsPage } from '@/pages/TermsPage';

import { HomePage } from './HomePage';
import styles from './marketing.module.css';
import { SecurityPage } from './SecurityPage';

const YEAR = new Date().getFullYear();

function MarketingChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.site}>
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
          <span>
            © {YEAR} askgrey · {MARKETING_HOST}
          </span>
          <div className={styles.footerLinks}>
            <Link className={styles.navLink} to="/security">
              Security
            </Link>
            <Link className={styles.navLink} to="/terms">
              Terms
            </Link>
            <a className={styles.navLink} href="/sitemap.xml">
              Sitemap
            </a>
            <a className={styles.navLink} href={productUrl('/login')}>
              Sign in
            </a>
          </div>
        </div>
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
        <Route path="/" element={<HomePage />} />
        <Route path="/security" element={<SecurityPage />} />
        {/* The accepted terms are public: a visitor can read them before there is an account. */}
        <Route path="/terms" element={<TermsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </MarketingChrome>
  );
}
