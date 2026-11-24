import json
import sqlite3


class DB:
    def __init__(self, path="bot.db"):
        self.c = sqlite3.connect(path)
        self.c.executescript("""
        create table if not exists scans(bar int, symbol text, ok int, soft int,
                                         hard text, softd text, vals text);
        create table if not exists trades(symbol text, entry real, exit real, qty real,
                                          why text, pnl real, ts int);
        create table if not exists equity(bar int, eq real);
        create table if not exists meta(k text primary key, v text);""")
        try:
            self.c.execute("alter table scans add column side text")
        except sqlite3.OperationalError:
            pass
        try:
            self.c.execute("alter table trades add column side text")
        except sqlite3.OperationalError:
            pass
        self.c.commit()

    def scan(self, bar, g):
        self.c.execute("insert into scans(bar,symbol,side,ok,soft,hard,softd,vals) values(?,?,?,?,?,?,?,?)",
            (bar, g.symbol, g.side, int(g.ok), g.soft_pass, json.dumps(g.hard),
             json.dumps(g.soft), json.dumps(g.vals)))
        self.c.commit()

    def trade(self, sym, x, px, why, pnl, ts):
        self.c.execute("insert into trades(symbol,entry,exit,qty,why,pnl,ts,side) values(?,?,?,?,?,?,?,?)",
                       (sym, x["entry"], px, x["qty"], why, pnl, ts, x.get("side", "long")))
        self.c.commit()

    def equity(self, bar, eq):
        self.c.execute("insert into equity values(?,?)", (bar, eq)); self.c.commit()

    def get(self, k):
        r = self.c.execute("select v from meta where k=?", (k,)).fetchone()
        return r[0] if r else None

    def set(self, k, v):
        self.c.execute("insert or replace into meta values(?,?)", (k, str(v))); self.c.commit()