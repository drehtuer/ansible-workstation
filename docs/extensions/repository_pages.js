'use strict'

// Antora extension: publish .adoc files that live outside the component.
//
// README.adoc is the repository's front page on GitHub and CLAUDE.adoc is
// read by the coding assistants, so neither can move into
// docs/modules/ROOT/pages/.  Copying them there would create a second
// source of truth that drifts.  Instead this extension reads them at build
// time and adds them to the content aggregate as if they had always been
// pages of the ROOT module.
//
// Configured in antora-playbook.yml:
//
//   antora:
//     extensions:
//       - require: ./docs/extensions/repository_pages.js
//         pages:
//           - source: README.adoc      # relative to the playbook directory
//             target: index.adoc       # relative to modules/ROOT/pages/

const { execFile } = require('node:child_process')
const fs = require('node:fs/promises')
const ospath = require('node:path')

const PAGES_PREFIX = 'modules/ROOT/pages/'

module.exports.register = function ({ config }) {
  const pages = config.pages || []
  if (!pages.length) return

  this.once('contentAggregated', async ({ playbook, contentAggregate }) => {
    for (const bucket of contentAggregate) {
      const origin = bucket.origins[bucket.origins.length - 1]
      for (const { source, target } of pages) {
        if (!source || !target) {
          throw new Error(
            'repository_pages: every entry needs a source and a target'
          )
        }
        const contents = await read(origin, source)
        bucket.files.push(createPage(source, target, contents, origin))
      }
    }
  })
}

// Where the file is read from depends on the ref being built.  The current
// worktree is on disk, so uncommitted edits show up; a release tag is not,
// so its content has to come out of the object database.  Reading a tag's
// page off disk would publish today's README as the documentation of an old
// release, which is the whole failure this indirection avoids.
function read (origin, source) {
  return origin.worktree
    ? readWorktree(ospath.join(origin.worktree, source), source)
    : readRef(origin, source)
}

// Say which playbook entry is wrong -- the default ENOENT names neither.
async function readWorktree (abspath, source) {
  try {
    return await fs.readFile(abspath)
  } catch (err) {
    throw new Error(`repository_pages: cannot read ${source}: ${err.message}`)
  }
}

function readRef (origin, source) {
  const ref = origin.refhash || origin.refname
  const args = ['--git-dir', origin.gitdir, 'show', `${ref}:${source}`]
  const opts = { encoding: 'buffer', maxBuffer: 16 * 1024 * 1024 }
  return new Promise((resolve, reject) => {
    execFile('git', args, opts, (err, stdout, stderr) => {
      if (!err) return resolve(stdout)
      const detail =
        err.code === 'ENOENT'
          ? 'git is not on PATH'
          : String(stderr).trim() || err.message
      reject(
        new Error(
          `repository_pages: cannot read ${source} at ` +
            `${origin.refname}: ${detail}`
        )
      )
    })
  })
}

function createPage (source, target, contents, origin) {
  const path = PAGES_PREFIX + target
  const extname = ospath.extname(target)
  const src = {
    path,
    basename: ospath.basename(target),
    stem: ospath.basename(target, extname),
    extname,
    origin,
  }
  // The URL patterns were built for files under the component's start path
  // (docs/); these files sit above it, so put the real path back in.
  const prefix = origin && origin.startPath ? origin.startPath + '/' : ''
  for (const [key, pattern] of [
    ['editUrl', origin && origin.editUrlPattern],
    ['fileUri', origin && origin.fileUriPattern],
  ]) {
    if (pattern) src[key] = pattern.replace(prefix + '%s', source)
  }
  return { path, contents, src }
}
