/** 将已构建的 DSH 插件归档发布到 npm，并校验 registry 同步结果。 */
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const registry = 'https://registry.npmjs.org'
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const voiceRoot = resolve(packageRoot, '../../..')
const output = resolve(process.env.VVOICE_PLUGIN_OUTPUT ?? join(voiceRoot, 'dist/dsh-plugin'))
const manifest = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'))
const archive = join(output, `ictrek-dsh-tool-v-yovoice-${manifest.version}.tgz`)
const compatibilityPath = join(output, 'compatibility.json')
const packumentUrl = `${registry}/${manifest.name.replace('/', '%2f')}`
const pollIntervalMs = 15_000
const pollTimeoutMs = 15 * 60_000
const rerunCommand = `pnpm --dir ${relative(voiceRoot, packageRoot)} run publish:npm`

class PublishError extends Error {
  constructor(message, exitCode = 1) {
    super(message)
    this.exitCode = exitCode
  }
}

function log(message) {
  process.stdout.write(`[publish:npm] ${message}\n`)
}

function fail(message, exitCode = 1) {
  throw new PublishError(message, exitCode)
}

async function readArchive() {
  let bytes
  try {
    bytes = await readFile(archive)
  } catch (error) {
    if (error.code === 'ENOENT') fail(`未找到归档：${archive}\n请先执行 build:release。`)
    throw error
  }
  return {
    sha256: createHash('sha256').update(bytes).digest('hex'),
    integrity: `sha512-${createHash('sha512').update(bytes).digest('base64')}`,
  }
}

async function readCompatibility(archiveInfo) {
  let compatibility
  try {
    compatibility = JSON.parse(await readFile(compatibilityPath, 'utf8'))
  } catch (error) {
    if (error.code === 'ENOENT') fail(`未找到 compatibility.json：${compatibilityPath}\n请先执行 build:release。`)
    throw error
  }
  if (compatibility.plugin !== manifest.name) fail(`compatibility.plugin 不匹配：${compatibility.plugin}`)
  if (compatibility.version !== manifest.version) fail(`compatibility.version 不匹配：${compatibility.version}`)
  if (compatibility.releaseTag !== `harness-plugin-v${manifest.version}`) fail(`compatibility.releaseTag 不匹配：${compatibility.releaseTag}`)
  if (compatibility.archive !== basename(archive)) fail(`compatibility.archive 不匹配：${compatibility.archive}`)
  if (compatibility.sha256 !== archiveInfo.sha256) fail('compatibility.sha256 与本地归档不一致')
  if (compatibility.releaseEligible !== true) fail('compatibility.json 的 releaseEligible 不是 true')
  if (compatibility.pluginSource?.dirty) fail('构建插件源码时工作区不是干净的')
  if (compatibility.targetVHarness?.sourceDirty) fail('构建时锁定的 v-harness 工作区不是干净的')
}

function checkAuth() {
  const result = spawnSync('npm', ['whoami', '--registry', registry], { encoding: 'utf8' })
  if (result.error) return { ok: false, reason: result.error.message }
  if (result.status !== 0) {
    const reason = `${result.stderr ?? ''}\n${result.stdout ?? ''}`.trim().split('\n')
      .filter(line => line && !line.startsWith('npm warn '))
      .slice(0, 2)
      .join(' ')
    return {
      ok: false,
      authRequired: /E401|ENEEDAUTH|Unauthorized|need auth/i.test(reason),
      reason: reason || `npm whoami 退出码 ${result.status}`,
    }
  }
  return { ok: true, user: result.stdout.trim() }
}

async function readPackument() {
  const response = await fetch(packumentUrl, {
    cache: 'no-store',
    headers: { accept: 'application/json' },
    signal: AbortSignal.timeout(15_000),
  })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`registry metadata 请求失败：HTTP ${response.status}`)
  return response.json()
}

function getVersion(packument) {
  return packument?.versions?.[manifest.version]
}

async function tarballStatus(url) {
  try {
    const response = await fetch(url, {
      method: 'HEAD',
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    })
    return { ok: response.ok, status: response.status }
  } catch (error) {
    return { ok: false, status: null, error: error.message }
  }
}

