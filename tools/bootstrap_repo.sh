#!/usr/bin/env bash
# Bootstrap del repositorio showpatch (repo personal, sin organización).
# Requiere: gh CLI autenticado con scope repo.
# Uso: OTHER_OWNER=<usuario-github> bash tools/bootstrap_repo.sh

set -euo pipefail

REPO_NAME="${REPO_NAME:-showpatch}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/5] Verificando gh CLI..."
gh auth status || { echo "Ejecuta 'gh auth login' primero"; exit 1; }

echo "[2/5] Inicializando git local..."
cd "$ROOT"
if [ ! -d .git ]; then
    git init -b main
fi

echo "[3/5] Primer commit..."
git add .
git -c user.name="ShowPatch" -c user.email="bootstrap@showpatch.local" \
    commit -m "chore: freeze unified_show-1.0.0 + contract test suite" || true

echo "[4/5] Creando repo público en GitHub..."
gh repo create "$REPO_NAME" --public --source=. --push \
    --description "ShowPatch — Automatización IA para consolas de iluminación" \
    || echo "(repo ya existe, continuando)"

echo "[5/5] Creando tag v1.0.0..."
git tag -a v1.0.0 -m "Contrato congelado v1.0.0" || true
git push origin v1.0.0 || true

echo
echo "✅ Repo: https://github.com/$(gh api user -q .login)/$REPO_NAME"
echo "✅ SHA:  $(git rev-parse HEAD)"
echo
echo "Próximos pasos:"
echo "  1. python tools/contract_test.py --verbose"
echo "  2. Proteger rama main: Settings → Branches → Add rule"
echo "  3. Activar Actions si no está activo por defecto"
