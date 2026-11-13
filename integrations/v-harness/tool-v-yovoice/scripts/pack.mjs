/** Package already built Host/Client artifacts without install-time scripts. */
import { readFile, writeFile, mkdir, cp, mkdtemp, rm, readdir } from 'node:fs/promises'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(packageRoot, '../../..')
const output = resolve(process.argv[2] ?? join(repoRoot, 'dist/v-yovoice'))
const manifest = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'))
const versions = new Map()
for (const group of ['packages', 'vendor']) {
  for (const entry of await readdir(join(repoRoot, group), { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const first = join(repoRoot, group, entry.name)
    const candidates = group === 'vendor' ? [first] : (await readdir(first, { withFileTypes: true })).filter(e => e.isDirectory()).map(e => join(first, e.name))
    for (const directory of candidates) {
      let data
      try { data = await readFile(join(directory, 'package.json'), 'utf8') }
      catch (error) { if (error.code === 'ENOENT') continue; throw error }
      const pkg = JSON.parse(data)
      versions.set(pkg.name, pkg.version)
    }
  }
}
for (const section of ['dependencies', 'peerDependencies']) {
  for (const [name, version] of Object.entries(manifest[section] ?? {})) {
    if (!version.startsWith('workspace:')) continue
    const exact = versions.get(name)
    if (!exact) throw new Error(`No workspace version for ${name}`)
    manifest[section][name] = section === 'peerDependencies' && name.startsWith('@deepseek-ai/dsh-') ? manifest.engines.dsh : section === 'peerDependencies' && ['@deepseek-ai/cordis', '@deepseek-ai/schemastery'].includes(name) ? `^${exact}` : exact
  }
}
delete manifest.devDependencies
delete manifest.scripts
const required = ['lib/index.js', 'lib/client.js', 'lib/typert.host.js', 'lib/typert.remote-client.js', 'lib/types/index.d.ts', 'lib/typert.remote-client.d.ts']
for (const path of required) await readFile(join(packageRoot, path))
await mkdir(output, { recursive: true })
const stage = await mkdtemp(join(output, '.pack-'))
try {
  const target = join(stage, 'package')
  await mkdir(target)
  await cp(join(packageRoot, 'lib'), join(target, 'lib'), {
    recursive: true,
    filter: source => !source.endsWith('.js.map') && !source.endsWith('.tsbuildinfo'),
  })
  // The CSS bundler annotates virtual modules with its absolute build directory.
  async function cleanBuildAnnotations(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await cleanBuildAnnotations(path)
      else if (entry.name.endsWith('.js')) {
        const text = (await readFile(path, 'utf8')).replace(/^\s*\/\/#region \\0dsh-css:[^\r\n]*/gmu, '\n//#region v-yovoice-plugin-css')
        if (text.includes(repoRoot)) throw new Error(`Build directory remains in ${entry.name}`)
        await writeFile(path, text)
      }
    }
  }
  await cleanBuildAnnotations(join(target, 'lib'))
  for (const file of ['cordis.patch.yml', 'README.md', 'README.zh.md']) await cp(join(packageRoot, file), join(target, file))
  await cp(join(packageRoot, 'LICENSE'), join(target, 'LICENSE'))
  await writeFile(join(target, 'package.json'), JSON.stringify(manifest, null, 2) + '\n')
  if (JSON.stringify(manifest).includes('workspace:')) throw new Error('Unresolved workspace spec')
  const filename = `ictrek-dsh-tool-v-yovoice-${manifest.version}.tgz`
  const archive = join(output, filename)
  execFileSync('tar', ['-czf', archive, '-C', stage, 'package'], {
    env: { ...process.env, COPYFILE_DISABLE: '1' },
  })
  const digest = createHash('sha256').update(await readFile(archive)).digest('hex')
  await writeFile(`${archive}.sha256`, `${digest}  ${filename}\n`)
  process.stdout.write(`${archive}\n${digest}\n`)
} finally { await rm(stage, { recursive: true, force: true }) }
