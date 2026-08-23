'use strict'

// Antora extension: mark named versions as prereleases.
//
// Antora sends the site's start page to the first version that is not a
// prerelease, so by default the moving branch wins and every release is
// buried in the version menu.  Marking `main` as a prerelease inverts that:
// a visitor lands on the newest release, while main and every older release
// stay one click away in the version selector.
//
// Before the first release exists there is nothing else to land on, and
// Antora falls back to the newest version -- main.  So this is safe to
// enable in a repository that has never been tagged.
//
// Antora offers no playbook key for this: `prerelease` can only be set in
// antora.yml, which is shared with every tag cut from the branch.  Setting
// it here keeps the flag with the version policy, in the playbook.
//
// Configured in antora-playbook.yml:
//
//   antora:
//     extensions:
//       - require: ./docs/extensions/prerelease_versions.js
//         versions: [main]

module.exports.register = function ({ config }) {
  const versions = config.versions || []
  if (!versions.length) return

  this.once('contentAggregated', ({ contentAggregate }) => {
    for (const bucket of contentAggregate) {
      if (versions.includes(bucket.version)) bucket.prerelease = true
    }
  })
}
