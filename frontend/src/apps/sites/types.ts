// Simple Sites — what backend/sites.py answers for a page or a short link.

/** A page's most content before the caps load, as the server counts it (common.SITE_MAX_BYTES). */
export const SITE_MAX_BYTES = 2_000_000;
export interface Site {
  id: number;
  kind: 'page' | 'link';
  code: string;
  name: string;
  title: string;
  /** The full address: the page, or where the link starts. */
  address: string;
  status: 'published' | 'unpublished';
  suspended_at?: string;
  expires_at?: string | null;
  short_name?: string | null;
  short_grace_until?: string | null;
  data_url?: string;
  source: string;
  source_client: string | null;
  created_at: string;
  updated_at: string;
  /** Opens of a page, follows of a link: present only when the account allows it (or self-hosted). */
  views?: number;
  /** A page that asks visitors for a password. */
  locked?: boolean;
  /** The owner's private note (who it is for), never shown on the page. */
  note?: string;
  /** The folder it is filed in, or '' for none. */
  folder?: string;
  /** Pages only. */
  format?: 'markdown' | 'html' | '';
  layout?: 'body' | 'files';
  size?: number;
  file_count?: number;
  bytes?: number;
  content?: string;
  data?: 'off' | 'collect' | 'shared';
  records?: number;
  /** Links only: where it goes. */
  target?: string;
}

/** How many pages and short links the account may hold now. */
export interface SiteCaps {
  pages: number;
  links: number;
  /** The most content one page may hold on this plan (UTF-8 bytes). */
  page_bytes?: number;
  site_bytes?: number;
  storage?: number;
  storage_used?: number;
  files_per_site?: number;
  short_names?: number;
}

/** A folder and how many pages and links it holds. */
export interface SiteFolder {
  name: string;
  count: number;
}

export interface SiteRecord {
  id: number;
  at: string;
  by: 'visitor' | 'owner';
  data: Record<string, unknown>;
}

export interface SiteRecords {
  records: SiteRecord[];
  next: number | null;
  more: boolean;
}
