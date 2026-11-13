/** Shared operation states for synchronous compatibility and future long-running jobs. */
import type { CapabilityId } from './capability.ts'

/** Terminal and non-terminal states visible to tools and cards. */
export type OperationState =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timed_out'
  | 'unknown'

/** One capability invocation that can be restored from the conversation. */
export interface OperationSnapshot {
  /** Stable idempotency identity. */
  id: string
  /** Capability that owns the operation. */
  capability: CapabilityId
  /** Current lifecycle state. */
  state: OperationState
  /** Creation time in ISO 8601 form. */
  createdAt: string
  /** Last state-change time in ISO 8601 form. */
  updatedAt: string
}

/** Represent a synchronous call that already completed successfully. */
export function completedOperation(capability: CapabilityId, id: string): OperationSnapshot {
  const now = new Date().toISOString()
  return { id, capability, state: 'completed', createdAt: now, updatedAt: now }
}
