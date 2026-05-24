"""Tests for code_parser — C#, TypeScript, and generic language chunkers."""

from __future__ import annotations

import pytest
from oapw.enterprise.code_parser import (
    parse_csharp,
    parse_typescript,
    parse_generic,
    parse_file,
    detect_language,
    CodeChunk,
)

REPO = "test-repo"
URL = "https://bitbucket.org/ws/test-repo"


# ── detect_language ───────────────────────────────────────────────────────────

class TestDetectLanguage:
    def test_csharp(self):
        assert detect_language("src/Api/Controller.cs") == "csharp"

    def test_typescript(self):
        assert detect_language("src/components/Login.tsx") == "typescript"

    def test_typescript_ts(self):
        assert detect_language("utils/helpers.ts") == "typescript"

    def test_javascript(self):
        assert detect_language("routes/api.js") == "javascript"

    def test_jsx(self):
        assert detect_language("App.jsx") == "javascript"

    def test_python(self):
        assert detect_language("main.py") == "python"

    def test_unknown(self):
        assert detect_language("data.json") == "other"


# ── C# parser ─────────────────────────────────────────────────────────────────

_CS_SOURCE = '''
using System;
namespace MyApp.Controllers
{
    /// <summary>
    /// Handles user authentication.
    /// </summary>
    public class AuthController : BaseController
    {
        /// <summary>Login a user.</summary>
        public async Task<IActionResult> Login(LoginRequest req)
        {
            var user = await _userService.FindAsync(req.Email);
            if (user == null) return Unauthorized();
            return Ok(new { token = _jwt.Generate(user) });
        }

        public IActionResult Logout()
        {
            HttpContext.SignOut();
            return Ok();
        }
    }

    public interface IAuthService
    {
        Task<User> FindUserAsync(string email);
    }
}
'''

class TestCSharpParser:
    def setup_method(self):
        self.chunks = parse_csharp(_CS_SOURCE, REPO, URL, "src/Controllers/AuthController.cs")

    def test_produces_chunks(self):
        assert len(self.chunks) > 0

    def test_file_summary_first(self):
        assert self.chunks[0].chunk_type == "file_summary"

    def test_file_summary_has_namespace(self):
        summary = self.chunks[0]
        assert summary.metadata.get("namespace") == "MyApp.Controllers"

    def test_finds_class(self):
        classes = [c for c in self.chunks if c.chunk_type == "class"]
        names = [c.name for c in classes]
        assert "AuthController" in names

    def test_finds_interface(self):
        classes = [c for c in self.chunks if c.chunk_type == "class"]
        names = [c.name for c in classes]
        assert "IAuthService" in names

    def test_finds_methods(self):
        funcs = [c for c in self.chunks if c.chunk_type == "function"]
        names = {c.name for c in funcs}
        assert "Login" in names or "Logout" in names

    def test_doc_comment_included(self):
        class_chunk = next(c for c in self.chunks if c.name == "AuthController")
        assert "authentication" in class_chunk.text.lower()

    def test_chunk_id_format(self):
        for chunk in self.chunks:
            assert chunk.id.startswith("code:test-repo:")

    def test_language_is_csharp(self):
        for chunk in self.chunks:
            assert chunk.language == "csharp"

    def test_line_numbers_positive(self):
        for chunk in self.chunks[1:]:  # skip file_summary
            assert chunk.line_start > 0

    def test_to_kb_doc_structure(self):
        doc = self.chunks[0].to_kb_doc()
        assert "id" in doc
        assert "text" in doc
        assert "metadata" in doc
        assert doc["metadata"]["source"] == "code"
        assert doc["metadata"]["repo_name"] == REPO


# ── TypeScript parser ─────────────────────────────────────────────────────────

_TS_SOURCE = '''
import React, { useState } from "react";

interface LoginFormProps {
  onSuccess: () => void;
}

/**
 * LoginForm component — handles user authentication.
 */
export const LoginForm: React.FC<LoginFormProps> = ({ onSuccess }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await fetch("/api/auth/login", { method: "POST" });
    if (res.ok) onSuccess();
  };

  return <form onSubmit={handleSubmit}></form>;
};

export function useAuth() {
  const [user, setUser] = useState(null);
  return { user, setUser };
}

export async function fetchUser(id: string) {
  const res = await fetch(`/api/users/${id}`);
  return res.json();
}

type UserRole = "admin" | "viewer" | "editor";
'''