async function waitForPublished(archiveInfo) {
  const started = Date.now()
  let attempt = 0
  let lastReason = 'version metadata 尚未出现'
  while (Date.now() - started < pollTimeoutMs) {
    attempt += 1
    try {
      const packument = await readPackument()
      const entry = getVersion(packument)
      if (!entry) {
        lastReason = 'version metadata 尚未出现'
      } else if (!entry.dist?.integrity) {
        lastReason = 'metadata 缺少 integrity'
      } else if (entry.dist.integrity !== archiveInfo.integrity) {
        fail(`registry integrity 与本地归档不一致：${entry.dist.integrity}`)
      } else if (!entry.dist?.tarball) {
        lastReason = 'metadata 缺少 tarball URL'
      } else {
        const tarball = await tarballStatus(entry.dist.tarball)
        if (!tarball.ok) {
          lastReason = tarball.status ? `tarball 返回 HTTP ${tarball.status}` : `tarball 请求失败：${tarball.error}`
        } else if (packument['dist-tags']?.latest !== manifest.version) {
          lastReason = `latest 当前指向 ${packument['dist-tags']?.latest ?? '空'}`
        } else {
          const elapsed = Math.round((Date.now() - started) / 1000)
          log(`已验证 ${manifest.name}@${manifest.version}，耗时 ${elapsed} 秒`)
          log(`tarball: ${entry.dist.tarball}`)
          log(`integrity: ${entry.dist.integrity}`)
          return
        }
      }
    } catch (error) {
      if (error instanceof PublishError) throw error
      lastReason = error.message
    }
    if (attempt === 1 || attempt % 4 === 0) {
      const elapsed = Math.round((Date.now() - started) / 1000)
      log(`等待 registry 同步（${elapsed} 秒）：${lastReason}`)
    }
    await new Promise(resolve => setTimeout(resolve, pollIntervalMs))
  }
  fail(`等待 ${manifest.name}@${manifest.version} 超过 15 分钟。\n不要重复发布；请检查 https://status.npmjs.org 后重新执行本脚本。\n最后状态：${lastReason}`)
}

function publish() {
  log(`发布 ${archive}`)
  log('若 npm 输出 auth URL，请在浏览器打开并确认；命令会继续等待，不要按 Ctrl+C。')
  const result = spawnSync('npm', [
    'publish', archive,
    '--registry', registry,
    '--access', 'public',
    '--tag', 'latest',
    '--browser=false',
  ], { stdio: 'inherit', env: process.env })
  if (result.error) throw result.error
  if (result.status !== 0) fail(`npm publish 退出码 ${result.status}`)
}

async function main() {
  const archiveInfo = await readArchive()
  await readCompatibility(archiveInfo)

  let packument
  try {
    packument = await readPackument()
  } catch (error) {
    fail(error.message)
  }
  if (getVersion(packument)) {
    log(`${manifest.name}@${manifest.version} 已存在，仅校验 registry，不重复发布`)
    const latest = packument['dist-tags']?.latest
    if (latest !== manifest.version) {
      fail(`${manifest.name}@${manifest.version} 已存在，但 latest 指向 ${latest ?? '空'}。\n不要重复发布；需要时执行：\n  npm dist-tag add ${manifest.name}@${manifest.version} latest --registry=${registry}`)
    }
    await waitForPublished(archiveInfo)
    return
  }

  const auth = checkAuth()
  if (auth.ok) log(`npm 用户：${auth.user}`)
  else log(`npm 登录不可用：${auth.reason}`)
  if (!auth.ok) {
    if (!auth.authRequired) fail(`npm whoami 失败：${auth.reason}`)
    fail(`发布 ${manifest.name}@${manifest.version} 需要 npm 登录。\n执行：\n  npm login --auth-type=web --browser=false --registry=${registry} --scope=${manifest.name.split('/')[0]}\n完成后重新执行：\n  ${rerunCommand}`, 2)
  }

  publish()
  await waitForPublished(archiveInfo)
}

try {
  await main()
} catch (error) {
  const message = error instanceof Error ? error.message : String(error)
  process.stderr.write(`[publish:npm] ${message}\n`)
  process.exit(error?.exitCode ?? 1)
}
