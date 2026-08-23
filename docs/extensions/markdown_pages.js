'use strict'

// Antora extension: render Markdown pages with kramdoc.
//
// Antora itself reads AsciiDoc and nothing else, and drops every other file
// found under a pages/ directory.  Some files have to be Markdown anyway --
// GitHub only recognises its templates in that format, and files that arrive
// from elsewhere rarely arrive as AsciiDoc.
//
// This extension converts them before Antora classifies the content, so a
// .md page becomes an ordinary .adoc page of the same name.  Nothing is
// written back to the worktree: the conversion happens in memory.
//
// kramdoc is the CLI of the kramdown-asciidoc Ruby gem:
//
//   gem install kramdown-asciidoc
//
// Configured in antora-playbook.yml, *after* repository_pages.js so that a
// lent Markdown file is converted too:
//
//   antora:
//     extensions:
//       - require: ./docs/extensions/markdown_pages.js

const { spawn } = require('node:child_process')

const COMMAND = 'kramdoc'
// GFM, because that is what GitHub renders and what these files are written
// against.  --wrap=preserve keeps the source line breaks, so the 80-column
// cap survives the conversion.
const ARGS = ['--format=GFM', '--wrap=preserve', '-o', '-', '-']
const MARKDOWN_PAGE_RX = /^modules\/[^/]+\/pages\/.+\.md$/

module.exports.register = function () {
  const logger = this.getLogger('markdown-pages')

  this.once('contentAggregated', async ({ contentAggregate }) => {
    for (const bucket of contentAggregate) {
      for (const file of bucket.files) {
        if (!MARKDOWN_PAGE_RX.test(file.path)) continue
        const source = file.path
        file.contents = await convert(file.contents, source)
        rename(file)
        logger.info('converted %s to %s', source, file.path)
      }
    }
  })
}

// Rewrite the file in place as its AsciiDoc counterpart.  src.editUrl and
// src.fileUri are deliberately left alone: they point at the Markdown file,
// which is still the file a reader should edit.
function rename (file) {
  const path = file.path.slice(0, -'.md'.length) + '.adoc'
  const stem = path.slice(path.lastIndexOf('/') + 1, -'.adoc'.length)
  file.path = path
  Object.assign(file.src, {
    path,
    basename: stem + '.adoc',
    stem,
    extname: '.adoc',
  })
}

function convert (contents, source) {
  return new Promise((resolve, reject) => {
    const child = spawn(COMMAND, ARGS)
    const out = []
    const err = []
    child.on('error', (cause) => {
      const hint =
        cause.code === 'ENOENT'
          ? `${COMMAND} is not on PATH -- gem install kramdown-asciidoc`
          : cause.message
      reject(new Error(`markdown_pages: cannot convert ${source}: ${hint}`))
    })
    child.stdout.on('data', (chunk) => out.push(chunk))
    child.stderr.on('data', (chunk) => err.push(chunk))
    child.on('close', (code) => {
      if (code === 0) return resolve(Buffer.concat(out))
      const detail = Buffer.concat(err).toString().trim() || `exit ${code}`
      reject(
        new Error(`markdown_pages: ${COMMAND} failed on ${source}: ${detail}`)
      )
    })
    child.stdin.end(contents)
  })
}
