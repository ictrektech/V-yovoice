/** Build the DSH plugin against an explicitly pinned v-harness checkout. */
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, lstat, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const voiceRoot = resolve(packageRoot, '../../..')
const output = join(voiceRoot, 'dist/dsh-plugin')
const manifest = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'))
const compatibility = JSON.parse(await readFile(join(packageRoot, 'harness-compatibility.json'), 'utf8'))
const expected = compatibility.target
const harnessRepo = resolve(process.env.V_HARNESS_REPO ?? '')
const allowDirty = process.argv.includes('--allow-dirty')
const allowPluginDirty = process.argv.includes('--allow-plugin-dirty')
const destinationRelative = 'packages/skill/tool-audio-transcription'
const destination = join(harnessRepo, destinationRelative)
const markerName = '.v-yovoice-generated-build'
const markerValue = `${manifest.name}@${manifest.version}:${expected.commit}\n`
const generated = []
const originalFiles = new Map()
let cleaning = false

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' }).trim()
}

function run(command, args, options = {}) {
  process.stdout.write(`\n$ ${[command, ...args].join(' ')}\n`)
  execFileSync(command, args, {
    cwd: options.cwd ?? harnessRepo,
    env: { ...process.env, ...options.env },
    stdio: 'inherit',
  })
}

async function exists(path) {
  try {
    await lstat(path)
    return true
  } catch (error) {
    if (error.code === 'ENOENT') return false
    throw error
  }
}

async function walk(directory) {
  const paths = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) paths.push(...await walk(path))
    else paths.push(path)
  }
  return paths
}

async function replaceHarnessFile(path, update) {
  if (!originalFiles.has(path)) originalFiles.set(path, await readFile(path, 'utf8'))
  const current = await readFile(path, 'utf8')
  await writeFile(path, update(current))
}

async function prepareHarness() {
  await replaceHarnessFile(join(harnessRepo, 'tsconfig.base.json'), (text) => {
    if (text.includes('"@deepseek-ai/dsh-tool-audio-transcription"')) return text
    const anchor = '      "@deepseek-ai/dsh-skill":'
    if (!text.includes(anchor)) throw new Error('pinned v-harness tsconfig.base.json lacks the skill path anchor')
    const paths = [
      '      "@deepseek-ai/dsh-tool-audio-transcription": ["./packages/skill/tool-audio-transcription/src/index.ts"],',
      '      "@deepseek-ai/dsh-tool-audio-transcription/client": ["./packages/skill/tool-audio-transcription/src/client/index.ts"],',
      '      "@deepseek-ai/dsh-tool-audio-transcription/types": ["./packages/skill/tool-audio-transcription/src/types.ts"],',
      '      "@deepseek-ai/dsh-tool-audio-transcription/remote": ["./packages/skill/tool-audio-transcription/lib/typert.remote-client.d.ts"],',
    ].join('\n')
    return text.replace(anchor, `${paths}\n${anchor}`)
  })
  for (const [name, face] of [['tsconfig.host.json', 'host'], ['tsconfig.client.json', 'client']]) {
    const reference = `./packages/skill/tool-audio-transcription/tsconfig.${face}.json`
    await replaceHarnessFile(join(harnessRepo, name), (text) => {
      if (text.includes(`"path": "${reference}"`)) return text
      const anchor = '  "references": [\n'
      if (!text.includes(anchor)) throw new Error(`pinned v-harness ${name} lacks the references anchor`)
      return text.replace(anchor, `${anchor}    { "path": "${reference}" },\n`)
    })
  }
  const importer = await readFile(join(packageRoot, 'scripts/pnpm-lock-importer.yaml'), 'utf8')
  await replaceHarnessFile(join(harnessRepo, 'pnpm-lock.yaml'), lockfile => installLockfileImporter(lockfile, importer))
}

async function auditArchive(archive) {
  const entries = execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split('\n')
  const sourceEntries = entries.filter(entry => entry.startsWith('package/src/') || entry.startsWith('package/scripts/'))
  const sourceFiles = entries.filter(entry => entry.endsWith('.ts') && !entry.endsWith('.d.ts'))
  if (sourceEntries.length > 0 || sourceFiles.length > 0) {
    throw new Error(`Archive contains source entries:\n${[...sourceEntries, ...sourceFiles].join('\n')}`)
  }

  const staging = await mkdtemp(join(output, '.audit-'))
  try {
    execFileSync('tar', ['-xzf', archive, '-C', staging], { stdio: 'inherit' })
    const stagedPackage = join(staging, 'package')
    const stagedManifest = JSON.parse(await readFile(join(stagedPackage, 'package.json'), 'utf8'))
    if (JSON.stringify(stagedManifest).includes('workspace:')) throw new Error('Archive contains an unresolved workspace specification')
    if (stagedManifest.devDependencies !== undefined) throw new Error('Archive contains development dependencies')
    if (stagedManifest.scripts !== undefined) throw new Error('Archive contains install or build scripts')
    if (Object.values(stagedManifest.exports ?? {}).some(value => JSON.stringify(value).includes('/src/'))) {
      throw new Error('Archive exports source files')
    }

    const forbidden = [
      harnessRepo,
      voiceRoot,
      output,
      packageRoot,
      '/Users/',
      '/home/czy/',
    ].filter(Boolean)
    for (const file of await walk(stagedPackage)) {
      if (!['.js', '.json', '.md', '.yml', '.yaml'].includes(file.slice(file.lastIndexOf('.')))) continue
      const text = await readFile(file, 'utf8')
      const found = forbidden.find(value => text.includes(value))
      if (found !== undefined) throw new Error(`Archive file ${relative(stagedPackage, file)} contains local path ${found}`)
    }
  } finally {
    await rm(staging, { recursive: true, force: true })
  }
}

