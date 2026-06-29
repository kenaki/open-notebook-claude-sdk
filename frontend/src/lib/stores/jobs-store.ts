import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type JobKind = 'notebook_chat' | 'source_chat' | 'podcast' | 'source' | 'transformation'
export type JobStatus = 'new' | 'running' | 'completed' | 'failed'

export interface BackgroundJob {
  jobId: string
  kind: JobKind
  sessionId?: string
  targetId?: string
  notebookId?: string
  label: string
  status: JobStatus
  progress?: { phase?: string }
  startedAt: string
  error?: string
}

/** Fields persisted across reloads; status is re-derived from server poll. */
type PersistedJob = Pick<
  BackgroundJob,
  'jobId' | 'kind' | 'sessionId' | 'targetId' | 'notebookId' | 'label' | 'startedAt'
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
        jobs: state.jobs.map(({ jobId, kind, sessionId, targetId, notebookId, label, startedAt }) => ({
          jobId,
          kind,
          sessionId,
          targetId,
          notebookId,
          label,
          startedAt,
        })),
      }),
    }
  )
)
