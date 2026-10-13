#!/bin/bash
# Publishes the control panel to the public repository that GitHub Pages serves. Only the page files go
# there (no bot code, no data, no keys). Needs that repository's deploy key on this computer: see
# docs/GUIDE.md, "Control panel". Usage: panel/publish.sh
set -euo pipefail

REPO="${PANEL_REPO:-git@github.com:breme-analytics/youtube-automation-panel.git}"
KEY="${PANEL_KEY:-$HOME/.ssh/youtube_automation_panel_deploy}"
SITE="${PANEL_SITE:-https://breme-analytics.github.io/youtube-automation-panel/}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# This key only, whatever this repository's own git settings say.
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes"

if [ -n "$(git ls-remote "$REPO" HEAD 2>/dev/null)" ]; then
  git clone -q --depth 1 "$REPO" "$WORK/site"
else
  git init -q -b main "$WORK/site"
  git -C "$WORK/site" remote add origin "$REPO"
fi

cp "$HERE/index.html" "$HERE/panel.css" "$HERE/panel.js" "$HERE/page.js" "$WORK/site/"
cp "$HERE/PUBLIC-README.md" "$WORK/site/README.md"
touch "$WORK/site/.nojekyll"   # serve the files as they are

cd "$WORK/site"
git add index.html panel.css panel.js page.js README.md .nojekyll
if git diff --cached --quiet; then
  echo "Nothing changed: the published panel is already up to date."
  exit 0
fi
git -c user.name="breme-analytics" -c user.email="341067996+breme-analytics@users.noreply.github.com" \
  commit -q -m "Publish the control panel"
git push -q origin HEAD:main
echo "Published. Open $SITE (GitHub Pages can take a minute to update)."
