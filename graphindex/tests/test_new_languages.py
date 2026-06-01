from graphindex.parsing.symbols import extract_symbols

def test_c_parsing():
    src = b"""
#include <stdio.h>
struct Point { int x; int y; };
void move(struct Point* p) {
    p->x += 1;
    update();
}
"""
    pf = extract_symbols("c", src)
    assert any(s.name == "Point" and s.kind == "class" for s in pf.symbols)
    assert any(s.name == "move" and s.kind == "function" for s in pf.symbols)
    move = next(s for s in pf.symbols if s.name == "move")
    assert "update" in move.calls

def test_cpp_parsing():
    src = b"""
namespace app {
    class Base {};
    class User : public Base {
        void save() { db_write(); }
    };
}
"""
    pf = extract_symbols("cpp", src)
    assert any(s.name == "app" and s.kind == "module" for s in pf.symbols)
    assert any(s.name == "Base" and s.kind == "class" for s in pf.symbols)
    user = next(s for s in pf.symbols if s.name == "User")
    assert "Base" in user.bases
    save = next(s for s in pf.symbols if s.name == "save")
    assert "db_write" in save.calls

def test_csharp_parsing():
    src = b"""
using System;
namespace App {
    public class Service : IBase, IService {
        public void Execute() {
            Logger.Log("done");
            var x = new OtherService();
        }
    }
}
"""
    pf = extract_symbols("c_sharp", src)
    service = next(s for s in pf.symbols if s.name == "Service")
    assert service.kind == "class"
    assert "IBase" in service.bases
    assert "IService" in service.bases
    execute = next(s for s in pf.symbols if s.name == "Execute")
    assert "Log" in execute.calls
    assert "OtherService" in execute.calls

def test_zig_parsing():
    src = b"""
const std = @import("std");
pub const Config = struct {
    version: u32,
    pub fn init() Config {
        return Config{ .version = 1 };
    }
};
const x = 1;
"""
    pf = extract_symbols("zig", src)
    assert any(s.name == "Config" and s.kind == "class" for s in pf.symbols)
    assert not any(s.name == "x" for s in pf.symbols) # Heuristic should skip plain const
    init = next(s for s in pf.symbols if s.name == "init")
    assert init.kind == "method"

def test_php_parsing():
    src = b"""
<?php
class Controller extends BaseController {
    public function action() {
        $this->render();
        helper();
    }
}
"""
    pf = extract_symbols("php", src)
    controller = next(s for s in pf.symbols if s.name == "Controller")
    assert "BaseController" in controller.bases
    action = next(s for s in pf.symbols if s.name == "action")
    assert action.kind == "method"
    assert "helper" in action.calls

def test_ruby_parsing():
    src = b"""
class User
  def self.find(id)
    query()
  end
  def save
    db_write()
  end
end
"""
    pf = extract_symbols("ruby", src)
    assert any(s.name == "User" and s.kind == "class" for s in pf.symbols)
    find = next(s for s in pf.symbols if s.name == "find")
    assert find.kind == "method"
    assert "query" in find.calls
    save = next(s for s in pf.symbols if s.name == "save")
    assert "db_write" in save.calls

def test_kotlin_parsing():
    src = b"""
package app
import lib.db
class User : Base() {
    fun save() {
        dbWrite()
    }
}
"""
    pf = extract_symbols("kotlin", src)
    assert any(s.name == "User" and s.kind == "class" for s in pf.symbols)
    user = next(s for s in pf.symbols if s.name == "User")
    assert "Base" in user.bases
    save = next(s for s in pf.symbols if s.name == "save")
    assert "dbWrite" in save.calls
    assert any("lib.db" in imp.modules for imp in pf.imports)

def test_bash_parsing():
    src = b"""
function deploy() {
    build_app
    start_server
}
deploy
"""
    pf = extract_symbols("bash", src)
    deploy = next(s for s in pf.symbols if s.name == "deploy")
    assert deploy.kind == "function"
    assert "build_app" in deploy.calls
    assert "start_server" in deploy.calls

def test_lua_parsing():
    src = b"""
function global_fn()
    print("hi")
end
local function local_fn()
    helper()
end
"""
    pf = extract_symbols("lua", src)
    assert any(s.name == "global_fn" and s.kind == "function" for s in pf.symbols)
    assert any(s.name == "local_fn" and s.kind == "function" for s in pf.symbols)
    local_fn = next(s for s in pf.symbols if s.name == "local_fn")
    assert "helper" in local_fn.calls

def test_sql_parsing():
    src = b"""
CREATE TABLE users (id INT);
CREATE VIEW active_users AS SELECT * FROM users;
CREATE FUNCTION get_user(uid INT) RETURNS TEXT AS '...' LANGUAGE SQL;
"""
    pf = extract_symbols("sql", src)
    assert any(s.name == "users" and s.kind == "class" for s in pf.symbols)
    assert any(s.name == "active_users" and s.kind == "class" for s in pf.symbols)
    assert any(s.name == "get_user" and s.kind == "function" for s in pf.symbols)
