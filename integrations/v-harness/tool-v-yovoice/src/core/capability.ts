/** Capability identities shared by tools, operations, artifacts and future UI. */

/** V-yovoice features exposed through the single DSH plugin. */
export type CapabilityId = 'transcription' | 'speech' | 'score' | 'music'

/** One capability known to the plugin process. */
export interface CapabilityDescriptor {
  /** Stable capability identity. */
  id: CapabilityId
  /** Whether the current plugin build contains the feature module. */
  available: boolean
}

/** Small registry used by the plugin entry to expose the active capability surface. */
export class CapabilityRegistry {
  private readonly capabilities = new Map<CapabilityId, CapabilityDescriptor>()

  /** Register one capability once. */
  register(descriptor: CapabilityDescriptor): void {
    if (this.capabilities.has(descriptor.id)) {
      throw new Error(`capability ${descriptor.id} is already registered`)
    }
    this.capabilities.set(descriptor.id, descriptor)
  }

  /** Return registered capabilities in deterministic order. */
  list(): CapabilityDescriptor[] {
    return [...this.capabilities.values()]
  }
}
