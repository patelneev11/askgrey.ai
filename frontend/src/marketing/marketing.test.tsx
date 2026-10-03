import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';

import { isMarketingHost, PRODUCT_ORIGIN, productUrl } from '@/lib/hosts';

import { MarketingSite } from './MarketingSite';

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

it('treats only the marketing hostname as the marketing site', () => {
  expect(isMarketingHost({ hostname: 'askgrey.app', search: '' })).toBe(true);
  expect(isMarketingHost({ hostname: 'www.askgrey.app', search: '' })).toBe(true);
  expect(isMarketingHost({ hostname: 'lab.askgrey.app', search: '' })).toBe(false);
  expect(isMarketingHost({ hostname: 'localhost', search: '' })).toBe(false);
  // A local preview of the public site, without owning the hostname.
  expect(isMarketingHost({ hostname: 'localhost', search: '?site=marketing' })).toBe(true);
});
