/** A staged profile configuration form owned by the installed plugin. */
import { SettingsFormModel, settingsNumberField, settingsTextField, type SettingsFormScope } from '@deepseek-ai/dsh-client-ui-primitives'

/** Editable values exposed by the Host's Config schema. */
export interface AudioSettings {
  baseUrl: string
  model: string
  requestTimeoutMs: number
  maxUploadBytes: number
  maxResponseBytes: number
  pageCharacters: number
}

/**
 * Bind fields to the shared Settings writer with its revision fence and discard behavior.
 * @param scope - the profile entry's configuration scope.
 * @returns staged form, store, and actions for the configuration slot.
 */
export function audioForm(scope: SettingsFormScope<AudioSettings>) {
  const fields = ['baseUrl', 'model', 'requestTimeoutMs', 'maxUploadBytes', 'maxResponseBytes', 'pageCharacters'] as const
  const form = new SettingsFormModel(scope, fields.map(field => field === 'baseUrl' || field === 'model' ? settingsTextField(field) : settingsNumberField(field)))
  const store = form.bind(() => ({ ...form.shell(), fields: { baseUrl: form.field('baseUrl'), model: form.field('model'), requestTimeoutMs: form.field('requestTimeoutMs'),
    maxUploadBytes: form.field('maxUploadBytes'), maxResponseBytes: form.field('maxResponseBytes'), pageCharacters: form.field('pageCharacters') } }))
  return { form, store, fields, actions: form.actions() }
}
