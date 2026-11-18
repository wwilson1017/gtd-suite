/**
 * Shared search / filter bar — keyword search and facet filters for the client-side lists.
 *
 * The contract: the **page** owns the query and the facet selections; `SearchFilterBar` is
 * fully controlled; the page computes ONE filtered array and renders from it.
 *
 * Pages filter with `util.matchesFilter`; this module needs no tokenized matcher or sort helpers.
 */
export { default as SearchFilterBar } from './SearchFilterBar';
export { toggleValue } from './persist';
export type { FacetOption, FacetGroup, SortDir, SortState, SortFieldDef } from './types';
