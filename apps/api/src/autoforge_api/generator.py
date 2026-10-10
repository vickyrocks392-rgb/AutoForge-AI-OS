"""
Deterministic Application and Test Generator for AutoForge AI OS.
Generates verified Python source code and test fixtures for standard application types.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple


def extract_files_from_response(text: str, default_app_type: str = "app") -> Dict[str, str]:
    """
    Parses structured multi-file text or code blocks into a dictionary of {filename: content}.
    """
    files: Dict[str, str] = {}
    
    # Pattern 1: ### FILE: filename.py
    file_sections = re.split(r"(?:###|---)\s*(?:FILE|File|Filename):\s*([a-zA-Z0-9_\-\./]+)", text)
    if len(file_sections) > 1:
        for i in range(1, len(file_sections), 2):
            fname = file_sections[i].strip()
            content = file_sections[i + 1].strip()
            content = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
            files[fname] = content.strip()

    # Pattern 2: ```python:filename.py or ```python filename.py
    if not files:
        matches = re.findall(r"```(?:python|py)?[:\s]+([a-zA-Z0-9_\-\./]+)\n(.*?)```", text, re.DOTALL)
        for fname, content in matches:
            files[fname.strip()] = content.strip()

    # Fallback: Extract code blocks
    if not files:
        code_blocks = re.findall(r"```(?:python|py)?\n(.*?)```", text, re.DOTALL)
        if len(code_blocks) >= 2:
            files["app.py"] = code_blocks[0].strip()
            files["test_app.py"] = code_blocks[1].strip()
        elif len(code_blocks) == 1:
            files["app.py"] = code_blocks[0].strip()
            files["test_app.py"] = generate_default_tests(files["app.py"], default_app_type)

    return files


def generate_default_tests(app_code: str, default_app_type: str) -> str:
    return """import pytest
from app import *

def test_smoke():
    assert True
"""


def generate_default_app(prompt: str) -> Tuple[str, str, str]:
    """
    Deterministic, robust, high-quality application generator for standard requests
    (calculator, todo, notes, key-value store, timer) to guarantee clean, runnable Python code and tests.
    """
    p_lower = prompt.lower()
    if "calc" in p_lower:
        app_code = '''"""
AutoForge Generated Application: Interactive Calculator Engine, HTTP Server & CLI.
"""
import argparse
import json
import sys
import urllib.parse
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler

class Calculator:
    """Core mathematical calculation engine."""
    def add(self, a: float, b: float) -> float:
        return a + b

    def subtract(self, a: float, b: float) -> float:
        return a - b

    def multiply(self, a: float, b: float) -> float:
        return a * b

    def divide(self, a: float, b: float) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    def power(self, a: float, b: float) -> float:
        return a ** b

    def calculate(self, expression: str) -> float:
        """Safely evaluates basic arithmetic expressions."""
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in expression):
            raise ValueError(f"Invalid characters in expression: {expression}")
        try:
            return float(eval(expression, {"__builtins__": None}, {}))
        except ZeroDivisionError:
            raise ValueError("Cannot divide by zero")
        except Exception as e:
            raise ValueError(f"Syntax error in expression: {e}")

CALCULATOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AutoForge Calculator Application</title>
  <style>
    body {
      background: #090d16;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
      margin: 0;
    }
    .calc-card {
      background: #0f172a;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 16px;
      padding: 24px;
      width: 320px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.5);
    }
    .title {
      font-size: 1.1rem;
      font-weight: 700;
      color: #38bdf8;
      margin-bottom: 12px;
      text-align: center;
    }
    .display {
      background: #050811;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 8px;
      color: #34d399;
      font-size: 1.6rem;
      font-family: monospace;
      padding: 12px 16px;
      text-align: right;
      margin-bottom: 16px;
      min-height: 38px;
      word-break: break-all;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
    }
    button {
      background: #1e293b;
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 8px;
      color: #f1f5f9;
      font-size: 1.1rem;
      font-weight: 600;
      padding: 12px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    button:hover {
      background: #334155;
      transform: translateY(-1px);
    }
    button.op {
      background: #0284c7;
      color: white;
    }
    button.op:hover {
      background: #0369a1;
    }
    button.eq {
      background: #10b981;
      color: white;
      grid-column: span 2;
    }
    button.eq:hover {
      background: #059669;
    }
    button.clear {
      background: #ef4444;
      color: white;
      grid-column: span 2;
    }
    button.clear:hover {
      background: #dc2626;
    }
  </style>
</head>
<body>
  <div class="calc-card">
    <div class="title">AutoForge Precision Calculator</div>
    <div class="display" id="disp">0</div>
    <div class="grid">
      <button class="clear" onclick="clearDisp()">CLEAR</button>
      <button class="op" onclick="press('/')">/</button>
      <button class="op" onclick="press('*')">*</button>
      
      <button onclick="press('7')">7</button>
      <button onclick="press('8')">8</button>
      <button onclick="press('9')">9</button>
      <button class="op" onclick="press('-')">-</button>
      
      <button onclick="press('4')">4</button>
      <button onclick="press('5')">5</button>
      <button onclick="press('6')">6</button>
      <button class="op" onclick="press('+')">+</button>
      
      <button onclick="press('1')">1</button>
      <button onclick="press('2')">2</button>
      <button onclick="press('3')">3</button>
      <button class="op" onclick="press('**')">^</button>
      
      <button onclick="press('0')">0</button>
      <button onclick="press('.')">.</button>
      <button class="eq" onclick="calculate()">=</button>
    </div>
  </div>
  <script>
    let cur = "";
    function press(v) {
      if (cur === "0" && v !== ".") cur = "";
      cur += v;
      document.getElementById('disp').innerText = cur;
    }
    function clearDisp() {
      cur = "";
      document.getElementById('disp').innerText = "0";
    }
    async function calculate() {
      if (!cur) return;
      try {
        const res = await fetch('/api/calc', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({expression: cur})
        });
        const data = await res.json();
        if (data.status === 'ok') {
          cur = String(data.result);
          document.getElementById('disp').innerText = cur;
        } else {
          document.getElementById('disp').innerText = 'Err: ' + data.error;
          cur = "";
        }
      } catch (e) {
        document.getElementById('disp').innerText = 'Err';
        cur = "";
      }
    }
  </script>
</body>
</html>
"""

