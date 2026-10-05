"""Evaluate robots.txt rules per crawler (RFC 9309 + Google matching semantics).

A crawler is "allowed" (1) if it may fetch the site root "/", "blocked" (0) if not.
"""
import re

# column name -> (company, ordered list of user-agent tokens to try; '*' fallback is implicit)
CRAWLERS = [
    ("Applebot", "Apple", ["applebot", "@googlebot"]),           # Apple follows Googlebot rules if Applebot is not named
    ("Applebot-Extended", "Apple", ["applebot-extended"]),
    ("Googlebot", "Google", ["googlebot"]),
    ("Google-Extended", "Google", ["google-extended"]),
    ("GPTBot", "OpenAI", ["gptbot"]),
    ("OAI-SearchBot", "OpenAI", ["oai-searchbot"]),
    ("ChatGPT-User", "OpenAI", ["chatgpt-user"]),
    ("Bingbot", "Microsoft", ["bingbot", "msnbot"]),
    ("PerplexityBot", "Perplexity", ["perplexitybot"]),
    ("Perplexity-User", "Perplexity", ["perplexity-user"]),
    ("ShapBot", "Parallel", ["shapbot"]),
    ("ExaSearchBot", "Exa", ["exasearchbot"]),
    ("Brave (Googlebot rules)", "Brave", ["googlebot"]),        # Brave has no own token; it obeys Googlebot rules
    ("YouBot", "You.com", ["youbot"]),
    ("ClaudeBot", "Anthropic", ["claudebot"]),
    ("Claude-SearchBot", "Anthropic", ["claude-searchbot"]),
    ("Claude-User", "Anthropic", ["claude-user"]),
    ("CCBot", "Common Crawl", ["ccbot"]),
    ("Meta-ExternalAgent", "Meta", ["meta-externalagent"]),
    ("Amazonbot", "Amazon", ["amazonbot"]),
    ("Bytespider", "ByteDance", ["bytespider"]),
    ("DuckDuckBot", "DuckDuckGo", ["duckduckbot"]),
    ("DuckAssistBot", "DuckDuckGo", ["duckassistbot"]),
    ("YandexBot", "Yandex", ["yandexbot", "yandex"]),
    ("Baiduspider", "Baidu", ["baiduspider"]),
    ("Yeti", "Naver", ["yeti"]),
    ("PetalBot", "Huawei", ["petalbot"]),
    ("cohere-ai", "Cohere", ["cohere-ai"]),
    ("MistralAI-User", "Mistral", ["mistralai-user"]),
    ("Diffbot", "Diffbot", ["diffbot"]),
]


def parse(text):
    """Return dict: ua_token -> list of (allow:bool, pattern). Groups with the same UA are merged."""
    groups = {}
    cur_uas, in_rules = [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lstrip("﻿")
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k in ("user-agent", "useragent", "user agent"):
            if in_rules:
                cur_uas, in_rules = [], False
            tok = v.split("/")[0].strip().lower() if v != "*" else "*"
            tok = tok.split()[0] if tok else tok
            if tok:
                cur_uas.append(tok)
                groups.setdefault(tok, [])
        elif k in ("allow", "disallow"):
            in_rules = True
            if not cur_uas:
                continue
            if k == "disallow" and v == "":
                continue
            for ua in cur_uas:
                groups[ua].append((k == "allow", v))
        # other directives (crawl-delay, sitemap, content-signal, ...) are ignored, as Google does
    return groups


def _match(pat, path):
    """Google-style robots pattern match: '*' = any sequence, trailing '$' = end anchor; prefix match otherwise.
    Non-backtracking two-pointer wildcard algorithm (avoids regex blow-ups on patterns with many '*')."""
    anchored = pat.endswith("$")
    if anchored:
        pat = pat[:-1]
    else:
        pat = pat + "*"
    p = s = 0
    star = -1; mark = 0
    while s < len(path):
        if p < len(pat) and pat[p] != "*" and pat[p] == path[s]:
            p += 1; s += 1
        elif p < len(pat) and pat[p] == "*":
            star = p; mark = s; p += 1
        elif star != -1:
            p = star + 1; mark += 1; s = mark
        else:
            return False
    while p < len(pat) and pat[p] == "*":
        p += 1
    return p == len(pat)


def allowed(rules, path="/"):
    best_len, best_allow = -1, True
    for allow, pat in rules:
        if not pat.startswith("/") and not pat.startswith("*"):
            pat = "/" + pat
        if _match(pat, path):
            ln = len(pat)
            if ln > best_len or (ln == best_len and allow):
                best_len, best_allow = ln, allow
    return best_allow


PROBES = ("/", "/zz-generic-content-page")


def evaluate(groups, tokens):
    """Return (allowed:bool, matched_group:str). Allowed = may fetch the homepage AND a generic content URL."""
    for t in tokens:
        t = t.lstrip("@")
        if t in groups:
            return all(allowed(groups[t], p) for p in PROBES), t
    if "*" in groups:
        return all(allowed(groups["*"], p) for p in PROBES), "*"
    return True, "(none)"


def looks_like_html(text):
    head = text.lstrip()[:300].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or "<head" in head or "<body" in head
