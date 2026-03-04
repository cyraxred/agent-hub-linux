import { create } from 'zustand';
import type { DiffMode, GitDiffFileEntry, DiffComment, RemoteBranch } from '@/types/generated';
import { api } from '@/api/client';

interface GitState {
  files: GitDiffFileEntry[];
  comments: DiffComment[];
  branches: RemoteBranch[];
  selectedFile: string | null;
  diffMode: DiffMode;
  loading: boolean;
  error: string | null;

  fetchDiff: (repoPath: string, mode?: DiffMode) => Promise<void>;
  fetchBranches: (repoPath: string) => Promise<void>;
  selectFile: (filePath: string | null) => void;
  setMode: (mode: DiffMode) => void;
  addComment: (comment: DiffComment) => void;
  clearDiffs: () => void;
}

export const useGitStore = create<GitState>((set, get) => ({
  files: [],
  comments: [],
  branches: [],
  selectedFile: null,
  diffMode: 'unstaged',
  loading: false,
  error: null,

  fetchDiff: async (repoPath, mode) => {
    const m = mode ?? get().diffMode;
    set({ loading: true, error: null, diffMode: m });
    try {
      const files = await api.git.diff(repoPath, m);
      set({
        files,
        loading: false,
        selectedFile: files.length > 0 ? (files[0]?.file_path ?? null) : null,
      });
    } catch (err) {
      set({ error: (err as Error).message, loading: false, files: [] });
    }
  },

  fetchBranches: async (repoPath) => {
    set({ error: null });
    try {
      const branches = await api.git.localBranches(repoPath);
      set({ branches });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  selectFile: (filePath) => set({ selectedFile: filePath }),
  setMode: (mode) => set({ diffMode: mode }),
  addComment: (comment) => set((s) => ({ comments: [...s.comments, comment] })),
  clearDiffs: () => set({ files: [], comments: [], selectedFile: null }),
}));
