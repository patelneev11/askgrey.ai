import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';

import { isMarketingHost, PRODUCT_ORIGIN, productUrl } from '@/lib/hosts';

import { MarketingSite } from './MarketingSite';
import { PRODUCT_TABS, tabPath } from './tabs';

function renderSite(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MarketingSite />
    </MemoryRouter>,
  );
}

it('tells a visitor what the product is, in the first heading', () => {
  renderSite();
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  expect(document.title).toMatch(/askgrey/i);
  expect(
    document.head.querySelector('meta[name="description"]')?.getAttribute('content'),
  ).toBeTruthy();
});

it('canonicalises every marketing page onto the marketing host', () => {
  renderSite('/security');
  expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
    'https://askgrey.app/security',
  );
});

it('gives each public page its own title, description and canonical', () => {
  const seen = new Map<string, string>();
  for (const path of ['/', '/security', '/terms']) {
    const view = renderSite(path);
    const description = document.head
      .querySelector('meta[name="description"]')
      ?.getAttribute('content');
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      `https://askgrey.app${path}`,
    );
    expect(description).toBeTruthy();
    seen.set(path, `${document.title}|${description ?? ''}`);
    view.unmount();
  }
  expect(new Set(seen.values()).size).toBe(seen.size);
});

it('sends every call to action at the sign-in page rather than a public path', () => {
  renderSite();
  const links = screen.getAllByRole('link', { name: /sign in|open the workspace|get started/i });
  expect(links.length).toBeGreaterThan(0);
  for (const link of links) {
    expect(link.getAttribute('href')).toMatch(/\/login$/);
  }
});

it('leaves the marketing host for the product host on a call to action', () => {
  const marketing = { hostname: 'askgrey.app', search: '' };
  expect(productUrl('/login', marketing)).toBe(`${PRODUCT_ORIGIN}/login`);
  // On the product itself (and on localhost) the same call stays where it is.
  expect(productUrl('/login', { hostname: 'lab.askgrey.app', search: '' })).toBe('/login');
});

it('says what the product cannot do as well as what it can', () => {
  renderSite('/security');
  const main = document.body;
  // The public site must not imply an audit, a BAA or a live ELN connection we do not have.
  expect(within(main).getByText(/no third-party penetration test/i)).toBeInTheDocument();
});

it('keeps the signed-in product off the public host entirely', () => {
  renderSite('/literature');
  // An unknown path on the marketing host is the homepage, not a sign-in redirect loop.
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
});

it('gives every destination in the product its own section, screenshot and anchor', () => {
  renderSite();
  expect(PRODUCT_TABS).toHaveLength(9);
  for (const tab of PRODUCT_TABS) {
    expect(screen.getByRole('heading', { name: tab.title })).toBeInTheDocument();
    // The anchor the index links to has to be the section itself, not a missing id.
    const section = document.getElementById(tab.id);
    expect(section).not.toBeNull();
    expect(within(section as HTMLElement).getByAltText(tab.alt)).toBeInTheDocument();
    const index = document.getElementById('product') as HTMLElement;
    expect(within(index).getByRole('link', { name: tab.name }).getAttribute('href')).toBe(
      `#${tab.id}`,
    );
  }
});

it('plays a recording of the product rather than describing one', () => {
  renderSite();
  const film = document.querySelector('video');
  expect(film?.getAttribute('src')).toBe('/demo/askgrey-literature.mp4');
  // Silent and captionless, so it is decoration: the page must still read without it.
  expect(film?.muted || film?.hasAttribute('muted')).toBe(true);
  expect(film?.getAttribute('aria-label')).toBeTruthy();
});

it('lists every tab under the nav, grouped, with its own page behind it', async () => {
  renderSite();
  const nav = within(screen.getByRole('navigation', { name: 'Site' }));
  const control = nav.getByRole('button', { name: /product/i });
  expect(control.getAttribute('aria-expanded')).toBe('false');
  expect(nav.queryByText('Research')).toBeNull();

  await userEvent.click(control);
  expect(control.getAttribute('aria-expanded')).toBe('true');
  // Grouped rather than one list of nine: research work, then what it runs on.
  expect(nav.getByText('Research')).toBeInTheDocument();
  expect(nav.getByText('Platform')).toBeInTheDocument();
  for (const tab of PRODUCT_TABS) {
    expect(nav.getByText(tab.name).closest('a')?.getAttribute('href')).toBe(tabPath(tab));
  }
});

it('gives a tab page its own heading, screenshot and marked place in the rail', () => {
  for (const tab of PRODUCT_TABS) {
    const view = renderSite(tabPath(tab));
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(tab.title);
    expect(screen.getAllByAltText(tab.alt).length).toBeGreaterThan(0);
    // The rail marks where the reader is, so a page reached from search still has a map.
    const rail = screen.getByRole('navigation', { name: 'Product' });
    expect(within(rail).getByRole('link', { current: 'page' }).textContent).toBe(tab.name);
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      `https://askgrey.app${tabPath(tab)}`,
    );
    view.unmount();
  }
});

it('treats only the marketing hostname as the marketing site', () => {
  expect(isMarketingHost({ hostname: 'askgrey.app', search: '' })).toBe(true);
  expect(isMarketingHost({ hostname: 'www.askgrey.app', search: '' })).toBe(true);
  expect(isMarketingHost({ hostname: 'lab.askgrey.app', search: '' })).toBe(false);
  expect(isMarketingHost({ hostname: 'localhost', search: '' })).toBe(false);
  // A local preview of the public site, without owning the hostname.
  expect(isMarketingHost({ hostname: 'localhost', search: '?site=marketing' })).toBe(true);
});
