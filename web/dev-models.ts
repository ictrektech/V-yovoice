import type { IncomingMessage, ServerResponse } from 'node:http';
import { GatewayError, gatewayModels } from './dev-gateway.ts';

type ModelFile = { path: string; size?: number; downloaded?: boolean };
type SupportedModel = {
  key: string; name: string; kind: string; modelscope_repo: string; import_required?: boolean;
  required_files: ModelFile[]; shared_files?: ModelFile[];
};
type HubRow = { model_id: string; status?: string; phase?: string; files?: string[]; task_id?: string;
  progress?: number; downloaded_bytes?: number; total_bytes?: number; error_msg?: string };
type Config = { base: string; token: string };
const clean = (id: string) => id.replace(/^(ms|hf):\/\//, '');
const active = (task: HubRow) => ['PENDING', 'DOWNLOADING', 'VERIFYING'].includes(task.phase ?? '');

export function taskMatches(model: SupportedModel, task: HubRow) {
  return clean(task.model_id) === model.modelscope_repo && (!model.shared_files || !task.files?.length ||
    model.shared_files.some(file => task.files!.includes(file.path)));
}

export function modelManagement(hub: Config, gateway: Config, catalog: { speech: SupportedModel[]; creative: SupportedModel[] }) {
  async function request(path: string, body?: unknown) {
    let response: Response;
    try { response = await fetch(hub.base + '/api/v1' + path, { method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(hub.token ? { Authorization: `Bearer ${hub.token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30_000), redirect: 'error' }); }
    catch { throw new GatewayError(502, '无法连接 V-Scheduler 模型仓库，请检查 MODEL_HUB_API_URL。'); }
    let value;
    try { value = await response.json(); } catch { throw new GatewayError(502, 'V-Scheduler 模型仓库响应无效。'); }
    if (!response.ok) throw new GatewayError(response.status, typeof value.detail === 'string' ? value.detail : `模型仓库请求失败（HTTP ${response.status}）。`);
    return value;
  }
  async function inventory(supported: SupportedModel[]) {
    let gatewayError = '';
    const services = await gatewayModels(gateway).catch(error => { gatewayError = error instanceof Error ? error.message : '模型网关不可用'; return []; });
    let models: HubRow[] = [], tasks: HubRow[] = [], storageError = '';
    try { [models, tasks] = await Promise.all([request('/models?status=all'), request('/tasks')]);
      if (!Array.isArray(models) || !Array.isArray(tasks)) throw new Error('模型仓库目录格式无效。'); }
    catch (error) { models = []; tasks = []; storageError = error instanceof Error ? error.message : '模型仓库不可用'; }
    const files = new Map<string, ModelFile[] | undefined>();
    await Promise.all([...new Set(supported.map(model => model.modelscope_repo))].map(async repo => {
      if (!models.some(model => clean(model.model_id) === repo)) { files.set(repo, []); return; }
      try { const value = await request(`/models/files?model_id=${encodeURIComponent('ms://' + repo)}`);
        files.set(repo, Array.isArray(value.files) ? value.files : undefined); }
      catch { files.set(repo, undefined); }
    }));
    return supported.map(model => {
      const listed = files.get(model.modelscope_repo);
      const prepared = !!listed && model.required_files.length > 0 && model.required_files.every(required => listed.some(file =>
        file.downloaded && (file.path === required.path || file.path.startsWith(required.path + '/')) &&
        (required.size === undefined || file.size === required.size)));
      const service = services.find(row => (row.qualified ?? row.id) === `v-voice/${model.key}`);
      const task = tasks.find(row => taskMatches(model, row));
      const relatedFailure = task?.phase === 'FAILED' && (!model.shared_files ||
        task.files?.some(path => model.shared_files!.some(file => file.path === path)) ||
        listed?.some(file => model.shared_files!.some(required => required.path === file.path)));
      const status = service ? 'ready' : task && active(task) ? 'downloading' : prepared ? 'downloaded'
        : storageError || listed === undefined ? 'unknown' : relatedFailure ? 'failed' : 'not_installed';
      return { ...model, status, files_ready: prepared, callable: !!service, inference_key: service?.qualified ?? service?.id,
        loaded: false, progress: task?.progress, downloaded_bytes: task?.downloaded_bytes, total_bytes: task?.total_bytes,
        service_error: gatewayError, error: storageError || (listed === undefined ? '无法核对平台模型文件。' : relatedFailure ? task?.error_msg : '') };
    });
  }
  async function pull(model: SupportedModel, force: boolean) {
    if (model.import_required) throw new GatewayError(409, '此模型需管理员提供原始权重，不能自动下载。');
    const payload = { source: 'ms', model_id: model.modelscope_repo, name: model.name, force: model.shared_files ? false : force,
      ...(model.shared_files ? { files: model.shared_files.map(file => file.path), append: true } : {}) };
    if (model.shared_files && force) {
      try { return await request(`/models/update?model_id=${encodeURIComponent('ms://' + model.modelscope_repo)}`, {}); }
      catch (error) { if (!(error instanceof GatewayError && error.status === 400 && error.message.includes('only ready models'))) throw error; }
    }
    try { return await request('/models/pull', payload); }
    catch (error) {
      if (model.shared_files && error instanceof GatewayError && error.status === 400 && error.message.includes('append requires a ready model')) {
        delete payload.append;
        return request('/models/pull', payload);
      }
      throw error;
    }
  }
  return async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    const management = url.pathname.match(/^\/api\/v1\/models\/([^/]+)\/(pull|stop|unload)$/);
    if (!['/api/v1/models', '/api/v1/creative-models'].includes(url.pathname) && !management) { next(); return; }
    const send = (status: number, value: unknown) => res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }).end(JSON.stringify(value));
    try {
      if (req.method === 'GET' && !management) { send(200, await inventory(url.pathname.includes('creative-') ? catalog.creative : catalog.speech)); return; }
      if (req.method !== 'POST' || !management) throw new GatewayError(405, '此模型管理操作不支持该请求方式。');
      const model = [...catalog.speech, ...catalog.creative].find(model => model.key === decodeURIComponent(management[1]));
      if (!model) throw new GatewayError(404, '不支持的模型。');
      if (management[2] === 'unload') throw new GatewayError(501, '推理实例由平台服务管理，本页仅管理平台模型文件。');
      if (management[2] === 'pull') { send(202, await pull(model, url.searchParams.get('force') === 'true')); return; }
      const tasks: HubRow[] = await request('/tasks');
      const matches = tasks.filter(task => active(task) && taskMatches(model, task));
      for (const task of matches) {
        if (!task.task_id) throw new GatewayError(502, '平台下载任务缺少任务 ID。');
        await request(`/tasks/${encodeURIComponent(task.task_id)}/cancel`, {});
      }
      send(200, { status: matches.length ? 'cancelled' : 'not_running', tasks: matches.map(task => task.task_id) });
    } catch (error) {
      send(error instanceof GatewayError ? error.status : 502, { detail: error instanceof GatewayError ? error.message : '平台模型管理响应无效。' });
    }
  };
}
