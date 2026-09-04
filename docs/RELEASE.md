# Release Runbook

`sot-graph` releases are fully automated from a git tag. There is exactly one
manual, one-time setup step (PyPI trusted-publisher registration); everything
afterwards is `git tag && git push --tags`.

## One-time setup (owner only)

Register the trusted publisher on PyPI so GitHub Actions can publish without
any stored credentials:

1. Sign in at <https://pypi.org> with the account that owns (or will create)
   the `sot-graph` project.
2. If the project does not exist yet: **Add a new project → publish via
   trusted publisher**. If it exists: **Publishing → Add a new pending
   publisher** (or manage publishers in project settings).
3. Enter exactly:
   - **PyPI project name**: `sot-graph`
   - **Owner**: `minhgv`
   - **Repository**: `sot-graph`
   - **Workflow name**: `ci.yml`
   - **Environment name**: `pypi`
4. In the GitHub repo, create the `pypi` **environment**
   (Settings → Environments → New environment → `pypi`). It can have zero
   protection rules; the workflow references it for the trusted-publisher
   audience.

## Cutting a release

```bash
# 1. Bump __version__ in src/sot_graph/__init__.py — the single source of
#    truth; pyproject reads it dynamically ([tool.setuptools.dynamic]) and
#    every runtime surface falls back to it. Then make sure the working
#    tree is clean and pushed.
# 2. Tag and push:
git tag -a v0.3.1 -m "sot-graph 0.3.1"
git push origin main --follow-tags
```

Pushing the tag triggers `.github/workflows/ci.yml`:

| Job | What it does |
| :-- | :-- |
| `lint` / `test` / `accuracy-oracle` / `quality-gates` / `module-eval` / `real-cbm-e2e` / `package-smoke` | Full gate matrix (now including Python 3.13/3.14 and the accuracy oracle as a release dependency) |
| `release` | `uv build` + GitHub Release with artifacts and generated notes |
| `publish-pypi` | Rebuild + publish sdist/wheel to PyPI via OIDC trusted publishing (with attestations) |

All gates must pass — `release.needs` includes `accuracy-oracle`, and
`module-eval --strict-probes` fails closed on probe crashes.

## After the first release

- Flip the README "From PyPI" note (remove the "once the first `v*` tag is
  pushed" caveat).
- Add a `docs/RELEASE_NOTES_vX.Y.Z.md` for user-visible changes.
