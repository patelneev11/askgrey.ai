import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { BrandMark } from '@/components/BrandMark';
import { MARKETING_HOST, productUrl } from '@/lib/hosts';
import { TermsPage } from '@/pages/TermsPage';

import { HomePage } from './HomePage';
import styles from './marketing.module.css';
import { ProductTabPage } from './ProductTabPage';
import { SecurityPage } from './SecurityPage';
import { PRODUCT_TABS, TAB_GROUPS, tabPath, tabsInGroup } from './tabs';
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
  ...PRODUCT_TABS.map((tab) => ({
    path: tabPath(tab),
    element: <ProductTabPage tab={tab} />,
    title: `${tab.name} — AskGrey`,
    description: tab.summary,
  })),
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

/**
 * The product menu: the nine tabs, split into the ones that do research and the ones the
 * research runs on. It is one component for both widths — on a phone the same panel is opened
 * by the menu button instead of by the Product control.
 */
function ProductMenu({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div className={styles.menuGroups}>
      {TAB_GROUPS.map((group) => (
        <div key={group.name} className={styles.menuGroup}>
          <p className={styles.menuGroupName}>{group.name}</p>
          <p className={styles.menuGroupBlurb}>{group.blurb}</p>
          {tabsInGroup(group.name).map((tab) => (
            <Link key={tab.id} className={styles.menuLink} to={tabPath(tab)} onClick={onNavigate}>
              <span className={styles.menuLinkName}>{tab.name}</span>
              <span className={styles.menuLinkBlurb}>{tab.summary}</span>
            </Link>
          ))}
        </div>
      ))}
    </div>
  );
}

function SiteNav() {
  const [open, setOpen] = useState<'product' | 'menu' | null>(null);
  const navRef = useRef<HTMLElement>(null);
  const { pathname, hash } = useLocation();

  // Arriving somewhere new closes whatever was open, including on a same-page anchor.
  useEffect(() => setOpen(null), [pathname, hash]);

  useEffect(() => {
    if (!open) return undefined;
    const dismiss = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape') return;
      if (event.type === 'pointerdown' && navRef.current?.contains(event.target as Node)) return;
      setOpen(null);
    };
    document.addEventListener('keydown', dismiss);
    document.addEventListener('pointerdown', dismiss);
    return () => {
      document.removeEventListener('keydown', dismiss);
      document.removeEventListener('pointerdown', dismiss);
    };
  }, [open]);

  const close = () => setOpen(null);

  return (
    <nav className={styles.nav} aria-label="Site" ref={navRef}>
      <Link to="/" className={styles.brand} onClick={close}>
        <BrandMark size={26} />
        askgrey
      </Link>
      <div className={styles.navLinks}>
        <button
          type="button"
          className={[styles.navLink, styles.navButton].join(' ')}
          aria-expanded={open === 'product'}
          aria-haspopup="true"
          onClick={() => setOpen(open === 'product' ? null : 'product')}
        >
          Product
          <span aria-hidden="true" className={styles.navCaret} />
        </button>
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
      <button
        type="button"
        className={styles.navToggle}
        aria-expanded={open === 'menu'}
        aria-label="Menu"
        onClick={() => setOpen(open === 'menu' ? null : 'menu')}
      >
        <span aria-hidden="true" className={styles.navToggleBars} />
      </button>

      {open === 'product' ? (
        <div className={styles.dropdown}>
          <ProductMenu onNavigate={close} />
        </div>
      ) : null}

      {open === 'menu' ? (
        <div className={styles.mobileMenu}>
          <ProductMenu onNavigate={close} />
          <div className={styles.menuGroup}>
            <p className={styles.menuGroupName}>Company</p>
            <a className={styles.menuLink} href="/#how-it-works" onClick={close}>
              <span className={styles.menuLinkName}>How it works</span>
            </a>
            <Link className={styles.menuLink} to="/security" onClick={close}>
              <span className={styles.menuLinkName}>Security</span>
            </Link>
            <Link className={styles.menuLink} to="/terms" onClick={close}>
              <span className={styles.menuLinkName}>Terms</span>
            </Link>
          </div>
          <a
            className={[styles.cta, styles.ctaPrimary, styles.menuCta].join(' ')}
            href={productUrl('/login')}
          >
            Sign in
          </a>
        </div>
      ) : null}
    </nav>
  );
}

function MarketingChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.site}>
      <p className={styles.banner}>
        Taking design partners in preclinical discovery.{' '}
        <a className={styles.bannerLink} href={productUrl('/login')}>
          Open the workspace
        </a>
      </p>
      <SiteNav />
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
          {TAB_GROUPS.map((group) => (
            <div key={group.name} className={styles.footerColumn}>
              <span className={styles.footerHeading}>{group.name}</span>
              {tabsInGroup(group.name).map((tab) => (
                <Link key={tab.id} className={styles.navLink} to={tabPath(tab)}>
                  {tab.name}
                </Link>
              ))}
            </div>
          ))}
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
