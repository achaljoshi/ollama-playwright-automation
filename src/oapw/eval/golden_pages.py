"""Canonical HTML page fixtures for the self-evaluation suite.

Each page is a self-contained HTML string. Pairs of (canonical, broken) variants
let the eval suite verify that healing restores correct element resolution.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoldenPage:
    name: str
    html: str
    intents: list[str]       # NL descriptions of elements that must be resolvable
    selectors: list[str]     # Expected CSS selectors (ground truth — for eval scoring)


# ── 1. Login form ─────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html><html><body>
<h1>Sign In</h1>
<form id="login-form">
  <label for="email">Email address</label>
  <input id="email" name="email" type="email" placeholder="Enter your email" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" placeholder="Enter your password" required>
  <button id="signin-btn" type="submit" data-testid="signin-btn">Sign in</button>
  <a href="/forgot">Forgot password?</a>
</form>
</body></html>"""

LOGIN_BROKEN_HTML = """<!DOCTYPE html><html><body>
<h1>Welcome Back</h1>
<form id="auth-form">
  <label for="user-email">Your Email</label>
  <input id="user-email" name="userEmail" type="email" placeholder="Email">
  <label for="user-pwd">Your Password</label>
  <input id="user-pwd" name="userPwd" type="password" placeholder="Password">
  <button id="login-submit" type="submit" data-testid="login-submit">Login</button>
  <a href="/reset">Forgot your password?</a>
</form>
</body></html>"""

LOGIN_PAGE = GoldenPage(
    name="login",
    html=LOGIN_HTML,
    intents=["Email address input", "Password input", "Sign in button", "Forgot password link"],
    selectors=["#email", "#password", "#signin-btn", "a[href='/forgot']"],
)

LOGIN_BROKEN_PAGE = GoldenPage(
    name="login_broken",
    html=LOGIN_BROKEN_HTML,
    intents=["Email address input", "Password input", "Sign in button", "Forgot password link"],
    selectors=["#user-email", "#user-pwd", "#login-submit", "a[href='/reset']"],
)


# ── 2. Search form ────────────────────────────────────────────────────────────

SEARCH_HTML = """<!DOCTYPE html><html><body>
<h1>Product Search</h1>
<form id="search-form">
  <label for="query">Search products</label>
  <input id="query" name="q" type="search" placeholder="Type to search...">
  <button id="search-btn" type="submit">Search</button>
</form>
</body></html>"""

SEARCH_BROKEN_HTML = """<!DOCTYPE html><html><body>
<h2>Find Products</h2>
<div class="search-container">
  <label for="search-input">Search</label>
  <input id="search-input" name="query" type="text" placeholder="What are you looking for?">
  <button class="btn-find" type="submit" aria-label="Find products">Find</button>
</div>
</body></html>"""

SEARCH_PAGE = GoldenPage(
    name="search",
    html=SEARCH_HTML,
    intents=["Search input", "Search button"],
    selectors=["#query", "#search-btn"],
)

SEARCH_BROKEN_PAGE = GoldenPage(
    name="search_broken",
    html=SEARCH_BROKEN_HTML,
    intents=["Search input", "Search button"],
    selectors=["#search-input", ".btn-find"],
)


# ── 3. Registration form ──────────────────────────────────────────────────────

REGISTRATION_HTML = """<!DOCTYPE html><html><body>
<h1>Create Account</h1>
<form id="register-form">
  <label for="first-name">First name</label>
  <input id="first-name" name="firstName" type="text" placeholder="First name" required>
  <label for="last-name">Last name</label>
  <input id="last-name" name="lastName" type="text" placeholder="Last name" required>
  <label for="reg-email">Email</label>
  <input id="reg-email" name="email" type="email" placeholder="Email address" required>
  <label for="reg-password">Password</label>
  <input id="reg-password" name="password" type="password" placeholder="Create a password" required>
  <button id="register-btn" type="submit">Create account</button>
</form>
</body></html>"""

REGISTRATION_PAGE = GoldenPage(
    name="registration",
    html=REGISTRATION_HTML,
    intents=[
        "First name input", "Last name input", "Email input",
        "Password input", "Create account button",
    ],
    selectors=[
        "#first-name", "#last-name", "#reg-email",
        "#reg-password", "#register-btn",
    ],
)


# ── 4. Product listing ────────────────────────────────────────────────────────

PRODUCT_HTML = """<!DOCTYPE html><html><body>
<h1>Our Products</h1>
<div id="product-grid">
  <div class="product-card" data-product-id="1">
    <h3 class="product-name">Nike Air Max</h3>
    <span class="price">₹4,999</span>
    <button class="add-to-cart" data-testid="add-to-cart-1">Add to cart</button>
  </div>
  <div class="product-card" data-product-id="2">
    <h3 class="product-name">Adidas Ultraboost</h3>
    <span class="price">₹7,999</span>
    <button class="add-to-cart" data-testid="add-to-cart-2">Add to cart</button>
  </div>
</div>
<nav aria-label="Pagination">
  <a href="?page=2">Next page</a>
</nav>
</body></html>"""

PRODUCT_PAGE = GoldenPage(
    name="product_listing",
    html=PRODUCT_HTML,
    intents=["Add to cart button", "Next page link"],
    selectors=[".add-to-cart", "a[href='?page=2']"],
)


# ── Registry ──────────────────────────────────────────────────────────────────

CANONICAL_PAGES = [LOGIN_PAGE, SEARCH_PAGE, REGISTRATION_PAGE, PRODUCT_PAGE]
BROKEN_PAIRS = [(LOGIN_PAGE, LOGIN_BROKEN_PAGE), (SEARCH_PAGE, SEARCH_BROKEN_PAGE)]
