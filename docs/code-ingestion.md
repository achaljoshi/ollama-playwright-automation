# Code Repository Ingestion

> Index your application's source code into the knowledge base so the AI understands how the app is built.

---

## Why index code?

Jira tickets describe *what* to test. Confluence pages describe *how* things should work. Source code shows *how they actually work* — field names, validation rules, API contracts, error messages, constants, and component structure.

With code indexed:

- The AI knows the exact field names your React components expect
- It knows what HTTP status codes your C# controllers return for invalid input
- It can write assertions that match your actual error messages (not guesses)
- It understands the data flow between frontend form and backend API

---

## Supported Languages

| Extension | Language | What gets extracted |
|---|---|---|
| `.cs` | C# | Namespaces, classes, interfaces, methods with XML `///` doc comments |
| `.ts` `.tsx` | TypeScript / React | React components, custom hooks, exported functions, interfaces, API routes |
| `.js` `.jsx` | JavaScript / React | Same as TypeScript |
| `.py` `.go` `.java` `.kt` | Others | Sliding-window 80-line chunks |
| `.md` `.txt` | Documentation | Sliding-window 80-line chunks |

---

## Setup

### 1. Store Bitbucket credentials

```bash
oapw auth bitbucket --username your-bitbucket-username
# Bitbucket App Password: [hidden input]
```

**Getting a Bitbucket App Password:**
1. Go to **Bitbucket** → **Personal Settings** → **App Passwords**
2. Click **Create app password**
3. Enable: **Repositories: Read** (only permission needed)
4. Copy the generated password and paste it when prompted

### 2. Sync your repos

```bash
oapw kb sync \
  --repo https://bitbucket.org/workspace/backend-api \
  --repo https://bitbucket.org/workspace/frontend-app \
  --branch main \
  --username your-bitbucket-username
```

First sync clones the repos and indexes everything. Subsequent syncs are incremental.

---

## First Sync vs Incremental Sync

### First sync

```
Clone:   git clone {authenticated_url} .oapw/repos/backend-api/
Index:   Walk all files matching _INDEXABLE_EXTENSIONS
         Skip: node_modules, .git, bin, obj, dist, build, __pycache__, ...
         Skip: files > 300 KB (minified / generated)
Store:   cache.set("code", "last_sha:backend-api", current_sha)
```

### Incremental sync

On every subsequent `oapw kb sync --repo ...`:

```
Pull:    git pull origin main
Compare: current_sha == last_sha?  → no changes, skip
Diff:    git diff --name-only {last_sha} {current_sha}
Index:   Only process changed files
Store:   cache.set("code", "last_sha:backend-api", current_sha)
```

A 1000-file repo re-syncs in seconds when only 3 files changed.

---

## What Each Chunk Contains

### C# method chunk

```
[CSHARP] AuthController.cs — Login
Namespace: MyApp.Controllers
Class: AuthController
Method: Login(LoginRequest request)

/// <summary>Authenticate a user and return a JWT token.</summary>
/// <param name="request">Login credentials</param>
/// <returns>JWT token or 401 Unauthorized</returns>
public async Task<IActionResult> Login([FromBody] LoginRequest request)
{
    if (!ModelState.IsValid)
        return BadRequest(ModelState);
    var result = await _authService.AuthenticateAsync(request.Email, request.Password);
    if (!result.Success)
        return Unauthorized(new { message = "Invalid credentials" });
    return Ok(new { token = result.Token, expiresIn = 3600 });
}
```

### TypeScript React component chunk

```
[TYPESCRIPT] LoginForm.tsx — LoginForm
Type: React Component

interface LoginFormProps {
  onSuccess: (token: string) => void;
  redirectUrl?: string;
}

export const LoginForm: React.FC<LoginFormProps> = ({ onSuccess, redirectUrl }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  // ...
}
```

### TypeScript custom hook chunk

```
[TYPESCRIPT] useAuth.ts — useAuth
Type: Custom Hook

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const login = useCallback(async (email: string, password: string) => {
    const response = await fetch('/api/auth/login', { ... });
    // ...
  }, []);

  return { user, loading, login, logout };
}
```

---

## Programmatic Usage

```python
from oapw.enterprise.code_ingest import CodeIngestor

ingestor = CodeIngestor()

# Add repos (can mix public and private)
ingestor.add_repo(
    "https://bitbucket.org/workspace/backend-api",
    branch="develop",
    username="your-username",   # triggers keyring credential lookup
)
ingestor.add_repo(
    "https://bitbucket.org/workspace/frontend-app",
    branch="main",
    username="your-username",
)

# Sync (sequential)
results = await ingestor.sync_all()
for r in results:
    print(f"{r.repo_name}: {r.files_indexed} files, {r.chunks_added} chunks")
    if r.errors:
        print(f"  ⚠ {r.errors} errors")
```

