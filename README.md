# GitPkg (self-hosted)

Install npm packages from GitHub monorepo subdirectories. A self-hosted alternative to [gitpkg.now.sh](https://github.com/EqualMa/gitpkg).

## Usage

```bash
npm install https://your-server/user/repo/packages/pkg?commit-ish
```

Full GitHub URL format is also supported:

```bash
npm install https://your-server/https://github.com/user/repo/tree/commit-ish/packages/pkg
```

If no commit is specified, defaults to `main`.

## Deploy

```bash
cp .env.example .env  # set your domain
docker compose up -d
```
