import '@testing-library/jest-dom/vitest';

// jsdom has no layout, so it ships neither of these: code that keeps a navigation's destination
// in view calls them, and without stubs the component throws instead of rendering.
Element.prototype.scrollIntoView = () => {};
window.scrollTo = () => {};