function installLockfileImporter(lockfile, importer) {
  if (lockfile.includes('\n  packages/skill/tool-audio-transcription:\n')) return lockfile
  const anchor = '\n  packages/skill/tool-skill:\n'
  if (!lockfile.includes(anchor)) throw new Error('pinned v-harness lockfile lacks the tool-skill importer anchor')
  return lockfile.replace(anchor, `\n${importer.trimEnd()}\n${anchor}`)
}

async function cleanGenerated() {
  if (cleaning) return
  cleaning = true
  for (const path of generated.reverse()) {
    try {
      if ((await readFile(join(path, markerName), 'utf8')) === markerValue) {
        await rm(path, { recursive: true, force: true })
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
    }
  }
  for (const [path, text] of originalFiles) await writeFile(path, text)
}

for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143], ['SIGHUP', 129]]) {
  process.once(signal, () => {
    void cleanGenerated().finally(() => { process.exit(code) })
  })
}

if (process.env.V_HARNESS_REPO === undefined || process.env.V_HARNESS_REPO === '') {
  throw new Error('V_HARNESS_REPO must name a v-harness checkout')
}
if (!(await stat(harnessRepo)).isDirectory()) throw new Error(`V_HARNESS_REPO is not a directory: ${harnessRepo}`)

const actualCommit = git(harnessRepo, 'rev-parse', 'HEAD')
if (actualCommit !== expected.commit) {
  throw new Error(`v-harness commit mismatch: expected ${expected.commit}, found ${actualCommit}`)
}
const harnessDirty = git(harnessRepo, 'status', '--porcelain=v1', '--untracked-files=all') !== ''
if (harnessDirty && !allowDirty) {
  throw new Error('v-harness checkout is dirty; commit or clean it, or pass --allow-dirty for a non-release build')
}
const harnessPackage = JSON.parse(await readFile(join(harnessRepo, 'package.json'), 'utf8'))
if (harnessPackage.version !== compatibility.dshVersion) {
  throw new Error(`DSH version mismatch: expected ${compatibility.dshVersion}, found ${harnessPackage.version}`)
}
const harnessVersionFile = (await readFile(join(harnessRepo, 'ictrek.app/VERSION'), 'utf8')).trim()

const pluginCommit = git(voiceRoot, 'rev-parse', 'HEAD')
const pluginDirty = git(voiceRoot, 'status', '--porcelain=v1', '--untracked-files=all', '--', relative(voiceRoot, packageRoot)) !== ''
if (pluginDirty && !allowPluginDirty) {
  throw new Error('plugin source is dirty; commit it, or run build:candidate for a non-release build')
}
const releaseEligible = !harnessDirty && !pluginDirty

if (await exists(destination)) throw new Error(`Refusing to overwrite existing ${destination}`)
await mkdir(dirname(destination), { recursive: true })
await mkdir(output, { recursive: true })

try {
  await prepareHarness()
  await cp(packageRoot, destination, {
    recursive: true,
    filter(source) {
      const path = relative(packageRoot, source)
      return path === '' || !(
        path === '.git' || path === 'lib' || path.startsWith('lib/') || path === 'node_modules'
        || path.startsWith('node_modules/') || path === 'dist' || path.startsWith('dist/')
        || path === 'README.i18n.yaml' || path === '.npmrc' || path === 'pnpm-workspace.yaml'
      )
    },
  })
  await writeFile(join(destination, markerName), markerValue)
  generated.push(destination)

  run('pnpm', ['install', '--frozen-lockfile', '--ignore-scripts', ...(process.env.DSH_OFFLINE === '1' ? ['--offline'] : [])])
  run('pnpm', ['exec', 'vitest', 'run', destinationRelative + '/tests', '--maxWorkers', '2'])
  run('pnpm', ['run', 'build:artifacts'], {
    env: {
      DSH_CLIENT_COMMIT_HASH: expected.commit,
      DSH_BUILD_CLIENT_PROFILE: 'official',
    },
  })
  run('pnpm', ['exec', 'oxlint', destinationRelative])
  run('pnpm', ['run', 'build:check'])

  const archive = join(output, `deepseek-ai-dsh-tool-audio-transcription-${manifest.version}.tgz`)
  await rm(archive, { force: true })
  await rm(`${archive}.sha256`, { force: true })
  await rm(join(output, 'compatibility.json'), { force: true })
  run(process.execPath, [join(destination, 'scripts/pack.mjs'), output], {
    env: { DSH_CLIENT_COMMIT_HASH: expected.commit, DSH_BUILD_CLIENT_PROFILE: 'official' },
  })
  await auditArchive(archive)

  const digest = createHash('sha256').update(await readFile(archive)).digest('hex')
  const releaseManifest = {
    plugin: manifest.name,
    version: manifest.version,
    releaseTag: `harness-plugin-v${manifest.version}`,
    archive: archive.slice(output.length + 1),
    sha256: digest,
    dshVersion: compatibility.dshVersion,
    supportedDshVersions: compatibility.supportedDshVersions,
    targetVHarness: {
      release: expected.release,
      commit: actualCommit,
      checkoutVersion: harnessVersionFile,
      sourceDirty: harnessDirty,
    },
    pluginSource: {
      commit: pluginCommit,
      dirty: pluginDirty,
    },
    build: {
      node: process.version,
      platform: process.platform,
      architecture: process.arch,
    },
    releaseEligible,
  }
  await writeFile(join(output, 'compatibility.json'), JSON.stringify(releaseManifest, null, 2) + '\n')
  process.stdout.write(`\nArchive: ${archive}\nSHA256: ${digest}\nRelease eligible: ${releaseEligible}\n`)
} finally {
  await cleanGenerated()
}
