import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Every background process type surfaced in the tray gets its own kind so it can
// carry a distinct icon, human label and click-through route. Backend command
// names are mapped onto these categories in `use-jobs-poller.ts` (deriveKind).
export type JobKind =
  | 'notebook_chat'
  | 'source_chat'
  | 'podcast'
  | 'source' // reading / processing a source (process_source)
  | 'embed' // indexing for search (embed_* / vectorize)
  | 'chapters' // building the chapter tree (build_sections)
  | 'verify' // proofing pages against the PDF (verify_clean_*)
  | 'summarize' // summarizing a chapter (summarize_section)
  | 'abstract' // writing the document abstract (generate_source_abstract)
  | 'insight' // running an insight / transformation (run_transformation, create_insight)
export type JobStatus = 'new' | 'running' | 'completed' | 'failed'

/**
 * i18n key for each kind's human-facing label. Shared by the tray row and the
 * poller's completion/failure toasts so both name a job identically. A job may
 * override this with its own `label` (chat sessions pass a session-specific one).
 */
export const KIND_LABEL_KEY: Record<JobKind, string> = {
  notebook_chat: 'jobs.kind.chat',
  source_chat: 'jobs.kind.chat',
  podcast: 'jobs.kind.podcast',
  source: 'jobs.kind.source',
  embed: 'jobs.kind.embed',
  chapters: 'jobs.kind.chapters',
  verify: 'jobs.kind.verify',
  summarize: 'jobs.kind.summarize',
  abstract: 'jobs.kind.abstract',
  insight: 'jobs.kind.insight',
}

export interface BackgroundJob {
  jobId: string
  kind: JobKind
  sessionId?: string
  targetId?: string
  notebookId?: string
  /** Optional custom title (chat jobs). When empty the row derives from `kind`. */
  label: string
  /** Raw backend command name (e.g. "embed_source") — shown as row metadata. */
  command?: string
  status: JobStatus
  progress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> }
  startedAt: string
  error?: string
}

/** Fields persisted across reloads; status is re-derived from server poll. */
type PersistedJob = Pick<
  BackgroundJob,
  'jobId' | 'kind' | 'sessionId' | 'targetId' | 'notebookId' | 'label' | 'command' | 'startedAt'
>

interface JobsState {
  jobs: BackgroundJob[]

  /** Add or replace a job in the store. */
  register: (job: BackgroundJob) => void

  /** Apply a partial patch to an existing job (matched by jobId). */
  update: (jobId: string, patch: Partial<Omit<BackgroundJob, 'jobId'>>) => void

  /** Remove a single job by id. */
  remove: (jobId: string) => void

  /** Remove all jobs whose status is 'completed' or 'failed'. */
  clearFinished: () => void

  /** True when any job for sessionId is in 'new' or 'running' status. */
  hasActiveForSession: (sessionId: string) => boolean
}

export const useJobsStore = create<JobsState>()(
  persist(
    (set, get) => ({
      jobs: [],

      register: (job) =>
        set((state) => {
          const existing = state.jobs.findIndex((j) => j.jobId === job.jobId)
          if (existing !== -1) {
            const updated = [...state.jobs]
            updated[existing] = job
            return { jobs: updated }
          }
          return { jobs: [...state.jobs, job] }
        }),

      update: (jobId, patch) =>
        set((state) => ({
          jobs: state.jobs.map((j) =>
            j.jobId === jobId ? { ...j, ...patch } : j
          ),
        })),

      remove: (jobId) =>
        set((state) => ({
          jobs: state.jobs.filter((j) => j.jobId !== jobId),
        })),

      clearFinished: () =>
        set((state) => ({
          jobs: state.jobs.filter(
            (j) => j.status !== 'completed' && j.status !== 'failed'
          ),
        })),

      hasActiveForSession: (sessionId) =>
        get().jobs.some(
          (j) =>
            j.sessionId === sessionId &&
            (j.status === 'new' || j.status === 'running')
        ),
    }),
    {
      name: 'jobs-storage',
      partialize: (state): { jobs: PersistedJob[] } => ({
        jobs: state.jobs.map(({ jobId, kind, sessionId, targetId, notebookId, label, command, startedAt }) => ({
          jobId,
          kind,
          sessionId,
          targetId,
          notebookId,
          label,
          command,
          startedAt,
        })),
      }),
    }
  )
)