### Local repos (already cloned)

```python
from pathlib import Path
from oapw.enterprise.code_ingest import CodeIngestor, RepoConfig

ingestor = CodeIngestor()
ingestor._repos.append(RepoConfig(
    url="https://github.com/your-org/backend",
    name="backend",
    local_path=Path("/path/to/already/cloned/backend"),
))
results = await ingestor.sync_all()
```

### Parse files directly

```python
from oapw.enterprise.code_parser import parse_file, parse_csharp, parse_typescript

# Parse a single file
chunks = parse_file(
    path=Path("AuthController.cs"),
    repo_name="backend-api",
    repo_url="https://bitbucket.org/workspace/backend-api",
)

for chunk in chunks:
    print(f"{chunk.chunk_type}: {chunk.name} ({chunk.line_start}-{chunk.line_end})")
    print(chunk.text[:200])
    print()
```

---

## Searching Code in the Knowledge Base

```python
from oapw.knowledge.rag import RAGRetriever

retriever = RAGRetriever()

# Find code related to login
snippets = await retriever.retrieve(
    "login authentication JWT token",
    source_filter="code",
    top_k=5,
)

for s in snippets:
    print(f"[{s.metadata.get('language', '?').upper()}] "
          f"{s.metadata.get('file_path', '?')} — {s.title}")
    print(f"  Score: {s.score:.2f}")
    print(f"  Type:  {s.metadata.get('chunk_type', '?')}")
```

---

## Clearing Code from the Knowledge Base

```bash
# Clear everything (all sources)
oapw kb clear --yes

# Then re-sync just code
oapw kb sync --repo https://bitbucket.org/workspace/backend-api --username user
```

Programmatically clear a specific repo:

```python
from oapw.enterprise.code_ingest import CodeIngestor

ingestor = CodeIngestor()
ingestor.clear_repo("backend-api")   # removes all chunks for this repo
```

---

## Supported File Types Detail

### C# (`.cs`)

Regex-based extraction (no external C# toolchain needed):

| Pattern | Extracted |
|---|---|
| `namespace Foo.Bar` | Namespace context |
| `public class AuthController` | Class chunk |
| `public interface IAuthService` | Interface chunk |
| `public async Task<IActionResult> Login(...)` | Method chunk |
| `/// <summary>...</summary>` | XML doc comments included |

### TypeScript / TSX / JavaScript / JSX

| Pattern | Extracted |
|---|---|
| `export const LoginForm: React.FC` | React component (uppercase name) |
| `export function useAuth()` | Custom hook (`use*` prefix) |
| `export function fetchUser()` | Exported function |
| `export interface LoginFormProps` | Interface / type definition |
| `router.get('/api/...', handler)` | Express API route |
| `/** JSDoc */` | JSDoc comments included |

### Generic (all other indexable files)

- 80-line sliding window
- 20-line overlap between consecutive chunks
- Chunk ID includes line range: `{repo}:{file_path}#L{start}-{end}`

---

## Configuration

```env
# No specific env vars for code ingestion
# Uses standard data dir for repo storage and cache
OAPW_DATA_DIR=.oapw

# Repos cloned under:
# .oapw/repos/{repo_slug}/
```

Tunable constants in `code_ingest.py` (edit source if needed):

| Constant | Default | Description |
|---|---|---|
| `_MAX_FILE_BYTES` | `300_000` | Skip files larger than this (300 KB) |
| `_BATCH_SIZE` | `20` | ChromaDB upsert batch size |
| `_SKIP_DIRS` | see source | Directories to skip entirely |
| `_INDEXABLE_EXTENSIONS` | see source | File extensions to index |

---

## Troubleshooting

### "Authentication failed" when cloning

```bash
# Verify the credential is stored
python -c "import keyring; print(keyring.get_password('oapw-bitbucket', 'your-username'))"

# Re-store it
oapw auth bitbucket --username your-username
```

### "Failed to clone" with a public repo

Public repos don't need credentials. Pass the URL directly without `--username`:

```bash
oapw kb sync --repo https://github.com/your-org/public-repo
```

### Repo is up to date but new files aren't indexed

The incremental sync compares git SHAs. If the SHA didn't change (e.g., you checked out the same commit), no files are reprocessed. To force a full re-index:

```python
from oapw.cache.manager import get_cache
get_cache().delete("code", "last_sha:your-repo-name")
```

Then run `oapw kb sync --repo ...` again.

### ChromaDB not installed

```
RuntimeError: chromadb is not installed
```

Install with extras:

```bash
poetry install --extras knowledge
```
