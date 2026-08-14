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
