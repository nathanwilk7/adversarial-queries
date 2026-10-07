"""Compile the repository's acyclic literal grammars for regex guidance."""
import json
import re


def lark_to_regex(grammar):
    rules = {}
    for line in grammar.splitlines():
        if not line.strip():
            continue
        name, sep, expression = line.partition(":")
        if not sep:
            raise ValueError(f"Unsupported grammar line: {line}")
        rules[name.strip()] = expression.strip()
    cache = {}

    def expand(name, active=()):
        if name in active:
            raise ValueError(f"Recursive rule cannot be expanded: {name}")
        if name in cache:
            return cache[name]
        expression = rules[name]
        pattern = []
        position = 0
        for match in re.finditer(r'"(?:\\.|[^"\\])*"|[a-zA-Z_][a-zA-Z_0-9]*|[?|]', expression):
            if expression[position:match.start()].strip():
                raise ValueError(f"Unsupported grammar expression: {expression}")
            token = match.group()
            if token.startswith('"'):
                pattern.append(re.escape(json.loads(token)))
            elif token in ('?', '|'):
                pattern.append(token)
            else:
                pattern.append(expand(token, (*active, name)))
            position = match.end()
        if expression[position:].strip():
            raise ValueError(f"Unsupported grammar expression: {expression}")
        cache[name] = '(?:' + ''.join(pattern) + ')'
        return cache[name]

    return expand('start')