_TS_ROUTES_SOURCE = '''
import express from "express";
const router = express.Router();
router.get("/users", getUsers);
router.post("/users", createUser);
router.put("/users/:id", updateUser);
router.delete("/users/:id", deleteUser);
'''

class TestTypeScriptParser:
    def setup_method(self):
        self.chunks = parse_typescript(_TS_SOURCE, REPO, URL, "src/components/LoginForm.tsx")

    def test_produces_chunks(self):
        assert len(self.chunks) > 0

    def test_file_summary_first(self):
        assert self.chunks[0].chunk_type == "file_summary"

    def test_finds_component(self):
        components = [c for c in self.chunks if c.chunk_type == "component"]
        assert any(c.name == "LoginForm" for c in components)

    def test_finds_hook(self):
        hooks = [c for c in self.chunks if c.chunk_type == "hook"]
        assert any(c.name == "useAuth" for c in hooks)

    def test_finds_exported_function(self):
        funcs = [c for c in self.chunks if c.chunk_type == "function"]
        assert any(c.name == "fetchUser" for c in funcs)

    def test_finds_interface(self):
        interfaces = [c for c in self.chunks if c.chunk_type == "interface"]
        assert any(c.name == "LoginFormProps" for c in interfaces)

    def test_jsdoc_included(self):
        comp = next(c for c in self.chunks if c.name == "LoginForm")
        assert "authentication" in comp.text.lower()

    def test_language_is_typescript(self):
        for chunk in self.chunks:
            assert chunk.language == "typescript"

    def test_no_duplicate_ids(self):
        ids = [c.id for c in self.chunks]
        assert len(ids) == len(set(ids))

    def test_api_routes_extracted(self):
        route_chunks = parse_typescript(_TS_ROUTES_SOURCE, REPO, URL, "src/routes/users.js")
        routes = [c for c in route_chunks if c.chunk_type == "api_routes"]
        assert len(routes) == 1
        assert "GET /users" in routes[0].text
        assert "POST /users" in routes[0].text
        assert "DELETE /users/:id" in routes[0].text


# ── Generic parser ────────────────────────────────────────────────────────────

_GO_SOURCE = "\n".join([f"line {i}" for i in range(200)])

class TestGenericParser:
    def test_produces_file_summary(self):
        chunks = parse_generic(_GO_SOURCE, REPO, URL, "main.go")
        assert chunks[0].chunk_type == "file_summary"

    def test_sliding_window_chunks(self):
        chunks = parse_generic(_GO_SOURCE, REPO, URL, "main.go")
        # Should have multiple window chunks for 200-line file
        assert len(chunks) > 2

    def test_no_overlapping_chunk_ids(self):
        chunks = parse_generic(_GO_SOURCE, REPO, URL, "main.go")
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_short_file_single_chunk(self):
        short = "package main\nfunc main() {}"
        chunks = parse_generic(short, REPO, URL, "main.go")
        # At least file_summary + 1 window
        assert len(chunks) >= 1


# ── parse_file dispatcher ─────────────────────────────────────────────────────

class TestParseFileDispatcher:
    def test_routes_cs_to_csharp_parser(self):
        chunks = parse_file("public class Foo {}", REPO, URL, "Foo.cs")
        assert all(c.language == "csharp" for c in chunks)

    def test_routes_ts_to_ts_parser(self):
        chunks = parse_file("export const x = 1;", REPO, URL, "x.ts")
        assert all(c.language == "typescript" for c in chunks)

    def test_routes_unknown_to_generic(self):
        chunks = parse_file("package main", REPO, URL, "main.go")
        assert chunks[0].chunk_type == "file_summary"

    def test_empty_file(self):
        chunks = parse_file("", REPO, URL, "empty.cs")
        assert isinstance(chunks, list)