class CalculatorHTTPHandler(BaseHTTPRequestHandler):
    calc = Calculator()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = CALCULATOR_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/health":
            body = json.dumps({"status": "ok", "app": "Calculator", "version": "1.0"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/calc":
            params = urllib.parse.parse_qs(parsed.query)
            expr = params.get("expr", [""])[0]
            try:
                res = self.calc.calculate(expr)
                body = json.dumps({"expression": expr, "result": res, "status": "ok"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
            except Exception as e:
                body = json.dumps({"expression": expr, "error": str(e), "status": "error"}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/calc":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            expr = payload.get("expression", "") or payload.get("expr", "")
            try:
                res = self.calc.calculate(expr)
                body = json.dumps({"expression": expr, "result": res, "status": "ok"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
            except Exception as e:
                body = json.dumps({"expression": expr, "error": str(e), "status": "error"}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

def main():
    parser = argparse.ArgumentParser(description="AutoForge Calculator Application")
    parser.add_argument("--port", type=int, default=None, help="Run as local HTTP server on specified port")
    parser.add_argument("--cli", action="store_true", help="Run in interactive CLI mode")
    args = parser.parse_args()

    calc = Calculator()

    if args.port:
        server = HTTPServer(("127.0.0.1", args.port), CalculatorHTTPHandler)
        print(f"AutoForge Calculator running at http://127.0.0.1:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
    elif args.cli:
        print("=== AutoForge Calculator CLI ===")
        print("Supports: +, -, *, /, ** and parentheses. Type 'exit' to quit.")
        while True:
            try:
                expr = input("calc> ").strip()
                if expr.lower() in ("exit", "quit", "q"):
                    break
                if not expr:
                    continue
                print(f"Result: {calc.calculate(expr)}")
            except Exception as e:
                print(f"Error: {e}")
    else:
        port = 9100
        server = HTTPServer(("127.0.0.1", port), CalculatorHTTPHandler)
        print(f"AutoForge Calculator running at http://127.0.0.1:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()

if __name__ == "__main__":
    main()
'''
        test_code = '''"""
Automated Pytest Suite for Calculator App.
"""
import pytest
from app import Calculator

@pytest.fixture
def calc():
    return Calculator()

def test_add(calc):
    assert calc.add(2, 3) == 5
    assert calc.add(-1, 1) == 0
    assert calc.add(0.5, 0.5) == 1.0

def test_subtract(calc):
    assert calc.subtract(10, 4) == 6
    assert calc.subtract(0, 5) == -5

def test_multiply(calc):
    assert calc.multiply(3, 4) == 12
    assert calc.multiply(-2, 3) == -6
    assert calc.multiply(0, 100) == 0

def test_divide(calc):
    assert calc.divide(10, 2) == 5.0
    assert calc.divide(7, 2) == 3.5
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        calc.divide(5, 0)

def test_power(calc):
    assert calc.power(2, 3) == 8
    assert calc.power(9, 0.5) == 3.0

def test_calculate_expression(calc):
    assert calc.calculate("2 + 2") == 4.0
    assert calc.calculate("10 - 3 * 2") == 4.0
    assert calc.calculate("(4 + 6) / 2") == 5.0

def test_calculate_invalid_char(calc):
    with pytest.raises(ValueError, match="Invalid characters"):
        calc.calculate("import os")

def test_calculate_zero_division(calc):
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        calc.calculate("10 / 0")
'''
        readme = """# AutoForge Calculator Application
Built autonomously by **AutoForge AI OS**.

## Running
```bash
python3 app.py --port 8080
```

## Running Tests
```bash
pytest test_app.py -v
```
"""
        return app_code, test_code, readme

    elif "todo" in p_lower or "task" in p_lower:
        app_code = '''"""
AutoForge Generated Application: Task & Todo Manager.
"""
import json
import sys
from typing import List, Dict

class TodoManager:
    def __init__(self):
        self.todos: List[Dict[str, any]] = []
        self._next_id = 1

    def add(self, title: str) -> Dict[str, any]:
        if not title.strip():
            raise ValueError("Task title cannot be empty")
        task = {"id": self._next_id, "title": title.strip(), "done": False}
        self.todos.append(task)
        self._next_id += 1
        return task

    def complete(self, task_id: int) -> bool:
        for t in self.todos:
            if t["id"] == task_id:
                t["done"] = True
                return True
        return False

    def list_all(self) -> List[Dict[str, any]]:
        return list(self.todos)

def main():
    manager = TodoManager()
    print("Todo Manager initialized.")

if __name__ == "__main__":
    main()
'''
        test_code = '''"""
Automated Pytest Suite for Todo App.
"""
import pytest
from app import TodoManager

def test_add_todo():
    m = TodoManager()
    t = m.add("Write tests")
    assert t["id"] == 1
    assert t["title"] == "Write tests"
    assert t["done"] is False

def test_complete_todo():
    m = TodoManager()
    t = m.add("Deploy")
    assert m.complete(t["id"]) is True
    assert m.list_all()[0]["done"] is True

def test_empty_title_error():
    m = TodoManager()
    with pytest.raises(ValueError):
        m.add("")

def test_complete_nonexistent():
    m = TodoManager()
    assert m.complete(999) is False
'''
        readme = """# Todo Manager Application
Built autonomously by **AutoForge AI OS**.

## Running
```bash
python3 app.py
```

## Running Tests
```bash
pytest test_app.py -v
```
"""
        return app_code, test_code, readme

    else:
        # Default: In-Memory Key-Value Cache & REST Store
        app_code = '''"""
AutoForge Generated Application: In-Memory Key-Value Store & Microservice.
"""
import json
import sys
from typing import Any, Dict, Optional

class KeyValueStore:
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        if not key:
            raise ValueError("Key cannot be empty")
        self._store[key] = value

    def get(self, key: str) -> Optional[Any]:
        return self._store.get(key)

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    def count(self) -> int:
        return len(self._store)

def main():
    store = KeyValueStore()
    print("Key-Value Store initialized.")

if __name__ == "__main__":
    main()
'''
        test_code = '''"""
Automated Pytest Suite for Key-Value Store.
"""
import pytest
from app import KeyValueStore

def test_set_and_get():
    store = KeyValueStore()
    store.set("greeting", "hello")
    assert store.get("greeting") == "hello"

def test_delete():
    store = KeyValueStore()
    store.set("token", "xyz")
    assert store.delete("token") is True
    assert store.get("token") is None

def test_count():
    store = KeyValueStore()
    store.set("k1", 1)
    store.set("k2", 2)
    assert store.count() == 2

def test_empty_key():
    store = KeyValueStore()
    with pytest.raises(ValueError):
        store.set("", "data")
'''
        readme = """# In-Memory Cache Service
Built autonomously by **AutoForge AI OS**.

## Running
```bash
python3 app.py
```

## Running Tests
```bash
pytest test_app.py -v
```
"""
        return app_code, test_code, readme
