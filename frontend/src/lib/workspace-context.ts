import { createContext, useContext } from 'react';

import type { CitationTarget } from '@/components/CitationViewer';

import type { ExportFormat } from './api';
import type { ExtractionCell, ExtractionTable, PaperRow } from './extraction';

/** A paper queued for review: either uploaded bytes or a PMC/PDF link. */
export interface Source {
  id: string;
  label: string;
  file?: File;
  url?: string;
  /**
   * The documents this source produced, once it has been extracted.
   *
   * A restored upload has ids but no `file` — its bytes live on the server, which is both
   * how it can be re-extracted and how its citations still render after a reload.
   */
  documentIds?: string[];
}

/**
 * The Literature workspace, held above the router.
 *
 * Routes unmount on navigation, so page-local state would throw away a generated table the
 * moment the user clicks another tab. Keeping the workspace here also lets an extraction that
 * is still running survive that navigation and land when it finishes.
 */
export interface WorkspaceContextValue {
  sources: Source[];
  goal: string;
  table: ExtractionTable;
  pendingColumns: string[];
  running: boolean;
  exporting: ExportFormat | null;
  error: string | null;
  target: CitationTarget | null;
  activeCell: string | null;
  /** False until the saved workspace has been read back, so the UI can avoid a flash. */
  restored: boolean;
  /** False when the deployment has no model credentials, so no extraction can run at all. */
  extractionAvailable: boolean;
  setGoal: (goal: string) => void;
  addFiles: (files: FileList | null) => void;
  addUrl: (url: string) => void;
  removeSource: (id: string) => void;
  runExtraction: () => Promise<void>;
  exportTable: (format: ExportFormat) => Promise<void>;
  selectCitation: (row: PaperRow, columnKey: string, cell: ExtractionCell) => void;
  fileFor: (documentId: string) => File | undefined;
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error('useWorkspace must be used inside a WorkspaceProvider');
  }
  return context;
}
