#!/usr/bin/env bash
# One-time setup: put ANCHOR autopilot on GitHub from your Mac.
# Creates the public repo Anchit-AI-Hustle/anchor-autopilot, pushes the code, switches on
# GitHub Pages (media host for Buffer) and starts the first daily drop. Until BUFFER_API_KEY is
# added as a repo secret, drops are released on the website and GitHub only (never on YouTube).
set -euo pipefail

REPO="Anchit-AI-Hustle/anchor-autopilot"
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nSTOPPED: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "git is not installed"
NAME="$(git config user.name || true)"
EMAIL="$(git config user.email || true)"
[ -n "$NAME" ] && [ -n "$EMAIL" ] || die "set your git identity first: git config --global user.name 'You' && git config --global user.email you@example.com"

step "Robot commits will be authored as $NAME <$EMAIL> (keeps Vercel deploying them)"
sed -i.bak -e "s|^  ROBOT_NAME: .*|  ROBOT_NAME: \"$NAME\"|" -e "s|^  ROBOT_EMAIL: .*|  ROBOT_EMAIL: \"$EMAIL\"|" .github/workflows/daily.yml
rm -f .github/workflows/daily.yml.bak

step "Committing"
if [ -d .git ]; then
  [ "$(git branch --show-current)" = "main" ] || git branch -M main
else
  git init -q -b main
fi
git add -A
git commit -q -m "ANCHOR autopilot v1: daily AI techno drop robot + anchor.anchit-tandon.com" \
  -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PjCiw5cvrb9nF4947Z925z" || echo "(nothing new to commit)"
git log --oneline -1

command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || {
  step "GitHub CLI (gh) not found or not logged in, so finish by hand:"
  echo "1) Create an EMPTY public repo: https://github.com/new  (owner Anchit-AI-Hustle, name anchor-autopilot, no README)"
  echo "2) Then run:"
  echo "   git remote add origin https://github.com/$REPO.git 2>/dev/null; git push -u origin main"
  echo "3) Repo Settings > Pages > Source: GitHub Actions"
  exit 2
}

if gh repo view "$REPO" >/dev/null 2>&1; then
  step "Repo $REPO already exists"
else
  step "Creating public repo $REPO"
  gh repo create "$REPO" --public \
    --description "ANCHOR: a new industrial hard techno track every day, fully automated (anchor.anchit-tandon.com)"
fi

PROTO="$(gh config get git_protocol -h github.com 2>/dev/null || true)"
if [ "$PROTO" = "ssh" ]; then URL="git@github.com:$REPO.git"; else URL="https://github.com/$REPO.git"; fi
if git remote get-url origin >/dev/null 2>&1; then git remote set-url origin "$URL"; else git remote add origin "$URL"; fi

step "Pushing to $URL"
if [ "$PROTO" = "ssh" ]; then
  git push -u origin main
else
  # 1st try: the GitHub CLI login. 2nd try: whatever git normally uses on this Mac. Never prompts.
  GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main \
    || GIT_TERMINAL_PROMPT=0 git push -u origin main \
    || die "push failed. If it mentions the 'workflow' scope, run: gh auth refresh -h github.com -s workflow  and run this script again"
fi
[ "$(git rev-parse HEAD)" = "$(git ls-remote origin refs/heads/main | cut -f1)" ] || die "push did not land on GitHub"
echo "   pushed $(git rev-parse --short HEAD) to https://github.com/$REPO"

step "Switching on GitHub Pages (source: GitHub Actions)"
if gh api -X POST "repos/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "repos/$REPO/pages" -f build_type=workflow >/dev/null 2>&1; then
  echo "   $(gh api "repos/$REPO/pages" --jq '"\(.build_type) -> \(.html_url)"')"
else
  echo "   Could not switch Pages on automatically: repo Settings > Pages > Source: GitHub Actions"
fi

step "Starting the first daily drop (website + GitHub release; YouTube waits for BUFFER_API_KEY)"
started=""
for i in $(seq 1 12); do
  if gh workflow run daily.yml --repo "$REPO" --ref main >/dev/null 2>&1; then started=1; break; fi
  sleep 5
done
[ -n "$started" ] || die "could not start the Daily drop workflow; open https://github.com/$REPO/actions"
sleep 8
gh run list --repo "$REPO" --limit 5 || true

echo
echo "DONE: https://github.com/$REPO"
echo "Runs: https://github.com/$REPO/actions"
