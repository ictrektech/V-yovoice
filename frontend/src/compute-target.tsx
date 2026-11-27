import { useEffect, useState } from 'react'
import { Localized } from './i18n/Localized'

export const placementKey = (item: VoicePlacement) => `${item.deployment_id}:${item.executor_id}`

export function useComputeTarget() {
  const [enabled, setEnabled] = useState(Boolean(window.vvoiceCompute))
  const [placements, setPlacements] = useState<VoicePlacement[]>([])
  const [unavailable, setUnavailable] = useState(false)
  const [canForce, setCanForce] = useState(false)
  const [node, setNode] = useState('local')
  useEffect(() => {
    let pending: AbortController | undefined
    async function refresh() {
      if (!window.vvoiceCompute || pending) return
      setEnabled(true)
      const controller = new AbortController()
      pending = controller
      try {
        const reply = await window.vvoiceCompute.placements(controller.signal)
        if (!reply.ok) throw new Error()
        const data: { items: VoicePlacement[]; can_force_admission?: boolean } = await reply.json()
        if (!controller.signal.aborted) {
          setPlacements(data.items)
          setCanForce(data.can_force_admission === true)
          setUnavailable(false)
        }
      } catch {
        if (!controller.signal.aborted) setUnavailable(true)
      } finally { pending = undefined }
    }
    const check = () => void refresh()
    document.addEventListener('vvoice-compute-ready', check)
    check()
    const timer = window.setInterval(check, 4500)
    return () => {
      pending?.abort()
      window.clearInterval(timer)
      document.removeEventListener('vvoice-compute-ready', check)
    }
  }, [])
  const placement = placements.find(item => placementKey(item) === node)
  return { enabled, placements, canForce, node, setNode, placement, remote: node !== 'local', unavailable }
}

export function ExecutionNode({ target, busy, onChange }: {
  target: ReturnType<typeof useComputeTarget>; busy: boolean; onChange: () => void
}) {
  if (!target.enabled) return null
  return <Localized><label>执行节点<select aria-label="执行节点" value={target.node} disabled={busy}
    onChange={event => { target.setNode(event.target.value); onChange() }}>
    <option value="local">主节点（本机）</option>
    {target.placements.map(item => <option key={placementKey(item)} value={placementKey(item)}>
      {item.node_name || item.node_id} · {item.profile} · {item.model_id}
    </option>)}
    {target.remote && !target.placement ? <option value={target.node} disabled>所选部署已不可用</option> : null}
  </select>{target.unavailable ? <small role="status">分节点列表暂不可用，主节点仍可使用。</small> : null}</label></Localized>
}

export async function checkResponse(response: Response) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || error.code || String(response.status))
  }
}

export function executionLabel(receipt: Pick<VoicePlacement, 'node_id' | 'deployment_id' | 'executor_id'>, selected: VoicePlacement) {
  if (receipt.node_id !== selected.node_id || receipt.deployment_id !== selected.deployment_id || receipt.executor_id !== selected.executor_id) {
    throw new Error('执行回执与所选节点或执行器不一致。')
  }
  return selected.node_name ? `${selected.node_name} · ${receipt.node_id}` : receipt.node_id
}
